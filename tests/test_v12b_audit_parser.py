"""Tests for v12.B — `audit_pass.parse_audit` (markdown response parser).

Pure-string parsing — no LLM calls, no network. Pins the contract
between `prompts/adversarial_audit_v1.md`'s response-format spec and
the `ParsedAudit` dataclass downstream code (reconciliation in v12.D)
consumes.

Test inputs are constructed strings that mimic real audit-LLM
responses. Mirrors `test_interpretive_pass_parse.py` in shape — the
audit parser is parallel to `parse_verdict` but enforces a different
schema (agreement_level / confidence / specific_concerns instead of
verdict / confidence / reasoning).
"""
from __future__ import annotations

import pytest

from portfolio.audit_pass import (
    AuditParseError,
    ParsedAudit,
    parse_audit,
)


def _full_response(*,
                   agreement_level: str = "partial",
                   confidence: str = "MEDIUM",
                   concerns: list[str] | None = None,
                   counter_verdict: str | None = None,
                   audit_self_check: str | None = None) -> str:
    """Build a canonical audit response with the three required
    sections plus selectable optional ones. Used as the happy-path
    baseline."""
    parts = [
        f"### agreement_level\n{agreement_level}",
        f"### confidence\n{confidence}",
    ]
    bullets = concerns or [
        "INCUMBENT UNDER-DETECTION: notateslaapp.com ranks for 4 of 5 cluster "
        "queries with `/year/` URL pattern not flagged by primary.",
    ]
    parts.append("### specific_concerns\n" +
                 "\n".join(f"- {c}" for c in bullets))
    if counter_verdict is not None:
        parts.append(f"### counter_verdict\n{counter_verdict}")
    if audit_self_check is not None:
        parts.append(f"### audit_self_check\n{audit_self_check}")
    return "\n\n".join(parts)


# ---------- happy path ----------


def test_parse_audit_required_fields_populated():
    r = parse_audit(_full_response())
    assert isinstance(r, ParsedAudit)
    assert r.agreement_level == "partial"
    assert r.confidence == "MEDIUM"
    assert len(r.specific_concerns) == 1
    assert "notateslaapp" in r.specific_concerns[0]


def test_parse_audit_returns_canonical_tokens():
    """agreement_level is lowercased; confidence is uppercased.
    Downstream reconciliation depends on stable string equality."""
    r = parse_audit(_full_response(
        agreement_level="PARTIAL", confidence="medium",
    ))
    assert r.agreement_level == "partial"
    assert r.confidence == "MEDIUM"


def test_parse_audit_optional_fields_default_when_absent():
    """Response with only the three required sections produces a
    ParsedAudit with sensible defaults for optional fields."""
    r = parse_audit(_full_response())
    assert r.counter_verdict_token == ""
    assert r.counter_verdict_reasoning == ""
    assert r.audit_self_check == ""


def test_parse_audit_strips_trailing_punctuation_on_tokens():
    """LLMs sometimes emit `partial.` or `HIGH,` — coerce."""
    r = parse_audit(_full_response(
        agreement_level="partial.", confidence="HIGH,",
    ))
    assert r.agreement_level == "partial"
    assert r.confidence == "HIGH"


def test_parse_audit_tolerates_preamble_chatter():
    """Anything before the first `### header` is discarded."""
    response = (
        "Here's my audit:\n\nLet me explain my reasoning before diving in.\n\n"
        + _full_response()
    )
    r = parse_audit(response)
    assert r.agreement_level == "partial"


def test_parse_audit_accepts_mixed_bullet_markers():
    """`-`, `*`, `+`, and numbered (`1.`) all parse as bullets."""
    response = (
        "### agreement_level\nfull\n\n"
        "### confidence\nLOW\n\n"
        "### specific_concerns\n"
        "- concern A\n"
        "* concern B\n"
        "+ concern C\n"
        "1. concern D\n"
        "2. concern E\n"
    )
    r = parse_audit(response)
    assert r.specific_concerns == [
        "concern A", "concern B", "concern C", "concern D", "concern E",
    ]


