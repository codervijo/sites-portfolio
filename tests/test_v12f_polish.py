"""Tests for v12.F — polish for the v12 audit-pass arc:
  (a) cost-estimate `costs` block aggregated into the cluster snapshot
  (b) `verify_by_default` operator-profile flag from `lamill.toml [operator]`
  (c) granular cache invalidation via `--invalidate {interpretive, audit, all}`

Three concerns under one phase; tests grouped by concern below.
"""
from __future__ import annotations

import io
import textwrap
from pathlib import Path

import pytest
from rich.console import Console

from portfolio import cli as cli_mod
from portfolio.operator_profile import (
    DEFAULT_VERIFY_BY_DEFAULT,
    OperatorProfile,
    load_operator_profile,
)


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


# ---------- (a) cost ledger — _update_cost_summary ----------


def test_update_cost_summary_aggregates_primary_only():
    """A primary-only run (no --verify) populates `costs` with audit
    contribution = 0 and total = primary."""
    payload = {
        "primary_pass_meta": {"cost_usd": 0.0423},
    }
    cli_mod._update_cost_summary(payload)
    assert payload["costs"]["primary_usd"] == pytest.approx(0.0423)
    assert payload["costs"]["audit_usd"] == 0.0
    assert payload["costs"]["total_usd"] == pytest.approx(0.0423)
    assert payload["costs"]["currency"] == "USD"


def test_update_cost_summary_aggregates_both_passes():
    """A --verify run populates both primary + audit USD."""
    payload = {
        "primary_pass_meta": {"cost_usd": 0.0423},
        "audit_pass_meta":   {"cost_usd": 0.0120},
    }
    cli_mod._update_cost_summary(payload)
    assert payload["costs"]["primary_usd"] == pytest.approx(0.0423)
    assert payload["costs"]["audit_usd"]   == pytest.approx(0.0120)
    assert payload["costs"]["total_usd"]   == pytest.approx(0.0543)


def test_update_cost_summary_handles_missing_metas():
    """A snapshot with no pass metas (gates-only run, or pre-v12.F)
    still gets a `costs` block — all zeros. Idempotent."""
    payload: dict = {}
    cli_mod._update_cost_summary(payload)
    assert payload["costs"]["primary_usd"] == 0.0
    assert payload["costs"]["audit_usd"]   == 0.0
    assert payload["costs"]["total_usd"]   == 0.0


def test_update_cost_summary_idempotent():
    """Calling twice produces the same result (audit pass triggers a
    second update after primary's update)."""
    payload = {
        "primary_pass_meta": {"cost_usd": 0.05},
        "audit_pass_meta":   {"cost_usd": 0.02},
    }
    cli_mod._update_cost_summary(payload)
    first = dict(payload["costs"])
    cli_mod._update_cost_summary(payload)
    assert payload["costs"] == first


def test_update_cost_summary_treats_none_as_zero():
    """LLM CLIs sometimes report cost_usd=None when the runtime
    couldn't compute it. None → 0.0 rather than crashing."""
    payload = {
        "primary_pass_meta": {"cost_usd": None},
        "audit_pass_meta":   {"cost_usd": 0.01},
    }
    cli_mod._update_cost_summary(payload)
    assert payload["costs"]["primary_usd"] == 0.0
    assert payload["costs"]["audit_usd"]   == pytest.approx(0.01)


# ---------- (a) cost ledger — render footer ----------


def _render_payload(*, primary_cost: float = 0.04,
                    audit_cost: float | None = None) -> dict:
    """Minimum payload that satisfies _render_research_v2_full's
    expectations. Only the costs-relevant fields matter here."""
    payload: dict = {
        "topic": "x",
        "cluster_queries": ["x"],
        "per_query_results": [],
        "primary_pass_meta": {"cost_usd": primary_cost},
    }
    if audit_cost is not None:
        payload["audit_pass_meta"] = {"cost_usd": audit_cost}
    cli_mod._update_cost_summary(payload)
    return payload


