"""Tests for v16.D — gsc_rollup fleet-aggregation helpers.

Stubs the cache-load boundary so tests don't need real GSC data on
disk. Exercises both happy paths and the various "cache absent /
stale / section missing" → None/[] responses.
"""
from __future__ import annotations

from unittest.mock import patch

from portfolio.gsc_rollup import (
    CoverageStats,
    domain_coverage_stats,
    domain_pages,
    domain_queries,
    fleet_aggregated_top_pages,
    fleet_aggregated_top_queries,
    fleet_page_2_opportunities,
    page_2_opp_count,
)


def _patch_snapshot(snap):
    """Patch `_load_fresh_snapshot` to return `snap` (dict or None)."""
    return patch(
        "portfolio.gsc_rollup._load_fresh_snapshot",
        lambda _: snap,
    )


# ---- domain_coverage_stats ----------------------------------------


def test_coverage_none_when_no_snapshot():
    with _patch_snapshot(None):
        assert domain_coverage_stats("x.com") is None


def test_coverage_none_when_inspections_section_missing():
    with _patch_snapshot({"v13b_diagnostics": {}}):
        assert domain_coverage_stats("x.com") is None


def test_coverage_counts_indexed_vs_failing():
    snap = {"v16c_inspections": [
        {"status": "ok", "coverage_state": "Submitted and indexed"},
        {"status": "ok", "coverage_state": "Submitted and indexed"},
        {"status": "ok", "coverage_state": "Indexed, not submitted in sitemap"},
        {"status": "ok", "coverage_state": "Crawled - currently not indexed"},
        {"status": "ok", "coverage_state": "Not found (404)"},
    ]}
    with _patch_snapshot(snap):
        stats = domain_coverage_stats("x.com")
    assert stats == CoverageStats(inspected=5, indexed=3, crawl_errors=2)
    assert stats.coverage_pct == 60.0


def test_coverage_errored_inspections_excluded():
    """Inspections that errored at the GSC layer don't count
    toward `inspected` (they're noise, not signal)."""
    snap = {"v16c_inspections": [
        {"status": "ok", "coverage_state": "Submitted and indexed"},
        {"status": "error", "error": "HttpError 500"},
        {"status": "ok", "coverage_state": "Crawled - currently not indexed"},
    ]}
    with _patch_snapshot(snap):
        stats = domain_coverage_stats("x.com")
    assert stats == CoverageStats(inspected=2, indexed=1, crawl_errors=1)


def test_coverage_none_when_all_errored():
    snap = {"v16c_inspections": [
        {"status": "error", "error": "x"},
        {"status": "error", "error": "y"},
    ]}
    with _patch_snapshot(snap):
        assert domain_coverage_stats("x.com") is None


# ---- domain_queries / domain_pages --------------------------------


def test_domain_queries_parses_rows():
    snap = {"v16b_queries": [
        {"keys": ["ev charger cost"], "clicks": 4, "impressions": 156,
         "ctr": 0.025, "position": 8.2},
        {"keys": ["motorhome hire"], "clicks": 3, "impressions": 89,
         "ctr": 0.033, "position": 12.1},
    ]}
    with _patch_snapshot(snap):
        rows = domain_queries("x.com")
    assert len(rows) == 2
    assert rows[0].key == "ev charger cost"
    assert rows[0].clicks == 4
    assert rows[0].position == 8.2


def test_domain_queries_empty_when_section_missing():
    with _patch_snapshot({"v13b_diagnostics": {}}):
        assert domain_queries("x.com") == []


def test_domain_queries_skips_malformed_rows():
    snap = {"v16b_queries": [
        {"keys": ["good"], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5},
        {"clicks": 1},                                       # no keys
        {"keys": [], "clicks": 1, "impressions": 10},        # empty keys
        "not a dict",                                         # garbage
    ]}
    with _patch_snapshot(snap):
        rows = domain_queries("x.com")
    assert len(rows) == 1
    assert rows[0].key == "good"


def test_domain_queries_handles_null_position():
    snap = {"v16b_queries": [
        {"keys": ["no-data"], "clicks": 0, "impressions": 0,
         "ctr": 0.0, "position": None},
    ]}
    with _patch_snapshot(snap):
        rows = domain_queries("x.com")
    assert rows[0].position is None


# ---- page_2_opp_count ---------------------------------------------


