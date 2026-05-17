"""Tests for v8.E — `parse_verdict` (markdown response parser).

Pure-string parsing — no LLM calls, no network. Pins the contract
between `prompts/niche_evaluation_v1.md`'s response-format spec and
the dataclass downstream code consumes.

Test inputs are constructed strings that mimic real LLM responses.
"""
from __future__ import annotations

import pytest

from portfolio.interpretive_pass import (
    ParsedVerdict,
    VerdictParseError,
    parse_verdict,
)


def _full_response(*, verdict="GO", confidence="HIGH",
                    reductions=None, warnings=None,
                    moat_required="false") -> str:
    """Build a canonical response with all required + a couple
    optional sections. Used as the happy-path baseline."""
    parts = [
        f"### verdict\n{verdict}",
        f"### confidence\n{confidence}",
        "### reasoning\n"
        "The mechanical Gate 1 passed with adequate volume, and the "
        "SERP doesn't show a programmatic incumbent. Operator's "
        "expertise in SEO programmatic content overlaps with the "
        "topic — execution feasible.",
        f"### moat_required\n{moat_required}",
    ]
    if reductions:
        parts.append("### reductions\n" + "\n".join(f"- {r}" for r in reductions))
    if warnings:
        parts.append("### operator_fit_warnings\n" +
                     "\n".join(f"- {w}" for w in warnings))
    return "\n\n".join(parts)


# ---------- happy path ----------


def test_parse_verdict_required_fields_populated():
    r = parse_verdict(_full_response())
    assert isinstance(r, ParsedVerdict)
    assert r.verdict == "GO"
    assert r.confidence == "HIGH"
    assert "Gate 1 passed" in r.reasoning


def test_parse_verdict_returns_canonical_tokens():
    """Verdict + confidence are normalized to uppercase canonical
    tokens — downstream rendering / reconciliation depends on stable
    string equality."""
    r = parse_verdict(_full_response(verdict="go", confidence="medium"))
    assert r.verdict == "GO"
    assert r.confidence == "MEDIUM"


def test_parse_verdict_optional_fields_default_when_absent():
    """Response with only the three required sections produces a
    ParsedVerdict with sensible defaults for the optional fields."""
    minimal = (
        "### verdict\nNICHE-DOWN\n\n"
        "### confidence\nMEDIUM\n\n"
        "### reasoning\nReasoning text here."
    )
    r = parse_verdict(minimal)
    assert r.moat_required is None
    assert r.moat_prompt == ""
    assert r.reductions == []
    assert r.operator_fit_warnings == []
    assert r.blind_spot_self_report == ""


def test_parse_verdict_full_response_with_all_sections():
    response = (
        "### verdict\nNICHE-DOWN\n\n"
        "### confidence\nMEDIUM\n\n"
        "### reasoning\n"
        "The mechanical Gate 2 FAIL keys on regex patterns that this "
        "cluster doesn't actually match. The real moat is permit-cost "
        "data, but volume there is uncertain.\n\n"
        "### moat_required\ntrue\n\n"
        "### moat_prompt\n"
        "What's your unfair advantage over notateslaapp.com's pattern?\n\n"
        "### reductions\n"
        "- Local-installer cost calculator\n"
        "- Permit-cost focus only\n"
        "- Region-specific (CA, NY) drill-down\n\n"
        "### operator_fit_warnings\n"
        "- Workflow mismatch: builder preference vs content niche\n\n"
        "### blind_spot_self_report\n"
        "I weighted Gate 2 lightly; might be over-correcting for the regex miss."
    )
    r = parse_verdict(response)
    assert r.verdict == "NICHE-DOWN"
    assert r.confidence == "MEDIUM"
    assert r.moat_required is True
    assert r.moat_prompt.startswith("What's your unfair advantage")
    assert r.reductions == [
        "Local-installer cost calculator",
        "Permit-cost focus only",
        "Region-specific (CA, NY) drill-down",
    ]
    assert r.operator_fit_warnings == [
        "Workflow mismatch: builder preference vs content niche",
    ]
    assert "weighted Gate 2 lightly" in r.blind_spot_self_report


# ---------- required-section enforcement ----------


def test_parse_verdict_raises_when_verdict_missing():
    no_verdict = (
        "### confidence\nHIGH\n\n"
        "### reasoning\nReasoning."
    )
    with pytest.raises(VerdictParseError) as exc:
        parse_verdict(no_verdict)
    assert "verdict" in str(exc.value)


def test_parse_verdict_raises_when_confidence_missing():
    no_confidence = (
        "### verdict\nGO\n\n"
        "### reasoning\nReasoning."
    )
    with pytest.raises(VerdictParseError) as exc:
        parse_verdict(no_confidence)
    assert "confidence" in str(exc.value)


def test_parse_verdict_raises_when_reasoning_missing():
    no_reasoning = (
        "### verdict\nGO\n\n"
        "### confidence\nHIGH"
    )
    with pytest.raises(VerdictParseError) as exc:
        parse_verdict(no_reasoning)
    assert "reasoning" in str(exc.value)


def test_parse_verdict_raises_on_unknown_verdict_token():
    bad_verdict = (
        "### verdict\nSHIP\n\n"            # not in canonical set
        "### confidence\nHIGH\n\n"
        "### reasoning\nReasoning."
    )
    with pytest.raises(VerdictParseError) as exc:
        parse_verdict(bad_verdict)
    assert "canonical set" in str(exc.value)


def test_parse_verdict_raises_on_unknown_confidence_token():
    bad_conf = (
        "### verdict\nGO\n\n"
        "### confidence\nVERY HIGH\n\n"
        "### reasoning\nReasoning."
    )
    with pytest.raises(VerdictParseError) as exc:
        parse_verdict(bad_conf)
    assert "confidence" in str(exc.value).lower()


