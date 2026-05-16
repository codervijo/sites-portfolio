"""Tests for v5.D — `check --seo` runtime probe."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from portfolio.seo_runtime import (
    SEORow,
    _live_domains_from_snapshot,
    _parse_robots_sitemaps,
    overall_status,
    probe_crux,
    probe_gsc,
    probe_http,
    row_statuses,
    sort_rows,
)


# ---------- HTTP probe ----------


def _mock_transport(handlers: dict[str, httpx.Response]) -> httpx.MockTransport:
    """Build a MockTransport that returns canned responses keyed by request path."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in handlers:
            return handlers[path]
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_probe_http_pass_all():
    transport = _mock_transport({
        "/": httpx.Response(200, headers={"strict-transport-security": "max-age=31536000"}),
        "/robots.txt": httpx.Response(200,
                                      headers={"content-type": "text/plain"},
                                      text="User-agent: *\n"),
        "/sitemap.xml": httpx.Response(200, text="<urlset/>"),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["status"] == 200
    assert r["error"] is None
    assert r["hsts"] is True
    assert r["robots_served"] is True
    assert r["sitemap_served"] is True


def test_probe_http_no_hsts():
    transport = _mock_transport({
        "/": httpx.Response(200),  # no HSTS header
        "/robots.txt": httpx.Response(404),
        "/sitemap.xml": httpx.Response(404),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["hsts"] is False
    assert r["robots_served"] is False
    assert r["sitemap_served"] is False


def test_probe_http_connection_error():
    def handler(request):
        raise httpx.ConnectError("dns failed")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        r = probe_http("nonexistent.test", client=client)
    assert r["status"] is None
    assert "ConnectError" in r["error"]


def test_probe_http_robots_must_be_text():
    """robots.txt served with HTML content-type should fail (parking page)."""
    transport = _mock_transport({
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200, headers={"content-type": "text/html"},
                                      text="<html>Parked</html>"),
        "/sitemap.xml": httpx.Response(404),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["robots_served"] is False


def test_probe_http_sitemap_url_passes_through_on_default():
    """When /sitemap.xml works, sitemap_url records the full URL."""
    transport = _mock_transport({
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200,
                                      headers={"content-type": "text/plain"},
                                      text="User-agent: *\n"),
        "/sitemap.xml": httpx.Response(200, text="<urlset/>"),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["sitemap_served"] is True
    assert r["sitemap_url"] == "https://example.com/sitemap.xml"


def test_probe_http_sitemap_falls_back_to_index_path():
    """When /sitemap.xml 404s, try /sitemap-index.xml — covers calcengine.site."""
    transport = _mock_transport({
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200,
                                      headers={"content-type": "text/plain"},
                                      text="User-agent: *\nAllow: /\n"),
        "/sitemap.xml": httpx.Response(404),
        "/sitemap-index.xml": httpx.Response(200, text="<sitemapindex/>"),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["sitemap_served"] is True
    assert r["sitemap_url"] == "https://example.com/sitemap-index.xml"


def test_probe_http_sitemap_follows_robots_directive():
    """A `Sitemap:` directive in robots.txt wins — even when it points at
    a host the probe wouldn't otherwise try (e.g. www subdomain)."""
    def handler(request):
        path = request.url.path
        host = request.url.host
        if host == "example.com" and path == "/":
            return httpx.Response(200)
        if host == "example.com" and path == "/robots.txt":
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                text="User-agent: *\nSitemap: https://www.example.com/sitemap-index.xml\n",
            )
        if host == "example.com" and path == "/sitemap.xml":
            return httpx.Response(404)
        if host == "www.example.com" and path == "/sitemap-index.xml":
            return httpx.Response(200, text="<sitemapindex/>")
        return httpx.Response(404)
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["sitemap_served"] is True
    assert r["sitemap_url"] == "https://www.example.com/sitemap-index.xml"


def test_probe_http_sitemap_all_candidates_404():
    transport = _mock_transport({
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200,
                                      headers={"content-type": "text/plain"},
                                      text="User-agent: *\n"),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        r = probe_http("example.com", client=client)
    assert r["sitemap_served"] is False
    assert r["sitemap_url"] is None


def test_parse_robots_sitemaps_basic():
    body = "User-agent: *\nDisallow:\nSitemap: https://x.com/a.xml\n"
    assert _parse_robots_sitemaps(body) == ["https://x.com/a.xml"]


def test_parse_robots_sitemaps_multiple_and_case_insensitive():
    body = (
        "User-agent: *\n"
        "sitemap: https://x.com/a.xml\n"
        "SITEMAP: https://x.com/b.xml\n"
        "Sitemap: https://x.com/c.xml\n"
    )
    assert _parse_robots_sitemaps(body) == [
        "https://x.com/a.xml", "https://x.com/b.xml", "https://x.com/c.xml"
    ]


def test_parse_robots_sitemaps_ignores_comments_and_relative():
    body = (
        "# Sitemap: https://x.com/commented.xml\n"
        "Sitemap: /relative.xml\n"      # ignored — must be absolute http(s)
        "Sitemap: ftp://x.com/wrong\n"  # ignored — wrong scheme
        "Sitemap: https://x.com/ok.xml\n"
    )
    assert _parse_robots_sitemaps(body) == ["https://x.com/ok.xml"]


def test_parse_robots_sitemaps_empty():
    assert _parse_robots_sitemaps("") == []
    assert _parse_robots_sitemaps("User-agent: *\nDisallow:\n") == []


# ---------- GSC probe ----------


def test_probe_gsc_auth_skipped():
    r = probe_gsc("example.com", days=28, auth_skipped=True)
    assert r["status"] == "auth-skipped"
    assert r["clicks"] is None


def test_probe_gsc_not_in_gsc():
    r = probe_gsc("example.com", days=28, gsc_service=MagicMock(), coverage={})
    assert r["status"] == "not-in-gsc"


def test_probe_gsc_ok_single_property(monkeypatch):
    # Patch query_totals to return canned data without hitting the API.
    from portfolio import seo_runtime
    fake = MagicMock(return_value={"clicks": 100, "impressions": 1000,
                                   "ctr": 0.1, "position": 12.5})
    monkeypatch.setattr("portfolio.gsc.query_totals", fake)

    service = MagicMock()
    sitemaps_mock = MagicMock()
    sitemaps_mock.list.return_value.execute.return_value = {
        "sitemap": [{"path": "https://example.com/sitemap.xml"}]
    }
    service.sitemaps.return_value = sitemaps_mock

    coverage = {"example.com": [{"siteUrl": "sc-domain:example.com"}]}
    r = probe_gsc("example.com", days=28, gsc_service=service, coverage=coverage)
    assert r["status"] == "ok"
    assert r["clicks"] == 100
    assert r["impressions"] == 1000
    assert r["ctr"] == pytest.approx(0.1)
    assert r["position"] == pytest.approx(12.5)
    assert r["sitemap_count"] == 1


def test_probe_gsc_merges_multiple_properties(monkeypatch):
    """sc-domain: + url-prefix for the same domain → merged totals,
    impression-weighted average position."""
    fake_returns = iter([
        {"clicks": 10, "impressions": 100, "ctr": 0.1, "position": 5.0},
        {"clicks": 20, "impressions": 400, "ctr": 0.05, "position": 15.0},
    ])
    monkeypatch.setattr("portfolio.gsc.query_totals", lambda *a, **k: next(fake_returns))

    service = MagicMock()
    service.sitemaps.return_value.list.return_value.execute.return_value = {"sitemap": []}

    coverage = {"example.com": [
        {"siteUrl": "sc-domain:example.com"},
        {"siteUrl": "https://example.com/"},
    ]}
    r = probe_gsc("example.com", days=28, gsc_service=service, coverage=coverage)
    assert r["clicks"] == 30
    assert r["impressions"] == 500
    # weighted: (5*100 + 15*400) / 500 = 13
    assert r["position"] == pytest.approx(13.0)


# ---------- CrUX probe ----------


def test_probe_crux_no_key():
    r = probe_crux("example.com", api_key="")
    assert r["status"] == "no-key"
    assert r["lcp_p75"] is None


def test_probe_crux_ok():
    body = {
        "record": {
            "metrics": {
                "largest_contentful_paint": {"percentiles": {"p75": 1800}},
                "interaction_to_next_paint": {"percentiles": {"p75": 150}},
                "cumulative_layout_shift": {"percentiles": {"p75": "0.05"}},
            }
        }
    }
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json=body)
    )
    with httpx.Client(transport=transport) as client:
        r = probe_crux("example.com", api_key="fake", client=client)
    assert r["status"] == "ok"
    assert r["lcp_p75"] == 1800.0
    assert r["inp_p75"] == 150.0
    assert r["cls_p75"] == pytest.approx(0.05)


def test_probe_crux_no_data_for_origin():
    transport = httpx.MockTransport(lambda req: httpx.Response(404, json={"error": "no data"}))
    with httpx.Client(transport=transport) as client:
        r = probe_crux("rare.test", api_key="fake", client=client)
    assert r["status"] == "no-data"
    assert r["lcp_p75"] is None


def test_probe_crux_http_error():
    transport = httpx.MockTransport(lambda req: httpx.Response(500, json={"error": "boom"}))
    with httpx.Client(transport=transport) as client:
        r = probe_crux("example.com", api_key="fake", client=client)
    assert r["status"] == "error"


# ---------- status emojis ----------


def test_overall_status_green_when_seo_signals_green():
    """All four SEO signals (imp, pos, robots, sitemap) green → green."""
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_impressions=1000, gsc_position=5.0)
    assert overall_status(row) == "🟢"


def test_overall_status_red_when_no_impressions():
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_impressions=0, gsc_position=5.0)
    assert overall_status(row) == "🔴"


def test_overall_status_ignores_hsts():
    """HSTS is a security signal, not SEO — must NOT affect row color."""
    # All SEO signals green; HSTS missing should NOT pull the row away from green.
    row_no_hsts = SEORow(domain="x", hsts=False,
                         robots_served=True, sitemap_served=True,
                         gsc_impressions=1000, gsc_position=5.0)
    assert overall_status(row_no_hsts) == "🟢"
    # And present HSTS shouldn't redeem an SEO red.
    row_with_hsts = SEORow(domain="x", hsts=True,
                           robots_served=False, sitemap_served=True,
                           gsc_impressions=1000, gsc_position=5.0)
    assert overall_status(row_with_hsts) == "🔴"


def test_overall_status_ignores_http_status():
    """HTTP status doesn't drive row color — failures cascade into robots/sitemap reds."""
    row = SEORow(domain="x", http_status=500,
                 robots_served=True, sitemap_served=True,
                 gsc_impressions=1000, gsc_position=5.0)
    assert overall_status(row) == "🟢"


def test_overall_status_ignores_crux():
    """CrUX field data is reported but doesn't drive SEO row color."""
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_impressions=1000, gsc_position=5.0,
                 crux_lcp_p75=10000)  # very poor LCP
    assert overall_status(row) == "🟢"


def test_overall_status_young_site_masks_imp_and_pos():
    """P4 — sites <90d old: imp + pos cells don't pull grade toward red.
    Real-world case: airsucks.com launched today, robots/sitemap/GSC all
    set up correctly, but imp=0 (no data yet) and no position. Mature-
    grading would call this 🔴; age-aware grading sees it as 🟢."""
    row = SEORow(domain="airsucks.com",
                 robots_served=True, sitemap_served=True,
                 gsc_status="ok", gsc_impressions=0,
                 gsc_position=None)
    assert overall_status(row) == "🔴"                          # default: not masked
    assert overall_status(row, site_age_days=1) == "🟢"        # young: masked
    assert overall_status(row, site_age_days=89) == "🟢"       # still inside window
    assert overall_status(row, site_age_days=90) == "🔴"       # just past threshold


def test_overall_status_young_site_does_not_mask_structural_signals():
    """Robots / sitemap / GSC are structural — age doesn't excuse them.
    A young site missing robots.txt is still 🔴."""
    row = SEORow(domain="x",
                 robots_served=False, sitemap_served=True,
                 gsc_status="ok", gsc_impressions=0)
    assert overall_status(row, site_age_days=5) == "🔴"


def test_overall_status_young_site_with_real_traffic_still_grades_pos():
    """An edge case: a young site that DOES have traffic + bad position.
    Masking imp/pos is conservative — even legitimate signals get masked
    inside the freshness window. By design (better to underflag young
    sites than nag the user about normal-for-young state)."""
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_status="ok", gsc_impressions=500,
                 gsc_position=60.0)
    # Mature: position=60 → 🔴. Young: imp + pos masked → 🟢.
    assert overall_status(row) == "🔴"
    assert overall_status(row, site_age_days=30) == "🟢"


def test_overall_status_custom_threshold_respected():
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_status="ok", gsc_impressions=0)
    # Tight 7-day threshold: 8-day-old site is past the window.
    assert overall_status(row, site_age_days=8, young_threshold_days=7) == "🔴"
    assert overall_status(row, site_age_days=5, young_threshold_days=7) == "🟢"