def test_render_footer_primary_only(monkeypatch):
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    cli_mod._render_research_v2_full(
        _render_payload(primary_cost=0.0423), cap,
    )
    out = cap.file.getvalue()
    assert "LLM cost: $0.0423" in out
    # No breakdown when audit didn't run:
    assert "primary $" not in out


def test_render_footer_with_audit_shows_breakdown(monkeypatch):
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    cli_mod._render_research_v2_full(
        _render_payload(primary_cost=0.04, audit_cost=0.012),
        cap,
    )
    out = cap.file.getvalue()
    assert "LLM cost: $0.0520" in out
    assert "primary $0.0400" in out
    assert "audit $0.0120" in out


def test_render_footer_omitted_when_no_costs(monkeypatch):
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    # Old snapshot without a costs block — render must not crash and
    # must not print a cost footer.
    cli_mod._render_research_v2_full(
        {"topic": "x", "cluster_queries": [], "per_query_results": []},
        cap,
    )
    out = cap.file.getvalue()
    assert "LLM cost" not in out


def test_render_footer_omitted_when_total_zero(monkeypatch):
    """Zero-cost snapshot (gates-only run, no LLM pass) doesn't show
    a footer with `$0.0000` — that's noise, not signal."""
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    payload = {"topic": "x", "cluster_queries": [], "per_query_results": []}
    cli_mod._update_cost_summary(payload)
    cli_mod._render_research_v2_full(payload, cap)
    out = cap.file.getvalue()
    assert "LLM cost" not in out


# ---------- (b) verify_by_default — operator profile loader ----------


def _write_lamill_toml(tmp_path: Path, body: str) -> Path:
    """Write a `lamill.toml` to a tmp dir; returns the path."""
    p = tmp_path / "lamill.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_verify_by_default_loads_true_when_set(tmp_path):
    path = _write_lamill_toml(tmp_path, """
        [operator]
        verify_by_default = true
    """)
    profile = load_operator_profile(path=path)
    assert profile.verify_by_default is True


def test_verify_by_default_loads_false_when_set(tmp_path):
    path = _write_lamill_toml(tmp_path, """
        [operator]
        verify_by_default = false
    """)
    profile = load_operator_profile(path=path)
    assert profile.verify_by_default is False


def test_verify_by_default_defaults_false_when_absent(tmp_path):
    """Profile without the field gets the default."""
    path = _write_lamill_toml(tmp_path, """
        [operator]
        workflow_preference = "builder"
    """)
    profile = load_operator_profile(path=path)
    assert profile.verify_by_default == DEFAULT_VERIFY_BY_DEFAULT
    assert profile.verify_by_default is False


def test_verify_by_default_tolerates_string_form(tmp_path):
    """Hand-edited TOML sometimes has strings instead of booleans —
    the loader tolerates `"true"`/`"false"` rather than crashing."""
    path = _write_lamill_toml(tmp_path, '''
        [operator]
        verify_by_default = "true"
    ''')
    profile = load_operator_profile(path=path)
    assert profile.verify_by_default is True


def test_verify_by_default_tolerates_garbage(tmp_path):
    """Unknown values fall back to default, matching the loader's
    general 'never raise on bad input' posture."""
    path = _write_lamill_toml(tmp_path, '''
        [operator]
        verify_by_default = "maybe"
    ''')
    profile = load_operator_profile(path=path)
    assert profile.verify_by_default == DEFAULT_VERIFY_BY_DEFAULT


def test_verify_by_default_missing_lamill_toml_returns_default(tmp_path):
    """No file → default profile with verify_by_default=False."""
    profile = load_operator_profile(path=tmp_path / "missing.toml")
    assert profile.verify_by_default is False


def test_configured_property_triggers_on_verify_by_default():
    """A profile with ONLY verify_by_default=True (everything else
    default) is still 'configured' — the `show` surface should
    distinguish this from the all-defaults case."""
    p = OperatorProfile(verify_by_default=True)
    assert p.configured is True

    p_default = OperatorProfile()
    assert p_default.configured is False


