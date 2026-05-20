"""Tests for CHECK_146 — last-build-success (v15.E)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from portfolio.checks.deploy.check_146_last_build_success import run


def _stub_hosting_dir(monkeypatch, tmp_path: Path) -> Path:
    """Patch `hosting_cache.HOSTING_DIR` to a per-test temp dir."""
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(
        "portfolio.hosting_cache.HOSTING_DIR", hosting_dir,
    )
    return hosting_dir


def _write_snapshot(hosting_dir: Path, rows: list[dict]) -> Path:
    hosting_dir.mkdir(parents=True, exist_ok=True)
    snap_path = hosting_dir / "today.json"
    snap_path.write_text(json.dumps({
        "fetched_at": "2026-05-20T10:00:00+00:00",
        "rows": rows,
        "skipped": {},
    }))
    return snap_path


def _make_site(tmp_path: Path, name: str) -> Path:
    site = tmp_path / name
    site.mkdir()
    return site


# ---- skip / data-availability paths -------------------------------


def test_warn_when_no_snapshot(tmp_path: Path, monkeypatch):
    _stub_hosting_dir(monkeypatch, tmp_path)
    site = _make_site(tmp_path, "example.com")
    result = run(str(site))
    assert result.status == "warn"
    assert "no `fleet hosting` snapshot" in result.message


def test_warn_when_domain_not_in_snapshot(tmp_path: Path, monkeypatch):
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{"domain": "other.com", "provider": "vercel"}])
    site = _make_site(tmp_path, "missing.com")
    result = run(str(site))
    assert result.status == "warn"
    assert "missing.com not in latest hosting snapshot" in result.message


def test_warn_when_provider_has_no_build_pipeline(tmp_path: Path, monkeypatch):
    """CF Workers + HostGator don't have a build-pipeline signal."""
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "airsucks.com",
        "provider": "cloudflare-workers",
    }])
    site = _make_site(tmp_path, "airsucks.com")
    result = run(str(site))
    assert result.status == "warn"
    assert "cloudflare-workers" in result.message
    assert "no build-pipeline signal" in result.message


def test_warn_when_hg_provider(tmp_path: Path, monkeypatch):
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "hybridautopart.com",
        "provider": "hostgator",
    }])
    site = _make_site(tmp_path, "hybridautopart.com")
    result = run(str(site))
    assert result.status == "warn"
    assert "hostgator" in result.message


# ---- pass paths ---------------------------------------------------


def test_pass_when_latest_deploy_ready(tmp_path: Path, monkeypatch):
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "ok.com",
        "provider": "vercel",
        "latest_deploy_status": "READY",
        "latest_deploy_at": "2026-05-20T09:00:00+00:00",
    }])
    site = _make_site(tmp_path, "ok.com")
    result = run(str(site))
    assert result.status == "pass"
    assert "READY" in result.message
    assert "2026-05-20" in result.message


def test_pass_lowercase_domain_lookup(tmp_path: Path, monkeypatch):
    """Domain lookup is case-insensitive."""
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "MiXeD.cOM",
        "provider": "cloudflare-pages",
        "latest_deploy_status": "SUCCESS",
    }])
    site = _make_site(tmp_path, "mixed.com")
    result = run(str(site))
    assert result.status == "pass"


# ---- fail paths ---------------------------------------------------


def test_fail_when_latest_deploy_error(tmp_path: Path, monkeypatch):
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "broken.com",
        "provider": "vercel",
        "latest_deploy_status": "ERROR",
        "consecutive_failures": 3,
    }])
    site = _make_site(tmp_path, "broken.com")
    result = run(str(site))
    assert result.status == "fail"
    assert "ERROR" in result.message
    assert "3 consecutive failures" in result.message


def test_fail_canceled_single_failure_omits_count(tmp_path: Path, monkeypatch):
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "broken.com",
        "provider": "cloudflare-pages",
        "latest_deploy_status": "CANCELED",
        "consecutive_failures": 1,
    }])
    site = _make_site(tmp_path, "broken.com")
    result = run(str(site))
    assert result.status == "fail"
    assert "CANCELED" in result.message
    # Single failure → don't decorate with "1 consecutive failures".
    assert "consecutive" not in result.message


# ---- in-flight ----------------------------------------------------


def test_warn_when_build_in_flight(tmp_path: Path, monkeypatch):
    hosting_dir = _stub_hosting_dir(monkeypatch, tmp_path)
    _write_snapshot(hosting_dir, [{
        "domain": "x.com",
        "provider": "vercel",
        "latest_deploy_status": "BUILDING",
    }])
    site = _make_site(tmp_path, "x.com")
    result = run(str(site))
    assert result.status == "warn"
    assert "BUILDING" in result.message