def test_overall_status_none_age_does_not_mask():
    """Backward-compatible — callers without age data get pre-P4 grading."""
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_status="ok", gsc_impressions=0)
    assert overall_status(row, site_age_days=None) == "🔴"


def test_overall_status_grey_when_all_seo_signals_unknown():
    """No SEO data at all → grey (e.g. probe failed, GSC not authed)."""
    row = SEORow(domain="x", http_status=200, hsts=True,
                 crux_lcp_p75=1500)
    assert overall_status(row) == "⚪"


def test_overall_status_red_when_not_in_gsc():
    """Domain is registered + serving but missing from Search Console
    → red. A site Google doesn't know about is invisible to organic."""
    row = SEORow(domain="x", http_status=200,
                 robots_served=True, sitemap_served=True,
                 gsc_status="not-in-gsc")
    assert overall_status(row) == "🔴"


def test_overall_status_green_when_in_gsc_with_traffic():
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_status="ok",
                 gsc_impressions=1000, gsc_position=5.0)
    assert overall_status(row) == "🟢"


def test_overall_status_ignores_gsc_when_auth_skipped():
    """`auth-skipped` is a tooling state ("you didn't run gsc auth"),
    not a domain problem — must NOT pull row to red."""
    row = SEORow(domain="x",
                 robots_served=True, sitemap_served=True,
                 gsc_status="auth-skipped")
    # Robots+Sitemap green; gsc grey → green wins.
    assert overall_status(row) == "🟢"


