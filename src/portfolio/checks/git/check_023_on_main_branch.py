"""CHECK_023 — On branch main (not on a feature branch)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_023"
CHECK_NAME = "on-main-branch"
CATEGORY = "git"
SEVERITY = "info"
DESCRIPTION = "Current branch is `main` (info — feature branches are normal mid-work)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    if not (p / ".git").exists():
        return CheckResult(status="warn", message="no .git — skipped")
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=p, capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(status="warn", message=f"git: {type(e).__name__}")
    if result.returncode != 0:
        return CheckResult(status="warn",
                           message=f"detached HEAD or unknown branch: {result.stderr.strip()}")
    branch = result.stdout.strip()
    if branch in ("main", "master"):
        return CheckResult(status="pass", message=f"on {branch}")
    return CheckResult(status="warn", message=f"on feature branch {branch!r}")
