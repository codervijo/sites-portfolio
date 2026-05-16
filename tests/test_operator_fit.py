"""Tests for v8.D P3.B — operator-fit logic.

`evaluate_operator_fit()` runs three checks (expertise / workflow /
cadence) on a cluster snapshot and returns an `OperatorFitResult`
that feeds into Gate 2's verdict.
"""
from __future__ import annotations

import pytest

from portfolio.operator_profile import (
    OperatorProfile,
    evaluate_operator_fit,
)
from portfolio.research_gates import OperatorFitResult


# ---------- helpers ----------


def _organic(domain: str, title: str = "", url: str = "") -> dict:
    return {
        "domain": domain,
        "url": url or f"https://{domain}/page",
        "title": title or f"{domain} page",
        "snippet": "",
    }


def _query_payload(query: str, organic: list[dict],
                   *, ai_overview: bool = False) -> dict:
    return {
        "query": query,
        "organic_results": organic,
        "features": {"ai_overview": {"present": ai_overview}},
    }


def _cluster(topic: str, per_query: list[dict]) -> dict:
    return {
        "topic": topic,
        "cluster_queries": [p["query"] for p in per_query],
        "per_query_results": per_query,
    }


_INFORMATIONAL_5Q = [
    "what is X",
    "how to use X",
    "best X tips",
    "X guide",
    "X examples",
]

_COMMERCIAL_5Q = [
    "buy X online",
    "X coupon code",
    "X price",
    "X discount 2026",
    "X shop near me",
]

_AUTHORITY_RESULTS = [
    _organic("cdc.gov", "CDC overview"),
    _organic("harvard.edu", "Harvard review"),
    _organic("nytimes.com", "NYT explainer"),
    _organic("widget.example", "Widget X"),
]

_GENERIC_RESULTS = [
    _organic("widget.example", "Widget X home"),
    _organic("toolco.io", "Toolco docs"),
    _organic("rando.net", "Random blog"),
]

_LISTICLE_RESULTS = [
    _organic("rando.net", "10 Best Mowers of 2026"),
    _organic("siteb.net", "Top 5 Robot Mowers"),
    _organic("realuse.example", "How I picked my mower"),
]


_MEDIA_PUBS = {
    "general": ["nytimes.com", "forbes.com", "wsj.com"],
}


# ---------- defaults / empty profile ----------


