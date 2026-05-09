"""CHECK_020 — Has own .git (not tracked-by-parent).

Equivalent to v1.A's `own-git-repo` rule, restated in the new catalog
namespace. Uses `git rev-parse --show-toplevel` and confirms the result
matches the project dir itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_020"
CHECK_NAME = "own-git-repo"
CATEGORY = "git"
SEVERITY = "error"
DESCRIPTION = "Project has its own .git repo (not tracked by a parent repo)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    if not (p / ".git").exists():
        return CheckResult(status="fail", message="no .git directory at repo root")
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=p, capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(status="warn", message=f"git: {type(e).__name__}")
    if result.returncode != 0:
        return CheckResult(status="fail",
                           message=f"git rev-parse failed: {result.stderr.strip()}")
    toplevel = Path(result.stdout.strip()).resolve()
    if toplevel == p:
        return CheckResult(status="pass", message="own .git repo")
    return CheckResult(status="fail",
                       message=f"tracked by parent repo at {toplevel}")
