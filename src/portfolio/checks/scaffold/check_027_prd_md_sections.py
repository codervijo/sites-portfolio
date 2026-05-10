"""CHECK_027 — docs/prd.md has minimum sections (## Problem, ## Users)."""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import (
    FixResult, FixerSpec, _append_section, _has_section_heading,
    ai_fixer_factory, project_context,
)
from ... import templates

CHECK_ID = "CHECK_027"
CHECK_NAME = "prd-md-min-sections"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/prd.md declares both `## Problem` and `## Users` sections."

_REQUIRED = ("Problem", "Users")


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "prd.md"
    if not p.is_file():
        return CheckResult(status="warn", message="docs/prd.md missing — skipped")
    text = p.read_text(errors="replace")
    headings = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    # Permit numbered heading prefixes ("## 1. Problem", "## 2. Users").
    headings_norm = {
        re.sub(r"^\d+\.\s*", "", h.strip()).strip().lower()
        for h in headings
    }
    missing = [h for h in _REQUIRED if h.lower() not in headings_norm]
    if not missing:
        return CheckResult(status="pass", message="`## Problem` + `## Users` present")
    return CheckResult(status="fail",
                       message=f"missing section(s): {', '.join('## ' + m for m in missing)}")


def _fix_check_027_tier_1(project_dir, dry_run, assume_yes):
    target = project_dir / "docs" / "prd.md"
    if not target.is_file():
        return FixResult("manual",
                         "docs/prd.md doesn't exist — fix CHECK_005 first",
                         [])
    text = target.read_text()
    added: list[str] = []
    if not _has_section_heading(text, "Problem"):
        text = _append_section(text, templates.prd_md_section_problem())
        added.append("## Problem")
    if not _has_section_heading(text, "Users"):
        text = _append_section(text, templates.prd_md_section_users())
        added.append("## Users")
    if not added:
        return FixResult("nothing-to-do",
                         "docs/prd.md already has both sections", [])
    if dry_run:
        return FixResult("would-fix",
                         f"append {' + '.join(added)} to docs/prd.md",
                         [target])
    target.write_text(text + "\n")
    return FixResult("fixed",
                     f"appended {' + '.join(added)} to docs/prd.md",
                     [target])


fix_tier_1 = FixerSpec(
    check_id="", tier=1,
    summary="append ## Problem + ## Users to docs/prd.md",
    apply=_fix_check_027_tier_1,
)


# Tier 2 (v6.C.1): fill the sections with project-specific content via Claude.
def _prompt_tier_2(project_dir):
    domain = project_dir.name
    return f"""You are improving `docs/prd.md` for {domain}.

The file has the required `## Problem` and `## Users` sections (Tier
1 added the headings if missing), but the content is generic
placeholder. Replace placeholders with content specific to this
project.

Edit ONLY `docs/prd.md`. Do not touch any other file.

For `## Problem`: 1-2 sentences on the user-facing problem this site
solves. Concrete and specific. Don't claim numbers without
evidence — speculate carefully if needed ("we hypothesize that...").

For `## Users`: who the target user is, what they care about,
roughly how many. If you don't know, say "(estimated ~N — verify)".

Source the project's actual topic from AI_AGENTS.md and the existing
prd content. Don't invent things.

Project context:
{project_context(project_dir)}
"""


fix_tier_2 = ai_fixer_factory(
    "CHECK_027", _prompt_tier_2,
    summary="fill docs/prd.md Problem + Users with real content",
)
