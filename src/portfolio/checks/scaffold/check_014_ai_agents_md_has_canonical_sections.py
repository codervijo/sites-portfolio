"""CHECK_014 — AI_AGENTS.md has all 10 canonical H2 sections.

Enforces the v9.A schema defined in `portfolio.canonical_sections`:
Summary, Audience, ICP, Goals, Tech stack, Building info,
Deployment info, Content strategy, Versioning, Conventions.

Five of those are operator-input (the bootstrap interactive
prompts in v9.B collect them at scaffold time); five are
template-driven (the bootstrap template renderer populates them).
The check doesn't distinguish — every section must be present
regardless of source. The tier-1 fix appends missing sections with
a `(to be filled in)` body that's intentionally obvious so
`project check <domain>` keeps the row visible until the operator
populates it.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...canonical_sections import AI_AGENTS_SECTIONS
from ...fix_helpers import FixResult, FixerSpec

CHECK_ID = "CHECK_014"
CHECK_NAME = "ai-agents-md-has-canonical-sections"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = (
    "AI_AGENTS.md has all 10 canonical H2 sections (Summary / Audience / "
    "ICP / Goals / Tech stack / Building info / Deployment info / "
    "Content strategy / Versioning / Conventions)."
)


def _existing_headings(text: str) -> set[str]:
    """Return the H2 heading names present in `text`, normalized to
    lowercase + stripped. Matches the same approach CHECK_026 uses
    for CLAUDE.md sections so missing-headings logic is consistent
    across the codebase."""
    return {
        h.strip().lower()
        for h in re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    }


def _missing_sections(text: str) -> list[str]:
    """Canonical sections (by heading) NOT present in `text`. Order
    is preserved from `AI_AGENTS_SECTIONS` so the tier-1 fix appends
    them in the canonical order, matching what the bootstrap template
    renderer produces."""
    headings = _existing_headings(text)
    return [s.heading for s in AI_AGENTS_SECTIONS
            if s.heading.lower() not in headings]


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "AI_AGENTS.md"
    if not p.is_file():
        # CHECK_002 (has-ai-agents-md) handles the absent-file case;
        # this check rides on top of that. Warn-skip to avoid
        # double-counting the same problem.
        return CheckResult(status="warn",
                           message="AI_AGENTS.md missing — skipped (see CHECK_002)")
    text = p.read_text(errors="replace")
    missing = _missing_sections(text)
    if not missing:
        return CheckResult(
            status="pass",
            message=f"all {len(AI_AGENTS_SECTIONS)} canonical sections present",
        )
    return CheckResult(
        status="fail",
        message=f"missing {len(missing)}/{len(AI_AGENTS_SECTIONS)} canonical "
                f"section(s): {', '.join('## ' + m for m in missing)}",
    )


def _fix_tier_1(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    """Append any missing canonical sections to AI_AGENTS.md.

    Idempotent — sections already present are left alone. Operator-
    input sections get a `(to be filled in)` placeholder body so
    `project check` keeps the row visible until populated; template-
    driven sections get a short hint pointing at where the canonical
    content should come from (full template population is the
    bootstrap renderer's job in v9.B, not this fixer's).

    Returns "manual" if AI_AGENTS.md doesn't exist — CHECK_002's
    fixer is the right hammer for that.
    """
    target = project_dir / "AI_AGENTS.md"
    if not target.is_file():
        return FixResult(
            status="manual",
            summary="AI_AGENTS.md doesn't exist — run fix on CHECK_002 first",
            files_touched=[],
        )
    text = target.read_text()
    missing = _missing_sections(text)
    if not missing:
        return FixResult(
            status="nothing-to-do",
            summary=f"AI_AGENTS.md already has all "
                    f"{len(AI_AGENTS_SECTIONS)} canonical sections",
            files_touched=[],
        )

    # Pre-compute the bodies we'd append so dry-run can report length.
    appended = _render_missing_sections(missing)
    if dry_run:
        return FixResult(
            status="would-fix",
            summary=f"append {len(missing)} missing section(s) to "
                    f"AI_AGENTS.md: {', '.join('## ' + m for m in missing)}",
            files_touched=[target],
        )
    # Append at the end; preserve a single trailing newline.
    new_text = text.rstrip() + "\n\n" + appended.rstrip() + "\n"
    target.write_text(new_text)
    return FixResult(
        status="fixed",
        summary=f"appended {len(missing)} canonical section(s) to AI_AGENTS.md "
                f"({', '.join('## ' + m for m in missing)})",
        files_touched=[target],
    )


def _render_missing_sections(missing: list[str]) -> str:
    """Return the markdown block to append for the given list of
    missing section headings. Each section gets an H2, a one-line
    description from the canonical list, and a placeholder body.

    Operator-input sections get `(to be filled in)`. Template-driven
    sections get a `(to be filled in by bootstrap template renderer)`
    hint so the operator knows that section is the tool's
    responsibility, not theirs — keeps the operator from
    hand-writing tech-stack details that v9.B's renderer will
    overwrite.
    """
    by_heading = {s.heading: s for s in AI_AGENTS_SECTIONS}
    blocks: list[str] = []
    for h in missing:
        spec = by_heading[h]
        placeholder = (
            "(to be filled in)"
            if spec.source == "operator"
            else "(to be filled in by bootstrap template renderer)"
        )
        blocks.append(
            f"## {h}\n\n"
            f"*{spec.description}*\n\n"
            f"{placeholder}\n"
        )
    return "\n".join(blocks)


fix_tier_1 = FixerSpec(
    check_id="",       # registry rewrites at discovery time
    tier=1,
    summary="append missing canonical sections to AI_AGENTS.md",
    apply=_fix_tier_1,
)