def test_page_2_opp_count():
    snap = {"v16b_pages": [
        {"keys": ["https://x.com/a"], "clicks": 1, "impressions": 100,
         "ctr": 0.01, "position": 5.0},      # not page-2
        {"keys": ["https://x.com/b"], "clicks": 2, "impressions": 80,
         "ctr": 0.025, "position": 12.5},    # page-2, ≥50 imp → count
        {"keys": ["https://x.com/c"], "clicks": 1, "impressions": 30,
         "ctr": 0.033, "position": 15.0},    # page-2 but < 50 imp → skip
        {"keys": ["https://x.com/d"], "clicks": 3, "impressions": 60,
         "ctr": 0.05, "position": 18.0},     # page-2, ≥50 → count
        {"keys": ["https://x.com/e"], "clicks": 1, "impressions": 200,
         "ctr": 0.005, "position": 25.0},    # > pos 20 → skip
    ]}
    with _patch_snapshot(snap):
        count = page_2_opp_count("x.com")
    assert count == 2


def test_page_2_opp_count_none_when_no_cache():
    with _patch_snapshot(None):
        assert page_2_opp_count("x.com") is None


# ---- fleet_aggregated_top_queries ---------------------------------


def test_fleet_aggregated_top_queries_sums_across_domains(monkeypatch):
    """Two domains have overlapping queries. Aggregation sums
    impressions + counts distinct sites per query."""
    by_domain = {
        "a.com": {"v16b_queries": [
            {"keys": ["ev charger"], "clicks": 4, "impressions": 100,
             "ctr": 0.04, "position": 8.0},
            {"keys": ["solar panels"], "clicks": 2, "impressions": 50,
             "ctr": 0.04, "position": 10.0},
        ]},
        "b.com": {"v16b_queries": [
            {"keys": ["ev charger"], "clicks": 2, "impressions": 60,
             "ctr": 0.033, "position": 11.0},
            {"keys": ["motorhome"], "clicks": 1, "impressions": 30,
             "ctr": 0.033, "position": 14.0},
        ]},
    }
    monkeypatch.setattr(
        "portfolio.gsc_rollup._load_fresh_snapshot",
        lambda d: by_domain.get(d),
    )
    rows = fleet_aggregated_top_queries(["a.com", "b.com"], top_n=10)
    # ev charger: 160 imp across 2 sites; solar 50 across 1; motorhome 30 across 1.
    by_key = {r[0]: r for r in rows}
    assert by_key["ev charger"] == ("ev charger", 160, 6, 2)
    assert by_key["solar panels"] == ("solar panels", 50, 2, 1)
    assert by_key["motorhome"] == ("motorhome", 30, 1, 1)
    # Sort order: impressions desc.
    assert rows[0][0] == "ev charger"


def test_fleet_aggregated_top_queries_respects_top_n(monkeypatch):
    snap = {"v16b_queries": [
        {"keys": [f"q{i}"], "clicks": 1, "impressions": 100 - i,
         "ctr": 0.01, "position": 10.0}
        for i in range(20)
    ]}
    monkeypatch.setattr(
        "portfolio.gsc_rollup._load_fresh_snapshot",
        lambda _: snap,
    )
    rows = fleet_aggregated_top_queries(["x.com"], top_n=5)
    assert len(rows) == 5
    assert rows[0][0] == "q0"      # 100 imp
    assert rows[4][0] == "q4"      # 96 imp


# ---- fleet_aggregated_top_pages -----------------------------------


def test_fleet_aggregated_top_pages(monkeypatch):
    snap = {"v16b_pages": [
        {"keys": ["https://x.com/a"], "clicks": 2, "impressions": 100,
         "ctr": 0.02, "position": 7.0},
        {"keys": ["https://x.com/b"], "clicks": 1, "impressions": 50,
         "ctr": 0.02, "position": 12.0},
    ]}
    monkeypatch.setattr(
        "portfolio.gsc_rollup._load_fresh_snapshot",
        lambda _: snap,
    )
    rows = fleet_aggregated_top_pages(["x.com"], top_n=10)
    assert rows[0] == ("https://x.com/a", 100, 2)


# ---- fleet_page_2_opportunities -----------------------------------


def test_fleet_page_2_opportunities(monkeypatch):
    by_domain = {
        "a.com": {"v16b_pages": [
            {"keys": ["https://a.com/p1"], "clicks": 2, "impressions": 80,
             "ctr": 0.025, "position": 13.0},   # qualifies
        ]},
        "b.com": {"v16b_pages": [
            {"keys": ["https://b.com/q1"], "clicks": 1, "impressions": 150,
             "ctr": 0.007, "position": 15.0},   # qualifies — higher imp
            {"keys": ["https://b.com/q2"], "clicks": 1, "impressions": 40,
             "ctr": 0.025, "position": 17.0},   # below imp threshold — skip
        ]},
    }
    monkeypatch.setattr(
        "portfolio.gsc_rollup._load_fresh_snapshot",
        lambda d: by_domain.get(d),
    )
    rows = fleet_page_2_opportunities(["a.com", "b.com"])
    assert len(rows) == 2
    # Sort by impressions desc.
    assert rows[0] == ("b.com", "https://b.com/q1", 150, 15.0)
    assert rows[1] == ("a.com", "https://a.com/p1", 80, 13.0)
