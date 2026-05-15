"""Tests for v8.D P2.A — three-gate skeleton.

P2.A is the dataclass / orchestrator scaffold. The actual gate logic
(volume math, classifiers, moat handling, verdict synthesis) lands in
P2.B / P2.C / P2.D / P2.E. These tests fix the *shape* so subsequent
commits can't accidentally break the contract.
"""
from __future__ import annotations

import pytest

from portfolio.research_gates import (
    GATE_1_VOLUME_THRESHOLD,
    GATE_2_BEATABLE_THRESHOLD,
    LABEL_FAIL,
    LABEL_PASS,
    LABEL_PENDING,
    LABEL_WEAK_PASS,
    VERDICT_GO,
    VERDICT_NICHE_DOWN,
    VERDICT_NO_GO,
    GateResult,
    GateResults,
    OperatorFitResult,
    evaluate_cluster,
    evaluate_gate_1,
    evaluate_gate_2,
    evaluate_gate_3,
    is_moat_required,
    synthesize_verdict,
)


# ---------- constants ----------


def test_label_constants_are_distinct():
    assert {LABEL_PASS, LABEL_FAIL, LABEL_WEAK_PASS, LABEL_PENDING} == \
        {"PASS", "FAIL", "WEAK-PASS", "PENDING"}


def test_verdict_constants_are_distinct():
    assert {VERDICT_GO, VERDICT_NICHE_DOWN, VERDICT_NO_GO} == \
        {"GO", "NICHE-DOWN", "NO-GO"}


def test_gate_1_threshold_matches_prd():
    """PRD §P2.2: pollution-adjusted volume must be ≥5K SV/month to PASS."""
    assert GATE_1_VOLUME_THRESHOLD == 5000


def test_gate_2_beatable_threshold_matches_prd():
    """PRD §P2.3: at least 3 POTENTIALLY_BEATABLE results to PASS."""
    assert GATE_2_BEATABLE_THRESHOLD == 3


# ---------- GateResult / GateResults dataclass ----------


def test_gate_result_serializes_to_dict():
    r = GateResult(passed=True, label=LABEL_PASS,
                   findings=["12K SV"], raw={"volume": 12000})
    d = r.to_dict()
    assert d == {
        "passed": True, "label": "PASS",
        "findings": ["12K SV"], "raw": {"volume": 12000},
    }


def test_gate_result_defaults():
    """Empty findings + raw default to empty list / dict."""
    r = GateResult(passed=False, label=LABEL_FAIL)
    assert r.findings == []
    assert r.raw == {}


def test_gate_result_passed_can_be_none():
    """PENDING gates carry passed=None — verdict logic treats as fail."""
    r = GateResult(passed=None, label=LABEL_PENDING)
    assert r.passed is None


def test_operator_fit_result_defaults_empty():
    op = OperatorFitResult()
    assert op.warnings == []
    assert op.auto_fail_gate_2 is False


def test_gate_results_to_dict_round_trips():
    g1 = GateResult(passed=True, label=LABEL_PASS, findings=["m1"])
    g2 = GateResult(passed=False, label=LABEL_FAIL, findings=["s1"])
    g3 = GateResult(passed=None, label=LABEL_PENDING)
    op = OperatorFitResult(warnings=["w"], auto_fail_gate_2=True)
    r = GateResults(
        gate_1_market=g1, gate_2_serp=g2, gate_3_moat=g3,
        operator_fit=op, verdict=VERDICT_NICHE_DOWN,
        suggested_reductions=["narrow to EV"],
        moat_required=True, moat_provided="my-edge",
    )
    d = r.to_dict()
    assert d["verdict"] == "NICHE-DOWN"
    assert d["gate_1_market"]["label"] == "PASS"
    assert d["gate_2_serp"]["label"] == "FAIL"
    assert d["gate_3_moat"]["label"] == "PENDING"
    assert d["operator_fit"]["auto_fail_gate_2"] is True
    assert d["suggested_reductions"] == ["narrow to EV"]
    assert d["moat_required"] is True
    assert d["moat_provided"] == "my-edge"


def test_gate_results_to_dict_keys_match_schema():
    """The dict keys are the slots that get written into the cluster
    snapshot's `gates` / `verdict` / `operator_fit` fields. Locked here
    so the renderer / cache layer can rely on them."""
    g = GateResult(passed=True, label=LABEL_PASS)
    r = GateResults(
        gate_1_market=g, gate_2_serp=g, gate_3_moat=g,
        operator_fit=OperatorFitResult(),
        verdict=VERDICT_GO,
    )
    d = r.to_dict()
    assert set(d.keys()) == {
        "gate_1_market", "gate_2_serp", "gate_3_moat",
        "operator_fit", "verdict",
        "suggested_reductions", "moat_required", "moat_provided",
    }


