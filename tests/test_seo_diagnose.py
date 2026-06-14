"""v36 — `project seo` problem-surfacing diagnostic core.

Pins the honesty contract: a 0-impression site with a not-indexed
homepage + a 1-URL sitemap is `blocked` with ≥3 blockers, never green;
the sitemap audit recurses/follows robots (no false "unreachable"); the
render probe flags SSR-less shells; the index state is read from the
cached `v16c_inspections`.
"""
from __future__ import annotations

import httpx

from portfolio.seo_diagnose import (
    IndexInsight,
    SitemapAudit,
    RenderIssue,
    audit_sitemap,
    compute_state,
    probe_render,
    read_index_insights,
)


def _mock_client(routes: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key in routes:
            return routes[key]
        # also try path-only
        if request.url.path in routes:
            return routes[request.url.path]
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=True)


# ---------- compute_state: the honesty core ----------


def test_airsucks_case_is_blocked_with_three_blockers():
    """DoD: young + 0 imp + not-indexed homepage + 1-URL sitemap →
    blocked, ≥3 blockers, never green."""
    insights = [IndexInsight(
        url="https://airsucks.com/",
        coverage_state="crawled_not_indexed",
        coverage_label="Crawled - currently not indexed",
        verdict="NEUTRAL", last_crawl_at="2026-04-12T00:17:25+00:00")]
    audit = SitemapAudit(
        reachable=True, url_count=1,
        sitemap_url="https://airsucks.com/sitemap-index.xml",
        submitted_to_gsc=False, page_urls=["https://airsucks.com/"])
    state, blockers = compute_state(
        origin="https://airsucks.com",
        impressions=0, site_age_days=20,
        index_insights=insights, sitemap_audit=audit)
    assert state == "blocked"
    assert len(blockers) >= 3
    # homepage-not-indexed is a hard ⛔ and sorts first
    assert blockers[0].kind == "blocker"
    titles = " | ".join(b.title for b in blockers)
    assert "Homepage" in titles
    assert "only 1 URL" in titles
    assert "not submitted" in titles


def test_healthy_when_earning_traffic():
    state, blockers = compute_state(
        origin="https://x.com", impressions=120, site_age_days=400,
        index_insights=[], sitemap_audit=None)
    assert state == "healthy"


def test_unproven_when_young_zero_traffic_nothing_wrong():
    insights = [IndexInsight("https://x.com/", "submitted_indexed",
                             "Submitted and indexed", "PASS", None)]
    audit = SitemapAudit(reachable=True, url_count=8,
                         sitemap_url="https://x.com/sitemap.xml",
                         submitted_to_gsc=True)
    state, blockers = compute_state(
        origin="https://x.com", impressions=0, site_age_days=10,
        index_insights=insights, sitemap_audit=audit)
    assert state == "unproven"
    assert blockers == []


def test_old_site_zero_traffic_no_detected_blocker_is_blocked():
    """Silence past the freshness window IS the blocker."""
    state, blockers = compute_state(
        origin="https://x.com", impressions=0, site_age_days=300,
        index_insights=[], sitemap_audit=None)
    assert state == "blocked"
    assert any("0 impressions" in b.title for b in blockers)


def test_indexed_homepage_does_not_block():
    insights = [IndexInsight("https://x.com/", "submitted_indexed",
                             "Submitted and indexed", "PASS", None)]
    state, blockers = compute_state(
        origin="https://x.com", impressions=5, site_age_days=200,
        index_insights=insights, sitemap_audit=None)
    assert state == "healthy"
    assert all("Homepage" not in b.title for b in blockers)


def test_content_unconfigured_adds_warn():
    _, blockers = compute_state(
        origin="https://x.com", impressions=3, site_age_days=5,
        index_insights=[], sitemap_audit=None, content_configured=False)
    assert any("[content]" in b.title for b in blockers)


def test_render_issues_flagged_as_blocker_entry():
    issues = [RenderIssue("https://x.com/a", has_title=False,
                          has_body_text=False)]
    _, blockers = compute_state(
        origin="https://x.com", impressions=9, site_age_days=5,
        index_insights=[], sitemap_audit=None, render_issues=issues)
    assert any("render empty" in b.title for b in blockers)


