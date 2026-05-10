"""CHECK_003 — AI_AGENTS.md contains a `## Building info` section."""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import section_inject
from ... import templates

CHECK_ID = "CHECK_003"
CHECK_NAME = "ai-agents-md-has-building-info"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "AI_AGENTS.md has a `## Building info` heading (referencing the central builder + ../Makefile)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "AI_AGENTS.md"
    if not p.exists():
        return CheckResult(status="fail", message="AI_AGENTS.md missing")
    text = p.read_text(errors="replace")
    if re.search(r"^## +Building info\b", text, re.MULTILINE | re.IGNORECASE):
        return CheckResult(status="pass", message="`## Building info` section present")
    return CheckResult(status="fail", message="AI_AGENTS.md missing `## Building info` heading")


fix_tier_1 = section_inject(
    "AI_AGENTS.md", "Building info",
    render=lambda _p: templates.ai_agents_section_building(),
    summary="append ## Building info to AI_AGENTS.md",
)
