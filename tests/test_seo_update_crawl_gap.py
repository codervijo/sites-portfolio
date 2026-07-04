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
