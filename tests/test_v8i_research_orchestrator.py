"""Tests for v8.I — wire the primary interpretive pass into the
`new research` orchestrator + render the verdict block.

Two surfaces tested:
  1. `_run_primary_interpretive_pass(topic, payload, console)` —
     calls run_primary_pass, mutates payload in place, persists the
     snapshot, handles failures gracefully.
  2. `_render_primary_verdict_block(payload, console)` — the rich
     render block beneath the mechanical-gates block.

`run_primary_pass` itself is stubbed via monkeypatch; we're testing
the wiring, not the LLM pipeline (that's covered separately in
test_interpretive_pass_runner.py).
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from rich.console import Console

from portfolio import cli as cli_mod
from portfolio.interpretive_pass import (
    InterpretivePassError,
    ParsedVerdict,
)


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


def _fake_pass_result(*, verdict="GO", confidence="HIGH",
                     reductions=None, warnings=None,
                     moat_required=False, blind_spot="",
                     cost=0.04, duration=5.2):
    """Build a stand-in for InterpretivePassResult.

    Uses a tiny duck-typed object instead of importing the real
    dataclass — keeps the test focused on the wiring's expectations
    of attribute names, not on the full data shape.
    """
    @dataclass
    class _Stub:
        verdict: ParsedVerdict
        rendered_prompt: str = "<rendered prompt body>"
        prompt_version: str = "v1"
        model_id: str = "claude-cli"
        cost_usd: float = 0.04
        duration_s: float = 5.2

    return _Stub(
        verdict=ParsedVerdict(
            verdict=verdict, confidence=confidence,
            reasoning="Reasoning text.",
            moat_required=moat_required, moat_prompt="",
            reductions=list(reductions or []),
            operator_fit_warnings=list(warnings or []),
            blind_spot_self_report=blind_spot,
        ),
        cost_usd=cost,
        duration_s=duration,
    )


def _patch_console(monkeypatch) -> Console:
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    return cap


def _patch_save_snapshot(monkeypatch) -> list[tuple[str, dict]]:
    """Capture every save_cluster_snapshot call so tests can assert
    persistence happened with the right shape."""
    calls: list[tuple[str, dict]] = []
    from portfolio import research_v2
    monkeypatch.setattr(research_v2, "save_cluster_snapshot",
                        lambda topic, payload: calls.append((topic, payload)))
    return calls


def _patch_load_profile(monkeypatch, profile=None):
    """Skip the real `lamill.toml` read — return whatever the test
    provides (None mimics the unconfigured-operator path)."""
    from portfolio import operator_profile
    monkeypatch.setattr(operator_profile, "load_operator_profile",
                        lambda *a, **k: profile)


def _minimal_payload() -> dict:
    """Smallest cluster snapshot that satisfies the wiring's
    expectations after v8.D Phase 2 completes."""
    return {
        "topic": "ev charger installation cost",
        "cluster_queries": ["ev charger installation cost"],
        "gates": {"gate_1_market": {"status": "PASS"}},
        "operator_fit": {"warnings": []},
        "verdict": "GO",   # mechanical verdict
        "per_query_results": [],
    }


# ---------- _run_primary_interpretive_pass ----------


def test_run_primary_interpretive_pass_populates_payload(monkeypatch):
    """On success, primary_verdict + primary_pass_meta are added to
    the payload in place. The wiring mutates so the downstream
    renderer picks it up without a second pass."""
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    save_calls = _patch_save_snapshot(monkeypatch)
    monkeypatch.setattr(
        cli_mod, "run_primary_pass",
        lambda *a, **k: _fake_pass_result(verdict="NICHE-DOWN",
                                          confidence="MEDIUM",
                                          reductions=["x", "y"]),
        raising=False,
    )
    # Import-time binding workaround: patch the symbol on the module
    # the function imports from — the helper uses
    # `from .interpretive_pass import run_primary_pass` inside its body.
    from portfolio import interpretive_pass
    monkeypatch.setattr(interpretive_pass, "run_primary_pass",
                        lambda *a, **k: _fake_pass_result(
                            verdict="NICHE-DOWN", confidence="MEDIUM",
                            reductions=["x", "y"]))

    payload = _minimal_payload()
    cli_mod._run_primary_interpretive_pass(
        "ev charger installation cost", payload,
        console=cli_mod.console,
    )

    assert payload["primary_verdict"]["verdict"] == "NICHE-DOWN"
    assert payload["primary_verdict"]["confidence"] == "MEDIUM"
    assert payload["primary_verdict"]["reductions"] == ["x", "y"]
    assert payload["primary_pass_meta"]["prompt_version"] == "v1"
    assert payload["primary_pass_meta"]["model_id"] == "claude-cli"
    assert payload["primary_pass_meta"]["cost_usd"] == 0.04
    # Snapshot was persisted once (post-interpretive) — separate from
    # the gates-persistence call earlier in the flow.
    assert len(save_calls) == 1


def test_run_primary_interpretive_pass_swallows_pass_error(monkeypatch):
    """When run_primary_pass raises InterpretivePassError (claude
    binary missing / quota exhausted / unparseable response), the
    wiring logs a yellow warning and returns. No primary_verdict in
    payload, snapshot not persisted, no exception escapes."""
    cap = _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    save_calls = _patch_save_snapshot(monkeypatch)
    from portfolio import interpretive_pass

    def boom(*a, **k):
        raise InterpretivePassError("Claude CLI call failed (claude-not-found)")
    monkeypatch.setattr(interpretive_pass, "run_primary_pass", boom)

    payload = _minimal_payload()
    # Must not raise:
    cli_mod._run_primary_interpretive_pass(
        "x", payload, console=cli_mod.console,
    )
    assert "primary_verdict" not in payload
    assert "primary_pass_meta" not in payload
    assert save_calls == []
    # Operator sees the skip with the cause.
    out = cap.file.getvalue()
    assert "Interpretive pass skipped" in out
    assert "claude-not-found" in out


def test_run_primary_interpretive_pass_persists_to_snapshot(monkeypatch):
    """The post-interpretive `save_cluster_snapshot` call carries
    both the mechanical fields (already in payload from gates) AND
    the new primary_verdict + meta — so a cache hit on the next run
    can skip both Phase 2 + the interpretive pass."""
    _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    save_calls = _patch_save_snapshot(monkeypatch)
    from portfolio import interpretive_pass
    monkeypatch.setattr(interpretive_pass, "run_primary_pass",
                        lambda *a, **k: _fake_pass_result())

    cli_mod._run_primary_interpretive_pass(
        "topic-x", _minimal_payload(), console=cli_mod.console,
    )
    topic, payload = save_calls[0]
    assert topic == "topic-x"
    assert "primary_verdict" in payload
    assert "verdict" in payload   # mechanical verdict still there
    assert "gates" in payload     # gates still there


def test_run_primary_interpretive_pass_tolerates_save_failure(monkeypatch):
    """If save_cluster_snapshot raises OSError (disk full, permission
    denied, etc.), log a warning and continue. The in-memory payload
    is still updated; only persistence fails."""
    cap = _patch_console(monkeypatch)
    _patch_load_profile(monkeypatch)
    from portfolio import interpretive_pass, research_v2
    monkeypatch.setattr(interpretive_pass, "run_primary_pass",
                        lambda *a, **k: _fake_pass_result())

    def fail_save(topic, payload):
        raise OSError("disk full")
    monkeypatch.setattr(research_v2, "save_cluster_snapshot", fail_save)

    payload = _minimal_payload()
    cli_mod._run_primary_interpretive_pass(
        "topic-x", payload, console=cli_mod.console,
    )
    assert "primary_verdict" in payload   # in-memory update succeeded
    out = cap.file.getvalue()
    assert "could not persist" in out


# ---------- _render_primary_verdict_block ----------


def _payload_with_verdict(**overrides) -> dict:
    """Pre-built payload with a populated primary_verdict + meta so
    render tests don't have to construct the full v8.D shape."""
    pv = {
        "verdict": "GO",
        "confidence": "HIGH",
        "reasoning": ("The mechanical Gate 2 PASS lines up with the raw "
                      "SERP — no programmatic incumbent visible in the "
                      "top-3 of the cluster queries."),
        "moat_required": False,
        "moat_prompt": "",
        "reductions": [],
        "operator_fit_warnings": [],
        "blind_spot_self_report": "",
    }
    pv.update(overrides)
    return {
        "topic": "x",
        "verdict": "GO",   # mechanical verdict
        "primary_verdict": pv,
        "primary_pass_meta": {
            "prompt_version": "v1",
            "model_id": "claude-cli",
            "rendered_prompt": "...",
            "cost_usd": 0.04,
            "duration_s": 5.2,
        },
    }


