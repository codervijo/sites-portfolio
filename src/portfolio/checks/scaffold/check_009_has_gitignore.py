"""CHECK_009 — Has .gitignore at repo root."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_009"
CHECK_NAME = "has-gitignore"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = ".gitignore exists at repo root."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / ".gitignore"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message=".gitignore present")
    return CheckResult(status="fail", message=".gitignore missing")
