"""CHECK_145 — the live CF Pages deploy is current: the latest build
succeeded AND the deployed commit matches local HEAD.

**v41.B (2026-06-15) rewrite.** Reads the **CF Pages deployments API**
(build status + the commit the deployment built from), not `/version.json`.
The version-stamp convention this check used to depend on was never rolled
out fleet-wide (0/39 sites served it), so the check was dead — it warn-skipped
everywhere. The CF API gives the same signal — *"did my latest commit
actually ship, and did the build pass?"* — with no per-site artifact, which is
the whole point: it's what makes lamill *notice* a silent CF build failure.

Scope: **cf-pages only** (the fleet became uniform cf-pages with the
2026-06-15 Worker→Pages consolidation). Non-cf-pages sites (vercel/hostgator)
warn-skip — their deploy state lives behind different APIs.

Project-name resolution: CF Pages project names follow two conventions in
this fleet — the `_project_name` slug (older sites: `scopeguard`) and the
dashed domain (sites migrated from Workers: `agesdk-dev`, `airsucks-com`).
We try both.

Pass / fail / warn:
  - pass: latest build succeeded AND deployed commit == local HEAD
  - fail: latest CF build **FAILED** (the headline case — a silent build
          failure leaves the old deploy serving), OR deployed commit !=
          local HEAD (unshipped commits / stale deploy)
  - warn: not cf-pages / no `lamill.toml` / no CF creds / project not
          resolvable / no deployments yet / build in a non-terminal or
          canceled state / local HEAD undetermined / commit metadata absent
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ..seo import _is_web_project
from ...lamill_toml import LAMILL_TOML_FILENAME, ParseError, load


def _origin_head_sha(repo_path: str, branch: str) -> str | None:
    """The commit at `origin/<branch>` — i.e. the latest *pushed* commit on the
    production branch, which is what CF builds from. Uses the local remote-
    tracking ref (no network; a `git push` updates it, so it's accurate right
    after a deploy). Compares against this, not the working-tree HEAD, so a
    local clone that's merely out of sync with origin doesn't false-fail."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", f"origin/{branch}"],
            capture_output=True, text=True, timeout=10)
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else None
    except Exception:  # noqa: BLE001 — not a git repo / git missing
        return None

CHECK_ID = "CHECK_145"
CHECK_NAME = "deploy-fresh"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Live CF Pages deploy is current — latest build succeeded and the deployed "
    "commit matches local HEAD (catches silent build failures + stale deploys)."
)


def _resolve_pages_project(domain: str, *, account_id: str, client) -> str | None:
    """Find the CF Pages project name for `domain`, trying both fleet naming
    conventions: the `_project_name` slug and the dashed domain."""
    from ...cloudflare import get_pages_project

    candidates: list[str] = []
    try:
        from ...bootstrap import _project_name
        candidates.append(_project_name(domain))
    except Exception:  # noqa: BLE001 — slug helper is best-effort
        pass
    candidates.append(domain.replace(".", "-"))

    seen: set[str] = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            # get_pages_project returns None on 404 (doesn't raise) — only a
            # non-None result means this name is a real Pages project.
            if get_pages_project(name, account_id=account_id, client=client) is not None:
                return name
        except Exception:  # noqa: BLE001 — transient/other error → try next
            continue
    return None


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    base = Path(repo_path).resolve()
    domain = base.name.lower()

    # cf-pages only — read the declared platform.
    try:
        payload = load(base)
    except ParseError as e:
        return CheckResult(status="warn",
                           message=f"{LAMILL_TOML_FILENAME} invalid — see CHECK_059 ({e})")
    if payload is None:
        return CheckResult(status="warn",
                           message=f"no {LAMILL_TOML_FILENAME} — deploy-fresh not checkable")
    platform = payload.deploy.platform
    if platform != "cf-pages":
        return CheckResult(
            status="warn",
            message=f"platform={platform} — deploy-fresh (CF Pages API) not applicable")

    # CF creds — degrade gracefully if absent.
    from ...apikeys import get_key
    token = get_key("CF_API_TOKEN")
    account = get_key("CF_ACCOUNT_ID")
    if not token or not account:
        return CheckResult(status="warn", message="CF API creds not configured — skipped")

    import httpx
    from ...cloudflare import latest_pages_deployment
    client = httpx.Client(
        base_url="https://api.cloudflare.com/client/v4",
        headers={"Authorization": f"Bearer {token}"}, timeout=20.0)
    try:
        project = _resolve_pages_project(domain, account_id=account, client=client)
        if not project:
            return CheckResult(status="warn",
                               message=f"no CF Pages project found for {domain} — skipped")
        try:
            status, commit, _dep = latest_pages_deployment(
                project, account_id=account, client=client)
        except Exception as e:  # noqa: BLE001 — transport/API error → soft-skip
            return CheckResult(status="warn",
                               message=f"CF deployments API error ({type(e).__name__}) — skipped")
    finally:
        client.close()

    if status is None:
        return CheckResult(status="warn", message=f"{project}: no deployments yet — skipped")
    if status == "failure":
        return CheckResult(
            status="fail",
            message=(
                f"latest CF Pages build FAILED ({project}) — the live site is "
                f"stale; the last push didn't ship. Check the build log in the "
                f"CF dashboard."))
    if status not in ("success", "active", "idle"):
        return CheckResult(status="warn",
                           message=f"{project}: latest build status={status} — skipped")

    # Build ok / in-flight — compare deployed commit to origin/<prod-branch>
    # (the latest pushed commit, which is what CF builds from).
    branch = payload.deploy.production_branch or "main"
    head = _origin_head_sha(str(base), branch)
    if not head:
        return CheckResult(
            status="warn",
            message=f"can't determine origin/{branch} — not a git repo or no remote ref")
    if not commit:
        return CheckResult(
            status="warn",
            message=f"{project}: deployment has no commit metadata — can't compare")
    if commit == head or commit.startswith(head) or head.startswith(commit):
        return CheckResult(status="pass",
                           message=f"latest pushed commit shipped · build {status} · {commit[:12]}")
    return CheckResult(
        status="fail",
        message=(
            f"deploy drift · origin/{branch} {head[:12]} ≠ deployed {commit[:12]} "
            f"({project}). The latest pushed commit didn't ship — re-trigger the "
            f"build or check its log."))