def test_row_statuses_gsc_column():
    from portfolio.seo_runtime import row_statuses
    assert row_statuses(SEORow(domain="x", gsc_status="ok"))["gsc"] == "🟢"
    assert row_statuses(SEORow(domain="x", gsc_status="not-in-gsc"))["gsc"] == "🔴"
    assert row_statuses(SEORow(domain="x", gsc_status="auth-skipped"))["gsc"] == "⚪"
    assert row_statuses(SEORow(domain="x", gsc_status="error"))["gsc"] == "⚪"


# ---------- GSC sitemap-submitted status ----------


def test_row_statuses_gsc_sitemap_submitted_green_when_count_ge_1():
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="ok", gsc_sitemap_count=1)
    assert row_statuses(r)["gsc_sitemap"] == "🟢"


def test_row_statuses_gsc_sitemap_submitted_green_when_count_multiple():
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="ok", gsc_sitemap_count=3)
    assert row_statuses(r)["gsc_sitemap"] == "🟢"


def test_row_statuses_gsc_sitemap_submitted_map_glyph_when_count_zero():
    """The distinct callout: in GSC but no sitemap submitted."""
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="ok", gsc_sitemap_count=0)
    assert row_statuses(r)["gsc_sitemap"] == "❌"


def test_row_statuses_gsc_sitemap_submitted_grey_when_not_in_gsc():
    """Not-in-GSC → we can't distinguish 'no submission' from 'no GSC entry'."""
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="not-in-gsc", gsc_sitemap_count=None)
    assert row_statuses(r)["gsc_sitemap"] == "⚪"


