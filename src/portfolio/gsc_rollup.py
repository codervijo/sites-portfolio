"""v16.D — Fleet-level GSC rollup helpers.

Read-only aggregation over the per-domain caches at
`data/gsc/<domain>/<UTC-today>.json`. Powers:
  - `fleet dashboard` GSC columns (Coverage % / Crawl-err / W/w Δ /
    Page-2 opp)
  - `fleet seo --detail` mode (fleet-aggregated top queries / top
    pages / page-2 opportunities)

The caches are populated by:
  - v13.B `project seo` (diagnostics block — sitemaps + per-URL
    coverage)
  - v16.C CHECK_147 url-indexed (URL Inspection sweep)
  - v16.B `gsc.query_with_dims()` (when invoked through a higher-
    level command that writes to `gsc_detail_cache`)

Caches that are absent or stale (`is_stale` at 24h default) render
as `None` from these helpers — callers map to `"—"` in the table
output. No automatic refresh from this module; that's a separate
operator action (`project seo --refresh` or future `fleet gsc
populate`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from . import gsc_detail_cache

# Coverage states that count as "indexed" per the v16.C convention.
# Duplicated from check_147 so this module doesn't depend on the
# checks layer.
_INDEXED_STATES = frozenset({
    "Submitted and indexed",
    "Indexed, not submitted in sitemap",
})


@dataclass(frozen=True)
class CoverageStats:
    """Per-domain coverage rollup from `v16c_inspections` cache."""
    inspected: int
    indexed: int
    crawl_errors: int   # non-indexed inspections — count, not list

    @property
    def coverage_pct(self) -> Optional[float]:
        if self.inspected == 0:
            return None
        return (self.indexed / self.inspected) * 100.0


@dataclass(frozen=True)
class QueryRow:
    """One row of GSC query data (clicks / impressions / etc.)."""
    key: str
    clicks: int
    impressions: int
    ctr: float
    position: Optional[float]


def domain_coverage_stats(domain: str) -> Optional[CoverageStats]:
    """Read the v16c_inspections section from the per-domain cache.
    Returns None when:
      - no cache exists for `domain`
      - cache is stale
      - cache doesn't have a `v16c_inspections` section yet
    """
    snap = _load_fresh_snapshot(domain)
    if snap is None:
        return None
    inspections = snap.get("v16c_inspections")
    if not isinstance(inspections, list) or not inspections:
        return None
    inspected = 0
    indexed = 0
    crawl_errors = 0
    for insp in inspections:
        if not isinstance(insp, dict):
            continue
        if insp.get("status") == "error":
            continue
        inspected += 1
        state = insp.get("coverage_state") or ""
        if state in _INDEXED_STATES:
            indexed += 1
        else:
            crawl_errors += 1
    if inspected == 0:
        return None
    return CoverageStats(
        inspected=inspected,
        indexed=indexed,
        crawl_errors=crawl_errors,
    )


def domain_queries(domain: str) -> list[QueryRow]:
    """Read the cached query-dimension rows (v16.B foundation)
    for `domain`. Returns [] when absent / stale / not yet populated.

    Cache section name: `v16b_queries` (a list of dicts shaped like
    `gsc.query_with_dims` output)."""
    return _parse_dim_section(domain, "v16b_queries")


def domain_pages(domain: str) -> list[QueryRow]:
    """Read the cached page-dimension rows (v16.B foundation).
    Cache section: `v16b_pages`."""
    return _parse_dim_section(domain, "v16b_pages")


def page_2_opp_count(
    domain: str,
    *,
    min_impressions: int = 50,
    pos_range: tuple[float, float] = (11.0, 20.0),
) -> Optional[int]:
    """Count pages with position in `pos_range` (default 11-20) AND
    impressions ≥ `min_impressions`. Returns None when no page cache
    is available."""
    pages = domain_pages(domain)
    if not pages:
        return None
    lo, hi = pos_range
    return sum(
        1 for p in pages
        if p.position is not None
        and lo <= p.position <= hi
        and p.impressions >= min_impressions
    )


def fleet_aggregated_top_queries(
    domains: Iterable[str],
    *,
    top_n: int = 10,
) -> list[tuple[str, int, int, int]]:
    """Sum clicks/impressions across all domains' cached query rows.

    Returns list of `(query, impressions, clicks, site_count)`, sorted
    by impressions desc, capped at `top_n`. `site_count` is the number
    of distinct domains the query appears in (1+ = how many of your
    sites Google sees this query for).
    """
    agg: dict[str, dict] = {}
    for d in domains:
        for q in domain_queries(d):
            slot = agg.setdefault(q.key, {"imp": 0, "clicks": 0, "sites": set()})
            slot["imp"] += q.impressions
            slot["clicks"] += q.clicks
            slot["sites"].add(d)
    rows = [
        (key, v["imp"], v["clicks"], len(v["sites"]))
        for key, v in agg.items()
    ]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:top_n]


def fleet_aggregated_top_pages(
    domains: Iterable[str],
    *,
    top_n: int = 10,
) -> list[tuple[str, int, int]]:
    """Sum clicks/impressions across all domains' cached page rows.

    Returns list of `(page_url, impressions, clicks)`, sorted by
    impressions desc, capped at `top_n`. Page URLs are absolute
    (GSC returns them that way), so dedup is by URL string.
    """
    agg: dict[str, dict] = {}
    for d in domains:
        for p in domain_pages(d):
            slot = agg.setdefault(p.key, {"imp": 0, "clicks": 0})
            slot["imp"] += p.impressions
            slot["clicks"] += p.clicks
    rows = [
        (url, v["imp"], v["clicks"])
        for url, v in agg.items()
    ]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:top_n]


def fleet_page_2_opportunities(
    domains: Iterable[str],
    *,
    min_impressions: int = 50,
    pos_range: tuple[float, float] = (11.0, 20.0),
    top_n: int = 15,
) -> list[tuple[str, str, int, float]]:
    """Cross-domain list of page-2 opportunity URLs — pages with
    position in `pos_range` AND impressions ≥ `min_impressions`,
    sorted by impressions desc.

    Returns `(domain, page_url, impressions, position)` tuples.
    """
    rows: list[tuple[str, str, int, float]] = []
    lo, hi = pos_range
    for d in domains:
        for p in domain_pages(d):
            if p.position is None:
                continue
            if not (lo <= p.position <= hi):
                continue
            if p.impressions < min_impressions:
                continue
            rows.append((d, p.key, p.impressions, p.position))
    rows.sort(key=lambda r: r[2], reverse=True)
    return rows[:top_n]


# ---- internals ----------------------------------------------------


def _load_fresh_snapshot(domain: str) -> Optional[dict]:
    snap_path = gsc_detail_cache.latest_snapshot(domain)
    if snap_path is None or gsc_detail_cache.is_stale(snap_path):
        return None
    try:
        return gsc_detail_cache.load_snapshot(snap_path)
    except (OSError, ValueError):
        return None


def _parse_dim_section(domain: str, section: str) -> list[QueryRow]:
    snap = _load_fresh_snapshot(domain)
    if snap is None:
        return []
    rows = snap.get(section)
    if not isinstance(rows, list):
        return []
    out: list[QueryRow] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        keys = r.get("keys")
        if not (isinstance(keys, list) and keys):
            continue
        out.append(QueryRow(
            key=str(keys[0]),
            clicks=int(r.get("clicks", 0)),
            impressions=int(r.get("impressions", 0)),
            ctr=float(r.get("ctr", 0.0)),
            position=(
                float(r["position"])
                if r.get("position") is not None
                else None
            ),
        ))
    return out
