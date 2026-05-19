"""Tests for v11.K — `fleet dashboard` + `project diagnose` integrations.

Two integration surfaces:
  - `dashboard.py`: Hosting column reads `data/hosting/<date>.json`
    via `_load_hosting_index`; populates `DashRow.host_dot` +
    `host_provider`; flows into rollup.
  - `diagnose.py`: new `HostingLayer` reads the same snapshot;
    `probe_hosting()` returns one entry per matching walker row.

Tests inject a tmp snapshot dir so the real `data/hosting/` stays
untouched.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from portfolio import dashboard, diagnose, hosting_cache
from portfolio.dashboard import _host_dot, _provider_short
from portfolio.hosting import (
    HostingResult,
    HostingRow,
    MAX_DEPLOY_LOOKBACK,
    PROVIDER_CF_PAGES,
    PROVIDER_CF_WORKERS,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
)


# ---- _host_dot priority cascade ---------------------------------


def _iso(ts: datetime) -> str:
    return ts.isoformat()


def _row(**kw) -> HostingRow:
    """Compact builder; default provider=vercel + recent success."""
    kw.setdefault("provider", PROVIDER_VERCEL)
    kw.setdefault("last_successful_deploy_at",
                  _iso(datetime.now(timezone.utc)))
    return HostingRow(domain=kw.pop("domain", "x.com"), **kw)


def test_host_dot_grey_when_no_rows():
    dot, provider, conflict = _host_dot([])
    assert dot == "—"
    assert provider is None
    assert conflict is False


def test_host_dot_red_for_multi_row_conflict():
    rows = [
        _row(domain="x.com", provider=PROVIDER_VERCEL),
        _row(domain="x.com", provider=PROVIDER_CF_PAGES),
    ]
    dot, provider, conflict = _host_dot(rows)
    assert dot == "🔴"
    assert conflict is True
    # First provider rendered with a `+` suffix to indicate "and more".
    assert provider == "vercel+"


def test_host_dot_red_when_runaway_failures():
    """consecutive_failures ≥ MAX_DEPLOY_LOOKBACK → red regardless of
    last_successful_deploy_at being recent."""
    rows = [_row(domain="x.com", consecutive_failures=MAX_DEPLOY_LOOKBACK)]
    dot, _, _ = _host_dot(rows)
    assert dot == "🔴"


def test_host_dot_green_for_recent_success():
    rows = [_row(domain="x.com",
                 last_successful_deploy_at=_iso(datetime.now(timezone.utc)))]
    dot, provider, conflict = _host_dot(rows)
    assert dot == "🟢"
    assert provider == "vercel"
    assert conflict is False


def test_host_dot_yellow_for_stale_success():
    """30-90 days old → yellow."""
    from datetime import timedelta
    rows = [_row(
        domain="x.com",
        last_successful_deploy_at=_iso(
            datetime.now(timezone.utc) - timedelta(days=45),
        ),
    )]
    dot, _, _ = _host_dot(rows)
    assert dot == "🟡"


def test_host_dot_red_for_dormant_success():
    """≥ 90 days → red (dormant)."""
    from datetime import timedelta
    rows = [_row(
        domain="x.com",
        last_successful_deploy_at=_iso(
            datetime.now(timezone.utc) - timedelta(days=120),
        ),
    )]
    dot, _, _ = _host_dot(rows)
    assert dot == "🔴"


def test_host_dot_green_for_hg_row_with_no_pipeline_data():
    """HG has no build pipeline; missing last_successful_deploy_at is
    normal — render green (presence = good enough)."""
    rows = [HostingRow(
        domain="hybridautopart.com", provider=PROVIDER_HOSTGATOR,
        hg_account_id="gator3164",
        last_successful_deploy_at=None,
    )]
    dot, provider, _ = _host_dot(rows)
    assert dot == "🟢"
    assert provider == "hostgator"


def test_host_dot_yellow_for_vercel_with_no_last_success():
    """Vercel project exists but never had a successful deploy →
    yellow (problem, but visible)."""
    rows = [HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        last_successful_deploy_at=None,
    )]
    dot, _, _ = _host_dot(rows)
    assert dot == "🟡"


def test_host_dot_grey_for_malformed_timestamp():
    """Defensive — corrupt timestamp falls through to grey."""
    rows = [_row(domain="x.com", last_successful_deploy_at="not-a-date")]
    dot, _, _ = _host_dot(rows)
    assert dot == "—"


# ---- _provider_short label compaction ---------------------------


def test_provider_short_maps_known_providers():
    assert _provider_short("vercel") == "VC"
    assert _provider_short("cloudflare-pages") == "CFP"
    assert _provider_short("cloudflare-workers") == "CFW"
    assert _provider_short("hostgator") == "HG"


def test_provider_short_passes_through_suffix():
    """When the host_dot helper appends `+` to indicate multi-row
    conflict, the short label preserves the marker."""
    assert _provider_short("vercel+") == "VC+"
    assert _provider_short("hostgator+") == "HG+"


def test_provider_short_grey_for_none():
    assert _provider_short(None) == "—"


def test_provider_short_unknown_provider_uses_3_letter_uppercase():
    """Defensive — if a future walker emits a string not in the
    PROVIDERS tuple, the renderer still produces something."""
    assert _provider_short("netlify") == "NET"


# ---- _load_hosting_index ----------------------------------------


def _write_snapshot(hosting_dir: Path, rows: list[HostingRow]) -> Path:
    """Build a hosting snapshot file the same way `save_snapshot`
    would, but in a test-controlled directory."""
    from dataclasses import asdict
    hosting_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = hosting_dir / f"{today}.json"
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": [asdict(r) for r in rows],
        "skipped": {},
    }
    path.write_text(json.dumps(payload, indent=2))
    return path


def test_load_hosting_index_returns_none_when_no_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", tmp_path / "no-such-dir")
    path, index = dashboard._load_hosting_index()
    assert path is None
    assert index == {}


def test_load_hosting_index_returns_rows_grouped_by_domain(monkeypatch, tmp_path):
    """Conflict rows (same domain, different walker entries) cluster
    under one key — caller iterates the list."""
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    _write_snapshot(hosting_dir, [
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164"),
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator4216"),
        HostingRow(domain="airsucks.com",
                   provider=PROVIDER_CF_WORKERS),
    ])

    path, index = dashboard._load_hosting_index()
    assert path is not None
    assert set(index.keys()) == {"hybridautopart.com", "airsucks.com"}
    assert len(index["hybridautopart.com"]) == 2
    assert len(index["airsucks.com"]) == 1


# ---- probe_hosting (diagnose) -----------------------------------


def test_probe_hosting_no_snapshot_returns_empty_layer(monkeypatch, tmp_path):
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", tmp_path / "no-such-dir")
    layer = diagnose.probe_hosting("airsucks.com")
    assert layer.snapshot_path is None
    assert layer.rows == []


def test_probe_hosting_finds_matching_rows(monkeypatch, tmp_path):
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    _write_snapshot(hosting_dir, [
        HostingRow(domain="airsucks.com",
                   provider=PROVIDER_CF_WORKERS,
                   project_slug="airsucks",
                   last_successful_deploy_at=_iso(datetime.now(timezone.utc))),
        HostingRow(domain="other.com",
                   provider=PROVIDER_VERCEL),
    ])

    layer = diagnose.probe_hosting("airsucks.com")
    assert layer.snapshot_path is not None
    assert len(layer.rows) == 1
    assert layer.rows[0].provider == "cloudflare-workers"
    assert layer.rows[0].project_slug == "airsucks"


def test_probe_hosting_returns_conflict_rows_for_drift_case(monkeypatch, tmp_path):
    """Cross-walker conflict (e.g. addon on both HG accounts) → both
    rows surface in the layer."""
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    _write_snapshot(hosting_dir, [
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164",
                   provider_conflict=True),
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator4216",
                   provider_conflict=True),
    ])

    layer = diagnose.probe_hosting("hybridautopart.com")
    assert len(layer.rows) == 2
    account_ids = {r.hg_account_id for r in layer.rows}
    assert account_ids == {"gator3164", "gator4216"}


def test_probe_hosting_case_insensitive_domain_match(monkeypatch, tmp_path):
    """Operator calling `diagnose AIRSUCKS.COM` should still match the
    snapshot row stored as `airsucks.com`."""
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    _write_snapshot(hosting_dir, [
        HostingRow(domain="airsucks.com",
                   provider=PROVIDER_CF_WORKERS),
    ])

    layer = diagnose.probe_hosting("AIRSUCKS.COM")
    assert len(layer.rows) == 1
