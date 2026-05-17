"""Tests for v9.A — CHECK_014 ai-agents-md-has-canonical-sections.

Pins the conformance behavior (pass / warn / fail across the three
states: file missing, all sections present, sections missing) and
the tier-1 fix behavior (idempotent, preserves existing content,
appends in canonical order, distinguishes operator-input vs
template placeholders).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.checks.scaffold import check_014_ai_agents_md_has_canonical_sections as mod
from portfolio.canonical_sections import AI_AGENTS_SECTIONS


def _full_ai_agents_md() -> str:
    """An AI_AGENTS.md with all 10 canonical H2 headings — the
    pass-state baseline."""
    return "\n".join(f"## {s.heading}\n\nbody\n" for s in AI_AGENTS_SECTIONS) + "\n"


def _partial_ai_agents_md(*, present_headings: list[str]) -> str:
    """An AI_AGENTS.md containing only a subset of the canonical
    headings — for the fail-state + tier-1-fix tests."""
    return "\n".join(f"## {h}\n\nbody\n" for h in present_headings) + "\n"


# ---------- run() ----------


def test_run_passes_when_all_sections_present(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(_full_ai_agents_md())
    r = mod.run(str(tmp_path))
    assert r.status == "pass"
    assert "all 10" in r.message or str(len(AI_AGENTS_SECTIONS)) in r.message


def test_run_fails_when_sections_missing(tmp_path):
    """Missing 3 sections → fail with a per-section list so the
    operator (or the tier-1 fix) knows exactly what's missing."""
    (tmp_path / "AI_AGENTS.md").write_text(
        _partial_ai_agents_md(present_headings=[
            "Summary", "Audience", "ICP", "Goals",
            "Tech stack", "Building info", "Deployment info",
        ])
    )
    r = mod.run(str(tmp_path))
    assert r.status == "fail"
    assert "## Content strategy" in r.message
    assert "## Versioning" in r.message
    assert "## Conventions" in r.message
    assert "3/10" in r.message


def test_run_warns_when_file_missing(tmp_path):
    """No AI_AGENTS.md at all → warn-skip, deferring to CHECK_002.
    Avoids double-counting the same problem."""
    r = mod.run(str(tmp_path))
    assert r.status == "warn"
    assert "CHECK_002" in r.message


def test_run_heading_match_is_case_insensitive(tmp_path):
    """`## summary` should satisfy the check (operators sometimes
    use lowercase headings). The schema is case-sensitive for the
    fix-side rendering, but matching for the check is tolerant —
    don't fail a project on a casing difference."""
    text = "\n".join(f"## {s.heading.lower()}\n\nbody\n" for s in AI_AGENTS_SECTIONS)
    (tmp_path / "AI_AGENTS.md").write_text(text)
    r = mod.run(str(tmp_path))
    assert r.status == "pass"


def test_run_tolerates_extra_sections(tmp_path):
    """A project that adds its OWN H2 sections beyond the canonical
    list (e.g., `## Custom workflow`) should still pass — the check
    is a "must contain at least" enforcement, not "must contain
    exactly"."""
    text = _full_ai_agents_md() + "\n## Custom workflow\n\nproject-specific stuff\n"
    (tmp_path / "AI_AGENTS.md").write_text(text)
    r = mod.run(str(tmp_path))
    assert r.status == "pass"


# ---------- tier-1 fix ----------


def test_fix_appends_missing_sections_in_canonical_order(tmp_path):
    """The 3 missing sections from the fail-state test should
    appear in the order they're declared in AI_AGENTS_SECTIONS,
    not the order the operator's existing file uses."""
    (tmp_path / "AI_AGENTS.md").write_text(
        _partial_ai_agents_md(present_headings=[
            "Conventions",     # canonical-last but operator put it first
            "Summary",         # canonical-first
        ])
    )
    out = mod._fix_tier_1(tmp_path, dry_run=False, assume_yes=False)
    assert out.status == "fixed"
    text = (tmp_path / "AI_AGENTS.md").read_text()
    # Appended block contains: Audience, ICP, Goals, Tech stack,
    # Building info, Deployment info, Content strategy, Versioning
    # in canonical order. Find each heading's position; assert order.
    headings_in_order = ["Audience", "ICP", "Goals", "Tech stack",
                         "Building info", "Deployment info",
                         "Content strategy", "Versioning"]
    positions = [text.index(f"## {h}") for h in headings_in_order]
    assert positions == sorted(positions)


def test_fix_preserves_existing_content(tmp_path):
    """The operator-written Summary section must not be replaced or
    duplicated when missing sections get appended."""
    existing = (
        "## Summary\n\n"
        "agesdk.dev is the operator's prized site for X.\n"
        "Multi-paragraph description goes here.\n"
    )
    (tmp_path / "AI_AGENTS.md").write_text(existing)
    mod._fix_tier_1(tmp_path, dry_run=False, assume_yes=False)
    text = (tmp_path / "AI_AGENTS.md").read_text()
    assert "agesdk.dev is the operator's prized site" in text
    # Existing Summary appears exactly once.
    assert text.count("## Summary") == 1


