"""CHECK_007 — Has docs/Prompts.md (or docs/prompts.md).

Stored prompts log per project. Convention is `Prompts.md` (capital P) but
we accept the lowercase form too since some projects use that.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_writer
from ... import templates

CHECK_ID = "CHECK_007"
CHECK_NAME = "has-docs-prompts"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/Prompts.md exists — stored-prompts log."


def run(repo_path: str) -> CheckResult:
    docs = Path(repo_path) / "docs"
    for name in ("Prompts.md", "prompts.md"):
        if (docs / name).is_file():
            return CheckResult(status="pass", message=f"docs/{name} present")
    return CheckResult(status="fail", message="docs/Prompts.md missing")


fix_tier_1 = file_writer(
    "docs/Prompts.md",
    render=lambda p: templates.docs_prompts_md(p.name, date.today().isoformat()),
    summary="write docs/Prompts.md skeleton",
)
