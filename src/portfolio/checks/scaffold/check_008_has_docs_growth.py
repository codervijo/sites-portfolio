"""CHECK_008 — Has docs/growth.md (per-project growth-experiment log)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_writer
from ... import templates

CHECK_ID = "CHECK_008"
CHECK_NAME = "has-docs-growth"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/growth.md exists — per-project growth-experiment log."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "growth.md"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message="docs/growth.md present")
    return CheckResult(status="fail", message="docs/growth.md missing")


fix_tier_1 = file_writer(
    "docs/growth.md",
    render=lambda p: templates.docs_growth_md(p.name, date.today().isoformat()),
    summary="write docs/growth.md skeleton",
)
