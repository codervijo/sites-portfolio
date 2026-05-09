"""CHECK_006 — Has docs/CLAUDE.md.

Per portfolio convention (locked 2026-05-09): every project has a
`docs/CLAUDE.md` for Claude-specific orientation, separate from the
root-level `AI_AGENTS.md` (CHECK_002).
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_006"
CHECK_NAME = "has-docs-claude"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "docs/CLAUDE.md exists — per-project Claude-specific orientation."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "CLAUDE.md"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message="docs/CLAUDE.md present")
    return CheckResult(status="fail", message="docs/CLAUDE.md missing")
