"""Tests for v9.A — `portfolio.canonical_sections` single source of
truth for the AI_AGENTS.md canonical section schema.

Pins:
  - exact section count (10)
  - exact section order (the bootstrap template renderer + the
    tier-1 fix both rely on iterating in this order)
  - source field values ("operator" / "template" only)
  - helper filters (operator_sections, template_sections,
    section_headings) return the right subsets

These are intentionally strict — the v9.A schema is the contract
that v9.B (interactive prompts), v9.D (growth.md), and v9.E
(JSON refactor) all consume. Drift here breaks every consumer.
"""
from __future__ import annotations

from portfolio.canonical_sections import (
    AI_AGENTS_SECTIONS,
    CanonicalSection,
    operator_sections,
    section_headings,
    template_sections,
)


# ---------- schema shape ----------


def test_schema_has_exactly_ten_sections():
    """The v9.A canonical schema is 10 sections. Adding / removing
    sections is a contract change — bump the schema version (v9.E
    or beyond) and update this assertion deliberately."""
    assert len(AI_AGENTS_SECTIONS) == 10


def test_schema_headings_in_canonical_order():
    """Order matters: the bootstrap template renderer writes sections
    in this sequence so new projects start with the canonical layout.
    The tier-1 fix also appends in this order when injecting missing
    sections, so the visual flow stays consistent."""
    expected = [
        "Summary",
        "Audience",
        "ICP",
        "Goals",
        "Tech stack",
        "Building info",
        "Deployment info",
        "Content strategy",
        "Versioning",
        "Conventions",
    ]
    assert [s.heading for s in AI_AGENTS_SECTIONS] == expected


def test_every_section_has_source_operator_or_template():
    """Source is a closed enum: `operator` (collected via v9.B
    prompts) or `template` (filled by bootstrap renderer). Any
    other string would crash v9.B's prompt-filtering logic."""
    for s in AI_AGENTS_SECTIONS:
        assert s.source in ("operator", "template"), (
            f"section {s.heading!r} has invalid source {s.source!r}"
        )


def test_every_section_has_non_empty_description():
    """Description is used by the tier-1 fix's placeholder body, the
    interactive-prompt help text, and the --help rendering. An
    empty string would produce ugly output everywhere."""
    for s in AI_AGENTS_SECTIONS:
        assert s.description.strip(), (
            f"section {s.heading!r} has empty description"
        )


def test_section_dataclass_is_frozen():
    """`CanonicalSection` is intentionally immutable — the schema
    constant gets imported all over the codebase and accidental
    mutation would be hard to trace."""
    import dataclasses
    s = CanonicalSection(heading="x", source="operator", description="x")
    assert dataclasses.is_dataclass(s)
    # `frozen=True` raises FrozenInstanceError on assignment.
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.heading = "y"   # type: ignore[misc]


# ---------- source-mix expectations ----------


def test_five_operator_input_sections():
    """v9.B's interactive prompts collect exactly 5 sections from
    the operator (Summary / Audience / ICP / Goals / Content
    strategy). Changing this count is a UX contract change."""
    op = operator_sections()
    assert len(op) == 5
    assert {s.heading for s in op} == {
        "Summary", "Audience", "ICP", "Goals", "Content strategy",
    }


def test_five_template_driven_sections():
    """The bootstrap template renderer populates 5 sections (Tech
    stack / Building info / Deployment info / Versioning /
    Conventions). Same contract logic as operator_sections."""
    tpl = template_sections()
    assert len(tpl) == 5
    assert {s.heading for s in tpl} == {
        "Tech stack", "Building info", "Deployment info",
        "Versioning", "Conventions",
    }


def test_operator_plus_template_equals_full_list():
    """Belt-and-suspenders — no section has a typo'd source value
    that drops it from both filters silently."""
    assert len(operator_sections()) + len(template_sections()) == len(AI_AGENTS_SECTIONS)


def test_operator_sections_preserves_canonical_order():
    """The interactive prompts (v9.B) should ask in the same order
    the sections appear in the canonical schema — operator's mental
    model stays consistent between the bootstrap flow and the
    rendered file."""
    op = operator_sections()
    op_headings = [s.heading for s in op]
    # Operator sections appear at indices 0, 1, 2, 3, 7 in canonical
    # order.
    canonical_order_for_operator = ["Summary", "Audience", "ICP",
                                     "Goals", "Content strategy"]
    assert op_headings == canonical_order_for_operator


def test_template_sections_preserves_canonical_order():
    tpl = template_sections()
    tpl_headings = [s.heading for s in tpl]
    canonical_order_for_template = ["Tech stack", "Building info",
                                     "Deployment info", "Versioning",
                                     "Conventions"]
    assert tpl_headings == canonical_order_for_template


# ---------- section_headings helper ----------


def test_section_headings_returns_just_strings_in_order():
    headings = section_headings()
    assert isinstance(headings, tuple)
    assert all(isinstance(h, str) for h in headings)
    assert headings == tuple(s.heading for s in AI_AGENTS_SECTIONS)


# ---------- specific-section content sanity ----------


def test_icp_description_distinguishes_from_audience():
    """The whole reason ICP is its own section (not folded into
    Audience) is that they describe different granularities.
    Description must convey that distinction so the operator
    doesn't write the same content twice."""
    by_heading = {s.heading: s for s in AI_AGENTS_SECTIONS}
    icp_desc = by_heading["ICP"].description.lower()
    assert "specific" in icp_desc
    # The description references Audience explicitly for contrast.
    assert "audience" in icp_desc
