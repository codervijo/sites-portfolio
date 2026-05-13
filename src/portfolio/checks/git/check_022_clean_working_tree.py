"""CHECK_022 — No uncommitted changes (clean working tree)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_022"
CHECK_NAME = "clean-working-tree"
CATEGORY = "git"
SEVERITY = "warn"
DESCRIPTION = "Working tree is clean (no uncommitted modifications)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    if not (p / ".git").exists():
        return CheckResult(status="warn", message="no .git — skipped")
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=p, capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(status="warn", message=f"git: {type(e).__name__}")
    if result.returncode != 0:
        return CheckResult(status="warn",
                           message=f"git status failed: {result.stderr.strip()}")
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        return CheckResult(status="pass", message="clean")
    return CheckResult(status="warn",
                       message=f"{len(lines)} uncommitted change(s)")
