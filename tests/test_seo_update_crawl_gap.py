"""Tests for the `fleet seo` Updated-vs-Last-crawl freshness gap.

Covers the pure cell renderer (`_update_crawl_gap_cell`) and the
per-domain last-commit-date helper (`_last_update_by_domain`).
"""
from __future__ import annotations

import portfolio.check_render as check_render
from portfolio.check_render import _is_stale_in_index, _update_crawl_gap_cell


def test_gap_cell_flags_push_newer_than_crawl():
    # Pushed 2026-06-20, Google last crawled 2026-06-12 → stale, flag 🔄.
    cell = _update_crawl_gap_cell("2026-06-20", "2026-06-12")
    assert "2026-06-20" in cell
    assert "🔄" in cell


def test_gap_cell_no_flag_when_crawl_newer_or_equal():
    # Google read on/after the last push → fresh, no flag.
    assert _update_crawl_gap_cell("2026-06-12", "2026-06-20") == "2026-06-12"
    assert _update_crawl_gap_cell("2026-06-12", "2026-06-12") == "2026-06-12"


def test_gap_cell_no_update_date_is_dim_dash():
    assert _update_crawl_gap_cell(None, "2026-06-12") == "[dim]—[/]"
    assert _update_crawl_gap_cell(None, None) == "[dim]—[/]"


# --- never-crawled ("Last crawl —") branch ---------------------------------

def test_never_crawled_pushed_unindexed_is_stale():
    # cricketfansite.com: pushed, no crawl date, 0 impressions, not dark →
    # Google has never seen the content → flag.
    assert _is_stale_in_index("2026-06-19", None, is_dark=False, indexed=False)
    cell = _update_crawl_gap_cell("2026-06-19", None, is_dark=False, indexed=False)
    assert "🔄" in cell


def test_never_crawled_but_indexed_is_not_stale():
    # hybridautopart.com: no homepage crawl date cached, but 22,990
    # impressions → the "—" is a cache gap, not "never crawled" → no flag.
    assert not _is_stale_in_index("2026-05-30", None, is_dark=False, indexed=True)
    cell = _update_crawl_gap_cell("2026-05-30", None, is_dark=False, indexed=True)
    assert "🔄" not in cell
    assert cell == "2026-05-30"


def test_dark_site_never_flagged():
    # csinorcal.church: deliberately dark (robots blocks crawlers) — never
    # stale-flag, even pushed + never crawled.
    assert not _is_stale_in_index("2026-05-30", None, is_dark=True, indexed=False)
    assert not _is_stale_in_index("2026-06-20", "2026-06-12", is_dark=True, indexed=False)
    assert "🔄" not in _update_crawl_gap_cell("2026-05-30", None, is_dark=True)


def test_no_update_date_never_stale():
    # carrepairsite.com: no local repo → no push date → nothing to compare.
    assert not _is_stale_in_index(None, None, is_dark=False, indexed=False)
    assert not _is_stale_in_index(None, "2026-06-12", is_dark=False, indexed=False)


def test_last_update_by_domain_reads_commit_date(tmp_path, monkeypatch):
    sites = tmp_path / "sites"
    (sites / "example.com").mkdir(parents=True)
    (sites / "other.dev").mkdir(parents=True)

    monkeypatch.setattr(check_render, "_last_update_by_domain",
                        check_render._last_update_by_domain)
    # Patch the symbols the helper imports from .project.
    import portfolio.project as project
    monkeypatch.setattr(project, "SITES_ROOT", sites)

    def fake_last_commit(project_dir):
        name = project_dir.name
        if name == "example.com":
            return {"date": "2026-06-20T11:30:00+00:00", "age_days": 2}
        return None  # other.dev: no repo / no commits

    monkeypatch.setattr(project, "fetch_last_commit", fake_last_commit)

    out = check_render._last_update_by_domain()
    assert out == {"example.com": "2026-06-20"}


# --- BUG-084: Last-crawl cache floor reads both GSC cache schemas -----------

def test_home_crawl_from_items_picks_homepage_across_schemas():
    from portfolio.check_render import _home_crawl_from_items
    # Newer schema: v16c_inspections[].last_crawl_time. Homepage preferred over
    # a deeper URL even when the deeper one is listed first.
    v16c = [
        {"url": "https://x.com/blog/", "last_crawl_time": "2026-05-01T00:00:00Z"},
        {"url": "https://x.com/", "last_crawl_time": "2026-07-11T09:00:00Z"},
    ]
    assert _home_crawl_from_items(v16c, "last_crawl_time", "x.com") == "2026-07-11"
    # Older schema: coverage[].last_crawl_at.
    cov = [{"url": "https://x.com/", "last_crawl_at": "2026-06-04T04:52:14+00:00"}]
    assert _home_crawl_from_items(cov, "last_crawl_at", "x.com") == "2026-06-04"
    # Empty / missing field → None.
    assert _home_crawl_from_items([], "last_crawl_time", "x.com") is None
    assert _home_crawl_from_items([{"url": "https://x.com/"}], "last_crawl_at", "x.com") is None


def test_last_crawl_by_domain_covers_legacy_coverage_schema(tmp_path, monkeypatch):
    """Regression for BUG-084: a domain whose latest cache snapshot predates the
    `v16c_inspections` schema (stores `coverage[].last_crawl_at` instead) must
    still get a fallback floor, so `--refresh` doesn't blank Last-crawl to "—"
    when the live inspection call returns None."""
    import json

    gsc_dir = tmp_path / "gsc"
    # Legacy-schema domain (the hybridautopart case): coverage[].last_crawl_at.
    legacy = gsc_dir / "hybridautopart.com"
    legacy.mkdir(parents=True)
    (legacy / "2026-06-06.json").write_text(json.dumps({
        "coverage": [
            {"url": "https://hybridautopart.com/", "last_crawl_at": "2026-06-04T04:52:14+00:00"},
            {"url": "https://hybridautopart.com/blog/", "last_crawl_at": "2026-05-29T00:00:00Z"},
        ],
    }))
    # Newer-schema domain still resolves: v16c_inspections[].last_crawl_time.
    modern = gsc_dir / "threadradar.xyz"
    modern.mkdir(parents=True)
    (modern / "2026-07-03.json").write_text(json.dumps({
        "v16c_inspections": [
            {"url": "https://threadradar.xyz/", "last_crawl_time": "2026-07-03T00:00:00Z"},
        ],
    }))

    import portfolio.gsc as gsc
    monkeypatch.setattr(gsc, "GSC_DIR", gsc_dir)

    out = check_render._last_crawl_by_domain()
    assert out["hybridautopart.com"] == "2026-06-04"   # was absent before the fix
    assert out["threadradar.xyz"] == "2026-07-03"
