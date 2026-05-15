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


# ---------- CHECK_091 — live-jsonld-parses ----------


def _stub_check_091(monkeypatch, *, urls, htmls):
    """Patch get_sitemap_urls + fetch_html for CHECK_091's run()."""
    monkeypatch.setattr(
        "portfolio.checks.seo.check_091_live_jsonld_parses.get_sitemap_urls",
        lambda origin: urls,
    )
    def _fetch(url):
        if url in htmls:
            return htmls[url]
        raise LiveFetchError(f"no stub for {url}")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_091_live_jsonld_parses.fetch_html",
        _fetch,
    )


def _site_with_homepage(tmp_path, name="x.test", homepage="https://x.test/"):
    site = tmp_path / name
    site.mkdir()
    (site / "package.json").write_text(f'{{"homepage": "{homepage}"}}')
    return site


def test_check_091_skipped_when_not_web_project(tmp_path):
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    r = run(str(tmp_path))
    assert r.status == "warn"


def test_check_091_skipped_when_no_live_url(tmp_path):
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    site = tmp_path / "portfolio"
    site.mkdir()
    (site / "package.json").write_text("{}")
    r = run(str(site))
    assert r.status == "warn"
    assert "no live URL" in r.message


def test_check_091_passes_when_all_blocks_parse(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    site = _site_with_homepage(tmp_path)
    valid_html = (
        '<head><script type="application/ld+json">'
        '{"@type":"WebSite","url":"https://x.test/"}'
        '</script></head>'
    )
    _stub_check_091(
        monkeypatch,
        urls=["https://x.test/a", "https://x.test/b"],
        htmls={"https://x.test/a": valid_html, "https://x.test/b": valid_html},
    )
    r = run(str(site))
    assert r.status == "pass"
    assert "2 JSON-LD block(s)" in r.message


def test_check_091_fails_when_a_block_doesnt_parse(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    site = _site_with_homepage(tmp_path)
    bad_html = '<script type="application/ld+json">not json at all</script>'
    _stub_check_091(
        monkeypatch,
        urls=["https://x.test/broken"],
        htmls={"https://x.test/broken": bad_html},
    )
    r = run(str(site))
    assert r.status == "fail"
    assert "https://x.test/broken" in r.message


def test_check_091_pass_when_no_blocks_anywhere(tmp_path, monkeypatch):
    """No JSON-LD on any page → not a CHECK_091 failure (CHECK_078
    covers `has-json-ld`)."""
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    site = _site_with_homepage(tmp_path)
    _stub_check_091(
        monkeypatch,
        urls=["https://x.test/"],
        htmls={"https://x.test/": "<html><head></head><body/></html>"},
    )
    r = run(str(site))
    assert r.status == "pass"


def test_check_091_warn_when_every_url_unreachable(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    site = _site_with_homepage(tmp_path)
    monkeypatch.setattr(
        "portfolio.checks.seo.check_091_live_jsonld_parses.get_sitemap_urls",
        lambda origin: ["https://x.test/a"],
    )
    def _explode(url):
        raise LiveFetchError("net")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_091_live_jsonld_parses.fetch_html",
        _explode,
    )
    r = run(str(site))
    assert r.status == "warn"


def test_check_091_reports_per_url_block_index(tmp_path, monkeypatch):
    """Failure message names the URL + which block (#1, #2) failed."""
    from portfolio.checks.seo.check_091_live_jsonld_parses import run
    site = _site_with_homepage(tmp_path)
    # Two blocks on one page — only the second is broken.
    html = (
        '<script type="application/ld+json">{"@type":"WebSite"}</script>'
        '<script type="application/ld+json">{broken}</script>'
    )
    _stub_check_091(
        monkeypatch,
        urls=["https://x.test/page"],
        htmls={"https://x.test/page": html},
    )
    r = run(str(site))
    assert r.status == "fail"
    assert "https://x.test/page#2" in r.message


# ---------- CHECK_092 — live-jsonld-url-matches-canonical ----------


def _stub_check_092(monkeypatch, *, urls, htmls):
    monkeypatch.setattr(
        "portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical.get_sitemap_urls",
        lambda origin: urls,
    )
    def _fetch(url):
        if url in htmls:
            return htmls[url]
        raise LiveFetchError(f"no stub for {url}")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical.fetch_html",
        _fetch,
    )


def _page_with_canonical_and_jsonld(canonical: str, jsonld_url: str,
                                    jsonld_type: str = "WebApplication") -> str:
    return (
        '<html><head>'
        f'<link rel="canonical" href="{canonical}" />'
        '<script type="application/ld+json">'
        f'{{"@type":"{jsonld_type}","url":"{jsonld_url}"}}'
        '</script>'
        '</head><body/></html>'
    )


def test_check_092_passes_when_url_matches_canonical(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    canonical = "https://x.test/page"
    html = _page_with_canonical_and_jsonld(canonical, canonical)
    _stub_check_092(monkeypatch,
                    urls=["https://x.test/page"],
                    htmls={"https://x.test/page": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_092_catches_washcalc_regression(tmp_path, monkeypatch):
    """The exact bug from washcalc.app's audit:
       canonical = https://www.washcalc.app/calculators/driveway
       JSON-LD url = https://www.washcalc.app/ (homepage)
    Different paths → FAIL."""
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    page_url = "https://www.washcalc.app/calculators/driveway"
    html = _page_with_canonical_and_jsonld(
        canonical="https://www.washcalc.app/calculators/driveway",
        jsonld_url="https://www.washcalc.app/",
        jsonld_type="WebApplication",
    )
    _stub_check_092(monkeypatch, urls=[page_url], htmls={page_url: html})
    r = run(str(site))
    assert r.status == "fail"
    assert "WebApplication" in r.message
    assert "https://www.washcalc.app/" in r.message       # the wrong url
    assert "calculators/driveway" in r.message            # the canonical


def test_check_092_normalizes_trailing_slash():
    """A trailing slash on deeper paths is ignored; URLs that only
    differ in a trailing slash count as matching."""
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import (
        _normalize_url,
    )
    assert _normalize_url("https://x.test/page/") == _normalize_url("https://x.test/page")
    # Root slash kept (origin form).
    assert _normalize_url("https://x.test/") == "https://x.test/"


def test_check_092_lowercases_scheme_and_host():
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import (
        _normalize_url,
    )
    assert (_normalize_url("HTTPS://X.TEST/PAGE")
            == _normalize_url("https://x.test/PAGE"))


def test_check_092_skips_nodes_outside_page_level_types(tmp_path, monkeypatch):
    """A BreadcrumbList item's `url`/`item` should NOT be checked
    against canonical — those are navigation links."""
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    # Canonical doesn't match the breadcrumb item URLs — but the check
    # shouldn't fire on those.
    html = (
        '<head>'
        '<link rel="canonical" href="https://x.test/products/widget" />'
        '<script type="application/ld+json">'
        '{"@type":"BreadcrumbList","itemListElement":['
        '{"@type":"ListItem","position":1,"name":"Home","item":"https://x.test/"},'
        '{"@type":"ListItem","position":2,"name":"Products","item":"https://x.test/products"}'
        ']}'
        '</script>'
        '</head><body/>'
    )
    _stub_check_092(monkeypatch,
                    urls=["https://x.test/products/widget"],
                    htmls={"https://x.test/products/widget": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_092_fires_on_softwareapplication(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    html = _page_with_canonical_and_jsonld(
        canonical="https://x.test/calc",
        jsonld_url="https://x.test/",
        jsonld_type="SoftwareApplication",
    )
    _stub_check_092(monkeypatch, urls=["https://x.test/calc"],
                    htmls={"https://x.test/calc": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "SoftwareApplication" in r.message


def test_check_092_pass_when_no_canonical(tmp_path, monkeypatch):
    """No canonical → nothing to compare against → pass.
    (Missing canonical is CHECK_072's territory.)"""
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    html = (
        '<head>'
        '<script type="application/ld+json">{"@type":"WebApplication","url":"https://x.test/anywhere"}</script>'
        '</head><body/>'
    )
    _stub_check_092(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_092_pass_when_no_page_level_url_field(tmp_path, monkeypatch):
    """A page-level node without a `url` field → pass."""
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    html = (
        '<head>'
        '<link rel="canonical" href="https://x.test/p" />'
        '<script type="application/ld+json">{"@type":"WebPage","name":"X"}</script>'
        '</head><body/>'
    )
    _stub_check_092(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_092_walks_into_graph(tmp_path, monkeypatch):
    """@graph wrapped JSON-LD: nodes inside the graph are inspected."""
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    html = (
        '<head>'
        '<link rel="canonical" href="https://x.test/calc" />'
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@graph":['
        '{"@type":"Organization","name":"X"},'
        '{"@type":"WebApplication","url":"https://x.test/"}'
        ']}'
        '</script>'
        '</head><body/>'
    )
    _stub_check_092(monkeypatch, urls=["https://x.test/calc"],
                    htmls={"https://x.test/calc": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "WebApplication" in r.message


def test_check_092_multiple_mismatches_reported(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    bad1 = _page_with_canonical_and_jsonld(
        "https://x.test/a", "https://x.test/", "WebApplication")
    bad2 = _page_with_canonical_and_jsonld(
        "https://x.test/b", "https://x.test/", "SoftwareApplication")
    _stub_check_092(monkeypatch,
                    urls=["https://x.test/a", "https://x.test/b"],
                    htmls={"https://x.test/a": bad1, "https://x.test/b": bad2})
    r = run(str(site))
    assert r.status == "fail"
    assert "2 mismatch(es)" in r.message


def test_check_092_warn_when_every_url_unreachable(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical import run
    site = _site_with_homepage(tmp_path)
    monkeypatch.setattr(
        "portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical.get_sitemap_urls",
        lambda origin: ["https://x.test/a"],
    )
    def _explode(url):
        raise LiveFetchError("net")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_092_live_jsonld_url_matches_canonical.fetch_html",
        _explode,
    )
    r = run(str(site))
    assert r.status == "warn"


# ---------- CHECK_093 — live-faqpage-shape ----------


def _stub_check_093(monkeypatch, *, urls, htmls):
    monkeypatch.setattr(
        "portfolio.checks.seo.check_093_live_faqpage_shape.get_sitemap_urls",
        lambda origin: urls,
    )
    def _fetch(url):
        if url in htmls:
            return htmls[url]
        raise LiveFetchError(f"no stub for {url}")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_093_live_faqpage_shape.fetch_html",
        _fetch,
    )


def _faqpage_html(faqpage_obj: dict) -> str:
    import json as _json
    return (
        '<head><script type="application/ld+json">'
        + _json.dumps(faqpage_obj)
        + '</script></head><body/>'
    )


def test_check_093_pass_when_faqpage_well_formed(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": "Q1?",
             "acceptedAnswer": {"@type": "Answer", "text": "A1"}},
            {"@type": "Question", "name": "Q2?",
             "acceptedAnswer": {"@type": "Answer", "text": "A2"}},
        ],
    })
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"
    assert "1 FAQPage block(s)" in r.message


def test_check_093_pass_when_no_faqpage_anywhere(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = (
        '<head><script type="application/ld+json">'
        '{"@type":"WebApplication"}</script></head><body/>'
    )
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"
    assert "no FAQPage" in r.message


def test_check_093_fails_when_main_entity_empty(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({"@type": "FAQPage", "mainEntity": []})
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "mainEntity missing or empty" in r.message


def test_check_093_fails_when_main_entity_missing(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({"@type": "FAQPage"})
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"


def test_check_093_fails_when_question_has_no_answer(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": "Q1?",
             "acceptedAnswer": {"@type": "Answer", "text": "A1"}},
            {"@type": "Question", "name": "Q2 missing answer?"},
        ],
    })
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "Q2 missing answer" in r.message
    assert "no acceptedAnswer" in r.message


def test_check_093_fails_when_answer_text_empty(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": "Q?",
             "acceptedAnswer": {"@type": "Answer", "text": "   "}},
        ],
    })
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "empty acceptedAnswer.text" in r.message


def test_check_093_fails_when_question_has_no_name(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question",
             "acceptedAnswer": {"@type": "Answer", "text": "A"}},
        ],
    })
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "has no `name`" in r.message


def test_check_093_fails_when_item_is_not_question(tmp_path, monkeypatch):
    """mainEntity[] should contain Questions; anything else is a shape bug."""
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Thing", "name": "wrong"},
        ],
    })
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "expected Question" in r.message


def test_check_093_walks_graph(tmp_path, monkeypatch):
    """FAQPage nested inside @graph is still inspected."""
    from portfolio.checks.seo.check_093_live_faqpage_shape import run
    site = _site_with_homepage(tmp_path)
    html = _faqpage_html({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebApplication"},
            {"@type": "FAQPage", "mainEntity": []},
        ],
    })
    _stub_check_093(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"


# ---------- CHECK_094 — live-breadcrumblist-shape ----------


def _stub_check_094(monkeypatch, *, urls, htmls):
    monkeypatch.setattr(
        "portfolio.checks.seo.check_094_live_breadcrumblist_shape.get_sitemap_urls",
        lambda origin: urls,
    )
    def _fetch(url):
        if url in htmls:
            return htmls[url]
        raise LiveFetchError(f"no stub for {url}")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_094_live_breadcrumblist_shape.fetch_html",
        _fetch,
    )


