"""v36.D (BUG-093) — GSC snapshot cache: merge, never clobber; and the
`project seo` State/Blockers read the same coverage the table renders.

Regressions pinned:
  * airsucks.com 2026-10-02 — `project seo` saved its diagnostics over
    today's file and dropped `check_147`'s `v16c_inspections`.
  * isitholiday.today 2026-10-05 — Blockers called /usa/ "Soft 404"
    (11-day-old inspection) while Coverage said `submitted_indexed`.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from portfolio import gsc_detail_cache, seo_diagnose
from portfolio.seo_diagnose import gather_seo_diagnosis, latest_inspections

SOFT_404_USA = {"url": "https://x.test/usa/", "coverage_state": "Soft 404",
                "verdict": "NEUTRAL", "last_crawl_time": "2026-09-09T19:47:07+00:00"}


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")


def _quiet_probes(monkeypatch):
    monkeypatch.setattr(seo_diagnose, "audit_sitemap", lambda *a, **k: seo_diagnose.SitemapAudit(
        reachable=True, url_count=3, sitemap_url="https://x.test/sitemap.xml",
        submitted_to_gsc=True, page_urls=[]))
    monkeypatch.setattr(seo_diagnose, "probe_render", lambda u: seo_diagnose.RenderIssue(
        url=u, has_title=True, has_body_text=True))
    monkeypatch.setattr(seo_diagnose, "_impressions_and_submitted", lambda d: (0, True, []))
    monkeypatch.setattr(seo_diagnose, "_resolve_age", lambda d: 400)
    monkeypatch.setattr(seo_diagnose, "_content_configured", lambda d: True)


def test_save_merges_sections_instead_of_overwriting(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    gsc_detail_cache.save_snapshot("x.test", {"v16c_inspections": [SOFT_404_USA]})
    path = gsc_detail_cache.save_snapshot("x.test", {"coverage": [], "hints": []})
    snap = json.loads(path.read_text())
    assert snap["v16c_inspections"] == [SOFT_404_USA]
    assert snap["coverage"] == [] and "fetched_at" in snap


def test_save_merge_false_still_overwrites(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    gsc_detail_cache.save_snapshot("x.test", {"v16c_inspections": [SOFT_404_USA]})
    path = gsc_detail_cache.save_snapshot("x.test", {"coverage": []}, merge=False)
    assert "v16c_inspections" not in json.loads(path.read_text())


def test_inspections_fall_back_to_newest_snapshot_that_has_them(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    d = tmp_path / "gsc" / "x.test"
    d.mkdir(parents=True)
    (d / "2026-09-21.json").write_text(json.dumps({"v16c_inspections": [SOFT_404_USA]}))
    (d / "2026-10-05.json").write_text(json.dumps({"coverage": []}))
    raw, snap_date = latest_inspections("x.test")
    assert raw == [SOFT_404_USA] and snap_date == "2026-09-21"


def test_blockers_use_the_coverage_the_table_renders(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _quiet_probes(monkeypatch)
    d = tmp_path / "gsc" / "x.test"
    d.mkdir(parents=True)
    (d / "2026-09-21.json").write_text(json.dumps({"v16c_inspections": [SOFT_404_USA]}))
    fresh = [
        {"url": "https://x.test/usa/", "coverage_state": "submitted_indexed",
         "verdict": "PASS", "last_crawl_at": "2026-10-01T00:00:00+00:00", "error": None},
        {"url": "https://x.test/india/", "coverage_state": "soft_404",
         "verdict": "NEUTRAL", "last_crawl_at": "2026-09-30T00:00:00+00:00", "error": None},
    ]
    diag = gather_seo_diagnosis("x.test", coverage=fresh)
    titles = " ".join(b.title for b in diag.blockers)
    assert "/usa/" not in titles
    assert "/india/" in titles


def test_without_coverage_falls_back_with_an_age_note(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    _quiet_probes(monkeypatch)
    d = tmp_path / "gsc" / "x.test"
    d.mkdir(parents=True)
    old = (date.today() - timedelta(days=14)).isoformat()
    (d / f"{old}.json").write_text(json.dumps({"v16c_inspections": [SOFT_404_USA]}))
    diag = gather_seo_diagnosis("x.test")
    assert any("/usa/" in b.title for b in diag.blockers)
    assert any("14d old" in n for n in diag.notes)
