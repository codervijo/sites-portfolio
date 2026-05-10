"""CHECK_009 — Has .gitignore at repo root."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_writer
from ... import templates

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


fix_tier_1 = file_writer(
    ".gitignore",
    render=lambda _p: templates.gitignore(),
    summary="write standard .gitignore",
)
