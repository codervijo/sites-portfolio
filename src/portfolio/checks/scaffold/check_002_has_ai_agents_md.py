"""CHECK_002 — Has AI_AGENTS.md at repo root.

Note: separate from `docs/CLAUDE.md` (CHECK_006). AI_AGENTS.md is the
project-orientation doc at the root; docs/CLAUDE.md is the per-project
Claude-specific guidance file inside docs/.
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_writer
from ... import templates

CHECK_ID = "CHECK_002"
CHECK_NAME = "has-ai-agents-md"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "AI_AGENTS.md exists at repo root."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "AI_AGENTS.md"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message="AI_AGENTS.md present")
    return CheckResult(status="fail", message="AI_AGENTS.md missing at repo root")


fix_tier_1 = file_writer(
    "AI_AGENTS.md",
    render=lambda p: templates.ai_agents_md(p.name),
    summary="write AI_AGENTS.md (with Building/Deployment sections)",
)