# ---------- (b) effective-verify resolution logic ----------


def _effective_verify(*, verify: bool, no_verify: bool,
                      profile_default: bool) -> bool:
    """Re-implementation of the resolution logic in `new_research`.
    Tests the boolean truth table independent of CLI parsing."""
    return (verify or profile_default) and not no_verify


def test_effective_verify_flag_only():
    """--verify alone activates audit; no profile influence needed."""
    assert _effective_verify(verify=True,  no_verify=False, profile_default=False) is True
    assert _effective_verify(verify=False, no_verify=False, profile_default=False) is False


def test_effective_verify_profile_default_only():
    """`verify_by_default = true` activates audit even without --verify."""
    assert _effective_verify(verify=False, no_verify=False, profile_default=True) is True


def test_effective_verify_no_verify_overrides_profile():
    """--no-verify is the kill switch when profile says verify=on."""
    assert _effective_verify(verify=False, no_verify=True,  profile_default=True)  is False
    # Also kills --verify (operator might want to opt out for this run):
    assert _effective_verify(verify=True,  no_verify=True,  profile_default=False) is False


def test_effective_verify_all_off():
    assert _effective_verify(verify=False, no_verify=False, profile_default=False) is False


def test_effective_verify_both_sources_on():
    """--verify + profile default + no-verify=False → audit runs."""
    assert _effective_verify(verify=True, no_verify=False, profile_default=True) is True


# ---------- (c) --invalidate parsing ----------


def _resolve_invalidate(raw: str) -> tuple[bool, bool]:
    """Re-implementation of the --invalidate parsing in `new_research`.
    Returns (invalidate_interpretive, invalidate_audit)."""
    s = (raw or "none").strip().lower()
    return (s in ("interpretive", "all"), s in ("audit", "all"))


def test_invalidate_none_keeps_both_cached():
    assert _resolve_invalidate("none") == (False, False)


def test_invalidate_default_keeps_both_cached():
    """Empty string + None both behave as 'none' (the default)."""
    assert _resolve_invalidate("") == (False, False)
    # Mirror the loader's defensive None handling:
    assert _resolve_invalidate(None) == (False, False)


def test_invalidate_interpretive_only():
    assert _resolve_invalidate("interpretive") == (True, False)


def test_invalidate_audit_only():
    assert _resolve_invalidate("audit") == (False, True)


def test_invalidate_all_invalidates_both():
    assert _resolve_invalidate("all") == (True, True)


def test_invalidate_case_insensitive():
    """Operator can pass `--invalidate AUDIT` or `--invalidate All`."""
    assert _resolve_invalidate("AUDIT") == (False, True)
    assert _resolve_invalidate("All") == (True, True)
    assert _resolve_invalidate("  audit  ") == (False, True)


def test_invalidate_unknown_falls_through_to_none():
    """Unknown value → don't invalidate (safer default than failing
    closed)."""
    assert _resolve_invalidate("primary") == (False, False)
    assert _resolve_invalidate("xyz") == (False, False)


# ---------- (c) cache short-circuit applies invalidate ----------


def test_cache_predicate_with_invalidate_interpretive():
    """`cache_has_primary` becomes False even on a full cache hit
    when --invalidate=interpretive is set."""
    payload = {
        "from_cache": True,
        "primary_verdict": {"verdict": "GO", "confidence": "HIGH"},
    }
    invalidate_interpretive = True
    cache_has_primary = (
        payload.get("from_cache") and payload.get("primary_verdict")
        and not invalidate_interpretive
    )
    assert bool(cache_has_primary) is False


def test_cache_predicate_with_invalidate_audit():
    """`cache_has_audit` becomes False when --invalidate=audit."""
    payload = {
        "from_cache": True,
        "audit": {"agreement_level": "full"},
    }
    invalidate_audit = True
    cache_has_audit = (
        payload.get("from_cache") and payload.get("audit")
        and not invalidate_audit
    )
    assert bool(cache_has_audit) is False