def test_row_statuses_gsc_sitemap_submitted_grey_when_auth_skipped():
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="auth-skipped", gsc_sitemap_count=None)
    assert row_statuses(r)["gsc_sitemap"] == "⚪"


def test_row_statuses_gsc_sitemap_submitted_grey_when_count_is_none():
    """Even with status=ok, a None count means we didn't get the data."""
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="ok", gsc_sitemap_count=None)
    assert row_statuses(r)["gsc_sitemap"] == "⚪"


def test_row_statuses_gsc_sitemap_independent_of_sitemap_served():
    """A site can SERVE a sitemap (sitemap_served=True) and still have
    ZERO submitted to GSC (gsc_sitemap_count=0). The two columns are
    independent."""
    from portfolio.seo_runtime import row_statuses
    r = SEORow(domain="x", gsc_status="ok",
               sitemap_served=True, gsc_sitemap_count=0)
    s = row_statuses(r)
    assert s["sitemap"] == "🟢"     # the live URL serves one
    assert s["gsc_sitemap"] == "❌"  # but nothing submitted to GSC


def test_row_statuses_dict_contains_gsc_sitemap_key():
    """The new key is always present in the output (renderer relies on it)."""
    from portfolio.seo_runtime import row_statuses
    assert "gsc_sitemap" in row_statuses(SEORow(domain="x"))


