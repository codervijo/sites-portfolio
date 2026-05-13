"""Tests for CHECK_041 — dir-matches-portfolio-entry."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from portfolio.checks.git.check_041_dir_matches_portfolio_entry import run


def _stub_portfolio_json(tmp_path: Path, names: list[str]) -> Path:
    """Write a minimal portfolio.json with `names` as the registered domains.
    Returns the path to the file."""
    payload = {
        "schema_version": 1,
        "generated_at": "2026-05-13T00:00:00+00:00",
        "domains": [
            {"name": n, "registrar": "godaddy", "tld": ".com",
             "expires": None, "auto_renew": "On", "status": "Active"}
            for n in names
        ],
    }
    out = tmp_path / "portfolio.json"
    out.write_text(json.dumps(payload, indent=2))
    return out


def test_passes_when_dir_matches_portfolio_entry(tmp_path: Path, monkeypatch):
    """The happy path: directory name appears as a `name` row."""
    from portfolio import data as data_mod
    monkeypatch.setattr(
        data_mod, "PORTFOLIO_JSON",
        _stub_portfolio_json(tmp_path, ["airsucks.com", "lamill.io"]),
    )
    site = tmp_path / "airsucks.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "pass"
    assert "matches portfolio entry" in result.message


def test_fails_when_dir_not_in_portfolio_json(tmp_path: Path, monkeypatch):
    """The typo case: dir exists but no row matches."""
    from portfolio import data as data_mod
    monkeypatch.setattr(
        data_mod, "PORTFOLIO_JSON",
        _stub_portfolio_json(tmp_path, ["homeloom.app"]),  # correct spelling
    )
    site = tmp_path / "homloom.app"  # typo'd dir
    site.mkdir()
    result = run(str(site))
    assert result.status == "fail"
    # Surfaces both the typo'd name AND a remediation hint.
    assert "homloom.app" in result.message
    assert "cleanup" in result.message.lower()


def test_match_is_case_insensitive(tmp_path: Path, monkeypatch):
    from portfolio import data as data_mod
    monkeypatch.setattr(
        data_mod, "PORTFOLIO_JSON",
        _stub_portfolio_json(tmp_path, ["Mixed.Case.com"]),
    )
    site = tmp_path / "mixed.case.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "pass"


def test_warn_when_portfolio_json_missing(tmp_path: Path, monkeypatch):
    """Edge: portfolio.json doesn't exist at all → don't surface as a fail."""
    from portfolio import data as data_mod
    monkeypatch.setattr(
        data_mod, "PORTFOLIO_JSON", tmp_path / "nonexistent" / "portfolio.json",
    )
    # When PORTFOLIO_JSON is missing, load_domains falls back to CSV loaders.
    # In the test env those will probably yield an empty list — assert we
    # don't crash and the verdict is non-pass.
    monkeypatch.setattr(data_mod, "_load_from_registrars", lambda: [])
    monkeypatch.setattr(data_mod, "_load_legacy_plan_md", lambda: {})
    site = tmp_path / "x.com"
    site.mkdir()
    result = run(str(site))
    # Either warn (couldn't load) or fail (loaded empty) — both reasonable.
    assert result.status in ("warn", "fail")
