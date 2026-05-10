"""Tests for v5.F.1 — `data/seo/<date>.json` snapshot persistence."""
from __future__ import annotations

import json

from portfolio import seo_cache
from portfolio.seo_runtime import SEORow


def _patch_seo_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(seo_cache, "SEO_DIR", tmp_path / "seo")


def test_save_and_round_trip(monkeypatch, tmp_path):
    _patch_seo_dir(monkeypatch, tmp_path)
    rows = [
        SEORow(domain="alpha.com", http_status=200, hsts=True,
               robots_served=True, sitemap_served=True,
               gsc_status="ok", gsc_impressions=100, gsc_position=12.3),
        SEORow(domain="beta.com", http_status=200,
               gsc_status="not-in-gsc"),
    ]
    path = seo_cache.save_snapshot(rows, days=28)
    assert path.exists()
    snap = seo_cache.load_snapshot(path)
    assert snap["days"] == 28
    assert "fetched_at" in snap
    out = seo_cache.rows_from_snapshot(snap)
    assert [r.domain for r in out] == ["alpha.com", "beta.com"]
    assert out[0].gsc_impressions == 100
    assert out[1].gsc_status == "not-in-gsc"


def test_latest_snapshot_picks_newest(monkeypatch, tmp_path):
    _patch_seo_dir(monkeypatch, tmp_path)
    seo_dir = tmp_path / "seo"
    seo_dir.mkdir()
    (seo_dir / "2026-05-08.json").write_text("{}")
    (seo_dir / "2026-05-09.json").write_text("{}")
    (seo_dir / "2026-05-07.json").write_text("{}")
    latest = seo_cache.latest_snapshot()
    assert latest is not None
    assert latest.name == "2026-05-09.json"


def test_latest_snapshot_none_when_no_dir(monkeypatch, tmp_path):
    _patch_seo_dir(monkeypatch, tmp_path)
    assert seo_cache.latest_snapshot() is None


def test_rows_from_snapshot_drops_unknown_keys(monkeypatch, tmp_path):
    """Forward-compat: a snapshot from a future SEORow with new fields
    must still load (the new keys are silently dropped, not crashing)."""
    _patch_seo_dir(monkeypatch, tmp_path)
    snap = {
        "rows": [
            {"domain": "x.com", "http_status": 200, "future_field": "foo"},
        ],
    }
    out = seo_cache.rows_from_snapshot(snap)
    assert len(out) == 1
    assert out[0].domain == "x.com"
    assert out[0].http_status == 200


def test_is_stale_old_file(monkeypatch, tmp_path):
    _patch_seo_dir(monkeypatch, tmp_path)
    (tmp_path / "seo").mkdir()
    p = tmp_path / "seo" / "2020-01-01.json"
    p.write_text(json.dumps({
        "fetched_at": "2020-01-01T00:00:00+00:00",
        "rows": [],
    }))
    assert seo_cache.is_stale(p) is True


def test_is_stale_recent_file(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    _patch_seo_dir(monkeypatch, tmp_path)
    (tmp_path / "seo").mkdir()
    p = tmp_path / "seo" / "2026-05-09.json"
    p.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": [],
    }))
    assert seo_cache.is_stale(p) is False