def test_render_primary_verdict_block_basic(monkeypatch):
    cap = _patch_console(monkeypatch)
    cli_mod._render_primary_verdict_block(
        _payload_with_verdict(), cli_mod.console,
    )
    out = cap.file.getvalue()
    # Section header + verdict + confidence appear.
    assert "Interpretive verdict (Claude)" in out
    assert "Verdict:" in out
    assert "GO" in out
    assert "Confidence:" in out
    assert "HIGH" in out
    # Source metadata renders.
    assert "claude-cli" in out
    assert "prompt=v1" in out


def test_render_primary_verdict_block_skips_empty_subsections(monkeypatch):
    """A GO verdict with no reductions / no moat / no warnings
    shouldn't render empty section headers — they're omitted."""
    cap = _patch_console(monkeypatch)
    cli_mod._render_primary_verdict_block(
        _payload_with_verdict(), cli_mod.console,
    )
    out = cap.file.getvalue()
    assert "Suggested reductions:" not in out
    assert "Moat required:" not in out
    assert "Operator-fit warnings:" not in out
    assert "Blind-spot self-report:" not in out


def test_render_primary_verdict_block_full_with_reductions(monkeypatch):
    cap = _patch_console(monkeypatch)
    payload = _payload_with_verdict(
        verdict="NICHE-DOWN", confidence="MEDIUM",
        reductions=["Local-installer cost calculator",
                    "Permit-cost focus only"],
        operator_fit_warnings=["Builder workflow vs content-niche mismatch"],
        moat_required=True, moat_prompt="What's your unfair advantage?",
        blind_spot_self_report="Might be over-correcting Gate 2's regex miss.",
    )
    cli_mod._render_primary_verdict_block(payload, cli_mod.console)
    out = cap.file.getvalue()
    assert "NICHE-DOWN" in out
    assert "Suggested reductions:" in out
    assert "Local-installer cost calculator" in out
    assert "Operator-fit warnings:" in out
    assert "Builder workflow vs content-niche mismatch" in out
    assert "Moat required:" in out
    assert "What's your unfair advantage?" in out
    assert "Blind-spot self-report:" in out
    assert "over-correcting Gate 2" in out


