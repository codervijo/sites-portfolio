"""Tests for v8.J — `audit_pass.build_audit_payload` + the
markdown-reconstruction helper.

Pure data-shaping — no LLM calls. Pins the contract between v8.I's
persisted `primary_verdict` shape and what the audit prompt expects
to read.
"""
from __future__ import annotations

import pytest

from portfolio.audit_pass import (
    _reconstruct_primary_markdown,
    build_audit_payload,
)
from portfolio.operator_profile import OperatorProfile


# ---------- fixtures ----------


def _minimal_cluster() -> dict:
    return {
        "topic": "ev charger installation cost",
        "cluster_queries": ["ev charger installation cost"],
        "gates": {"gate_1_market": {"status": "PASS"}},
        "operator_fit": {"warnings": []},
        "per_query_results": [
            {"query": "ev charger installation cost",
             "organic_results": [
                 {"position": 1, "domain": "x.com",
                  "url": "https://x.com/", "title": "X",
                  "snippet": "...", "displayed_link": "x.com"},
             ],
             "features": {"ai_overview": {"present": True}}},
        ],
    }


def _full_primary_verdict() -> dict:
    """Matches the shape v8.I persists into payload['primary_verdict']."""
    return {
        "verdict": "NICHE-DOWN",
        "confidence": "MEDIUM",
        "reasoning": (
            "Gate 2 FAIL keys on regex patterns this cluster doesn't "
            "actually match. The real moat is permit-cost data."
        ),
        "moat_required": True,
        "moat_prompt": "What's your unfair advantage over X?",
        "reductions": [
            "Local-installer cost calculator",
            "Permit-cost focus only",
        ],
        "operator_fit_warnings": [
            "Builder workflow vs content-niche mismatch",
        ],
        "blind_spot_self_report": (
            "I may have over-weighted the permit-cost moat; volume "
            "there is uncertain."
        ),
    }


# ---------- _reconstruct_primary_markdown ----------


def test_reconstruct_strips_blind_spot_by_default():
    """The audit prompt teaches: hiding blind_spot_self_report
    prevents the audit from anchoring on the primary's own
    concerns. Default behavior must strip."""
    md = _reconstruct_primary_markdown(_full_primary_verdict())
    assert "### verdict" in md
    assert "NICHE-DOWN" in md
    # blind_spot_self_report is NOT in the reconstructed output.
    assert "### blind_spot_self_report" not in md
    assert "over-weighted the permit-cost moat" not in md


def test_reconstruct_with_blind_spot_when_explicit():
    md = _reconstruct_primary_markdown(
        _full_primary_verdict(), strip_blind_spot=False,
    )
    assert "### blind_spot_self_report" in md
    assert "over-weighted the permit-cost moat" in md


def test_reconstruct_required_sections_always_present():
    """verdict / confidence / reasoning are required by both the
    parser and the audit prompt. They must appear even when other
    fields are empty."""
    minimal = {
        "verdict": "GO",
        "confidence": "HIGH",
        "reasoning": "Just go for it.",
    }
    md = _reconstruct_primary_markdown(minimal)
    assert "### verdict\nGO" in md
    assert "### confidence\nHIGH" in md
    assert "### reasoning\nJust go for it." in md


def test_reconstruct_skips_empty_optional_sections():
    """Empty `moat_prompt`, empty reductions/warnings lists — those
    sections shouldn't render at all. Matches the prompt's "leave
    empty when X" convention."""
    minimal = {
        "verdict": "GO",
        "confidence": "HIGH",
        "reasoning": "x.",
        "moat_required": False,
        "moat_prompt": "",
        "reductions": [],
        "operator_fit_warnings": [],
    }
    md = _reconstruct_primary_markdown(minimal)
    assert "### moat_prompt" not in md
    assert "### reductions" not in md
    assert "### operator_fit_warnings" not in md
    # moat_required IS rendered (it's a bool, not absent — false is a
    # real value the audit may want to check).
    assert "### moat_required\nfalse" in md


