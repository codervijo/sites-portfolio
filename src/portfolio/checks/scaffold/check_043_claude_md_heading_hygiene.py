"""CHECK_043 — docs/CLAUDE.md has a `## Heading hygiene` section.

Fleet-wide rule introduced 2026-05-18: every sibling project's
docs/CLAUDE.md should declare a `## Heading hygiene` section
documenting the pre-edit outline ritual (grep the heading outline,
confirm depth/label don't collide before writing). Lesson from
sites/portfolio's docs/prd.md drift where four detailed-PRD bodies
got inlined at `##` heading depth, creating parallel
`## 1. Problem statement` collisions with the file's top-level
`## 1. Purpose`.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import section_inject
from ... import templates

CHECK_ID = "CHECK_043"
CHECK_NAME = "claude-md-heading-hygiene"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/CLAUDE.md declares a `## Heading hygiene` section."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "CLAUDE.md"
    if not p.is_file():
        return CheckResult(status="warn", message="docs/CLAUDE.md missing — skipped")
    text = p.read_text(errors="replace")
    # Same case-insensitive + numeric-prefix-tolerant pattern fix_helpers uses.
    pattern = r"^##\s+(?:\d+\.\s*)?Heading hygiene\s*$"
    if re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE):
        return CheckResult(status="pass", message="`## Heading hygiene` present")
    return CheckResult(status="fail",
                       message="missing section: `## Heading hygiene`")


# Tier 1: append the canonical Heading hygiene section using the shared
# emitter in templates.py. Idempotent — section_inject skips if heading
# is already present.
fix_tier_1 = section_inject(
    "docs/CLAUDE.md",
    "Heading hygiene",
    render=lambda _project_dir: templates.claude_md_section_heading_hygiene(),
    summary="append `## Heading hygiene` section to docs/CLAUDE.md",
)
