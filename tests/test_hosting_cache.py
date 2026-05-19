"""Tests for v11.F — `src/portfolio/hosting_cache.py`."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from portfolio import hosting_cache
from portfolio.hosting import (
    PROVIDER_CF_PAGES,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
    HostingResult,
    HostingRow,
)


def _patch_hosting_dir(monkeypatch, tmp_path: Path) -> Path:
    """Redirect the cache module at a tmp dir so tests don't touch
    the real `data/hosting/`."""
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    return hosting_dir


# ---- list / latest snapshots ---------------------------------------


def test_list_snapshots_empty_when_dir_missing(monkeypatch, tmp_path):
    _patch_hosting_dir(monkeypatch, tmp_path)
    assert hosting_cache.list_snapshots() == []


def test_list_snapshots_newest_first(monkeypatch, tmp_path):
    hosting_dir = _patch_hosting_dir(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    for name in ("2026-05-15.json", "2026-05-18.json", "2026-05-16.json"):
        (hosting_dir / name).write_text("{}")
    snaps = hosting_cache.list_snapshots()
    assert [p.name for p in snaps] == [
        "2026-05-18.json", "2026-05-16.json", "2026-05-15.json",
    ]


def test_latest_snapshot_returns_first_or_none(monkeypatch, tmp_path):
    hosting_dir = _patch_hosting_dir(monkeypatch, tmp_path)
    assert hosting_cache.latest_snapshot() is None
    hosting_dir.mkdir(parents=True)
    (hosting_dir / "2026-05-18.json").write_text("{}")
    latest = hosting_cache.latest_snapshot()
    assert latest is not None and latest.name == "2026-05-18.json"


# ---- save / load roundtrip ---------------------------------------


def test_save_then_load_roundtrips_rows(monkeypatch, tmp_path):
    _patch_hosting_dir(monkeypatch, tmp_path)
    result = HostingResult(
        rows=[
            HostingRow(domain="airsucks.com", provider=PROVIDER_VERCEL,
                       project_slug="airsucks", project_id="prj_1",
                       latest_deploy_status="READY",
                       last_successful_deploy_at="2026-05-18T16:00:00+00:00"),
            HostingRow(domain="hybridautopart.com", provider=PROVIDER_HOSTGATOR,
                       hg_account_id="gator3164", disk_used_mb=1430,
                       wp_version="6.7.1",
                       install_path="/home1/user/public_html/hybridautopart.com"),
        ],
        skipped={"vercel": "VERCEL_TOKEN not set"},
    )
    path = hosting_cache.save_snapshot(result)
    loaded = hosting_cache.load_snapshot(path)
    assert loaded["rows"][0]["domain"] == "airsucks.com"
    assert loaded["skipped"] == {"vercel": "VERCEL_TOKEN not set"}
    assert "fetched_at" in loaded


def test_save_snapshot_writes_to_utc_today_filename(monkeypatch, tmp_path):
    _patch_hosting_dir(monkeypatch, tmp_path)
    path = hosting_cache.save_snapshot(HostingResult())
    expected_name = datetime.now(timezone.utc).strftime("%Y-%m-%d") + ".json"
    assert path.name == expected_name


def test_save_snapshot_overwrites_same_day(monkeypatch, tmp_path):
    """One snapshot per UTC date — re-saving replaces the prior content."""
    _patch_hosting_dir(monkeypatch, tmp_path)
    p1 = hosting_cache.save_snapshot(HostingResult(
        rows=[HostingRow(domain="a.com", provider=PROVIDER_VERCEL)],
    ))
    p2 = hosting_cache.save_snapshot(HostingResult(
        rows=[HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES)],
    ))
    assert p1 == p2  # same filename
    loaded = hosting_cache.load_snapshot(p2)
    assert loaded["rows"][0]["domain"] == "b.com"


def test_result_from_snapshot_reconstructs_typed_result(monkeypatch, tmp_path):
    """Round-trip through asdict → load → typed HostingResult."""
    _patch_hosting_dir(monkeypatch, tmp_path)
    original = HostingResult(
        rows=[
            HostingRow(domain="x.com", provider=PROVIDER_VERCEL,
                       consecutive_failures=2),
            HostingRow(domain="y.com", provider=PROVIDER_HOSTGATOR,
                       hg_account_id="gator3164", disk_used_mb=500),
        ],
        skipped={"hostgator:gator4216": "auth — 401"},
    )
    path = hosting_cache.save_snapshot(original)
    snap = hosting_cache.load_snapshot(path)
    rebuilt = hosting_cache.result_from_snapshot(snap)

    assert len(rebuilt.rows) == 2
    assert rebuilt.rows[0].domain == "x.com"
    assert rebuilt.rows[0].consecutive_failures == 2
    assert rebuilt.rows[1].hg_account_id == "gator3164"
    assert rebuilt.rows[1].disk_used_mb == 500
    assert rebuilt.skipped == {"hostgator:gator4216": "auth — 401"}


def test_result_from_snapshot_drops_unknown_row_keys():
    """Forward-compat: a future HostingRow field gets ignored if the
    snapshot was written by a newer version of the tool."""
    snap = {
        "rows": [
            {"domain": "x.com", "provider": "vercel",
             "future_field_we_dont_know_about": "value"},
        ],
        "skipped": {},
    }
    rebuilt = hosting_cache.result_from_snapshot(snap)
    assert len(rebuilt.rows) == 1
    assert rebuilt.rows[0].domain == "x.com"


def test_result_from_snapshot_handles_missing_skipped():
    """Older snapshots written before HostingResult.skipped existed —
    fall back to empty dict."""
    snap = {"rows": [{"domain": "x.com", "provider": "vercel"}]}
    rebuilt = hosting_cache.result_from_snapshot(snap)
    assert rebuilt.skipped == {}


# ---- is_stale ----------------------------------------------------


def test_is_stale_returns_true_for_old_snapshot(monkeypatch, tmp_path):
    hosting_dir = _patch_hosting_dir(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    path = hosting_dir / "2026-04-01.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    path.write_text(
        '{"fetched_at": "' + old_ts + '", "rows": []}'
    )
    assert hosting_cache.is_stale(path) is True


def test_is_stale_returns_false_for_fresh_snapshot(monkeypatch, tmp_path):
    hosting_dir = _patch_hosting_dir(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    path = hosting_dir / "today.json"
    fresh_ts = datetime.now(timezone.utc).isoformat()
    path.write_text(
        '{"fetched_at": "' + fresh_ts + '", "rows": []}'
    )
    assert hosting_cache.is_stale(path) is False


def test_is_stale_returns_true_on_unreadable_file(tmp_path):
    """Corrupt/missing-fetched_at counts as stale — safe default."""
    path = tmp_path / "garbage.json"
    path.write_text("not json")
    assert hosting_cache.is_stale(path) is True


def test_is_stale_returns_true_when_fetched_at_missing(monkeypatch, tmp_path):
    hosting_dir = _patch_hosting_dir(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    path = hosting_dir / "today.json"
    path.write_text('{"rows": []}')   # no fetched_at
    assert hosting_cache.is_stale(path) is True


def test_is_stale_custom_max_age(monkeypatch, tmp_path):
    """Caller can pass a stricter freshness window."""
    hosting_dir = _patch_hosting_dir(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    path = hosting_dir / "today.json"
    five_hours_ago = (
        datetime.now(timezone.utc) - timedelta(hours=5)
    ).isoformat()
    path.write_text('{"fetched_at": "' + five_hours_ago + '", "rows": []}')
    # default 24h → fresh
    assert hosting_cache.is_stale(path) is False
    # 4h cap → stale
    assert hosting_cache.is_stale(path, max_age_hours=4) is True
