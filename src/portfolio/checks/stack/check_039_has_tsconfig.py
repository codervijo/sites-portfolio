"""CHECK_039 — TypeScript config present (info — TS adoption signal)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_039"
CHECK_NAME = "has-tsconfig"
CATEGORY = "stack"
SEVERITY = "info"
DESCRIPTION = "tsconfig.json present (info — TypeScript adoption signal)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if (Path(repo_path) / "tsconfig.json").is_file():
        return CheckResult(status="pass", message="tsconfig.json present")
    return CheckResult(status="warn", message="tsconfig.json missing (no TypeScript)")
