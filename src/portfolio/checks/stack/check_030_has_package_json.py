"""CHECK_030 — Has package.json (web project)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_030"
CHECK_NAME = "has-package-json"
CATEGORY = "stack"
SEVERITY = "info"
DESCRIPTION = "package.json exists at repo root (web project marker)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "package.json"
    if p.is_file():
        return CheckResult(status="pass", message="package.json present")
    return CheckResult(status="warn",
                       message="not a web project — skipped")