def _breadcrumb_html(obj: dict) -> str:
    import json as _json
    return (
        '<head><script type="application/ld+json">'
        + _json.dumps(obj)
        + '</script></head><body/>'
    )


def _good_breadcrumb(*items: tuple[int, str, str]) -> dict:
    """items is a tuple of (position, name, url)."""
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": p, "name": n, "item": u}
            for p, n, u in items
        ],
    }


def test_check_094_pass_when_well_formed(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html(_good_breadcrumb(
        (1, "Home", "https://x.test/"),
        (2, "Products", "https://x.test/products"),
        (3, "Widget", "https://x.test/products/widget"),
    ))
    _stub_check_094(monkeypatch, urls=["https://x.test/products/widget"],
                    htmls={"https://x.test/products/widget": html})
    r = run(str(site))
    assert r.status == "pass"
    assert "1 BreadcrumbList" in r.message


def test_check_094_pass_when_no_breadcrumblist_anywhere(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = '<head><script type="application/ld+json">{"@type":"WebApplication"}</script></head><body/>'
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"
    assert "no BreadcrumbList" in r.message


def test_check_094_fails_when_itemlist_empty(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html({"@type": "BreadcrumbList", "itemListElement": []})
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "itemListElement missing or empty" in r.message


def test_check_094_fails_when_positions_not_sequential(tmp_path, monkeypatch):
    """Positions 1, 2, 4 (skipping 3) → not sequential → fail."""
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html(_good_breadcrumb(
        (1, "A", "https://x.test/a"),
        (2, "B", "https://x.test/b"),
        (4, "D", "https://x.test/d"),
    ))
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "not sequential" in r.message


def test_check_094_fails_when_positions_start_at_zero(tmp_path, monkeypatch):
    """Positions 0, 1, 2 — must start at 1 per BreadcrumbList convention."""
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html(_good_breadcrumb(
        (0, "Home", "https://x.test/"),
        (1, "Products", "https://x.test/products"),
    ))
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"


def test_check_094_fails_when_item_missing_name(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html({
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "item": "https://x.test/"},
        ],
    })
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "missing/empty `name`" in r.message


def test_check_094_fails_when_item_missing_url(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html({
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home"},
        ],
    })
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "missing/empty `item`" in r.message


def test_check_094_fails_when_position_is_string(tmp_path, monkeypatch):
    """Position must be an integer — `"1"` string fails."""
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html({
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": "1", "name": "Home", "item": "https://x.test/"},
        ],
    })
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "non-integer position" in r.message


def test_check_094_fails_when_listitem_type_missing(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html({
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"position": 1, "name": "Home", "item": "https://x.test/"},
        ],
    })
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "expected ListItem" in r.message


