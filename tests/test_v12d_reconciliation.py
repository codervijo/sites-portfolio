"""Tests for v12.D — `reconciliation.reconcile` (primary + audit
combiner).

Pure logic — no LLM calls, no fixtures from the live fleet. Pins
the contract for how the three audit agreement levels collapse
into a single `Reconciliation` the operator sees.
"""
from __future__ import annotations

import pytest

from portfolio.audit_pass import ParsedAudit
from portfolio.interpretive_pass import ParsedVerdict
from portfolio.reconciliation import (
    REVIEW_REQUIRED,
    Reconciliation,
    reconcile,
)


# ---------- fixtures ----------


def _primary(verdict: str = "GO", confidence: str = "HIGH",
             reasoning: str = "Gates passed; SERP clean.",
             **kwargs) -> ParsedVerdict:
    return ParsedVerdict(
        verdict=verdict,
        confidence=confidence,
        reasoning=reasoning,
        **kwargs,
    )


def _audit(agreement_level: str = "full", confidence: str = "MEDIUM",
           concerns: list[str] | None = None,
           counter_token: str = "",
           counter_reasoning: str = "",
           audit_self_check: str = "") -> ParsedAudit:
    return ParsedAudit(
        agreement_level=agreement_level,
        confidence=confidence,
        specific_concerns=concerns or [
            "INCUMBENT UNDER-DETECTION: missed templated URLs.",
        ],
        counter_verdict_token=counter_token,
        counter_verdict_reasoning=counter_reasoning,
        audit_self_check=audit_self_check,
    )


# ---------- full-agreement path ----------


def test_full_agreement_preserves_primary_verdict():
    primary = _primary("GO", "HIGH")
    audit = _audit("full")
    r = reconcile(primary, audit)
    assert r.final_verdict == "GO"
    assert r.final_confidence == "HIGH"


def test_full_agreement_no_caveats():
    """Full agreement → no caveats surfaced. Audit's concerns
    (which it must still report on full per the prompt) are
    available via `r.audit.specific_concerns`, but they're not
    promoted into the final caveats list."""
    audit = _audit("full", concerns=["minor nit about pollution rate"])
    r = reconcile(_primary(), audit)
    assert r.caveats == []
    # Still accessible for renderers that want to show it:
    assert r.audit.specific_concerns == ["minor nit about pollution rate"]


def test_full_agreement_confidence_not_boosted():
    """Confidence is preserved verbatim — not auto-boosted to HIGH
    just because the audit agreed. The audit confirming a primary's
    LOW-confidence call doesn't make the underlying data stronger."""
    r = reconcile(_primary("NICHE-DOWN", "LOW"), _audit("full"))
    assert r.final_confidence == "LOW"


# ---------- partial-agreement path ----------


def test_partial_agreement_preserves_verdict():
    """Partial → primary's verdict still stands; the audit raised
    concerns but didn't reject the call."""
    primary = _primary("GO", "HIGH")
    audit = _audit("partial", concerns=[
        "INTENT MISCLASSIFICATION: AI Overview suggests informational.",
        "TAM OVER-COUNTING: pollution rate unadjusted.",
    ])
    r = reconcile(primary, audit)
    assert r.final_verdict == "GO"


def test_partial_agreement_downgrades_confidence_high_to_medium():
    r = reconcile(_primary("GO", "HIGH"), _audit("partial"))
    assert r.final_confidence == "MEDIUM"


def test_partial_agreement_downgrades_confidence_medium_to_low():
    r = reconcile(_primary("NICHE-DOWN", "MEDIUM"), _audit("partial"))
    assert r.final_confidence == "LOW"


def test_partial_agreement_low_confidence_saturates():
    """Already-LOW confidence stays LOW (no negative confidence)."""
    r = reconcile(_primary("GO", "LOW"), _audit("partial"))
    assert r.final_confidence == "LOW"


def test_partial_agreement_caveats_from_audit_concerns():
    concerns = [
        "MOAT UNFALSIFIABILITY: 'better content' not testable.",
        "OPERATOR-FIT UNDER-WEIGHTING: workflow mismatch ignored.",
    ]
    r = reconcile(_primary(), _audit("partial", concerns=concerns))
    assert r.caveats == concerns