def test_empty_profile_produces_no_findings():
    profile = OperatorProfile()
    cluster = _cluster(
        "x",
        [_query_payload(q, _AUTHORITY_RESULTS, ai_overview=True)
         for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.warnings == []
    assert r.auto_fail_gate_2 is False


# ---------- Expertise check ----------


def test_expertise_check_auto_fails_when_no_overlap():
    """Informational intent + E-E-A-T-rewarded SERP + no expertise overlap → auto-fail."""
    profile = OperatorProfile(expertise=["Python CLI tooling"])
    cluster = _cluster(
        "nutrition tracking",
        [_query_payload(q, _AUTHORITY_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    # Patch the queries to match the topic, so intent + authority both fire.
    cluster["cluster_queries"] = _INFORMATIONAL_5Q
    cluster["topic"] = "nutrition tracking apps"
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is True
    assert any("Operator lacks declared expertise" in w for w in r.warnings)


def test_expertise_check_no_fail_when_overlap():
    """Topic stems overlap with expertise → check does not fire."""
    profile = OperatorProfile(expertise=["Python CLI tooling"])
    cluster = _cluster(
        "python cli framework comparison",
        [_query_payload(q, _AUTHORITY_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is False
    assert _FINDING_EXPERTISE_PARTIAL not in " ".join(r.warnings)


def test_expertise_check_no_fail_when_commercial_intent():
    """Commercial queries don't trigger the expertise check even
    if SERP is authority-rewarded and there's no overlap."""
    profile = OperatorProfile(expertise=["something else"])
    cluster = _cluster(
        "specialty mowers",
        [_query_payload(q, _AUTHORITY_RESULTS) for q in _COMMERCIAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is False


def test_expertise_check_no_fail_when_serp_not_authority():
    """Generic publisher results don't trigger E-E-A-T threshold."""
    profile = OperatorProfile(expertise=["something else"])
    cluster = _cluster(
        "widget x",
        [_query_payload(q, _GENERIC_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is False


def test_expertise_check_no_fail_when_expertise_empty():
    """Empty expertise[] → check no-ops (we have nothing to compare)."""
    profile = OperatorProfile(expertise=[])
    cluster = _cluster(
        "nutrition tracking",
        [_query_payload(q, _AUTHORITY_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is False


def test_expertise_check_institutional_tld_counts():
    """Institutional TLDs (.gov, .edu) qualify as E-E-A-T even without
    appearing in the media-pubs list."""
    profile = OperatorProfile(expertise=["X"])
    cluster = _cluster(
        "nutrition",
        [_query_payload(q, [
            _organic("cdc.gov"),
            _organic("nih.gov"),
            _organic("harvard.edu"),
        ]) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs={})
    assert r.auto_fail_gate_2 is True


# ---------- Workflow check ----------


def test_workflow_check_fires_for_builder_with_listicle_serps():
    profile = OperatorProfile(
        expertise=[],  # disable expertise check
        workflow_preference="builder",
    )
    cluster = _cluster(
        "robot lawn mower",
        [_query_payload(q, _LISTICLE_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is False
    assert any("Builder profile" in w for w in r.warnings)


def test_workflow_check_silent_for_mixed_profile():
    profile = OperatorProfile(workflow_preference="mixed")
    cluster = _cluster(
        "robot lawn mower",
        [_query_payload(q, _LISTICLE_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert not any("Builder profile" in w for w in r.warnings)


def test_workflow_check_silent_for_writer_profile():
    profile = OperatorProfile(workflow_preference="writer")
    cluster = _cluster(
        "robot lawn mower",
        [_query_payload(q, _LISTICLE_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert not any("Builder profile" in w for w in r.warnings)


def test_workflow_check_silent_when_no_listicle_dominance():
    profile = OperatorProfile(workflow_preference="builder")
    cluster = _cluster(
        "robot lawn mower",
        [_query_payload(q, _GENERIC_RESULTS) for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert not any("Builder profile" in w for w in r.warnings)


# ---------- Cadence check ----------


def test_cadence_check_fires_for_weekly_evergreen():
    profile = OperatorProfile(motivation_cadence="weekly")
    cluster = _cluster(
        "X",
        [_query_payload(q, _GENERIC_RESULTS, ai_overview=True)
         for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert any("Cadence: weekly" in w for w in r.warnings)


def test_cadence_check_silent_for_monthly_default():
    profile = OperatorProfile(motivation_cadence="monthly")
    cluster = _cluster(
        "X",
        [_query_payload(q, _GENERIC_RESULTS, ai_overview=True)
         for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert not any("Cadence: weekly" in w for w in r.warnings)


def test_cadence_check_silent_without_ai_overview():
    profile = OperatorProfile(motivation_cadence="weekly")
    cluster = _cluster(
        "X",
        [_query_payload(q, _GENERIC_RESULTS, ai_overview=False)
         for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert not any("Cadence: weekly" in w for w in r.warnings)


def test_cadence_check_silent_for_commercial_intent():
    profile = OperatorProfile(motivation_cadence="weekly")
    cluster = _cluster(
        "X",
        [_query_payload(q, _GENERIC_RESULTS, ai_overview=True)
         for q in _COMMERCIAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert not any("Cadence: weekly" in w for w in r.warnings)


# ---------- combined behavior ----------


def test_multiple_findings_compose():
    """Builder + weekly + no-overlap, on a listicle-heavy informational
    cluster with AI Overviews → all three findings fire and auto_fail."""
    profile = OperatorProfile(
        expertise=["unrelated"],
        workflow_preference="builder",
        motivation_cadence="weekly",
    )
    cluster = _cluster(
        "robot mower",
        [_query_payload(q, _LISTICLE_RESULTS + _AUTHORITY_RESULTS,
                        ai_overview=True)
         for q in _INFORMATIONAL_5Q],
    )
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert r.auto_fail_gate_2 is True
    assert len(r.warnings) == 3
    assert any("Operator lacks declared expertise" in w for w in r.warnings)
    assert any("Builder profile" in w for w in r.warnings)
    assert any("Cadence: weekly" in w for w in r.warnings)


def test_returns_operator_fit_result_type():
    profile = OperatorProfile()
    cluster = _cluster("x", [])
    r = evaluate_operator_fit(cluster, profile, media_pubs=_MEDIA_PUBS)
    assert isinstance(r, OperatorFitResult)


# Sentinel — used in test_expertise_check_no_fail_when_overlap.
_FINDING_EXPERTISE_PARTIAL = "Operator lacks declared expertise"
