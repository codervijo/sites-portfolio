"""CHECK_010 — Has tests directory.

Accepts `tests/`, `test/`, or `src/__tests__/`. Not all projects have
tests yet — informational severity, not a hard requirement.
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_010"
CHECK_NAME = "has-tests"
CATEGORY = "scaffold"
SEVERITY = "info"
DESCRIPTION = "Has tests directory (tests/, test/, or src/__tests__/)."


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    for rel in ("tests", "test", "src/__tests__"):
        if (base / rel).is_dir():
            return CheckResult(status="pass", message=f"{rel}/ present")
    return CheckResult(status="warn", message="no tests/ or src/__tests__/ found")
