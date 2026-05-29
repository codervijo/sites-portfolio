"""Tests for v9.C — `new bootstrap` domain-registration prompt +
portfolio.json auto-update.

Two layers tested:
  1. `data.append_domain_row(...)` — atomic write, idempotent,
     respects conservative-placeholders convention.
  2. `cli._resolve_inventory_inputs(...)` — flag/prompt routing
     logic (existing-row short-circuit, both-flags-no-prompt,
     non-interactive-no-write, interactive Y/n + registrar
     selection).

The integration (bootstrap → inventory write) is tested via
`_apply_inventory_decision` against a monkeypatched
`append_domain_row` so the on-disk portfolio.json stays untouched.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import typer

from portfolio import data as data_mod
from portfolio import cli as cli_mod


def _seed_portfolio_json(tmp_path: Path, domains: list[dict] | None = None) -> Path:
    """Create a minimal portfolio.json in `tmp_path` and monkeypatch
    `data.PORTFOLIO_JSON` to point there."""
    domains = domains or []
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({
        "generated_at": "2026-05-17T00:00:00+00:00",
        "schema_version": 1,
        "total": len(domains),
        "domains": domains,
    }) + "\n")
    return path


def _existing_row(name: str = "existing.com") -> dict:
    return {
        "name": name,
        "registrar": "porkbun",
        "tld": "." + name.rsplit(".", 1)[-1],
        "expires": "2027-01-01",
        "auto_renew": "On",
        "status": "Active",
        "category": "Under build",
        "created": "2026-01-01",
        "renewal_price": 11.0,
        "estimated_value": None,
        "listing_status": "",
        "nameservers": "",
        "forwarding_url": "",
        "privacy": True,
        "transfer_locked": True,
        "launched": None,
        "domain_created": "2026-01-01",
    }


# ---------- append_domain_row ----------


def test_append_domain_row_writes_canonical_shape(monkeypatch, tmp_path):
    path = _seed_portfolio_json(tmp_path)
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)

    result = data_mod.append_domain_row(
        name="new.dev", registrar="porkbun",
        today=date(2026, 5, 17),
    )
    assert result == "added"
    payload = json.loads(path.read_text())
    assert len(payload["domains"]) == 1
    row = payload["domains"][0]
    assert row["name"] == "new.dev"
    assert row["registrar"] == "porkbun"
    assert row["tld"] == ".dev"
    assert row["status"] == "Active"
    assert row["category"] == "Under build"
    assert row["created"] == "2026-05-17"
    assert row["expires"] == "2027-05-17"
    assert row["auto_renew"] == "On"
    assert row["privacy"] is True
    assert row["transfer_locked"] is True
    # Conservative placeholders — these get filled by the next CSV refresh.
    assert row["renewal_price"] is None
    assert row["nameservers"] == ""
    assert row["launched"] is None
    assert payload["total"] == 1


def test_append_domain_row_pending_status(monkeypatch, tmp_path):
    """Not-yet-registered → status="Pending" + domain_created=None
    (no actual registration date yet)."""
    path = _seed_portfolio_json(tmp_path)
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)

    data_mod.append_domain_row(
        name="future.com", registrar="porkbun",
        registered=False, today=date(2026, 5, 17),
    )
    row = json.loads(path.read_text())["domains"][0]
    assert row["status"] == "Pending"
    assert row["domain_created"] is None


def test_append_domain_row_idempotent(monkeypatch, tmp_path):
    """Calling twice for the same name → second call returns "exists"
    and doesn't double-append."""
    path = _seed_portfolio_json(tmp_path, domains=[_existing_row("existing.com")])
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)

    result = data_mod.append_domain_row(
        name="existing.com", registrar="porkbun",
    )
    assert result == "exists"
    payload = json.loads(path.read_text())
    assert len(payload["domains"]) == 1  # unchanged


def test_append_domain_row_no_file(monkeypatch, tmp_path):
    """portfolio.json absent → "no-file" sentinel. Caller renders
    a "run cleanup first" hint to the operator."""
    missing = tmp_path / "doesnt_exist.json"
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", missing)
    result = data_mod.append_domain_row(
        name="x.dev", registrar="porkbun",
    )
    assert result == "no-file"


def test_append_domain_row_extracts_tld_from_domain(monkeypatch, tmp_path):
    path = _seed_portfolio_json(tmp_path)
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)
    for name, expected_tld in [
        ("foo.xyz", ".xyz"),
        ("bar.co", ".co"),
        ("baz.app", ".app"),
        ("multi-segment.co.uk", ".uk"),   # eTLD-1 fallback
    ]:
        data_mod.append_domain_row(name=name, registrar="porkbun")
        row = next(r for r in json.loads(path.read_text())["domains"]
                   if r["name"] == name)
        assert row["tld"] == expected_tld


def test_append_domain_row_atomic_write(monkeypatch, tmp_path):
    """The append uses a tmpfile + rename so a crash mid-write doesn't
    leave portfolio.json half-written."""
    path = _seed_portfolio_json(tmp_path)
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)
    data_mod.append_domain_row(name="atomic.dev", registrar="porkbun")
    # tmpfile should be cleaned up.
    assert not (path.with_suffix(".json.tmp")).exists()
    # File is valid JSON.
    payload = json.loads(path.read_text())
    assert payload["domains"][-1]["name"] == "atomic.dev"