def test_reconstruct_renders_moat_required_lowercase():
    """`true` / `false` lowercase — matches the prompt's response
    format and what `parse_verdict` accepts on input. Mismatch
    here would mean the audit reads "True" / "False" Python-style
    strings, which the audit prompt isn't trained to handle."""
    md = _reconstruct_primary_markdown(
        {"verdict": "GO", "confidence": "HIGH", "reasoning": "x.",
         "moat_required": True},
    )
    assert "### moat_required\ntrue" in md
    md_false = _reconstruct_primary_markdown(
        {"verdict": "GO", "confidence": "HIGH", "reasoning": "x.",
         "moat_required": False},
    )
    assert "### moat_required\nfalse" in md_false


def test_reconstruct_renders_bullets_for_lists():
    md = _reconstruct_primary_markdown(_full_primary_verdict())
    assert "### reductions\n- Local-installer cost calculator" in md
    assert "- Permit-cost focus only" in md
    assert "### operator_fit_warnings\n- Builder workflow vs content-niche mismatch" in md


def test_reconstruct_empty_dict_returns_empty_string():
    """Defensive — if `primary_verdict` somehow ends up empty on the
    cluster snapshot (e.g., the v8.I helper raised mid-write), the
    reconstruction returns "" rather than crashing on missing keys."""
    assert _reconstruct_primary_markdown({}) == ""
    assert _reconstruct_primary_markdown(None) == ""


# ---------- build_audit_payload ----------


def test_build_audit_payload_inherits_primary_payload_shape():
    """The audit payload extends `build_payload`'s output — every
    key the primary saw is still present, in the same shape."""
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
    )
    for k in ("topic", "cluster_queries", "gates", "operator_fit",
              "operator_profile_summary", "raw_top_10_per_query",
              "serp_features_per_query"):
        assert k in payload, f"required primary-payload key {k!r} missing"


def test_build_audit_payload_adds_primary_response_markdown():
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
    )
    md = payload["primary_response_markdown"]
    # Has the required sections.
    assert "### verdict\nNICHE-DOWN" in md
    assert "### confidence\nMEDIUM" in md
    assert "### reasoning" in md
    # blind_spot_self_report is stripped (anti-anchoring).
    assert "### blind_spot_self_report" not in md


def test_build_audit_payload_passes_operator_profile_through():
    """Operator profile flows into `build_payload` exactly like the
    primary path — operator_profile_summary uses the same formatting."""
    profile = OperatorProfile(
        expertise=["SEO programmatic content"],
        workflow_preference="builder",
        motivation_cadence="weekly",
    )
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
        operator_profile=profile,
    )
    assert "SEO programmatic content" in payload["operator_profile_summary"]
    assert "builder" in payload["operator_profile_summary"]
    assert "weekly" in payload["operator_profile_summary"]


def test_build_audit_payload_no_profile_uses_unconfigured_sentinel():
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
        operator_profile=None,
    )
    assert payload["operator_profile_summary"] == "no operator profile configured"


def test_build_audit_payload_tolerates_minimal_primary_verdict():
    """A primary_verdict with only the required fields (verdict /
    confidence / reasoning) still produces a usable payload — the
    optional fields just don't render in the markdown."""
    minimal_primary = {
        "verdict": "GO", "confidence": "HIGH",
        "reasoning": "Mechanical gates lined up.",
    }
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=minimal_primary,
    )
    assert "GO" in payload["primary_response_markdown"]
    # Reductions / warnings / moat sections absent in the markdown
    # because they weren't supplied. Audit just sees less context.
    assert "### reductions" not in payload["primary_response_markdown"]
    assert "### moat_prompt" not in payload["primary_response_markdown"]


def test_build_audit_payload_preserves_cluster_data():
    """Cluster gates pass through verbatim — same as build_payload's
    contract. Audit needs to see the mechanical-gate output, not a
    summary of it."""
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
    )
    assert payload["gates"]["gate_1_market"]["status"] == "PASS"
