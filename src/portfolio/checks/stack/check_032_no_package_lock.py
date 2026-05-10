"""CHECK_032 — No package-lock.json (pnpm-only convention)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_deleter
from . import _is_web_project

CHECK_ID = "CHECK_032"
CHECK_NAME = "no-package-lock-json"
CATEGORY = "stack"
SEVERITY = "error"
DESCRIPTION = "No package-lock.json (sites/* uses pnpm exclusively)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if (Path(repo_path) / "package-lock.json").is_file():
        return CheckResult(status="fail",
                           message="package-lock.json present (delete it; pnpm-only)")
    return CheckResult(status="pass", message="no package-lock.json")


fix_tier_1 = file_deleter(
    "package-lock.json",
    summary="delete package-lock.json (pnpm-only convention)",
)
