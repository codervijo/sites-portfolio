"""Tests for v5.D live-runtime SEO checks (CHECK_090+).

Covers both the shared `_live.py` helpers and the per-check files.
Tests use httpx.MockTransport for deterministic HTTP behavior (same
pattern as tests/test_seo_runtime.py).
"""
from __future__ import annotations

import pytest

import httpx

from portfolio.checks.seo import _live
from portfolio.checks.seo._live import (
    JsonLdBlock,
    LiveFetchError,
    _derive_from_dirname,
    _extract_sitemap_locs,
    _parse_robots_sitemap_urls,
    _read_package_homepage,
    _scan_docs_for_url,
    clear_cache,
    fetch_html,
    fetch_response_status,
    get_sitemap_urls,
    iter_jsonld_nodes,
    node_type,
    parse_canonical,
    parse_jsonld_blocks,
    resolve_live_url,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Per-test cache reset so fetches don't bleed across cases."""
    clear_cache()
    yield
    clear_cache()


def _transport(handlers: dict) -> httpx.MockTransport:
    """Build a MockTransport keyed by full URL string."""
    def handler(request: httpx.Request) -> httpx.Response:
        key = str(request.url)
        if key in handlers:
            return handlers[key]
        return httpx.Response(404)
    return httpx.MockTransport(handler)


# ---------- resolve_live_url ----------


def test_read_package_homepage_returns_url(tmp_path):
    (tmp_path / "package.json").write_text('{"homepage": "https://x.test/"}')
    assert _read_package_homepage(str(tmp_path)) == "https://x.test"


def test_read_package_homepage_returns_none_when_missing(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert _read_package_homepage(str(tmp_path)) is None


def test_read_package_homepage_returns_none_when_invalid(tmp_path):
    (tmp_path / "package.json").write_text("not json")
    assert _read_package_homepage(str(tmp_path)) is None


def test_scan_docs_for_url_finds_live_line(tmp_path):
    (tmp_path / "README.md").write_text(
        "# x\n\nLive site: https://x.test/calculator\n"
    )
    assert _scan_docs_for_url(str(tmp_path)) == "https://x.test/calculator"


def test_scan_docs_for_url_skips_localhost_and_examples(tmp_path):
    (tmp_path / "README.md").write_text(
        "Live: https://example.com/\nLive: https://localhost:3000/\n"
    )
    assert _scan_docs_for_url(str(tmp_path)) is None


def test_derive_from_dirname_returns_https_when_looks_like_domain(tmp_path):
    site_dir = tmp_path / "washcalc.app"
    site_dir.mkdir()
    assert _derive_from_dirname(str(site_dir)) == "https://washcalc.app"


def test_derive_from_dirname_rejects_non_domain_name(tmp_path):
    site_dir = tmp_path / "portfolio"
    site_dir.mkdir()
    assert _derive_from_dirname(str(site_dir)) is None


def test_resolve_live_url_prefers_package_json(tmp_path):
    site = tmp_path / "washcalc.app"
    site.mkdir()
    (site / "package.json").write_text('{"homepage": "https://override.test/"}')
    assert resolve_live_url(str(site)) == "https://override.test"


def test_resolve_live_url_strips_to_origin(tmp_path):
    site = tmp_path / "x.test"
    site.mkdir()
    (site / "package.json").write_text(
        '{"homepage": "https://www.x.test/some/deep/path"}'
    )
    assert resolve_live_url(str(site)) == "https://www.x.test"


def test_resolve_live_url_falls_back_through_chain(tmp_path):
    """No package.json + no README → dir-name fallback."""
    site = tmp_path / "washcalc.app"
    site.mkdir()
    assert resolve_live_url(str(site)) == "https://washcalc.app"


def test_resolve_live_url_returns_none_when_no_signal(tmp_path):
    """Non-domain dirname + no docs → None."""
    site = tmp_path / "portfolio"
    site.mkdir()
    assert resolve_live_url(str(site)) is None


# ---------- fetch_html / fetch_response_status / cache ----------


def test_fetch_html_returns_body_with_googlebot_ua():
    seen_uas: list[str] = []
    def handler(request):
        seen_uas.append(request.headers.get("user-agent", ""))
        return httpx.Response(200, text="<html>ok</html>")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, follow_redirects=True,
                      headers={"User-Agent": _live.GOOGLEBOT_UA}) as client:
        body = fetch_html("https://x.test/", client=client)
    assert body == "<html>ok</html>"
    assert "Googlebot" in seen_uas[0]


def test_fetch_html_caches_within_process():
    """A second call for the same URL hits the cache (no second HTTP call)."""
    call_count = [0]
    def handler(request):
        call_count[0] += 1
        return httpx.Response(200, text="body")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        fetch_html("https://x.test/page", client=client)
        fetch_html("https://x.test/page", client=client)
    assert call_count[0] == 1


def test_fetch_html_raises_on_5xx():
    transport = _transport({"https://x.test/": httpx.Response(503)})
    with httpx.Client(transport=transport) as client:
        with pytest.raises(LiveFetchError, match="503"):
            fetch_html("https://x.test/", client=client)


def test_fetch_html_raises_on_4xx():
    """4xx responses raise — the wrapper distinguishes via
    fetch_response_status if the caller needs the actual code."""
    transport = _transport({"https://x.test/": httpx.Response(404)})
    with httpx.Client(transport=transport) as client:
        with pytest.raises(LiveFetchError, match="404"):
            fetch_html("https://x.test/", client=client)


def test_fetch_html_raises_on_connection_error():
    def handler(request):
        raise httpx.ConnectError("dns failed")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        with pytest.raises(LiveFetchError, match="ConnectError"):
            fetch_html("https://x.test/", client=client)


def test_fetch_response_status_returns_4xx_without_raising():
    transport = _transport({"https://x.test/missing": httpx.Response(404)})
    with httpx.Client(transport=transport) as client:
        assert fetch_response_status("https://x.test/missing", client=client) == 404


def test_fetch_response_status_raises_on_5xx():
    transport = _transport({"https://x.test/": httpx.Response(503)})
    with httpx.Client(transport=transport) as client:
        with pytest.raises(LiveFetchError, match="503"):
            fetch_response_status("https://x.test/", client=client)


def test_fetch_response_status_caches_200_body():
    """Status returned 200 → the body lands in the fetch cache, so a
    subsequent fetch_html call doesn't re-request."""
    call_count = [0]
    def handler(request):
        call_count[0] += 1
        return httpx.Response(200, text="cached body")
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        fetch_response_status("https://x.test/", client=client)
        body = fetch_html("https://x.test/", client=client)
    assert body == "cached body"
    assert call_count[0] == 1


# ---------- sitemap discovery ----------


def test_parse_robots_sitemap_urls():
    body = "User-agent: *\nDisallow:\nSitemap: https://x.test/sitemap.xml\n"
    assert _parse_robots_sitemap_urls(body) == ["https://x.test/sitemap.xml"]


def test_parse_robots_sitemap_urls_multiple_case_insensitive():
    body = (
        "User-agent: *\n"
        "sitemap: https://x.test/a.xml\n"
        "SITEMAP: https://x.test/b.xml\n"
    )
    assert _parse_robots_sitemap_urls(body) == [
        "https://x.test/a.xml", "https://x.test/b.xml",
    ]


def test_parse_robots_sitemap_urls_ignores_relative():
    body = "Sitemap: /relative.xml\nSitemap: https://x.test/ok.xml\n"
    assert _parse_robots_sitemap_urls(body) == ["https://x.test/ok.xml"]


def test_extract_sitemap_locs_urlset():
    xml = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x.test/a</loc></url>
  <url><loc>https://x.test/b</loc></url>
</urlset>"""
    urls, nested = _extract_sitemap_locs(xml)
    assert urls == ["https://x.test/a", "https://x.test/b"]
    assert nested == []


def test_extract_sitemap_locs_sitemapindex():
    xml = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://x.test/sitemap-pages.xml</loc></sitemap>
  <sitemap><loc>https://x.test/sitemap-blog.xml</loc></sitemap>
</sitemapindex>"""
    urls, nested = _extract_sitemap_locs(xml)
    assert urls == []
    assert nested == [
        "https://x.test/sitemap-pages.xml",
        "https://x.test/sitemap-blog.xml",
    ]


def test_extract_sitemap_locs_returns_empty_on_invalid_xml():
    urls, nested = _extract_sitemap_locs("not xml at all")
    assert urls == []
    assert nested == []


def test_get_sitemap_urls_via_robots_directive():
    """robots.txt declares Sitemap: <url>. Use it."""
    urlset = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.test/a</loc></url></urlset>'
    transport = _transport({
        "https://x.test/robots.txt": httpx.Response(
            200, text="Sitemap: https://x.test/sitemap-x.xml"),
        "https://x.test/sitemap-x.xml": httpx.Response(200, text=urlset),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        urls = get_sitemap_urls("https://x.test", client=client)
    assert urls == ["https://x.test/a"]


def test_get_sitemap_urls_fallback_to_default_path():
    """No robots.txt → fall back to /sitemap.xml."""
    urlset = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.test/a</loc></url><url><loc>https://x.test/b</loc></url></urlset>'
    transport = _transport({
        "https://x.test/sitemap.xml": httpx.Response(200, text=urlset),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        urls = get_sitemap_urls("https://x.test", client=client)
    assert urls == ["https://x.test/a", "https://x.test/b"]


def test_get_sitemap_urls_falls_back_to_index_path():
    urlset = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.test/p</loc></url></urlset>'
    transport = _transport({
        "https://x.test/sitemap-index.xml": httpx.Response(200, text=urlset),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        urls = get_sitemap_urls("https://x.test", client=client)
    assert urls == ["https://x.test/p"]


def test_get_sitemap_urls_recurses_into_sitemapindex():
    index = '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><sitemap><loc>https://x.test/sm-pages.xml</loc></sitemap></sitemapindex>'
    pages = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://x.test/page-1</loc></url></urlset>'
    transport = _transport({
        "https://x.test/sitemap.xml": httpx.Response(200, text=index),
        "https://x.test/sm-pages.xml": httpx.Response(200, text=pages),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        urls = get_sitemap_urls("https://x.test", client=client)
    assert urls == ["https://x.test/page-1"]


def test_get_sitemap_urls_raises_when_no_sitemap_reachable():
    transport = _transport({})  # everything 404s
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        with pytest.raises(LiveFetchError, match="no sitemap"):
            get_sitemap_urls("https://x.test", client=client)


def test_get_sitemap_urls_caps_at_limit():
    """The 50-URL cap is honored for the SITEMAP_URL_LIMIT default."""
    locs = "".join(f"<url><loc>https://x.test/u{i}</loc></url>"
                   for i in range(200))
    urlset = f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>'
    transport = _transport({
        "https://x.test/sitemap.xml": httpx.Response(200, text=urlset),
    })
    with httpx.Client(transport=transport, follow_redirects=True) as client:
        urls = get_sitemap_urls("https://x.test", client=client, limit=10)
    assert len(urls) == 10
    assert urls[0] == "https://x.test/u0"


# ---------- HTML parsing helpers ----------


def test_parse_jsonld_blocks_finds_each_script():
    html = """<html><head>
<script type="application/ld+json">{"@type":"WebSite"}</script>
<script type="application/ld+json">{"@type":"Organization"}</script>
</head><body/></html>"""
    blocks = parse_jsonld_blocks(html)
    assert len(blocks) == 2
    assert blocks[0].parsed == {"@type": "WebSite"}
    assert blocks[1].parsed == {"@type": "Organization"}
    assert all(b.error is None for b in blocks)


def test_parse_jsonld_blocks_records_parse_error():
    html = '<script type="application/ld+json">not json</script>'
    blocks = parse_jsonld_blocks(html)
    assert len(blocks) == 1
    assert blocks[0].parsed is None
    assert blocks[0].error is not None


def test_parse_jsonld_blocks_ignores_other_script_types():
    html = """<script>var x = 1;</script>
<script type="application/javascript">{}</script>
<script type="application/ld+json">{"@type":"X"}</script>"""
    blocks = parse_jsonld_blocks(html)
    assert len(blocks) == 1


def test_parse_jsonld_blocks_handles_singleline_html():
    """Prerendered HTML is often on one line — must parse anyway."""
    html = '<html><head><script type="application/ld+json">{"@type":"WebApplication","url":"https://x.test/"}</script></head><body></body></html>'
    blocks = parse_jsonld_blocks(html)
    assert len(blocks) == 1
    assert blocks[0].parsed["url"] == "https://x.test/"


def test_parse_canonical_returns_href():
    html = '<head><link rel="canonical" href="https://x.test/page" /></head>'
    assert parse_canonical(html) == "https://x.test/page"


def test_parse_canonical_returns_none_when_missing():
    assert parse_canonical("<head></head>") is None


def test_parse_canonical_strips_whitespace():
    html = '<link rel="canonical" href="  https://x.test/  " />'
    assert parse_canonical(html) == "https://x.test/"


def test_iter_jsonld_nodes_walks_graph():
    obj = {
        "@graph": [
            {"@type": "Organization"},
            {"@type": "WebSite"},
        ]
    }
    types = [node_type(n) for n in iter_jsonld_nodes(obj)]
    # First yield is the wrapper (no @type), then each @graph child.
    flat = [t for sub in types for t in sub]
    assert "Organization" in flat
    assert "WebSite" in flat


def test_node_type_handles_string_and_list():
    assert node_type({"@type": "Organization"}) == ["Organization"]
    assert node_type({"@type": ["Organization", "WebSite"]}) == [
        "Organization", "WebSite"
    ]
    assert node_type({}) == []


# ---------- CHECK_090 — live-sitemap-fetches ----------


def test_check_090_skipped_when_not_web_project(tmp_path):
    from portfolio.checks.seo.check_090_live_sitemap_fetches import run
    # No package.json → not a web project.
    r = run(str(tmp_path))
    assert r.status == "warn"


def test_check_090_skipped_when_no_live_url(tmp_path):
    from portfolio.checks.seo.check_090_live_sitemap_fetches import run
    # Has package.json but no homepage + non-domain dirname + no docs.
    site = tmp_path / "portfolio"
    site.mkdir()
    (site / "package.json").write_text("{}")
    r = run(str(site))
    assert r.status == "warn"
    assert "no live URL" in r.message


def test_check_090_pass_when_all_urls_return_200(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_090_live_sitemap_fetches import run
    site = tmp_path / "x.test"
    site.mkdir()
    (site / "package.json").write_text('{"homepage": "https://x.test/"}')
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.get_sitemap_urls",
        lambda origin: ["https://x.test/a", "https://x.test/b"],
    )
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.fetch_response_status",
        lambda url: 200,
    )
    r = run(str(site))
    assert r.status == "pass"
    assert "2 sitemap URL(s)" in r.message


def test_check_090_fail_when_a_url_404s(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_090_live_sitemap_fetches import run
    site = tmp_path / "x.test"
    site.mkdir()
    (site / "package.json").write_text('{"homepage": "https://x.test/"}')
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.get_sitemap_urls",
        lambda origin: ["https://x.test/ok", "https://x.test/bad"],
    )
    statuses = {"https://x.test/ok": 200, "https://x.test/bad": 404}
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.fetch_response_status",
        lambda url: statuses[url],
    )
    r = run(str(site))
    assert r.status == "fail"
    assert "https://x.test/bad → 404" in r.message


def test_check_090_warn_on_sitemap_unreachable(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_090_live_sitemap_fetches import run
    site = tmp_path / "x.test"
    site.mkdir()
    (site / "package.json").write_text('{"homepage": "https://x.test/"}')
    def _explode(origin):
        raise LiveFetchError("network down")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.get_sitemap_urls",
        _explode,
    )
    r = run(str(site))
    assert r.status == "warn"
    assert "sitemap unreachable" in r.message


def test_check_090_warn_when_every_url_unreachable(tmp_path, monkeypatch):
    """All URLs fail at the network layer → warn (likely flaky CI),
    not fail (would be a site bug)."""
    from portfolio.checks.seo.check_090_live_sitemap_fetches import run
    site = tmp_path / "x.test"
    site.mkdir()
    (site / "package.json").write_text('{"homepage": "https://x.test/"}')
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.get_sitemap_urls",
        lambda origin: ["https://x.test/a", "https://x.test/b"],
    )
    def _explode(url):
        raise LiveFetchError("connection reset")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_090_live_sitemap_fetches.fetch_response_status",
        _explode,
    )
    r = run(str(site))
    assert r.status == "warn"
    assert "all 2 sitemap URL(s) unreachable" in r.message