def test_check_094_walks_graph(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_094_live_breadcrumblist_shape import run
    site = _site_with_homepage(tmp_path)
    html = _breadcrumb_html({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebApplication"},
            {"@type": "BreadcrumbList", "itemListElement": []},
        ],
    })
    _stub_check_094(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"


# ---------- CHECK_095 — live-faq-answers-in-html ----------


def _stub_check_095(monkeypatch, *, urls, htmls):
    monkeypatch.setattr(
        "portfolio.checks.seo.check_095_live_faq_answers_in_html.get_sitemap_urls",
        lambda origin: urls,
    )
    def _fetch(url):
        if url in htmls:
            return htmls[url]
        raise LiveFetchError(f"no stub for {url}")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_095_live_faq_answers_in_html.fetch_html",
        _fetch,
    )


def _page_with_faqs(faqs: list[tuple[str, str]], body_answers: list[str]) -> str:
    """Build a page with FAQPage JSON-LD listing `faqs` and a body
    containing each string in `body_answers`."""
    import json as _json
    faq_obj = {
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in faqs
        ],
    }
    body_text = "<br />\n".join(body_answers)
    return (
        '<html><head><script type="application/ld+json">'
        + _json.dumps(faq_obj)
        + '</script></head><body><div class="content">'
        + body_text
        + '</div></body></html>'
    )


