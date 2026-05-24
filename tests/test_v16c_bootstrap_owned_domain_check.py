"""Tests for the owned-domains pre-flight check on `new bootstrap`.

Logged 2026-05-20 — operator typo'd `lamill new bootstrap ageskd.dev`
(meant `agesdk.dev`); bootstrap silently scaffolded the wrong dir
+ polluted `data/portfolio.json`. Fix: cross-check the requested
domain against `data/portfolio.json` (canonical) with a CSV fallback
when portfolio.json is absent. Unknown / typo'd domains exit 2 with
a "Did you mean: …?" hint unless `--force` is passed.

Two layers tested:

  1. `bootstrap.validate_owned_domain(...)` — pure inventory check
     (found / close_matches / source preference). Direct unit
     tests covering the portfolio.json → CSV fallback path.
  2. `new bootstrap` CLI surface — exit code + console message
     when the domain isn't known, plus `--force` bypass. Uses
     `CliRunner` from `typer.testing`, mirroring
     `test_settings_operator_cli.py` etc.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio import bootstrap as bs_mod
from portfolio import data as data_mod
from portfolio.bootstrap import validate_owned_domain
from portfolio.cli import app


# ---------- fixtures ----------


def _write_portfolio_json(path: Path, names: list[str]) -> Path:
    """Seed a minimal portfolio.json with the given domain names."""
    rows = [
        {
            "name": n,
            "registrar": "porkbun",
            "tld": "." + n.rsplit(".", 1)[-1],
            "expires": "2027-01-01",
            "auto_renew": "On",
            "status": "Active",
            "category": "Under build",
        }
        for n in names
    ]
    path.write_text(json.dumps({
        "schema_version": 1,
        "generated_at": "2026-05-20T00:00:00+00:00",
        "total": len(rows),
        "domains": rows,
    }) + "\n")
    return path


def _write_porkbun_csv(path: Path, names: list[str]) -> Path:
    """Seed a minimal data/domains/porkbun.csv with the given names."""
    header = (
        "DOMAIN,TLD,STATUSES,CREATE DATE,EXPIRE DATE,AUTO RENEW,"
        "EST. RENEWAL PRICE,NAMESERVERS,URL FORWARDS,PRIVACY,LOCKED\n"
    )
    rows = "".join(
        f"{n},{n.rsplit('.', 1)[-1]},ACTIVE,2026-05-17 06:21:14,"
        f"2027-05-17 06:21:14,ON,,,,Yes,Yes\n"
        for n in names
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + rows)
    return path


def _patch_inventory_paths(monkeypatch, tmp_path: Path,
                           *, names_json: list[str] | None,
                           names_csv: list[str] | None = None) -> None:
    """Point `bootstrap.PORTFOLIO_JSON` + `bootstrap.DOMAINS_DIR` at
    `tmp_path`. When `names_json` is None, portfolio.json is absent
    (cold-start). When `names_csv` is provided, a porkbun.csv is
    written under tmp_path/domains/."""
    pj = tmp_path / "portfolio.json"
    if names_json is not None:
        _write_portfolio_json(pj, names_json)
    domains_dir = tmp_path / "domains"
    if names_csv is not None:
        _write_porkbun_csv(domains_dir / "porkbun.csv", names_csv)
    else:
        domains_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(bs_mod, "PORTFOLIO_JSON", pj)
    monkeypatch.setattr(bs_mod, "DOMAINS_DIR", domains_dir)
    # Also patch the data-module path so `_resolve_inventory_inputs`
    # (called later in the CLI flow) sees the same picture.
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", pj)


# ---------- validate_owned_domain (unit) ----------


def test_validate_owned_domain_found_in_portfolio_json(tmp_path):
    pj = tmp_path / "portfolio.json"
    _write_portfolio_json(pj, ["agesdk.dev", "homeloom.app"])
    result = validate_owned_domain(
        "agesdk.dev", portfolio_json=pj, domains_dir=tmp_path / "domains",
    )
    assert result.found is True
    assert result.source == "portfolio.json"
    assert result.close_matches == []


def test_validate_owned_domain_close_match_typo(tmp_path):
    """The bug repro: `ageskd.dev` typo → close_matches surfaces
    the correct `agesdk.dev`."""
    pj = tmp_path / "portfolio.json"
    _write_portfolio_json(pj, ["agesdk.dev", "homeloom.app"])
    result = validate_owned_domain(
        "ageskd.dev", portfolio_json=pj, domains_dir=tmp_path / "domains",
    )
    assert result.found is False
    assert "agesdk.dev" in result.close_matches
    assert result.source == "portfolio.json"


def test_validate_owned_domain_no_close_match(tmp_path):
    pj = tmp_path / "portfolio.json"
    _write_portfolio_json(pj, ["agesdk.dev", "homeloom.app"])
    result = validate_owned_domain(
        "totallyrandom.example", portfolio_json=pj,
        domains_dir=tmp_path / "domains",
    )
    assert result.found is False
    assert result.close_matches == []


def test_validate_owned_domain_falls_back_to_csv(tmp_path):
    """portfolio.json absent → scan `data/domains/<reg>.csv`."""
    domains_dir = tmp_path / "domains"
    _write_porkbun_csv(domains_dir / "porkbun.csv",
                       ["agesdk.dev", "homeloom.app"])
    result = validate_owned_domain(
        "agesdk.dev",
        portfolio_json=tmp_path / "no-such-file.json",
        domains_dir=domains_dir,
    )
    assert result.found is True
    assert result.source == "csv"


def test_validate_owned_domain_csv_fallback_typo_match(tmp_path):
    """portfolio.json absent + CSV present → close_matches still
    works against the CSV-sourced names."""
    domains_dir = tmp_path / "domains"
    _write_porkbun_csv(domains_dir / "porkbun.csv",
                       ["agesdk.dev", "homeloom.app"])
    result = validate_owned_domain(
        "ageskd.dev",
        portfolio_json=tmp_path / "no-such-file.json",
        domains_dir=domains_dir,
    )
    assert result.found is False
    assert "agesdk.dev" in result.close_matches
    assert result.source == "csv"


def test_validate_owned_domain_no_inventory_at_all(tmp_path):
    """Neither portfolio.json nor any CSVs → `source=none`,
    inventory_size=0, no close matches possible."""
    result = validate_owned_domain(
        "anything.dev",
        portfolio_json=tmp_path / "missing.json",
        domains_dir=tmp_path / "missing-dir",
    )
    assert result.found is False
    assert result.source == "none"
    assert result.inventory_size == 0
    assert result.close_matches == []


# ---------- CLI integration ----------


def test_cli_bootstrap_unknown_typo_exits_with_suggestion(
    monkeypatch, tmp_path,
):
    """The original bug: `new bootstrap ageskd.dev` → exit 2 with a
    "Did you mean: agesdk.dev?" hint, no files written."""
    _patch_inventory_paths(monkeypatch, tmp_path,
                           names_json=["agesdk.dev", "homeloom.app"])
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(bs_mod, "SITES_ROOT", sites_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["new", "bootstrap", "ageskd.dev", "--non-interactive"],
    )
    assert result.exit_code == 2
    flat = " ".join(result.stdout.split())
    assert "not in your owned-domains inventory" in flat
    assert "agesdk.dev" in flat   # suggestion surfaced
    # No project dir written for the typo.
    assert not (sites_root / "ageskd.dev").exists()


def test_cli_bootstrap_unknown_no_close_match_exits(
    monkeypatch, tmp_path,
):
    """Unknown domain with no nearby match → still exits 2; warning
    asks operator to verify spelling rather than suggesting an
    alternative."""
    _patch_inventory_paths(monkeypatch, tmp_path,
                           names_json=["agesdk.dev", "homeloom.app"])
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(bs_mod, "SITES_ROOT", sites_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["new", "bootstrap", "totallyrandom.example", "--non-interactive"],
    )
    assert result.exit_code == 2
    assert "not in your owned-domains inventory" in result.stdout
    # Rich console may wrap the hint across lines — collapse
    # all whitespace before substring match. Bootstrap should lead
    # with the `fleet sync --refresh` recovery (most common case for
    # fresh purchases) and surface --force as the secondary escape.
    flat = " ".join(result.stdout.split())
    assert "fleet sync --refresh" in flat
    assert "--force" in flat
    assert not (sites_root / "totallyrandom.example").exists()


def test_cli_bootstrap_known_domain_proceeds(monkeypatch, tmp_path):
    """Happy path: a domain present in portfolio.json passes the
    pre-flight check and the bootstrap scaffold runs to completion."""
    _patch_inventory_paths(monkeypatch, tmp_path,
                           names_json=["agesdk.dev", "homeloom.app"])
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(bs_mod, "SITES_ROOT", sites_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["new", "bootstrap", "agesdk.dev", "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    # Bootstrap scaffolded the project dir.
    assert (sites_root / "agesdk.dev").is_dir()
    assert (sites_root / "agesdk.dev" / "package.json").exists()


def test_cli_bootstrap_force_bypasses_check(monkeypatch, tmp_path):
    """`--force` skips the inventory check entirely — the scaffold
    proceeds for a domain nowhere in the operator's inventory."""
    _patch_inventory_paths(monkeypatch, tmp_path,
                           names_json=["agesdk.dev"])
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(bs_mod, "SITES_ROOT", sites_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["new", "bootstrap", "brandnew.dev", "--force",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    assert (sites_root / "brandnew.dev").is_dir()


def test_cli_bootstrap_csv_fallback_when_portfolio_json_absent(
    monkeypatch, tmp_path,
):
    """portfolio.json absent + CSV inventory present → the CLI
    pre-flight reads the CSV and accepts a known domain. Covers the
    cold-start case before `fleet sync` has produced portfolio.json."""
    _patch_inventory_paths(
        monkeypatch, tmp_path,
        names_json=None,                         # no portfolio.json
        names_csv=["agesdk.dev", "homeloom.app"],
    )
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(bs_mod, "SITES_ROOT", sites_root)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["new", "bootstrap", "agesdk.dev", "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    assert (sites_root / "agesdk.dev").is_dir()
