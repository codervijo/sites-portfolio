"""CHECK_040 — git remote name matches the project's full domain.

Naming convention for the portfolio: each `sites/<domain>/` standalone
repo should publish to `<owner>/<domain>` on GitHub, where `<domain>`
is the full domain including TLD (e.g., `codervijo/airsucks.com`, not
`codervijo/airsucks`).

The convention exists so that finding a project's GitHub repo from the
filesystem layout (or vice versa) is mechanical — no need to remember
which repos got their TLDs trimmed. Today's fleet has a mix:

  ✓ codervijo/airsucks.com         (full)
  ✓ codervijo/hybridautopart.com   (full)
  ✓ codervijo/lamill.io            (full)
  ✗ codervijo/csinorcal            (truncated — should be csinorcal.church)
  ✗ codervijo/keralavotemap        (truncated — should be keralavotemap.site)

This check does not auto-rename existing remotes — that would break
deploy hooks (Vercel/CF Pages auto-deploy is wired to the repo URL).
It flags violations so the user can do the rename + redeploy-config
update manually when convenient.

Pass / fail / skip:
  - pass:  origin remote URL path ends with `<basename>.git` where
           basename matches the project directory name
  - fail:  origin remote exists but the URL path doesn't end with
           the expected basename
  - warn:  no `origin` remote configured (CHECK_020 covers the
           "needs a repo" gap; this check is only meaningful when
           a remote exists)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_040"
CHECK_NAME = "git-remote-name-matches-domain"
CATEGORY = "git"
SEVERITY = "warn"
DESCRIPTION = (
    "Origin remote name matches the project's full domain "
    "(e.g., codervijo/airsucks.com — not codervijo/airsucks)."
)


def _repo_basename(remote_url: str) -> str | None:
    """Extract the trailing `<basename>` from a remote URL.

    Handles both SSH (`git@github.com:owner/repo.git`) and HTTPS
    (`https://github.com/owner/repo.git`) formats, with or without
    the `.git` suffix.
    """
    # Strip protocol prefix + owner; we only care about the trailing component.
    # SSH: git@host:owner/repo[.git]
    # HTTPS: https://host/owner/repo[.git]
    m = re.search(r"[/:]([^/:]+)/?$", remote_url.strip().rstrip("/"))
    if not m:
        return None
    basename = m.group(1)
    if basename.endswith(".git"):
        basename = basename[:-4]
    return basename or None


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    # Skip archived/tombstoned sites — naming violations don't matter
    # for a project being wound down.
    try:
        from ...fleet_repos import _archived_reason
        if _archived_reason(p) is not None:
            return CheckResult(
                status="warn",
                message=f"archived — skipped",
            )
    except Exception:
        pass
    if not (p / ".git").exists():
        # CHECK_020 handles the "no .git at all" case.
        return CheckResult(status="warn", message="no .git directory — skipped")
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=p, capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(status="warn", message=f"git: {type(e).__name__}")
    if result.returncode != 0:
        return CheckResult(status="warn", message="no origin remote — skipped")
    remote_url = result.stdout.strip()
    if not remote_url:
        return CheckResult(status="warn", message="empty origin remote — skipped")

    basename = _repo_basename(remote_url)
    expected = p.name
    if basename is None:
        return CheckResult(status="fail",
                           message=f"could not parse remote URL: {remote_url!r}")
    if basename == expected:
        return CheckResult(status="pass", message=f"origin → {basename}")
    return CheckResult(status="fail",
                       message=(f"origin → {basename}; expected {expected} "
                                f"(full-domain naming convention)"))