def test_gsc_sitemap_status_not_in_overall_keys():
    """The new sitemap-submitted signal is a sidecar — don't pull the
    overall SEO grade because a site doesn't have a submitted sitemap.
    Operators can decide if that's worth fixing on a per-site basis."""
    from portfolio.seo_runtime import _OVERALL_KEYS
    assert "gsc_sitemap" not in _OVERALL_KEYS


def test_row_statuses_lcp_thresholds():
    # 2500ms = green, 4000ms = yellow, 6000ms = orange, beyond = red
    assert row_statuses(SEORow(domain="x", crux_lcp_p75=2000))["lcp"] == "🟢"
    assert row_statuses(SEORow(domain="x", crux_lcp_p75=3500))["lcp"] == "🟡"
    assert row_statuses(SEORow(domain="x", crux_lcp_p75=5000))["lcp"] == "🟠"
    assert row_statuses(SEORow(domain="x", crux_lcp_p75=8000))["lcp"] == "🔴"


def test_row_statuses_position_lower_is_better():
    assert row_statuses(SEORow(domain="x", gsc_position=5.0))["pos"] == "🟢"
    assert row_statuses(SEORow(domain="x", gsc_position=20.0))["pos"] == "🟡"
    assert row_statuses(SEORow(domain="x", gsc_position=40.0))["pos"] == "🟠"
    assert row_statuses(SEORow(domain="x", gsc_position=80.0))["pos"] == "🔴"


# ---------- snapshot filtering ----------


def test_live_domains_picks_live_site_and_forwarder():
    snap = {"results": [
        {"domain": "alive.com", "variant": "bare", "classification": "live-site"},
        {"domain": "redirect.com", "variant": "bare", "classification": "forwarder"},
        {"domain": "dead.com", "variant": "bare", "classification": "dead"},
        {"domain": "parked.com", "variant": "bare", "classification": "parked"},
    ]}
    assert _live_domains_from_snapshot(snap) == ["alive.com", "redirect.com"]


def test_live_domains_dedupes_bare_and_www():
    snap = {"results": [
        {"domain": "x.com", "variant": "bare", "classification": "live-site"},
        {"domain": "x.com", "variant": "www", "classification": "live-site"},
    ]}
    assert _live_domains_from_snapshot(snap) == ["x.com"]


# ---------- sort ----------


def test_sort_rows_impressions_desc():
    rows = [
        SEORow(domain="a", gsc_impressions=10),
        SEORow(domain="b", gsc_impressions=100),
        SEORow(domain="c", gsc_impressions=None),
    ]
    out = sort_rows(rows, "impressions")
    assert [r.domain for r in out] == ["b", "a", "c"]


def test_sort_rows_position_lower_first_none_last():
    rows = [
        SEORow(domain="a", gsc_position=20.0),
        SEORow(domain="b", gsc_position=5.0),
        SEORow(domain="c", gsc_position=None),
    ]
    out = sort_rows(rows, "position")
    assert [r.domain for r in out] == ["b", "a", "c"]


# ---------- snapshot-scope refresh logic ----------


def test_snapshot_refresh_decision():
    """`--seo --only=all` with a `wip`-scoped snapshot must force a refresh.
    `--only=wip` against `all`-scoped snapshot must NOT refresh."""
    from portfolio.cli import _seo_snapshot_needs_refresh

    # No snapshot at all → refresh whichever scope was asked for.
    assert _seo_snapshot_needs_refresh(None, "wip") is True
    assert _seo_snapshot_needs_refresh(None, "all") is True

    # all-scope requested: must have an all-scope snapshot.
    assert _seo_snapshot_needs_refresh("wip", "all") is True
    assert _seo_snapshot_needs_refresh("all", "all") is False

    # wip-scope requested: any existing snapshot is acceptable
    # (all-scope snapshot is a superset; we filter at read time).
    assert _seo_snapshot_needs_refresh("wip", "wip") is False
    assert _seo_snapshot_needs_refresh("all", "wip") is False

    # Unknown scope (snapshot file lacks `scope` field) → treat as
    # only-trustworthy-for-wip; refresh if all is requested.
    assert _seo_snapshot_needs_refresh("", "all") is True
    assert _seo_snapshot_needs_refresh("", "wip") is False