# ---------- stub gate functions ----------


def test_evaluate_gate_1_stub_returns_pending():
    r = evaluate_gate_1({"topic": "x"})
    assert r.label == LABEL_PENDING
    assert r.passed is None
    assert "P2.B" in " ".join(r.findings)


def test_evaluate_gate_2_stub_returns_pending():
    r = evaluate_gate_2({"topic": "x"})
    assert r.label == LABEL_PENDING
    assert r.passed is None


def test_evaluate_gate_3_stub_returns_pending():
    g2 = GateResult(passed=False, label=LABEL_FAIL)
    r = evaluate_gate_3(g2, None)
    assert r.label == LABEL_PENDING


# ---------- moat-required helper ----------


def test_is_moat_required_when_specialty_incumbent_detected():
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {"specialty_incumbent": ["notateslaapp.com"]}
    })
    assert is_moat_required(g2) is True


def test_is_moat_required_when_programmatic_at_scale_detected():
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {"programmatic_at_scale": ["someone.com"]}
    })
    assert is_moat_required(g2) is True


def test_is_moat_required_false_when_only_softer_classifiers():
    """Reddit + media + AI-Overview alone do NOT trigger moat —
    only specialty/programmatic incumbents do (PRD §P2.4)."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "reddit_present": True,
            "media_locked": ["wpengine.com"],
            "ai_overview_dominant": True,
        }
    })
    assert is_moat_required(g2) is False


def test_is_moat_required_false_when_raw_empty():
    g2 = GateResult(passed=True, label=LABEL_PASS)
    assert is_moat_required(g2) is False


def test_is_moat_required_false_when_classifications_missing():
    g2 = GateResult(passed=True, label=LABEL_PASS, raw={"other": "data"})
    assert is_moat_required(g2) is False


# ---------- synthesize_verdict (stub) ----------


def test_synthesize_verdict_stub_returns_no_go():
    """Stub returns NO-GO until P2.E lands. Locks the function signature."""
    g_pending = GateResult(passed=None, label=LABEL_PENDING)
    assert synthesize_verdict(g_pending, g_pending, g_pending) == VERDICT_NO_GO


def test_synthesize_verdict_accepts_op_fit_kw():
    """Keyword-only operator-fit param is part of the signature so
    Phase 3 can wire it without changing call sites."""
    g = GateResult(passed=True, label=LABEL_PASS)
    op = OperatorFitResult(warnings=["w"], auto_fail_gate_2=True)
    result = synthesize_verdict(g, g, g, op_fit=op)
    # Stub still returns NO-GO — but the call must accept op_fit.
    assert result in {VERDICT_GO, VERDICT_NICHE_DOWN, VERDICT_NO_GO}


# ---------- evaluate_cluster (orchestrator) ----------


def test_evaluate_cluster_returns_full_gate_results():
    """The orchestrator returns a GateResults with all four slots
    populated, even when every individual gate is a stub PENDING."""
    cluster = {"topic": "x", "cluster_queries": ["x"], "per_query_results": []}
    r = evaluate_cluster(cluster)
    assert isinstance(r, GateResults)
    assert r.gate_1_market.label == LABEL_PENDING
    assert r.gate_2_serp.label == LABEL_PENDING
    assert r.gate_3_moat.label == LABEL_PENDING
    assert isinstance(r.operator_fit, OperatorFitResult)


def test_evaluate_cluster_carries_moat_through():
    cluster = {"topic": "x"}
    r = evaluate_cluster(cluster, moat_sentence="my moat")
    assert r.moat_provided == "my moat"


def test_evaluate_cluster_defaults_no_moat():
    cluster = {"topic": "x"}
    r = evaluate_cluster(cluster)
    assert r.moat_provided is None


def test_evaluate_cluster_with_operator_fit_carries_through():
    cluster = {"topic": "x"}
    op = OperatorFitResult(warnings=["builder + writer niche"])
    r = evaluate_cluster(cluster, operator_fit=op)
    assert r.operator_fit.warnings == ["builder + writer niche"]


def test_evaluate_cluster_non_interactive_does_not_crash():
    """The non_interactive flag is part of the orchestrator signature
    so the CLI's --json / --non-interactive paths can pass it."""
    cluster = {"topic": "x"}
    r = evaluate_cluster(cluster, non_interactive=True)
    assert r.gate_3_moat.label == LABEL_PENDING
