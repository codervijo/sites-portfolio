"""CHECK_004 — AI_AGENTS.md contains a `## Deployment info` section."""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import section_inject
from ... import templates

CHECK_ID = "CHECK_004"
CHECK_NAME = "ai-agents-md-has-deployment-info"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "AI_AGENTS.md has a `## Deployment info` heading (platform / live URL / deploy trigger)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "AI_AGENTS.md"
    if not p.exists():
        return CheckResult(status="fail", message="AI_AGENTS.md missing")
    text = p.read_text(errors="replace")
    if re.search(r"^## +Deployment info\b", text, re.MULTILINE | re.IGNORECASE):
        return CheckResult(status="pass", message="`## Deployment info` section present")
    return CheckResult(status="fail", message="AI_AGENTS.md missing `## Deployment info` heading")


fix_tier_1 = section_inject(
    "AI_AGENTS.md", "Deployment info",
    render=lambda _p: templates.ai_agents_section_deployment(),
    summary="append ## Deployment info to AI_AGENTS.md",
)