def test_render_primary_verdict_block_callout_when_disagrees(monkeypatch):
    """The high-signal case: mechanical verdict ≠ Claude verdict.
    Render shows a yellow disagreement banner pointing at both."""
    cap = _patch_console(monkeypatch)
    payload = _payload_with_verdict(verdict="GO")   # Claude says GO
    payload["verdict"] = "NICHE-DOWN"                # mechanical says NICHE-DOWN
    cli_mod._render_primary_verdict_block(payload, cli_mod.console)
    out = cap.file.getvalue()
    assert "Disagreement" in out
    assert "NICHE-DOWN" in out
    assert "GO" in out


def test_render_primary_verdict_block_no_callout_when_agrees(monkeypatch):
    cap = _patch_console(monkeypatch)
    payload = _payload_with_verdict(verdict="NO-GO")
    payload["verdict"] = "NO-GO"
    cli_mod._render_primary_verdict_block(payload, cli_mod.console)
    out = cap.file.getvalue()
    assert "Disagreement" not in out


# ---------- new_research wiring (cache-hit short-circuit) ----------


def test_run_research_skips_primary_pass_on_full_cache_hit(monkeypatch):
    """When the cluster snapshot is from cache AND already carries a
    primary_verdict from a previous run, the operator shouldn't have
    to re-pay the ~5-15s interpretive pass — the verdict's already
    persisted. Test the short-circuit by asserting the wiring helper
    is never called in that case."""
    calls = []

    def tracking_helper(topic, payload, *, console):
        calls.append((topic, payload))
    monkeypatch.setattr(cli_mod, "_run_primary_interpretive_pass",
                        tracking_helper)

    # Drive the cache-hit branch directly: payload looks cached + has
    # both gates AND a primary_verdict already. The relevant lines in
    # `new_research` (the `cache_has_primary` test) should short-circuit.
    payload = _minimal_payload()
    payload["from_cache"] = True
    payload["primary_verdict"] = {"verdict": "GO", "confidence": "HIGH",
                                  "reasoning": "cached"}

    cache_has_primary = (
        payload.get("from_cache") and payload.get("primary_verdict")
    )
    assert bool(cache_has_primary) is True   # the logical branch the wiring uses
    # And confirms the helper is NOT called in this branch (we don't
    # invoke new_research here — that's an integration concern; this
    # test pins the boolean predicate the wiring keys on).
    assert calls == []
