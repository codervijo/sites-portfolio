"""Tests for CHECK_042 — live-final-url-matches-domain."""
from __future__ import annotations

import json
from pathlib import Path

from portfolio.checks.git.check_042_live_final_url_matches_domain import run


def _stub_checks_snapshot(tmp_path: Path, results: list[dict]) -> Path:
    """Write a minimal data/checks/<date>.json snapshot. Returns its path."""
    checks_dir = tmp_path / "data" / "checks"
    checks_dir.mkdir(parents=True)
    out = checks_dir / "2026-05-13.json"
    out.write_text(json.dumps({
        "fetched_at": "2026-05-13T00:00:00+00:00",
        "scope": "wip",
        "results": results,
    }))
    return out


def _patch_check_module(monkeypatch, tmp_path: Path, results: list[dict]):
    """Redirect the check module's data lookups at a synthetic snapshot."""
    from portfolio import check as check_mod
    snap = _stub_checks_snapshot(tmp_path, results)
    monkeypatch.setattr(check_mod, "latest_snapshot", lambda: snap)
    return snap


def test_passes_when_final_url_matches_bare_domain(tmp_path: Path, monkeypatch):
    _patch_check_module(monkeypatch, tmp_path, [
        {"domain": "airsucks.com", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://airsucks.com"},
    ])
    site = tmp_path / "airsucks.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "pass"
    assert "airsucks.com" in result.message


def test_passes_when_final_url_is_www_variant(tmp_path: Path, monkeypatch):
    """Many sites canonicalize www. → bare or bare → www. Both are valid."""
    _patch_check_module(monkeypatch, tmp_path, [
        {"domain": "lamill.io", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://www.lamill.io/"},
    ])
    site = tmp_path / "lamill.io"
    site.mkdir()
    result = run(str(site))
    assert result.status == "pass"
    assert "www.lamill.io" in result.message


def test_fails_when_final_url_is_a_different_domain(tmp_path: Path, monkeypatch):
    """The forwarder case — airsucks.com → www.thakinaam.com."""
    _patch_check_module(monkeypatch, tmp_path, [
        {"domain": "airsucks.com", "variant": "bare",
         "classification": "forwarder", "status": 200,
         "final_url": "http://www.thakinaam.com"},
    ])
    site = tmp_path / "airsucks.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "fail"
    assert "thakinaam.com" in result.message
    assert "airsucks.com" in result.message


def test_warn_when_no_row_for_domain(tmp_path: Path, monkeypatch):
    """Domain not in the snapshot → can't conclude, skip."""
    _patch_check_module(monkeypatch, tmp_path, [
        {"domain": "other.com", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://other.com"},
    ])
    site = tmp_path / "untested.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "warn"
    assert "no row" in result.message


def test_warn_when_no_final_url(tmp_path: Path, monkeypatch):
    """Domain probed but never reached a final URL (dead / error)."""
    _patch_check_module(monkeypatch, tmp_path, [
        {"domain": "broken.com", "variant": "bare",
         "classification": "dead", "status": None,
         "final_url": None,
         "error": "ConnectTimeout"},
    ])
    site = tmp_path / "broken.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "warn"
    assert "classification=dead" in result.message


def test_warn_when_no_snapshot(tmp_path: Path, monkeypatch):
    """No data/checks/*.json at all → skip rather than fail."""
    from portfolio import check as check_mod
    monkeypatch.setattr(check_mod, "latest_snapshot", lambda: None)
    site = tmp_path / "anywhere.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "warn"
    assert "no live snapshot" in result.message


def test_picks_bare_variant_when_both_present(tmp_path: Path, monkeypatch):
    """When both bare and www rows exist (common after fleet live), the
    classification-priority logic in best_per_domain decides which
    variant's final URL drives the check. live-site wins over dead /
    error / etc., so a working www variant rescues a bad bare row."""
    _patch_check_module(monkeypatch, tmp_path, [
        {"domain": "x.com", "variant": "bare",
         "classification": "dead", "status": None, "final_url": None,
         "error": "ConnectTimeout"},
        {"domain": "x.com", "variant": "www",
         "classification": "live-site", "status": 200,
         "final_url": "https://www.x.com/"},
    ])
    site = tmp_path / "x.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "pass"
    assert "www.x.com" in result.message