# ---------- audit_sitemap: recursion + no false unreachable ----------


def test_audit_follows_robots_and_recurses_index():
    robots = "User-agent: *\nAllow: /\nSitemap: https://s.com/sitemap-index.xml\n"
    index_xml = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 '<sitemap><loc>https://s.com/sitemap-0.xml</loc></sitemap></sitemapindex>')
    child_xml = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 '<url><loc>https://s.com/</loc></url>'
                 '<url><loc>https://s.com/about</loc></url>'
                 '<url><loc>https://s.com/blog</loc></url></urlset>')
    client = _mock_client({
        "https://s.com/robots.txt": httpx.Response(200, text=robots),
        "https://s.com/sitemap-index.xml": httpx.Response(200, text=index_xml),
        "https://s.com/sitemap-0.xml": httpx.Response(200, text=child_xml),
    })
    audit = audit_sitemap("https://s.com", submitted_to_gsc=True, client=client)
    assert audit.reachable is True
    assert audit.url_count == 3
    assert audit.sitemap_url == "https://s.com/sitemap-index.xml"
    assert audit.thin is False
    assert audit.healthy is True


def test_audit_no_false_unreachable_when_sitemap_xml_missing():
    """The reported bug: /sitemap.xml 404s but robots declares an index —
    must be reachable, not 'unreachable'."""
    robots = "User-agent: *\nSitemap: https://s.com/sitemap-index.xml\n"
    index_xml = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 '<url><loc>https://s.com/</loc></url></urlset>')
    client = _mock_client({
        "https://s.com/robots.txt": httpx.Response(200, text=robots),
        "https://s.com/sitemap.xml": httpx.Response(404),
        "https://s.com/sitemap-index.xml": httpx.Response(200, text=index_xml),
    })
    audit = audit_sitemap("https://s.com", submitted_to_gsc=False, client=client)
    assert audit.reachable is True
    assert audit.url_count == 1
    assert audit.thin is True            # only the homepage
    assert audit.healthy is False        # not submitted + thin


def test_audit_genuinely_unreachable():
    client = _mock_client({})            # everything 404s
    audit = audit_sitemap("https://s.com", submitted_to_gsc=False, client=client)
    assert audit.reachable is False
    assert audit.url_count == 0
    assert audit.error


# ---------- probe_render ----------


def test_probe_render_flags_empty_spa_shell():
    shell = ('<!doctype html><html><head><title></title></head>'
             '<body><div id="root"></div><script src="/app.js"></script></body></html>')
    client = _mock_client({"https://x.com/route": httpx.Response(200, text=shell)})
    ri = probe_render("https://x.com/route", client=client)
    assert ri.empty_shell is True


def test_probe_render_passes_ssr_page():
    page = ('<!doctype html><html><head><title>About Us</title></head>'
            '<body><h1>About Us</h1><p>We are a real company with real '
            'content that a crawler can read without JavaScript.</p></body></html>')
    client = _mock_client({"https://x.com/about": httpx.Response(200, text=page)})
    ri = probe_render("https://x.com/about", client=client)
    assert ri.empty_shell is False
    assert ri.has_title and ri.has_body_text


# ---------- read_index_insights (from cache) ----------


def test_read_index_insights_from_injected_loader():
    raw = [{
        "url": "https://airsucks.com/", "status": "ok",
        "coverage_state": "Crawled - currently not indexed",
        "verdict": "NEUTRAL", "last_crawl_time": "2026-04-12T00:17:25+00:00",
    }]
    got = read_index_insights("airsucks.com", loader=lambda d: raw)
    assert len(got) == 1
    assert got[0].coverage_state == "crawled_not_indexed"
    assert got[0].is_indexed is False
    assert got[0].coverage_label == "Crawled - currently not indexed"


def test_read_index_insights_empty_when_no_cache():
    assert read_index_insights("nope.com", loader=lambda d: None) == []
