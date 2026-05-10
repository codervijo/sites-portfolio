"""CHECK_033 — No bun.lockb (pnpm-only convention)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_deleter
from . import _is_web_project

CHECK_ID = "CHECK_033"
CHECK_NAME = "no-bun-lockb"
CATEGORY = "stack"
SEVERITY = "error"
DESCRIPTION = "No bun.lockb (sites/* uses pnpm; bun trips CF Pages auto-detect)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if (Path(repo_path) / "bun.lockb").is_file():
        return CheckResult(status="fail",
                           message="bun.lockb present (delete; CF Pages will pick bun and break)")
    return CheckResult(status="pass", message="no bun.lockb")


fix_tier_1 = file_deleter(
    "bun.lockb",
    summary="delete bun.lockb (pnpm-only convention)",
)