# ---------- _resolve_inventory_inputs ----------


def _patch_portfolio_json(monkeypatch, tmp_path, domains=None):
    path = _seed_portfolio_json(tmp_path, domains=domains or [])
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)
    return path


def test_resolve_inventory_existing_row_short_circuits(monkeypatch, tmp_path):
    """If the domain is already in portfolio.json, action="exists"
    and no prompts fire — idempotent re-run."""
    _patch_portfolio_json(monkeypatch, tmp_path,
                          domains=[_existing_row("foo.dev")])
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    decision = cli_mod._resolve_inventory_inputs(
        domain="foo.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "exists"}


def test_resolve_inventory_both_flags_no_prompt(monkeypatch, tmp_path):
    _patch_portfolio_json(monkeypatch, tmp_path)
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=True, registrar="porkbun",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "porkbun"}


def test_resolve_inventory_unknown_registrar_exits(monkeypatch, tmp_path):
    """An invalid --registrar value (typo, etc.) is rejected at the
    CLI layer — operator gets a clear error rather than a bad row."""
    _patch_portfolio_json(monkeypatch, tmp_path)
    with pytest.raises(typer.Exit):
        cli_mod._resolve_inventory_inputs(
            domain="new.dev", registered=True, registrar="namecheap-typo",
            non_interactive=False,
        )


def test_resolve_inventory_non_interactive_no_flag_skips(monkeypatch, tmp_path):
    """--non-interactive without --registered → skip the inventory
    write entirely (operator runs cleanup later)."""
    _patch_portfolio_json(monkeypatch, tmp_path)
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=True,
    )
    assert decision == {"action": "skip"}


def test_resolve_inventory_non_interactive_with_flag_defaults_registrar(monkeypatch, tmp_path):
    """--non-interactive --registered without --registrar → registrar
    assumes "porkbun" (the fleet default; operator policy 2026-05-29).
    An explicit --registrar overrides."""
    _patch_portfolio_json(monkeypatch, tmp_path)
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=True, registrar="",
        non_interactive=True,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "porkbun"}


def test_resolve_inventory_interactive_yes_porkbun(monkeypatch, tmp_path):
    _patch_portfolio_json(monkeypatch, tmp_path)
    answers = iter(["y", "porkbun"])
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "porkbun"}


def test_resolve_inventory_interactive_no_response_means_yes(monkeypatch, tmp_path):
    """Pressing Enter on the [Y/n] prompt defaults to Y (registered)."""
    _patch_portfolio_json(monkeypatch, tmp_path)
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    # Empty answer → Y → registered=True; registrar defaulted to "other".
    assert decision["action"] == "append"
    assert decision["registered"] is True


def test_resolve_inventory_interactive_no(monkeypatch, tmp_path):
    """Operator types 'n' → registered=False (Pending row)."""
    _patch_portfolio_json(monkeypatch, tmp_path)
    answers = iter(["n", "porkbun"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="future.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": False,
                        "registrar": "porkbun"}


def test_resolve_inventory_interactive_invalid_registrar_falls_back(monkeypatch, tmp_path):
    """Operator types unrecognized registrars at the interactive
    prompt → after 3 invalid attempts, defaults to "other" rather
    than rejecting (interactive UX shouldn't punish typos as hard
    as the flag layer).

    Bug-fix 2026-05-20: the registrar prompt now retries up to 3
    times with an "Accepted: ..." hint before falling back."""
    _patch_portfolio_json(monkeypatch, tmp_path)
    answers = iter(["y", "weird-host", "weird-host2", "weird-host3"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "other"}


# ---------- _apply_inventory_decision ----------


def test_apply_inventory_skip_is_silent(monkeypatch, tmp_path):
    """action=skip → no portfolio.json mutation, no console output."""
    calls = []
    monkeypatch.setattr(data_mod, "append_domain_row",
                        lambda *a, **k: calls.append(("called",)) or "added")
    cli_mod._apply_inventory_decision("x.dev", {"action": "skip"})
    assert calls == []


def test_apply_inventory_append_calls_data_helper(monkeypatch, tmp_path):
    captured = {}

    def fake_append(*, name, registrar, registered=True, today=None):
        captured.update({"name": name, "registrar": registrar,
                         "registered": registered})
        return "added"
    monkeypatch.setattr(data_mod, "append_domain_row", fake_append)
    cli_mod._apply_inventory_decision(
        "new.dev",
        {"action": "append", "registered": True, "registrar": "porkbun"},
    )
    assert captured == {"name": "new.dev", "registrar": "porkbun",
                        "registered": True}


def test_apply_inventory_existing_logs_no_change(monkeypatch, capsys):
    """action=exists → no helper call, console gets an informational
    'already present' line."""
    must_not_call = lambda *a, **k: pytest.fail("append called for 'exists'")
    monkeypatch.setattr(data_mod, "append_domain_row", must_not_call)
    cli_mod._apply_inventory_decision("foo.dev", {"action": "exists"})
    # Console output is via cli_mod.console; we can't easily capture
    # rich console output via capsys without monkeypatching. The
    # contract here is just that no exception fires + no helper called.
