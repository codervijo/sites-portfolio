"""CHECK_034 — No yarn.lock (pnpm-only convention)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_034"
CHECK_NAME = "no-yarn-lock"
CATEGORY = "stack"
SEVERITY = "error"
DESCRIPTION = "No yarn.lock (sites/* uses pnpm exclusively)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if (Path(repo_path) / "yarn.lock").is_file():
        return CheckResult(status="fail",
                           message="yarn.lock present (delete it; pnpm-only)")
    return CheckResult(status="pass", message="no yarn.lock")