def test_parse_audit_full_response_with_all_sections():
    response = (
        "### agreement_level\ndisagree\n\n"
        "### confidence\nHIGH\n\n"
        "### specific_concerns\n"
        "- INCUMBENT UNDER-DETECTION: 4 templated URLs missed.\n"
        "- KD-TRAP REASONING: low KD but entrenched programmatic.\n\n"
        "### counter_verdict\n"
        "NO-GO: programmatic incumbents own the top-3 across the entire "
        "cluster; new entry without a structural moat cannot displace them.\n\n"
        "### audit_self_check\n"
        "I may be over-indexing on URL patterns; the primary's intent read "
        "could still be correct."
    )
    r = parse_audit(response)
    assert r.agreement_level == "disagree"
    assert r.confidence == "HIGH"
    assert len(r.specific_concerns) == 2
    assert r.counter_verdict_token == "NO-GO"
    assert r.counter_verdict_reasoning.startswith("programmatic incumbents")
    assert "over-indexing" in r.audit_self_check


# ---------- required-section enforcement ----------


def test_parse_audit_raises_when_agreement_level_missing():
    no_agreement = (
        "### confidence\nHIGH\n\n"
        "### specific_concerns\n- a concern"
    )
    with pytest.raises(AuditParseError, match="agreement_level"):
        parse_audit(no_agreement)


def test_parse_audit_raises_when_confidence_missing():
    no_confidence = (
        "### agreement_level\nfull\n\n"
        "### specific_concerns\n- a concern"
    )
    with pytest.raises(AuditParseError, match="confidence"):
        parse_audit(no_confidence)


def test_parse_audit_raises_when_specific_concerns_missing():
    no_concerns = (
        "### agreement_level\nfull\n\n"
        "### confidence\nHIGH"
    )
    with pytest.raises(AuditParseError, match="specific_concerns"):
        parse_audit(no_concerns)


# ---------- token validation ----------


def test_parse_audit_raises_on_unknown_agreement_level():
    """`maybe` is not in {full, partial, disagree}."""
    with pytest.raises(AuditParseError, match="agreement_level"):
        parse_audit(_full_response(agreement_level="maybe"))


def test_parse_audit_raises_on_unknown_confidence():
    """`MAYBE` is not in {HIGH, MEDIUM, LOW}."""
    with pytest.raises(AuditParseError, match="confidence"):
        parse_audit(_full_response(confidence="MAYBE"))


# ---------- specific_concerns ≥ 1 bullet ----------


def test_parse_audit_raises_when_specific_concerns_has_no_bullets():
    """Per the audit prompt: 'concrete or omitted'. Prose-only
    specific_concerns is rejected — vague concerns aren't useful."""
    response = (
        "### agreement_level\nfull\n\n"
        "### confidence\nHIGH\n\n"
        "### specific_concerns\nNothing to flag actually."
    )
    with pytest.raises(AuditParseError, match="at least one bullet"):
        parse_audit(response)


def test_parse_audit_raises_when_specific_concerns_is_empty():
    response = (
        "### agreement_level\nfull\n\n"
        "### confidence\nHIGH\n\n"
        "### specific_concerns\n"
    )
    with pytest.raises(AuditParseError, match="at least one bullet"):
        parse_audit(response)


# ---------- disagree + counter_verdict contract ----------


def test_parse_audit_disagree_requires_counter_verdict():
    """agreement_level=disagree without a counter_verdict section
    is rejected — the audit prompt makes counter_verdict mandatory
    on disagree so reconciliation has both verdicts to render."""
    response = _full_response(agreement_level="disagree")
    with pytest.raises(AuditParseError, match="counter_verdict"):
        parse_audit(response)