# ---------- token normalization tolerance ----------


def test_parse_verdict_normalizes_trailing_punctuation():
    """LLMs sometimes emit `GO.` or `NO-GO!` — strip trailing
    punctuation before validating against canonical set."""
    response = (
        "### verdict\nGO.\n\n"
        "### confidence\nHIGH!\n\n"
        "### reasoning\nReasoning."
    )
    r = parse_verdict(response)
    assert r.verdict == "GO"
    assert r.confidence == "HIGH"


def test_parse_verdict_normalizes_niche_down_separator():
    """`NICHE DOWN` (space) and `NICHE_DOWN` (underscore) both
    canonicalize to `NICHE-DOWN`."""
    for variant in ("NICHE DOWN", "niche_down", "NICHE-DOWN"):
        response = (
            f"### verdict\n{variant}\n\n"
            "### confidence\nMEDIUM\n\n"
            "### reasoning\nx."
        )
        assert parse_verdict(response).verdict == "NICHE-DOWN"


def test_parse_verdict_lowercase_headers_work():
    """`### verdict` (lowercase, as the prompt template uses) AND
    `### Verdict` (capitalized, which some models prefer) both
    resolve to the same section. Header lookup is case-insensitive."""
    capitalized = (
        "### Verdict\nGO\n\n"
        "### Confidence\nHIGH\n\n"
        "### Reasoning\nReasoning."
    )
    r = parse_verdict(capitalized)
    assert r.verdict == "GO"
    assert r.confidence == "HIGH"


def test_parse_verdict_discards_preamble_chatter():
    """LLMs sometimes prepend "Here's my analysis:" before the first
    `### ...` line. Anything before the first section is discarded —
    no need to be strict on the prelude."""
    with_preamble = (
        "Here's my analysis based on the SERP data:\n\n"
        "It was a close call but I think the verdict should be:\n\n"
        "### verdict\nGO\n\n"
        "### confidence\nHIGH\n\n"
        "### reasoning\nReasoning."
    )
    r = parse_verdict(with_preamble)
    assert r.verdict == "GO"
    # Preamble doesn't leak into reasoning.
    assert "Here's my analysis" not in r.reasoning


# ---------- moat_required tolerance ----------


def test_parse_verdict_moat_required_yes_no_accepted():
    """LLMs sometimes write `yes` / `no` instead of strict
    `true` / `false`. Accept those too rather than failing the
    whole verdict on this optional field."""
    yes = (
        "### verdict\nNICHE-DOWN\n\n"
        "### confidence\nLOW\n\n"
        "### reasoning\nx.\n\n"
        "### moat_required\nyes"
    )
    no = yes.replace("yes", "no")
    assert parse_verdict(yes).moat_required is True
    assert parse_verdict(no).moat_required is False


def test_parse_verdict_moat_required_unparseable_becomes_none():
    """LLM hedge ("likely" / "depends") on moat_required → None,
    not a parse failure. The audit pass surfaces the disagreement
    if it matters."""
    hedged = (
        "### verdict\nGO\n\n"
        "### confidence\nMEDIUM\n\n"
        "### reasoning\nx.\n\n"
        "### moat_required\nlikely but depends on execution"
    )
    assert parse_verdict(hedged).moat_required is None


# ---------- bullet-parsing tolerance ----------


def test_parse_verdict_accepts_various_bullet_markers():
    """Reductions / warnings can use `-`, `*`, `+`, or numbered
    bullets — accept all."""
    response = (
        "### verdict\nNICHE-DOWN\n\n"
        "### confidence\nMEDIUM\n\n"
        "### reasoning\nx.\n\n"
        "### reductions\n"
        "- dash bullet\n"
        "* asterisk bullet\n"
        "+ plus bullet\n"
        "1. numbered bullet"
    )
    r = parse_verdict(response)
    assert r.reductions == [
        "dash bullet", "asterisk bullet",
        "plus bullet", "numbered bullet",
    ]


def test_parse_verdict_empty_reductions_section():
    """Per prompt spec, reductions is empty on GO verdicts. An empty
    section (or one with only whitespace / a "(none)" line) parses
    to an empty list rather than `["(none)"]`."""
    response = (
        "### verdict\nGO\n\n"
        "### confidence\nHIGH\n\n"
        "### reasoning\nx.\n\n"
        "### reductions\n\n"   # explicit empty body
        "### moat_required\nfalse"
    )
    r = parse_verdict(response)
    assert r.reductions == []


def test_parse_verdict_strips_whitespace_around_bullet_text():
    """Bullet bodies sometimes have trailing spaces. Strip them so
    downstream rendering doesn't show ragged-right list items."""
    response = (
        "### verdict\nNICHE-DOWN\n\n"
        "### confidence\nMEDIUM\n\n"
        "### reasoning\nx.\n\n"
        "### reductions\n"
        "-   leading spaces in bullet body\n"
        "- trailing spaces   "
    )
    r = parse_verdict(response)
    assert r.reductions == ["leading spaces in bullet body",
                            "trailing spaces"]


# ---------- section-order tolerance ----------


def test_parse_verdict_section_order_does_not_matter():
    """The prompt suggests an order but doesn't enforce it. Model
    might emit reasoning first; parser must still resolve by
    header name, not position."""
    out_of_order = (
        "### reasoning\nReasoning text.\n\n"
        "### confidence\nLOW\n\n"
        "### verdict\nNO-GO"
    )
    r = parse_verdict(out_of_order)
    assert r.verdict == "NO-GO"
    assert r.confidence == "LOW"
    assert "Reasoning text" in r.reasoning
