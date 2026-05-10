"""CHECK_026 — docs/CLAUDE.md has minimum sections (## Project, ## Commands)."""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import (
    FixResult, FixerSpec, _append_section, _has_section_heading,
    ai_fixer_factory, project_context,
)
from ... import templates

CHECK_ID = "CHECK_026"
CHECK_NAME = "claude-md-min-sections"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/CLAUDE.md declares both `## Project` and `## Commands` sections."

_REQUIRED = ("Project", "Commands")


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "CLAUDE.md"
    if not p.is_file():
        return CheckResult(status="warn", message="docs/CLAUDE.md missing — skipped")
    text = p.read_text(errors="replace")
    headings = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    headings_norm = {h.strip().lower() for h in headings}
    missing = [h for h in _REQUIRED if h.lower() not in headings_norm]
    if not missing:
        return CheckResult(status="pass", message="`## Project` + `## Commands` present")
    return CheckResult(status="fail",
                       message=f"missing section(s): {', '.join('## ' + m for m in missing)}")


# Tier 1: append both `## Project` and `## Commands` headings (idempotent
# per-section). Tier 2 (below) replaces placeholder content with real text.
def _fix_check_026_tier_1(project_dir, dry_run, assume_yes):
    target = project_dir / "docs" / "CLAUDE.md"
    if not target.is_file():
        return FixResult("manual",
                         "docs/CLAUDE.md doesn't exist — fix CHECK_006 first",
                         [])
    text = target.read_text()
    added: list[str] = []
    if not _has_section_heading(text, "Project"):
        text = _append_section(text, templates.claude_md_section_project(project_dir.name))
        added.append("## Project")
    if not _has_section_heading(text, "Commands"):
        text = _append_section(text, templates.claude_md_section_commands())
        added.append("## Commands")
    if not added:
        return FixResult("nothing-to-do",
                         "docs/CLAUDE.md already has both sections", [])
    if dry_run:
        return FixResult("would-fix",
                         f"append {' + '.join(added)} to docs/CLAUDE.md",
                         [target])
    target.write_text(text + "\n")
    return FixResult("fixed",
                     f"appended {' + '.join(added)} to docs/CLAUDE.md",
                     [target])


fix_tier_1 = FixerSpec(
    check_id="", tier=1,
    summary="append ## Project + ## Commands to docs/CLAUDE.md",
    apply=_fix_check_026_tier_1,
)


# Tier 2 (v6.C.1): spawn `claude -p` to fill the sections with content
# specific to this project, drawn from AI_AGENTS.md + package.json + ...
def _prompt_tier_2(project_dir):
    domain = project_dir.name
    return f"""You are improving `docs/CLAUDE.md` for {domain}.

The file already has the required `## Project` and `## Commands`
section headings (added by Tier 1), but the content under them is
generic placeholder text. Replace the placeholders with content
specific to this project, drawn from the context below.

Edit ONLY `docs/CLAUDE.md`. Do not touch any other file.

For `## Project`: 1-2 sentences saying what {domain} actually does
(its real topic), who the target user is, and the stack. Use the
project's AI_AGENTS.md as the source of truth.

For `## Commands`: replace generic placeholders with the actual
commands this project uses — read the Makefile, package.json
scripts, pyproject.toml scripts to figure out what's there.

Don't invent users or numbers. Keep it concise — this is orientation
for future Claude sessions, not a sales page.

Project context:
{project_context(project_dir)}
"""


fix_tier_2 = ai_fixer_factory(
    "CHECK_026", _prompt_tier_2,
    summary="fill docs/CLAUDE.md Project + Commands with real content",
)
