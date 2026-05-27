"""v15.I — GitHub REST API repo create + git push helpers.

Used by `lamill new deploy <domain>` to set up the GitHub remote
side of the git-integrated CF deploy pipeline (ADR-0012). Two
auth paths supported, in priority order:

  1. **REST API via `GITHUB_TOKEN`** (primary; portable; doesn't
     require `gh` to be installed). Endpoints:
       - `GET  /user`               — resolve owner login
       - `GET  /repos/{owner}/{repo}` — idempotency probe
       - `POST /user/repos`         — create repo

  2. **`gh` CLI fallback** when `GITHUB_TOKEN` is missing/empty.
     Shells out to `gh api user / gh repo view / gh repo create`.
     Requires `gh auth login` done once locally.

If both are unavailable, raises `GhAuthError` with explicit
remediation hints (set GITHUB_TOKEN; or install gh and run
`gh auth login`).
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

from .apikeys import get_key

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS_BASE = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
HTTP_TIMEOUT = 15.0


# ---- exceptions + dataclasses --------------------------------------


class GhError(RuntimeError):
    """Base for v15.I GitHub-side failures."""


class GhAuthError(GhError):
    """Both `GITHUB_TOKEN` and `gh` CLI unavailable.

    Raised at pre-flight so the operator sees the failure before
    the deploy pipeline writes anything. Message includes both
    remediation paths.
    """


class GhApiError(GhError):
    """REST API returned a non-2xx response (after we believed auth
    was OK). Wraps the response text + status for surfacing."""


class GhCliError(GhError):
    """`gh` CLI shelled out non-zero, OR output wasn't parseable."""


@dataclass(frozen=True)
class RepoInfo:
    """Subset of GH's repo response we use downstream."""
    owner: str
    name: str
    full_name: str           # "owner/name"
    clone_url_ssh: str       # git@github.com:owner/name.git
    clone_url_https: str     # https://github.com/owner/name.git
    private: bool
    default_branch: str
    created: bool            # True iff THIS process created the repo (vs. detected existing)


# ---- auth-path discovery -------------------------------------------


def auth_path() -> str:
    """Return which auth path the pipeline will use.

    Order of preference:
      - "token"   if GITHUB_TOKEN is set + non-empty
      - "gh-cli"  if `gh` is on PATH
      - "none"    otherwise (caller should raise GhAuthError)
    """
    if (get_key("GITHUB_TOKEN") or "").strip():
        return "token"
    if shutil.which("gh"):
        return "gh-cli"
    return "none"


def ensure_auth() -> str:
    """Same as `auth_path()` but raises `GhAuthError` on "none".

    Pre-flight helper — callers use this to fail fast before any
    write step in the deploy pipeline."""
    path = auth_path()
    if path == "none":
        raise GhAuthError(
            "Neither GITHUB_TOKEN nor `gh` CLI is available. "
            "Either set GITHUB_TOKEN in portfolio.env "
            "(`lamill settings apikeys set GITHUB_TOKEN <pat>`), "
            "or install GitHub CLI + run `gh auth login`."
        )
    return path


# ---- owner detection -----------------------------------------------


def detect_gh_owner() -> str:
    """Resolve the GitHub owner (login) the pipeline will create
    repos under. Uses whichever auth path is available."""
    path = ensure_auth()
    if path == "token":
        return _detect_owner_via_token()
    return _detect_owner_via_cli()


