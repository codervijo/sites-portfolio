"""CHECK_007 — Has docs/Prompts.md (or docs/prompts.md).

Stored prompts log per project. Convention is `Prompts.md` (capital P) but
we accept the lowercase form too since some projects use that.
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_007"
CHECK_NAME = "has-docs-prompts"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "docs/Prompts.md exists — stored-prompts log."


def run(repo_path: str) -> CheckResult:
    docs = Path(repo_path) / "docs"
    for name in ("Prompts.md", "prompts.md"):
        if (docs / name).is_file():
            return CheckResult(status="pass", message=f"docs/{name} present")
    return CheckResult(status="fail", message="docs/Prompts.md missing")
