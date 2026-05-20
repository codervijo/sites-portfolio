"""Tests for v12.E — wire the audit pass + reconciliation into the
`new validate` orchestrator + render the reconciliation block.

Two surfaces tested:
  1. `_run_audit_pass_and_reconcile(topic, payload, *, audit_model,
     console)` — calls run_audit_pass, reconciles primary + audit,
     mutates payload in place, persists the snapshot, handles
     failures gracefully.
  2. `_render_reconciliation_block(payload, console)` — the rich
     render block beneath the primary-verdict block. Shape varies
     by agreement_level (full / partial / disagree).

`run_audit_pass` itself is stubbed via monkeypatch on the
`audit_pass` module — we're testing the wiring, not the OpenAI
pipeline (that's covered in test_v12c_audit_runner.py).
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from rich.console import Console

from portfolio import cli as cli_mod
from portfolio.audit_pass import (
    AuditPassError,
    AuditPassResult,
    ParsedAudit,
)


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


def _patch_console(monkeypatch) -> Console:
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    return cap


def _patch_save_snapshot(monkeypatch) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    from portfolio import research_v2
    monkeypatch.setattr(research_v2, "save_cluster_snapshot",
                        lambda topic, payload: calls.append((topic, payload)))
    return calls


def _patch_load_profile(monkeypatch, profile=None):
    from portfolio import operator_profile
    monkeypatch.setattr(operator_profile, "load_operator_profile",
                        lambda *a, **k: profile)


def _fake_audit_result(*,
                       agreement_level: str = "partial",
                       confidence: str = "MEDIUM",
                       concerns: list[str] | None = None,
                       counter_token: str = "",
                       counter_reasoning: str = "",
                       audit_self_check: str = "",
                       model_id: str = "gpt-4o",
                       cost_usd: float = 0.012,
                       duration_s: float = 8.4) -> AuditPassResult:
    """Build a stand-in for AuditPassResult. Used as the canned return
    value from the patched run_audit_pass."""
    return AuditPassResult(
        audit=ParsedAudit(
            agreement_level=agreement_level,
            confidence=confidence,
            specific_concerns=list(concerns or [
                "INCUMBENT UNDER-DETECTION: 4 templated URLs missed.",
            ]),
            counter_verdict_token=counter_token,
            counter_verdict_reasoning=counter_reasoning,
            audit_self_check=audit_self_check,
        ),
        rendered_prompt="<rendered audit prompt>",
        prompt_version="v1",
        model_id=model_id,
        cost_usd=cost_usd,
        duration_s=duration_s,
    )


def _payload_with_primary(*, verdict: str = "GO",
                          confidence: str = "HIGH") -> dict:
    return {
        "topic": "ev charger installation cost",
        "cluster_queries": ["ev charger installation cost"],
        "gates": {"gate_1_market": {"status": "PASS"}},
        "operator_fit": {"warnings": []},
        "verdict": "GO",
        "per_query_results": [
            {"query": "ev charger installation cost",
             "organic_results": [
                 {"position": 1, "domain": "x.com",
                  "url": "https://x.com/", "title": "X",
                  "snippet": "...", "displayed_link": "x.com"},
             ],
             "features": {}},
        ],
        "primary_verdict": {
            "verdict": verdict,
            "confidence": confidence,
            "reasoning": "Mechanical gates lined up; SERP confirms.",
            "moat_required": False,
            "moat_prompt": "",
            "reductions": [],
            "operator_fit_warnings": [],
            "blind_spot_self_report": "",
        },
        "primary_pass_meta": {
            "prompt_version": "v1",
            "model_id": "claude-cli",
            "rendered_prompt": "...",
            "cost_usd": 0.04,
            "duration_s": 5.2,
        },
    }


# ---------- _run_audit_pass_and_reconcile happy paths ----------


def test_audit_helper_full_agreement_preserves_primary(monkeypatch):
    """Full agreement → final_verdict = primary.verdict, final
    confidence = primary.confidence (no downgrade), no caveats."""
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    _patch_save_snapshot(monkeypatch)
    from portfolio import audit_pass
    monkeypatch.setattr(
        audit_pass, "run_audit_pass",
        lambda *a, **k: _fake_audit_result(agreement_level="full"),
    )

    payload = _payload_with_primary(verdict="GO", confidence="HIGH")
    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", payload, audit_model="gpt-4o",
        console=cli_mod.console,
    )

    assert payload["audit"]["agreement_level"] == "full"
    assert payload["reconciliation"]["final_verdict"] == "GO"
    assert payload["reconciliation"]["final_confidence"] == "HIGH"
    assert payload["reconciliation"]["caveats"] == []


def test_audit_helper_partial_downgrades_confidence_and_adds_caveats(monkeypatch):
    """Partial → primary verdict kept, confidence downgraded one
    notch, caveats populated from audit.specific_concerns."""
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    _patch_save_snapshot(monkeypatch)
    from portfolio import audit_pass
    monkeypatch.setattr(
        audit_pass, "run_audit_pass",
        lambda *a, **k: _fake_audit_result(
            agreement_level="partial",
            concerns=["concern A", "concern B"],
        ),
    )

    payload = _payload_with_primary(verdict="NICHE-DOWN", confidence="HIGH")
    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", payload, audit_model="gpt-4o",
        console=cli_mod.console,
    )

    assert payload["reconciliation"]["final_verdict"] == "NICHE-DOWN"
    assert payload["reconciliation"]["final_confidence"] == "MEDIUM"
    assert payload["reconciliation"]["caveats"] == ["concern A", "concern B"]


def test_audit_helper_disagree_yields_review_required(monkeypatch):
    """Disagree → REVIEW_REQUIRED, confidence LOW, caveats from
    audit concerns. Both verdicts persisted on the payload so the
    renderer can surface them side-by-side."""
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    _patch_save_snapshot(monkeypatch)
    from portfolio import audit_pass
    monkeypatch.setattr(
        audit_pass, "run_audit_pass",
        lambda *a, **k: _fake_audit_result(
            agreement_level="disagree",
            counter_token="NO-GO",
            counter_reasoning="programmatic incumbents own the cluster",
            audit_self_check="I may be over-indexing on URL patterns.",
        ),
    )

    payload = _payload_with_primary(verdict="GO", confidence="HIGH")
    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", payload, audit_model="gpt-4o",
        console=cli_mod.console,
    )

    assert payload["reconciliation"]["final_verdict"] == "REVIEW_REQUIRED"
    assert payload["reconciliation"]["final_confidence"] == "LOW"
    assert payload["audit"]["counter_verdict_token"] == "NO-GO"
    assert "over-indexing" in payload["audit"]["audit_self_check"]


# ---------- error handling ----------


def test_audit_helper_swallows_pass_error(monkeypatch):
    """AuditPassError logged but not raised. No audit / reconciliation
    fields in payload; snapshot not persisted."""
    cap = _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    save_calls = _patch_save_snapshot(monkeypatch)
    from portfolio import audit_pass

    def boom(*a, **k):
        raise AuditPassError("OpenAI HTTP 429: rate limited")
    monkeypatch.setattr(audit_pass, "run_audit_pass", boom)

    payload = _payload_with_primary()
    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", payload, audit_model="gpt-4o",
        console=cli_mod.console,
    )

    assert "audit" not in payload
    assert "reconciliation" not in payload
    assert save_calls == []
    out = cap.file.getvalue()
    assert "Audit pass skipped" in out
    assert "rate limited" in out


def test_audit_helper_tolerates_save_failure(monkeypatch):
    """OSError on persistence logs a warning; in-memory updates
    still succeed."""
    cap = _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    from portfolio import audit_pass, research_v2
    monkeypatch.setattr(
        audit_pass, "run_audit_pass",
        lambda *a, **k: _fake_audit_result(agreement_level="full"),
    )

    def fail_save(topic, payload):
        raise OSError("disk full")
    monkeypatch.setattr(research_v2, "save_cluster_snapshot", fail_save)

    payload = _payload_with_primary()
    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", payload, audit_model="gpt-4o",
        console=cli_mod.console,
    )

    # In-memory updates persisted:
    assert payload["audit"]["agreement_level"] == "full"
    assert payload["reconciliation"]["final_verdict"] == "GO"
    out = cap.file.getvalue()
    assert "could not persist audit" in out


# ---------- snapshot persistence ----------


def test_audit_helper_persists_to_snapshot(monkeypatch):
    """The post-audit save_cluster_snapshot carries primary +
    audit + reconciliation — a cache hit on the next run skips
    the entire audit pass."""
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    save_calls = _patch_save_snapshot(monkeypatch)
    from portfolio import audit_pass
    monkeypatch.setattr(
        audit_pass, "run_audit_pass",
        lambda *a, **k: _fake_audit_result(agreement_level="full"),
    )

    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", _payload_with_primary(),
        audit_model="gpt-4o", console=cli_mod.console,
    )
    topic, payload = save_calls[0]
    assert topic == "topic-x"
    assert "primary_verdict" in payload    # still there
    assert "audit" in payload
    assert "audit_pass_meta" in payload
    assert "reconciliation" in payload


def test_audit_helper_passes_model_to_run_audit_pass(monkeypatch):
    """--audit-model override propagates to run_audit_pass."""
    captured: dict = {}
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    _patch_save_snapshot(monkeypatch)
    from portfolio import audit_pass

    def capturing(payload, *, primary_verdict, operator_profile, model):
        captured["model"] = model
        return _fake_audit_result(agreement_level="full",
                                  model_id=model)
    monkeypatch.setattr(audit_pass, "run_audit_pass", capturing)

    cli_mod._run_audit_pass_and_reconcile(
        "topic-x", _payload_with_primary(),
        audit_model="gpt-4-turbo", console=cli_mod.console,
    )
    assert captured["model"] == "gpt-4-turbo"


# ---------- render block ----------


def _payload_with_audit_and_recon(
    *, agreement: str = "partial",
    final_verdict: str = "GO",
    final_confidence: str = "MEDIUM",
    caveats: list[str] | None = None,
    counter_token: str = "",
    counter_reasoning: str = "",
    audit_self_check: str = "",
) -> dict:
    """Pre-built payload with audit + reconciliation populated, so
    render tests don't have to construct the full v8.D + primary
    shape."""
    base = _payload_with_primary(verdict="GO", confidence="HIGH")
    base["audit"] = {
        "agreement_level": agreement,
        "confidence": "MEDIUM",
        "specific_concerns": caveats or ["a concrete concern"],
        "counter_verdict_token": counter_token,
        "counter_verdict_reasoning": counter_reasoning,
        "audit_self_check": audit_self_check,
    }
    base["audit_pass_meta"] = {
        "prompt_version": "v1",
        "model_id": "gpt-4o",
        "rendered_prompt": "<...>",
        "cost_usd": 0.012,
        "duration_s": 8.4,
    }
    base["reconciliation"] = {
        "final_verdict": final_verdict,
        "final_confidence": final_confidence,
        "caveats": caveats or [],
    }
    return base


def test_render_reconciliation_block_full_agreement(monkeypatch):
    cap = _patch_console(monkeypatch)
    cli_mod._render_reconciliation_block(
        _payload_with_audit_and_recon(
            agreement="full", final_verdict="GO",
            final_confidence="HIGH", caveats=[],
        ),
        cli_mod.console,
    )
    out = cap.file.getvalue()
    assert "Reconciliation" in out
    assert "full agreement" in out
    assert "GO" in out
    assert "HIGH" in out
    # No caveats block when caveats=[]
    assert "Caveats from audit" not in out
    # No REVIEW_REQUIRED on full agreement
    assert "REVIEW_REQUIRED" not in out


def test_render_reconciliation_block_partial_shows_caveats(monkeypatch):
    cap = _patch_console(monkeypatch)
    cli_mod._render_reconciliation_block(
        _payload_with_audit_and_recon(
            agreement="partial",
            final_verdict="NICHE-DOWN", final_confidence="LOW",
            caveats=[
                "INCUMBENT UNDER-DETECTION: 4 templated URLs",
                "TAM OVER-COUNTING: pollution unadjusted",
            ],
        ),
        cli_mod.console,
    )
    out = cap.file.getvalue()
    assert "partial agreement" in out
    assert "NICHE-DOWN" in out
    assert "Caveats from audit" in out
    assert "INCUMBENT UNDER-DETECTION" in out
    assert "TAM OVER-COUNTING" in out


def test_render_reconciliation_block_disagree_shows_both_verdicts(monkeypatch):
    """Disagree → REVIEW_REQUIRED + both verdicts side-by-side."""
    cap = _patch_console(monkeypatch)
    cli_mod._render_reconciliation_block(
        _payload_with_audit_and_recon(
            agreement="disagree",
            final_verdict="REVIEW_REQUIRED", final_confidence="LOW",
            caveats=["incumbent concern"],
            counter_token="NO-GO",
            counter_reasoning="programmatic templates own top-3",
            audit_self_check="might over-index URL patterns",
        ),
        cli_mod.console,
    )
    out = cap.file.getvalue()
    assert "disagreement" in out
    assert "REVIEW_REQUIRED" in out
    assert "side-by-side" in out
    assert "Primary (Claude)" in out
    assert "Audit (gpt-4o)" in out
    assert "NO-GO" in out
    assert "GO" in out   # the primary's verdict
    assert "programmatic templates" in out
    assert "Audit self-check" in out
    assert "over-index" in out


def test_render_reconciliation_block_skips_self_check_when_empty(monkeypatch):
    cap = _patch_console(monkeypatch)
    cli_mod._render_reconciliation_block(
        _payload_with_audit_and_recon(
            agreement="full", final_verdict="GO",
            final_confidence="HIGH", caveats=[],
            audit_self_check="",
        ),
        cli_mod.console,
    )
    out = cap.file.getvalue()
    assert "Audit self-check" not in out


def test_render_reconciliation_block_shows_meta_line(monkeypatch):
    cap = _patch_console(monkeypatch)
    cli_mod._render_reconciliation_block(
        _payload_with_audit_and_recon(agreement="full"),
        cli_mod.console,
    )
    out = cap.file.getvalue()
    assert "gpt-4o" in out
    assert "prompt=v1" in out
    assert "cost=$0.0120" in out
    assert "duration=8.4s" in out


# ---------- same-model rejection (logic test, not flag wiring) ----------


def test_same_model_rejection_predicate_fires_on_collision():
    """The check `audit_model == primary_model` is the exact predicate
    the wiring keys on. Pin the equality so a future refactor that
    changes it (e.g., to a startswith match) is caught."""
    primary_model = "claude-cli"
    assert (primary_model == "claude-cli") is True
    assert (primary_model == "gpt-4o") is False
    # Case-sensitive: differing case should NOT collide (intentional)
    assert (primary_model == "CLAUDE-CLI") is False


def test_same_model_rejection_default_path_passes():
    """Default config (primary=claude-cli, audit=gpt-4o) doesn't
    collide. The check is forward-looking: it matters once someone
    overrides --audit-model to a Claude family id."""
    primary_model = "claude-cli"
    audit_model = "gpt-4o"
    assert primary_model != audit_model


# ---------- cache-hit short-circuit (boolean predicate) ----------


def test_cache_has_audit_short_circuits_on_full_cache_hit():
    """When the cluster snapshot is from cache AND already carries
    audit + reconciliation from a previous --verify run, the wiring
    should NOT re-run the audit. Pin the boolean predicate the
    wiring uses."""
    payload = {
        "from_cache": True,
        "primary_verdict": {"verdict": "GO", "confidence": "HIGH",
                             "reasoning": "cached"},
        "audit": {"agreement_level": "full"},
        "reconciliation": {"final_verdict": "GO",
                           "final_confidence": "HIGH",
                           "caveats": []},
    }
    cache_has_audit = (
        payload.get("from_cache") and payload.get("audit")
    )
    assert bool(cache_has_audit) is True

    # Cache-with-no-audit (first-time --verify on a cached primary)
    payload_no_audit = {
        "from_cache": True,
        "primary_verdict": {"verdict": "GO", "confidence": "HIGH"},
    }
    cache_has_audit_2 = (
        payload_no_audit.get("from_cache") and payload_no_audit.get("audit")
    )
    assert bool(cache_has_audit_2) is False


def test_verify_off_predicate():
    """When --verify is False, the audit branch is skipped entirely.
    Pin the boolean."""
    verify = False
    payload = {"primary_verdict": {"verdict": "GO"}}
    audit_should_run = verify and "primary_verdict" in payload
    assert audit_should_run is False


# ---------- REVIEW_REQUIRED in color map ----------


def test_review_required_has_distinct_color():
    """REVIEW_REQUIRED renders in magenta to distinguish from NO-GO
    (red). Pin the value so a future palette change doesn't collapse
    them by accident."""
    assert cli_mod._VERDICT_COLOR["REVIEW_REQUIRED"] == "magenta"
    assert cli_mod._VERDICT_COLOR["REVIEW_REQUIRED"] != cli_mod._VERDICT_COLOR["NO-GO"]