def test_partial_agreement_caveats_is_a_copy_not_alias():
    """The Reconciliation's caveats list is a copy of the audit's
    specific_concerns — mutating one doesn't leak into the other.
    Important for downstream callers that might filter / extend
    the caveats without realizing they're touching the source."""
    audit = _audit("partial", concerns=["concern A", "concern B"])
    r = reconcile(_primary(), audit)
    r.caveats.append("appended downstream")
    assert audit.specific_concerns == ["concern A", "concern B"]


# ---------- disagree path ----------


def test_disagree_produces_review_required():
    primary = _primary("GO", "HIGH")
    audit = _audit(
        "disagree",
        counter_token="NO-GO",
        counter_reasoning="programmatic incumbents own top-3.",
    )
    r = reconcile(primary, audit)
    assert r.final_verdict == REVIEW_REQUIRED
    assert r.final_verdict == "REVIEW_REQUIRED"  # exact string contract


def test_disagree_confidence_is_low():
    """REVIEW_REQUIRED signals 'operator must decide' — confidence
    LOW reflects that the tool isn't making the call."""
    r = reconcile(
        _primary("GO", "HIGH"),
        _audit("disagree", counter_token="NO-GO",
               counter_reasoning="x"),
    )
    assert r.final_confidence == "LOW"


def test_disagree_caveats_from_audit_concerns():
    concerns = ["INCUMBENT under-detection on 4 of 5 queries"]
    r = reconcile(
        _primary("GO", "HIGH"),
        _audit("disagree", concerns=concerns,
               counter_token="NO-GO", counter_reasoning="x"),
    )
    assert r.caveats == concerns


def test_disagree_preserves_both_verdicts_on_result():
    """Renderer (v12.E) needs both verdicts to show side-by-side."""
    primary = _primary("GO", "HIGH")
    audit = _audit(
        "disagree",
        counter_token="NO-GO",
        counter_reasoning="incumbents own the cluster.",
        audit_self_check="I may be over-indexing on URL patterns.",
    )
    r = reconcile(primary, audit)
    assert r.primary is primary
    assert r.audit is audit
    assert r.audit.counter_verdict_token == "NO-GO"
    assert r.audit.counter_verdict_reasoning == "incumbents own the cluster."


def test_disagree_when_counter_token_same_as_primary():
    """The parser doesn't enforce that disagree's counter_token
    differs from the primary's verdict — the audit prompt asks
    LLMs to flag disagreement, and we trust that
    self-categorization. Even if the tokens happen to match,
    `disagree` still produces REVIEW_REQUIRED."""
    r = reconcile(
        _primary("GO", "HIGH"),
        _audit("disagree", counter_token="GO",  # same token!
               counter_reasoning="for different reasons, but still GO"),
    )
    assert r.final_verdict == REVIEW_REQUIRED


# ---------- result-shape contract ----------


def test_reconciliation_requires_review_property_true_on_disagree():
    r = reconcile(
        _primary(),
        _audit("disagree", counter_token="NO-GO",
               counter_reasoning="x"),
    )
    assert r.requires_review is True


def test_reconciliation_requires_review_property_false_on_full():
    r = reconcile(_primary(), _audit("full"))
    assert r.requires_review is False


def test_reconciliation_requires_review_property_false_on_partial():
    r = reconcile(_primary(), _audit("partial"))
    assert r.requires_review is False


def test_review_required_constant_value():
    """The token string itself is part of the contract — downstream
    code (v12.E renderer, v12.F snapshot serialization) matches on
    this exact value."""
    assert REVIEW_REQUIRED == "REVIEW_REQUIRED"


def test_reconciliation_is_isinstance_check():
    r = reconcile(_primary(), _audit("full"))
    assert isinstance(r, Reconciliation)


# ---------- determinism ----------


def test_reconcile_is_pure_same_input_same_output():
    """Pure function — calling twice with the same input yields
    identical outputs (no hidden state, no randomness)."""
    primary = _primary("NICHE-DOWN", "MEDIUM")
    audit = _audit("partial", concerns=["one", "two"])
    a = reconcile(primary, audit)
    b = reconcile(primary, audit)
    assert a.final_verdict == b.final_verdict
    assert a.final_confidence == b.final_confidence
    assert a.caveats == b.caveats