def test_parse_audit_disagree_with_empty_counter_verdict_raises():
    response = _full_response(
        agreement_level="disagree", counter_verdict="   ",
    )
    with pytest.raises(AuditParseError, match="counter_verdict"):
        parse_audit(response)


def test_parse_audit_disagree_counter_verdict_missing_colon_raises():
    """`<TOKEN>: <reasoning>` is the required shape."""
    response = _full_response(
        agreement_level="disagree",
        counter_verdict="NO-GO programmatic incumbents own the cluster",
    )
    with pytest.raises(AuditParseError, match="TOKEN.*reasoning"):
        parse_audit(response)


def test_parse_audit_disagree_counter_verdict_unknown_token_raises():
    response = _full_response(
        agreement_level="disagree",
        counter_verdict="MAYBE: I'm not sure, leaning toward no.",
    )
    with pytest.raises(AuditParseError, match="counter_verdict token"):
        parse_audit(response)


def test_parse_audit_counter_verdict_token_normalized():
    """Trivial variation in the token — `NICHE DOWN` / `niche-down` /
    trailing period — all normalize to canonical `NICHE-DOWN`."""
    for raw in ("NICHE DOWN: rationale", "niche-down: rationale",
                "NICHE_DOWN: rationale", "NICHE-DOWN.: rationale"):
        r = parse_audit(_full_response(
            agreement_level="disagree", counter_verdict=raw,
        ))
        assert r.counter_verdict_token == "NICHE-DOWN", f"failed for {raw!r}"


def test_parse_audit_counter_verdict_reasoning_can_span_lines():
    multiline_counter = (
        "GO: the primary's NICHE-DOWN read over-weights the regex miss.\n"
        "Volume on the unreduced topic is sufficient even after pollution."
    )
    r = parse_audit(_full_response(
        agreement_level="disagree", counter_verdict=multiline_counter,
    ))
    assert r.counter_verdict_token == "GO"
    assert "Volume on the unreduced topic" in r.counter_verdict_reasoning


# ---------- counter_verdict permissiveness on non-disagree ----------


def test_parse_audit_full_with_off_spec_counter_verdict_parsed():
    """LLM sometimes emits a counter on full/partial against
    instructions. Well-formed counter is parsed and stored — the
    field is available to reconciliation, which may ignore it on
    non-disagree audits."""
    r = parse_audit(_full_response(
        agreement_level="full",
        counter_verdict="NO-GO: just in case the primary is wrong.",
    ))
    assert r.agreement_level == "full"
    assert r.counter_verdict_token == "NO-GO"
    assert r.counter_verdict_reasoning.startswith("just in case")


def test_parse_audit_full_with_malformed_counter_verdict_tolerated():
    """Malformed counter on a non-disagree audit doesn't raise —
    raw body falls into `counter_verdict_reasoning`, token stays
    empty. The audit's value is in the concerns list."""
    r = parse_audit(_full_response(
        agreement_level="partial",
        counter_verdict="vague hedging without a token at all",
    ))
    assert r.agreement_level == "partial"
    assert r.counter_verdict_token == ""
    assert r.counter_verdict_reasoning == (
        "vague hedging without a token at all"
    )


# ---------- header case insensitivity ----------


def test_parse_audit_accepts_uppercase_headers():
    """`### Agreement_Level` and `### agreement_level` both work."""
    response = (
        "### Agreement_Level\nfull\n\n"
        "### Confidence\nHIGH\n\n"
        "### Specific_Concerns\n- a concrete concern\n"
    )
    r = parse_audit(response)
    assert r.agreement_level == "full"
    assert r.confidence == "HIGH"


# ---------- audit_self_check passthrough ----------


def test_parse_audit_self_check_preserved_verbatim():
    response = _full_response(
        audit_self_check=(
            "I may be over-weighting the URL-pattern signal; intent could "
            "still be informational despite the templated structures."
        ),
    )
    r = parse_audit(response)
    assert "over-weighting" in r.audit_self_check
    assert "informational despite" in r.audit_self_check
