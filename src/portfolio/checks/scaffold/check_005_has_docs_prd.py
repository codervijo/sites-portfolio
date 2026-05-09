"""CHECK_005 — Has docs/prd.md."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_005"
CHECK_NAME = "has-docs-prd"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/prd.md exists — single source of truth for project spec/roadmap."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "prd.md"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message="docs/prd.md present")
    return CheckResult(status="fail", message="docs/prd.md missing")
