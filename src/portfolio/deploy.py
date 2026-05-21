"""Deploy abstraction (v3.C) — `DeployTarget` interface + Cloudflare Pages impl.

Automates the post-bootstrap deploy plumbing the user otherwise does by
clicking through the Cloudflare dashboard:

  1. `gh repo create <slug> --source=. --remote=origin --push` — pushes the
     bootstrapped project to GitHub.
  2. CF Pages REST API: create a Pages project tied to that GitHub repo,
     with the **build command and output dir set explicitly** (`pnpm run
     build` → `dist/`) so CF doesn't auto-detect bun and break the build.
     This is the kwizicle.com lesson burned into automation.

Provider-agnostic: `DeployTarget` is a Protocol; future `VercelDeploy` /
`NetlifyDeploy` impls slot in without any caller changes.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import requests


CF_API_BASE = "https://api.cloudflare.com/client/v4"
CF_API_TIMEOUT = 30.0
DEFAULT_BUILD_COMMAND = "pnpm run build"
DEFAULT_DEST_DIR = "dist"
DEFAULT_PRODUCTION_BRANCH = "main"


class DeployError(Exception):
    """Raised when an unrecoverable deploy step fails."""


@dataclass
class StepResult:
    """One step of a deploy run. Composable across providers."""
    step: str
    ok: bool
    detail: str = ""
    skipped: bool = False
    payload: dict = field(default_factory=dict)


@dataclass
class VerifyResult:
    ok: bool
    missing: list[str]
    notes: list[str]


# ---------- DeployTarget protocol ----------


class DeployTarget(Protocol):
    """Provider-agnostic deploy interface. Implementations: CloudflarePagesDeploy
    (this file). Future: VercelDeploy, NetlifyDeploy.
    """

    @property
    def name(self) -> str: ...

    def verify_local_config(self, project_dir: Path) -> VerifyResult: ...

    def create_github_repo(self, project_dir: Path, slug: str, private: bool = False) -> StepResult: ...

    def create_project(self, project_dir: Path, domain: str, gh_owner: str, gh_repo: str) -> StepResult: ...


# ---------- CloudflarePagesDeploy ----------


@dataclass
class CloudflarePagesDeploy:
    """Concrete `DeployTarget` for Cloudflare Pages.

    Auth via env vars (typically loaded from `portfolio.env` by the caller):
      - `CF_API_TOKEN` — token with Pages:Edit permissions.
      - `CF_ACCOUNT_ID` — Cloudflare account ID.
      - `gh` CLI must be authenticated for `create_github_repo`.
    """
    api_token: str
    account_id: str
    dry_run: bool = False

    @property
    def name(self) -> str:
        return "cloudflare-pages"

    # -- verify --

    def verify_local_config(self, project_dir: Path) -> VerifyResult:
        """Check the local project has everything CF Pages needs to build cleanly.

        Returns missing files + advisory notes the deploy step will rely on.
        """
        missing: list[str] = []
        notes: list[str] = []

        wrangler = project_dir / "wrangler.jsonc"
        if not wrangler.exists():
            missing.append("wrangler.jsonc")
        else:
            try:
                cfg = json.loads(_strip_jsonc_comments(wrangler.read_text()))
                cf_name = cfg.get("name")
                if not cf_name:
                    notes.append("wrangler.jsonc has no `name` field — CF Pages project name will be inferred from domain")
                else:
                    notes.append(f"wrangler.jsonc declares CF project name: {cf_name!r}")
            except json.JSONDecodeError as e:
                missing.append(f"wrangler.jsonc (unparseable: {e})")

        if not (project_dir / "public" / "_headers").exists():
            notes.append("public/_headers missing — security + cache headers won't ship in dist/")

        pkg_path = project_dir / "package.json"
        if not pkg_path.exists():
            missing.append("package.json")
        else:
            try:
                pkg = json.loads(pkg_path.read_text())
                build_cmd = (pkg.get("scripts") or {}).get("build", "")
                if "vite build" not in build_cmd and "astro build" not in build_cmd:
                    notes.append(f"package.json `build` script unusual: {build_cmd!r} — verify it produces a static dist/")
            except json.JSONDecodeError:
                missing.append("package.json (unparseable)")

        for forbidden, mgr in [("bun.lockb", "bun"), ("package-lock.json", "npm"), ("yarn.lock", "yarn")]:
            if (project_dir / forbidden).exists():
                missing.append(f"{forbidden} present (CF will pick {mgr}; pnpm-only convention violated)")

        if not (project_dir / "pnpm-lock.yaml").exists():
            missing.append("pnpm-lock.yaml (required — CF must use pnpm per the project convention)")

        if not (project_dir / ".git").is_dir():
            missing.append(".git (project must be its own repo before pushing to GitHub)")

        return VerifyResult(ok=(len(missing) == 0), missing=missing, notes=notes)

    # -- github --

    def create_github_repo(self, project_dir: Path, slug: str, private: bool = False) -> StepResult:
        """Create + push the GitHub repo via `gh repo create`. Idempotent: if the
        repo already exists, returns skipped=True without erroring.
        """
        visibility = "--private" if private else "--public"
        cmd = ["gh", "repo", "create", slug, visibility, "--source=.", "--remote=origin", "--push"]
        if self.dry_run:
            return StepResult(step="create_github_repo", ok=True, skipped=False,
                              detail=f"[dry-run] would run: {' '.join(cmd)}")
        try:
            existing = subprocess.run(["gh", "repo", "view", slug, "--json", "url"],
                                      cwd=project_dir, capture_output=True, text=True, timeout=20)
            if existing.returncode == 0:
                try:
                    payload = json.loads(existing.stdout) if existing.stdout.strip() else {}
                except json.JSONDecodeError:
                    payload = {}
                return StepResult(step="create_github_repo", ok=True, skipped=True,
                                  detail=f"GitHub repo {slug!r} already exists",
                                  payload=payload)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return StepResult(step="create_github_repo", ok=False,
                              detail="gh CLI not found or timed out; install gh and `gh auth login`")
        try:
            proc = subprocess.run(cmd, cwd=project_dir, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return StepResult(step="create_github_repo", ok=False, detail="gh repo create timed out")
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout).strip()
            return StepResult(step="create_github_repo", ok=False, detail=f"gh repo create failed: {err}")
        return StepResult(step="create_github_repo", ok=True,
                          detail=f"created + pushed: {slug}",
                          payload={"slug": slug, "stdout": proc.stdout.strip()})

    # -- cf pages project --

    def create_project(self, project_dir: Path, domain: str, gh_owner: str, gh_repo: str) -> StepResult:
        """Create the Cloudflare Pages project tied to the GitHub repo with build
        command + output dir explicitly set. Idempotent: if a project with this
        name already exists, returns skipped=True.
        """
        from .bootstrap import _project_name

        wrangler = project_dir / "wrangler.jsonc"
        cf_name = _project_name(domain)
        if wrangler.exists():
            try:
                cfg = json.loads(_strip_jsonc_comments(wrangler.read_text()))
                cf_name = cfg.get("name") or cf_name
            except json.JSONDecodeError:
                pass

        body = {
            "name": cf_name,
            "production_branch": DEFAULT_PRODUCTION_BRANCH,
            "source": {
                "type": "github",
                "config": {
                    "owner": gh_owner,
                    "repo_name": gh_repo,
                    "production_branch": DEFAULT_PRODUCTION_BRANCH,
                    "pr_comments_enabled": True,
                    "deployments_enabled": True,
                },
            },
            "build_config": {
                "build_command": DEFAULT_BUILD_COMMAND,
                "destination_dir": DEFAULT_DEST_DIR,
                "root_dir": "",
            },
        }

        if self.dry_run:
            return StepResult(step="create_pages_project", ok=True, skipped=False,
                              detail=f"[dry-run] would POST to {CF_API_BASE}/accounts/{self.account_id}/pages/projects",
                              payload={"body": body})

        existing = self._get_existing_project(cf_name)
        if existing is not None:
            return StepResult(step="create_pages_project", ok=True, skipped=True,
                              detail=f"CF Pages project {cf_name!r} already exists",
                              payload={"existing": existing})

        headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}
        url = f"{CF_API_BASE}/accounts/{self.account_id}/pages/projects"
        try:
            r = requests.post(url, headers=headers, json=body, timeout=CF_API_TIMEOUT)
        except Exception as e:
            return StepResult(step="create_pages_project", ok=False,
                              detail=f"CF API call failed: {type(e).__name__}: {e}")

        if r.status_code in (200, 201):
            try:
                data = r.json()
            except ValueError:
                data = {}
            return StepResult(step="create_pages_project", ok=True,
                              detail=f"CF Pages project {cf_name!r} created (build_command={DEFAULT_BUILD_COMMAND!r})",
                              payload=data.get("result", data))

        try:
            err_payload = r.json()
        except ValueError:
            err_payload = {"raw": r.text}
        msg = err_payload.get("errors") or err_payload
        return StepResult(step="create_pages_project", ok=False,
                          detail=f"CF API HTTP {r.status_code}: {msg}",
                          payload=err_payload)

    def _get_existing_project(self, cf_name: str) -> dict | None:
        """Return the existing CF Pages project dict if `cf_name` already exists, else None."""
        headers = {"Authorization": f"Bearer {self.api_token}"}
        url = f"{CF_API_BASE}/accounts/{self.account_id}/pages/projects/{cf_name}"
        try:
            r = requests.get(url, headers=headers, timeout=CF_API_TIMEOUT)
        except Exception:
            return None
        if r.status_code == 200:
            try:
                return r.json().get("result")
            except ValueError:
                return None
        return None


# ---------- helpers ----------


def _strip_jsonc_comments(text: str) -> str:
    """Strip // line comments + /* block comments */ from JSONC. Naive but
    sufficient for the wrangler.jsonc files we generate."""
    out: list[str] = []
    i = 0
    in_str = False
    in_block = False
    n = len(text)
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def detect_gh_owner() -> str | None:
    """Return the user's GitHub login from `gh api user`, or None if `gh` isn't authed."""
    try:
        r = subprocess.run(["gh", "api", "user", "-q", ".login"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip() or None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


# ---------- v11.M shell-out deployers ----------
#
# CF Workers + Vercel deploys re-use the operator's installed tooling
# (wrangler via `pnpm run deploy`; `vercel` CLI). Replicating either
# pipeline against raw HTTP APIs reasonably means reproducing wrangler's
# asset-upload flow or vercel's file-hashing pipeline — both nontrivial
# and a maintenance burden the operator does not need.
#
# Returns `StepResult` so the CLI renderer can treat each deploy
# uniformly (ok=True on subprocess returncode 0).


# v15.K (ADR-0012) removed `deploy_cf_workers_via_shell`. cf-workers
# deploys go through the unified Pages-API pipeline in
# `cli.py::_deploy_cf_unified()`. No wrangler shell-out anywhere in
# the deploy path. `vercel` keeps its shell helper below (still the
# right tool for that platform's hash-and-upload pipeline).


def deploy_vercel_via_shell(
    project_dir: Path,
    *,
    dry_run: bool = False,
    runner=None,
) -> StepResult:
    """Run `vercel deploy --prod` in `project_dir`.

    Assumes the `vercel` CLI is installed and authenticated.
    """
    cmd = ["vercel", "deploy", "--prod"]
    if dry_run:
        return StepResult(
            step="vercel-shell",
            ok=True,
            detail=f"DRY-RUN — would run: {' '.join(cmd)} (cwd={project_dir})",
            skipped=True,
        )
    return _run_shell_deploy(cmd, project_dir, step="vercel-shell", runner=runner)


def _run_shell_deploy(
    cmd: list[str],
    cwd: Path,
    *,
    step: str,
    runner=None,
) -> StepResult:
    run = runner or subprocess.run
    try:
        result = run(cmd, cwd=str(cwd), check=False)
    except FileNotFoundError:
        return StepResult(
            step=step,
            ok=False,
            detail=f"command not found: {cmd[0]} (install it and try again)",
        )
    rc = getattr(result, "returncode", 0)
    if rc == 0:
        return StepResult(
            step=step,
            ok=True,
            detail=f"ran `{' '.join(cmd)}` in {cwd}",
        )
    return StepResult(
        step=step,
        ok=False,
        detail=f"`{' '.join(cmd)}` exited with code {rc}",
    )