def test_fix_is_idempotent(tmp_path):
    """Running the fix on a file that's already complete should be
    a no-op (status=nothing-to-do, no file write)."""
    (tmp_path / "AI_AGENTS.md").write_text(_full_ai_agents_md())
    target_mtime_before = (tmp_path / "AI_AGENTS.md").stat().st_mtime
    out = mod._fix_tier_1(tmp_path, dry_run=False, assume_yes=False)
    assert out.status == "nothing-to-do"
    assert (tmp_path / "AI_AGENTS.md").stat().st_mtime == target_mtime_before


def test_fix_returns_manual_when_file_absent(tmp_path):
    """No AI_AGENTS.md → manual (deferring to CHECK_002's fixer)."""
    out = mod._fix_tier_1(tmp_path, dry_run=False, assume_yes=False)
    assert out.status == "manual"
    assert "CHECK_002" in out.summary


def test_fix_dry_run_does_not_write(tmp_path):
    target = tmp_path / "AI_AGENTS.md"
    target.write_text(_partial_ai_agents_md(present_headings=["Summary"]))
    original_text = target.read_text()
    out = mod._fix_tier_1(tmp_path, dry_run=True, assume_yes=False)
    assert out.status == "would-fix"
    assert target.read_text() == original_text   # untouched
    # Summary line in the dry-run output reports the count + names.
    assert "9 missing" in out.summary or "9/10" in out.summary or "9 " in out.summary


def test_fix_uses_operator_placeholder_for_operator_sections(tmp_path):
    """Operator-input sections (Summary, Audience, ICP, Goals,
    Content strategy) get `(to be filled in)` — short and unambiguous.
    Template-driven sections get a longer hint pointing at the
    bootstrap renderer as the source of truth (so operators don't
    hand-write tech-stack content that gets overwritten later)."""
    # Start with empty file → all 10 sections injected.
    (tmp_path / "AI_AGENTS.md").write_text("")
    mod._fix_tier_1(tmp_path, dry_run=False, assume_yes=False)
    text = (tmp_path / "AI_AGENTS.md").read_text()
    # Operator section: short placeholder.
    summary_block_start = text.index("## Summary")
    summary_block = text[summary_block_start:text.index("##", summary_block_start + 5)]
    assert "(to be filled in)" in summary_block
    # Template section: longer placeholder calling out the renderer.
    tech_block_start = text.index("## Tech stack")
    tech_block_end = text.index("##", tech_block_start + 5)
    tech_block = text[tech_block_start:tech_block_end]
    assert "bootstrap template renderer" in tech_block


def test_fix_includes_section_description_in_placeholder(tmp_path):
    """The canonical description (`one paragraph: what this site is...`)
    gets surfaced inline as an italic hint above the placeholder so
    the operator knows what content the section expects without
    looking up the schema."""
    (tmp_path / "AI_AGENTS.md").write_text("")
    mod._fix_tier_1(tmp_path, dry_run=False, assume_yes=False)
    text = (tmp_path / "AI_AGENTS.md").read_text()
    # Summary's description starts with "one paragraph: what this site is".
    assert "*one paragraph: what this site is, what it does*" in text


# ---------- internal helpers ----------


def test_existing_headings_strips_whitespace(tmp_path):
    """Headings with trailing spaces should still match the canonical
    list — Vim sometimes auto-saves with trailing whitespace."""
    text = "## Summary   \n\n## Audience\n"
    headings = mod._existing_headings(text)
    assert "summary" in headings
    assert "audience" in headings


def test_missing_sections_returns_canonical_order(tmp_path):
    """The _missing_sections helper's output order MUST match the
    canonical schema's order — that's what the tier-1 fix relies on
    when appending."""
    text = ""   # nothing present → all 10 missing
    missing = mod._missing_sections(text)
    assert missing == [s.heading for s in AI_AGENTS_SECTIONS]


# ---------- registry integration ----------


def test_check_014_is_registered():
    """The check module is auto-discovered by the registry; this
    just confirms the metadata matches the file."""
    from portfolio.checks.registry import _all_checks
    spec = _all_checks().get("CHECK_014")
    assert spec is not None
    assert spec.category == "scaffold"
    assert spec.name == "ai-agents-md-has-canonical-sections"


def test_check_014_has_tier_1_fix():
    from portfolio.fix_registry import get_tier_1
    spec = get_tier_1("CHECK_014")
    assert spec is not None
    assert spec.tier == 1
    assert "AI_AGENTS.md" in spec.summary