def _detect_owner_via_token() -> str:
    token = (get_key("GITHUB_TOKEN") or "").strip()
    try:
        r = httpx.get(
            f"{GITHUB_API}/user",
            headers={**GITHUB_HEADERS_BASE, "Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise GhApiError(f"GET /user failed: {type(e).__name__}: {e}") from e
    if r.status_code != 200:
        raise GhApiError(
            f"GET /user → HTTP {r.status_code}: {r.text[:200]}"
        )
    try:
        login = r.json().get("login")
    except ValueError as e:
        raise GhApiError(f"GET /user returned non-JSON: {e}") from e
    if not isinstance(login, str) or not login.strip():
        raise GhApiError("GET /user response missing 'login'")
    return login


def _detect_owner_via_cli() -> str:
    try:
        proc = subprocess.run(
            ["gh", "api", "user", "-q", ".login"],
            capture_output=True, text=True, timeout=15.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise GhCliError(f"gh api user failed: {type(e).__name__}: {e}") from e
    if proc.returncode != 0:
        raise GhCliError(
            f"gh api user → exit {proc.returncode}: {proc.stderr.strip()[:200]}"
        )
    login = proc.stdout.strip()
    if not login:
        raise GhCliError("gh api user returned empty output")
    return login


# ---- repo get + create ---------------------------------------------


def get_repo(owner: str, name: str) -> Optional[RepoInfo]:
    """Idempotency probe — returns RepoInfo if the repo exists, None
    if it doesn't, raises on transport / auth errors."""
    path = ensure_auth()
    if path == "token":
        return _get_repo_via_token(owner, name)
    return _get_repo_via_cli(owner, name)


def _get_repo_via_token(owner: str, name: str) -> Optional[RepoInfo]:
    token = (get_key("GITHUB_TOKEN") or "").strip()
    try:
        r = httpx.get(
            f"{GITHUB_API}/repos/{owner}/{name}",
            headers={**GITHUB_HEADERS_BASE, "Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise GhApiError(
            f"GET /repos/{owner}/{name} failed: {type(e).__name__}: {e}"
        ) from e
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise GhApiError(
            f"GET /repos/{owner}/{name} → HTTP {r.status_code}: {r.text[:200]}"
        )
    return _repo_info_from_json(r.json(), created=False)


def _get_repo_via_cli(owner: str, name: str) -> Optional[RepoInfo]:
    slug = f"{owner}/{name}"
    try:
        proc = subprocess.run(
            ["gh", "repo", "view", slug, "--json",
             "name,owner,nameWithOwner,sshUrl,url,isPrivate,defaultBranchRef"],
            capture_output=True, text=True, timeout=15.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise GhCliError(f"gh repo view failed: {type(e).__name__}: {e}") from e
    if proc.returncode != 0:
        # gh prints "Could not resolve to a Repository" to stderr on 404.
        if "could not resolve" in proc.stderr.lower() or "not found" in proc.stderr.lower():
            return None
        raise GhCliError(
            f"gh repo view {slug} → exit {proc.returncode}: {proc.stderr.strip()[:200]}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise GhCliError(f"gh repo view returned non-JSON: {e}") from e
    return _repo_info_from_gh_cli_json(data, created=False)


def ensure_repo(name: str, *, owner: Optional[str] = None,
                private: bool = False) -> RepoInfo:
    """Idempotent create — detect existing repo or create new one.

    `owner=None` resolves via `detect_gh_owner()` first.
    `private=False` creates a public repo (matches existing
    `_deploy_cf_pages_v3c` default).
    """
    resolved_owner = owner if owner else detect_gh_owner()
    existing = get_repo(resolved_owner, name)
    if existing is not None:
        return existing
    return _create_repo(name, owner=resolved_owner, private=private)


def _create_repo(name: str, *, owner: str, private: bool) -> RepoInfo:
    path = ensure_auth()
    if path == "token":
        return _create_repo_via_token(name, owner=owner, private=private)
    return _create_repo_via_cli(name, owner=owner, private=private)


def _create_repo_via_token(name: str, *, owner: str, private: bool) -> RepoInfo:
    token = (get_key("GITHUB_TOKEN") or "").strip()
    # POST /user/repos creates under the authenticated user. We don't
    # support org repos in v15.I (would need POST /orgs/{org}/repos).
    try:
        r = httpx.post(
            f"{GITHUB_API}/user/repos",
            headers={**GITHUB_HEADERS_BASE, "Authorization": f"Bearer {token}"},
            json={"name": name, "private": private, "auto_init": False},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise GhApiError(
            f"POST /user/repos failed: {type(e).__name__}: {e}"
        ) from e
    if r.status_code == 201:
        return _repo_info_from_json(r.json(), created=True)
    # 422 = name conflict (someone else created it under same login in
    # the race window). Re-fetch as detection.
    if r.status_code == 422:
        existing = _get_repo_via_token(owner, name)
        if existing is not None:
            return existing
    raise GhApiError(
        f"POST /user/repos → HTTP {r.status_code}: {r.text[:200]}"
    )


def _create_repo_via_cli(name: str, *, owner: str, private: bool) -> RepoInfo:
    slug = f"{owner}/{name}"
    args = ["gh", "repo", "create", slug, "--description", "", "--disable-issues=false"]
    args.append("--private" if private else "--public")
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=30.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise GhCliError(
            f"gh repo create failed: {type(e).__name__}: {e}"
        ) from e
    if proc.returncode != 0:
        # `gh repo create` errors with "Name already exists" if the repo's
        # already there. Surface as detection.
        stderr = proc.stderr.lower()
        if "already exists" in stderr or "name already" in stderr:
            existing = _get_repo_via_cli(owner, name)
            if existing is not None:
                return existing
        raise GhCliError(
            f"gh repo create {slug} → exit {proc.returncode}: "
            f"{proc.stderr.strip()[:200]}"
        )
    # `gh repo create` prints the URL to stdout. Re-fetch via API for
    # the full structured response.
    existing = _get_repo_via_cli(owner, name)
    if existing is None:
        raise GhCliError(
            f"gh repo create {slug} reported success but repo not found"
        )
    # Override `created` flag — this run did create it.
    return RepoInfo(
        owner=existing.owner, name=existing.name,
        full_name=existing.full_name,
        clone_url_ssh=existing.clone_url_ssh,
        clone_url_https=existing.clone_url_https,
        private=existing.private,
        default_branch=existing.default_branch,
        created=True,
    )


# ---- git remote + push ---------------------------------------------


def ensure_origin_remote(project_dir: Path, clone_url: str) -> bool:
    """Idempotent `git remote add origin <url>`. Returns True if a
    new remote was added; False if `origin` already pointed at the
    expected URL.

    If `origin` exists but points elsewhere, raises GhError — operator
    must reconcile manually.
    """
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_dir),
            capture_output=True, text=True, timeout=10.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise GhError(f"git remote get-url failed: {type(e).__name__}: {e}") from e

    if proc.returncode == 0:
        current = proc.stdout.strip()
        if current == clone_url:
            return False
        raise GhError(
            f"origin already points to {current!r} but expected {clone_url!r}. "
            f"Operator must reconcile (e.g. `git remote set-url origin {clone_url}`)."
        )

    # `origin` doesn't exist — add it.
    add = subprocess.run(
        ["git", "remote", "add", "origin", clone_url],
        cwd=str(project_dir),
        capture_output=True, text=True, timeout=10.0, check=False,
    )
    if add.returncode != 0:
        raise GhError(
            f"git remote add origin → exit {add.returncode}: "
            f"{add.stderr.strip()[:200]}"
        )
    return True


def push_to_origin(project_dir: Path, *, branch: str = "main") -> bool:
    """Idempotent `git push -u origin <branch>`. Returns True if a
    push happened; False if local was already up-to-date with remote.

    Detects "already up-to-date" via git's standard output text.
    """
    try:
        proc = subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=str(project_dir),
            capture_output=True, text=True, timeout=60.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise GhError(f"git push failed: {type(e).__name__}: {e}") from e

    combined = (proc.stdout + proc.stderr).lower()
    if proc.returncode == 0:
        # `Everything up-to-date` or new push — both are success.
        return "everything up-to-date" not in combined
    raise GhError(
        f"git push → exit {proc.returncode}: {proc.stderr.strip()[:200]}"
    )


# ---- local-origin readers (slug-mismatch fix; 2026-05-27) -----------


def read_local_origin(project_dir: Path) -> Optional[str]:
    """Return the value of `git remote get-url origin` for project_dir,
    or None if origin isn't set / git isn't installed / the dir isn't
    a repo. Never raises.

    Used by the deploy pipeline to detect when an operator's local
    repo already points at a GH name that differs from lamill's
    TLD-stripped default (e.g. `kwizicle.com.git` vs `kwizicle.git`).
    """
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_dir),
            capture_output=True, text=True, timeout=10.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    url = proc.stdout.strip()
    return url or None


@dataclass(frozen=True)
class ParsedRemote:
    owner: str
    name: str


def parse_github_remote(url: str) -> Optional[ParsedRemote]:
    """Parse a GitHub remote URL into (owner, name), or None if it
    isn't a recognizable GitHub URL.

    Accepts the four shapes git emits:
      - `git@github.com:owner/name.git` (SSH)
      - `ssh://git@github.com/owner/name.git`
      - `https://github.com/owner/name.git`
      - `https://github.com/owner/name` (no `.git` suffix)

    Returns None for non-GitHub hosts and malformed inputs. Does not
    lowercase — the repo name on GH is case-preserving even though
    lookups are case-insensitive.
    """
    if not url:
        return None
    s = url.strip()

    # SSH shorthand: git@github.com:owner/name(.git)?
    if s.startswith("git@github.com:"):
        path = s[len("git@github.com:"):]
    elif s.startswith("ssh://git@github.com/"):
        path = s[len("ssh://git@github.com/"):]
    elif s.startswith("https://github.com/"):
        path = s[len("https://github.com/"):]
    elif s.startswith("http://github.com/"):
        path = s[len("http://github.com/"):]
    else:
        return None

    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return ParsedRemote(owner=parts[0], name=parts[1])


# ---- internal: JSON → RepoInfo -------------------------------------


def _repo_info_from_json(payload: dict, *, created: bool) -> RepoInfo:
    """Shape from `POST /user/repos` + `GET /repos/{owner}/{repo}`."""
    owner_login = (payload.get("owner") or {}).get("login")
    name = payload.get("name")
    full_name = payload.get("full_name")
    clone_https = payload.get("clone_url")
    clone_ssh = payload.get("ssh_url")
    private = bool(payload.get("private"))
    default_branch = payload.get("default_branch") or "main"
    if not all([owner_login, name, full_name, clone_https, clone_ssh]):
        raise GhApiError(
            f"Repo JSON missing required fields: "
            f"owner={owner_login} name={name} full_name={full_name}"
        )
    return RepoInfo(
        owner=owner_login, name=name, full_name=full_name,
        clone_url_ssh=clone_ssh, clone_url_https=clone_https,
        private=private, default_branch=default_branch,
        created=created,
    )


def _repo_info_from_gh_cli_json(payload: dict, *, created: bool) -> RepoInfo:
    """Shape from `gh repo view --json` — slightly different field names."""
    owner_dict = payload.get("owner") or {}
    owner_login = owner_dict.get("login") or owner_dict.get("name")
    name = payload.get("name")
    full = payload.get("nameWithOwner") or (
        f"{owner_login}/{name}" if owner_login and name else None
    )
    clone_ssh = payload.get("sshUrl")
    clone_https = payload.get("url") or (
        f"https://github.com/{full}.git" if full else None
    )
    private = bool(payload.get("isPrivate"))
    default_branch_ref = payload.get("defaultBranchRef") or {}
    default_branch = default_branch_ref.get("name") if isinstance(default_branch_ref, dict) else None
    default_branch = default_branch or "main"
    if not all([owner_login, name, full, clone_ssh, clone_https]):
        raise GhCliError(
            f"gh repo view JSON missing required fields: "
            f"owner={owner_login} name={name} nameWithOwner={full}"
        )
    return RepoInfo(
        owner=owner_login, name=name, full_name=full,
        clone_url_ssh=clone_ssh, clone_url_https=clone_https,
        private=private, default_branch=default_branch,
        created=created,
    )
