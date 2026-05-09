"""CHECK_021 — Last commit within 30 days.

`pass` when last commit < 30 days ago, `warn` when 30–60, `fail` when
> 60 days. No commits at all → fail with "no commits yet".
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_021"
CHECK_NAME = "last-commit-30d"
CATEGORY = "git"
SEVERITY = "warn"
DESCRIPTION = "Last commit within 30 days (warn at 30-60, fail at >60)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    if not (p / ".git").exists():
        return CheckResult(status="warn", message="no .git — can't check")
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct"],
            cwd=p, capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(status="warn", message=f"git: {type(e).__name__}")
    if result.returncode != 0 or not result.stdout.strip():
        return CheckResult(status="fail", message="no commits yet")
    try:
        ts = int(result.stdout.strip())
    except ValueError:
        return CheckResult(status="warn", message="couldn't parse commit timestamp")
    age_days = (datetime.now(timezone.utc).timestamp() - ts) / 86400
    if age_days <= 30:
        return CheckResult(status="pass", message=f"last commit {age_days:.0f}d ago")
    if age_days <= 60:
        return CheckResult(status="warn", message=f"last commit {age_days:.0f}d ago")
    return CheckResult(status="fail", message=f"last commit {age_days:.0f}d ago (dormant)")