def test_check_095_pass_when_all_answers_in_body(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    answer = "Most pros charge $0.20–$0.25 per square foot. A typical driveway lands $160–$250."
    html = _page_with_faqs(
        faqs=[("How much per sq ft?", answer)],
        body_answers=[answer],
    )
    _stub_check_095(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_095_pass_when_no_faqpage_at_all(tmp_path, monkeypatch):
    """No FAQPage block → nothing to check → pass."""
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    html = '<head><script type="application/ld+json">{"@type":"WebApplication"}</script></head><body>x</body>'
    _stub_check_095(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_095_fails_when_answer_only_in_jsonld(tmp_path, monkeypatch):
    """The exact washcalc accordion case: 5 Qs in JSON-LD, only 1
    rendered in body (closed accordions hidden)."""
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    answers = [
        "Most pros charge $0.20 per square foot for a standard residential job.",
        "Heavy soiling adds about thirty percent to typical labor time totals.",
        "Hot water and chemicals can reduce per-job time on tough stains.",
        "Soft wash is required for older siding to avoid surface damage.",
        "A standard two-story home takes around two to three hours to wash.",
    ]
    faqs = [(f"Q{i}?", a) for i, a in enumerate(answers, 1)]
    # Only answer #1 is rendered in body — the rest are hidden in closed
    # accordions and therefore absent from the SSR HTML.
    html = _page_with_faqs(faqs=faqs, body_answers=[answers[0]])
    _stub_check_095(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"
    assert "4 FAQ answer(s)" in r.message
    # Should name the questions that are missing.
    assert "Q2" in r.message or "Q3" in r.message


def test_check_095_strips_script_tags_before_searching(tmp_path, monkeypatch):
    """The answer text in JSON-LD must not satisfy the body-presence
    check — script content is stripped first."""
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    answer = "This text only exists inside JSON-LD and nowhere else on the page body."
    # The body has NO matching text — only the JSON-LD script does.
    html = _page_with_faqs(
        faqs=[("Q?", answer)],
        body_answers=["totally unrelated body content here"],
    )
    _stub_check_095(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "fail"


def test_check_095_tolerates_minor_whitespace_differences(tmp_path, monkeypatch):
    """Body wraps the answer differently from the JSON-LD source — the
    signature match should still succeed."""
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    answer = "Most pros charge $0.20 per square foot for a standard driveway."
    body_with_wrap = (
        "<p>Most pros</p><p>charge $0.20 per square foot</p>"
        "<span>for a standard driveway.</span>"
    )
    html = _page_with_faqs(faqs=[("Q?", answer)], body_answers=[body_with_wrap])
    _stub_check_095(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_095_skips_too_short_answers(tmp_path, monkeypatch):
    """A 1-word answer ("Yes.") is too short for a meaningful signature
    — skip rather than risk a false-positive match against boilerplate."""
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    html = _page_with_faqs(
        faqs=[("Is it free?", "Yes.")],
        body_answers=["totally unrelated body content here"],
    )
    _stub_check_095(monkeypatch, urls=["https://x.test/p"],
                    htmls={"https://x.test/p": html})
    r = run(str(site))
    assert r.status == "pass"


def test_check_095_warn_when_every_url_unreachable(tmp_path, monkeypatch):
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import run
    site = _site_with_homepage(tmp_path)
    monkeypatch.setattr(
        "portfolio.checks.seo.check_095_live_faq_answers_in_html.get_sitemap_urls",
        lambda origin: ["https://x.test/a"],
    )
    def _explode(url):
        raise LiveFetchError("net")
    monkeypatch.setattr(
        "portfolio.checks.seo.check_095_live_faq_answers_in_html.fetch_html",
        _explode,
    )
    r = run(str(site))
    assert r.status == "warn"


def test_signature_takes_first_n_words():
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import (
        _signature, SIGNATURE_WORDS,
    )
    text = " ".join(f"word{i}" for i in range(20))
    sig = _signature(text)
    assert len(sig.split()) == SIGNATURE_WORDS


def test_signature_lowercase():
    from portfolio.checks.seo.check_095_live_faq_answers_in_html import _signature
    assert _signature("Hello World") == "hello world"
