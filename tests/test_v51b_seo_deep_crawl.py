"""v51.B — `seo_deep` crawl probe + link graph (raw HTML, no network)."""
from __future__ import annotations

import httpx
import pytest

from portfolio.seo_deep import (
    crawl_site,
    parse_robots,
    probe_url,
    url_key,
    RobotsRules,
)

O = "https://s.com"


def _client(routes: dict[str, httpx.Response]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))
    return httpx.Client(transport=httpx.MockTransport(handler))


def _html(body: str = "", *, title: str = "T", head: str = "",
          text: str = "x" * 60) -> httpx.Response:
    return httpx.Response(
        200, headers={"content-type": "text/html"},
        text=f"<html><head><title>{title}</title>{head}</head>"
             f"<body><p>{text}</p>{body}</body></html>")


ALLOW_ALL = RobotsRules(status=404)


# ---------- url_key ----------

def test_url_key_folds_slash_www_fragment_index():
    assert url_key("https://www.S.com/a/") == url_key("https://s.com/a")
    assert url_key("https://s.com/a#x") == "https://s.com/a"
    assert url_key("https://s.com/a/index.html") == "https://s.com/a"
    assert url_key("https://s.com") == url_key("https://s.com/") == "https://s.com/"
    assert url_key("https://s.com/a?q=1") != url_key("https://s.com/a")


# ---------- robots (Google semantics) ----------

def test_robots_longest_match_wins_and_allow_wins_tie():
    r = parse_robots("User-agent: *\nDisallow: /a\nAllow: /a/b\nDisallow: /c\nAllow: /c\n")
    assert r.check(O + "/a/x")[0] is False
    assert r.check(O + "/a/b/x") == (True, "Allow: /a/b")
    assert r.check(O + "/c")[0] is True            # tie → Allow
    assert r.check(O + "/z") == (True, None)


def test_robots_googlebot_group_overrides_star():
    r = parse_robots("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nDisallow: /private\n")
    assert r.group == "googlebot"
    assert r.check(O + "/calc")[0] is True
    assert r.check(O + "/private/x")[0] is False


def test_robots_wildcards_and_anchor():
    r = parse_robots("User-agent: *\nDisallow: /*.json$\nDisallow: /api/\n")
    assert r.check(O + "/data.json")[0] is False
    assert r.check(O + "/data.json?x=1")[0] is True
    assert r.check(O + "/api/v1")[0] is False


def test_robots_empty_disallow_and_status_semantics():
    assert parse_robots("User-agent: *\nDisallow:\n").check(O + "/x")[0] is True
    assert RobotsRules(status=404).check(O + "/x")[0] is True
    assert RobotsRules(status=503).check(O + "/x")[0] is False
    assert RobotsRules(status=None).check(O + "/x")[0] is False


def test_robots_grouped_user_agents_share_rules():
    r = parse_robots("User-agent: bingbot\nUser-agent: *\nDisallow: /x\n")
    assert r.check(O + "/x")[0] is False


# ---------- probe_url ----------

def test_probe_records_redirect_chain_and_final():
    c = _client({
        O + "/a": httpx.Response(301, headers={"location": "/a/"}),
        O + "/a/": httpx.Response(308, headers={"location": O + "/b"}),
        O + "/b": _html(head=f'<link rel="canonical" href="{O}/b">'),
    })
    p = probe_url(O + "/a", origin=O, robots=ALLOW_ALL, client=c)
    assert [h.status for h in p.redirects] == [301, 308]
    assert p.status == 200 and p.final_url == O + "/b"
    assert p.canonical_kind == "self"


def test_probe_redirect_loop_is_an_error_not_a_hang():
    c = _client({
        O + "/a": httpx.Response(302, headers={"location": "/b"}),
        O + "/b": httpx.Response(302, headers={"location": "/a"}),
    })
    p = probe_url(O + "/a", origin=O, robots=ALLOW_ALL, client=c)
    assert p.error == "redirect loop"


def test_probe_transport_error_lands_in_error():
    def boom(request):
        raise httpx.ConnectError("nope")
    c = httpx.Client(transport=httpx.MockTransport(boom))
    p = probe_url(O + "/a", origin=O, robots=ALLOW_ALL, client=c)
    assert p.error == "ConnectError" and not p.ok


@pytest.mark.parametrize("head,kind", [
    ("", "missing"),
    ('<link rel="canonical" href="/p">', "self"),
    ('<link rel="canonical" href="/p/">', "variant"),
    ('<link rel="canonical" href="/other">', "other"),
    ('<link rel="canonical" href="https://www.s.com/p">', "host_mismatch"),
    ('<link rel="canonical" href="https://else.com/p">', "cross_site"),
    ('<link rel="canonical" href="/p"><link rel="canonical" href="/q">', "multiple"),
])
def test_canonical_kinds(head, kind):
    c = _client({O + "/p": _html(head=head)})
    assert probe_url(O + "/p", origin=O, robots=ALLOW_ALL, client=c).canonical_kind == kind


def test_noindex_meta_and_header_and_scoped_header():
    c = _client({
        O + "/m": _html(head='<meta name="robots" content="index, NOINDEX">'),
        O + "/h": httpx.Response(200, headers={"content-type": "text/html",
                                               "x-robots-tag": "noindex"}, text="<p>x</p>"),
        O + "/g": httpx.Response(200, headers={"content-type": "text/html",
                                               "x-robots-tag": "googlebot: none"}, text="<p>x</p>"),
        O + "/b": httpx.Response(200, headers={"content-type": "text/html",
                                               "x-robots-tag": "bingbot: noindex"}, text="<p>x</p>"),
        O + "/u": httpx.Response(200, headers={"content-type": "text/html",
                                               "x-robots-tag": "unavailable_after: 2030-01-01"},
                                 text="<p>x</p>"),
    })
    get = lambda path: probe_url(O + path, origin=O, robots=ALLOW_ALL, client=c)
    assert (get("/m").noindex, get("/m").noindex_source) == (True, "meta")
    assert (get("/h").noindex, get("/h").noindex_source) == (True, "header")
    assert get("/g").noindex is True
    assert get("/b").noindex is False
    assert get("/u").noindex is False


def test_empty_shell_vs_server_rendered():
    c = _client({
        O + "/spa": httpx.Response(200, headers={"content-type": "text/html"},
                                   text='<html><head><title>X</title></head><body>'
                                        '<div id="root"></div><script>big()</script></body></html>'),
        O + "/ssr": _html(),
    })
    spa = probe_url(O + "/spa", origin=O, robots=ALLOW_ALL, client=c)
    ssr = probe_url(O + "/ssr", origin=O, robots=ALLOW_ALL, client=c)
    assert spa.empty_shell and spa.body_chars == 0
    assert not ssr.empty_shell and ssr.has_title


def test_links_followable_same_site_only():
    body = ('<a href="/a">a</a><a href="/a#frag">dup</a><a href="https://www.s.com/b">b</a>'
            '<a href="https://ext.com/x">ext</a><a href="mailto:x@s.com">m</a>'
            '<a href="/n" rel="nofollow">n</a><a href="#top">top</a><a href="tel:1">t</a>')
    c = _client({O + "/": _html(body)})
    p = probe_url(O + "/", origin=O, robots=ALLOW_ALL, client=c)
    assert [url_key(u) for u in p.internal_links] == [O + "/a", O + "/b"]
    assert p.nofollow_links == 1


def test_robots_verdict_attached_to_probe():
    robots = parse_robots("User-agent: *\nDisallow: /api/\n")
    c = _client({O + "/api/x": _html()})
    p = probe_url(O + "/api/x", origin=O, robots=robots, client=c)
    assert p.robots_allowed is False and p.robots_rule == "Disallow: /api/"


# ---------- crawl_site / link graph ----------

def _site() -> dict[str, httpx.Response]:
    return {
        O + "/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
        O + "/": _html('<a href="/hub">hub</a><a href="/old">old</a>'),
        O + "/hub": _html('<a href="/c1">1</a><a href="/c2">2</a><a href="/extra">x</a>'),
        O + "/c1": _html('<a href="/hub">up</a>'),
        O + "/c2": _html(),
        O + "/orphan": _html('<a href="/island">i</a>'),
        O + "/island": _html(),
        O + "/extra": _html(),
        O + "/old": httpx.Response(301, headers={"location": "/c2"}),
    }


SITEMAP = [O + "/", O + "/hub", O + "/c1", O + "/c2", O + "/orphan", O + "/island"]


def test_crawl_graph_depth_orphans_and_unlisted():
    r = crawl_site(O, client=_client(_site()), sitemap_urls=SITEMAP, workers=1)
    assert r.depth_of(O + "/") == 0
    assert r.depth_of(O + "/hub") == 1
    assert r.depth_of(O + "/c1") == 2
    assert r.depth_of(O + "/c2") == 1             # / → /old (301) → /c2
    assert r.orphans == [O + "/orphan"]
    # /island has an inbound link but only from an unreachable page.
    assert r.inbound_count(O + "/island") == 1
    assert set(r.unreachable_from_home) == {O + "/orphan", O + "/island"}
    assert r.linked_not_in_sitemap == [O + "/extra"]
    assert not r.crawl_capped


def test_link_through_redirect_counts_for_target():
    r = crawl_site(O, client=_client(_site()), sitemap_urls=SITEMAP, workers=1)
    # /c2 is linked by /hub and by / (through /old → /c2).
    assert r.inbound_count(O + "/c2") == 2


def test_crawl_cap_is_reported():
    r = crawl_site(O, client=_client(_site()), sitemap_urls=SITEMAP,
                   page_cap=3, workers=1)
    assert r.crawl_capped and len(r.probes) == 3


def test_crawl_discovers_sitemap_when_not_given():
    routes = _site()
    routes[O + "/robots.txt"] = httpx.Response(
        200, text=f"User-agent: *\nAllow: /\nSitemap: {O}/sitemap.xml\n")
    routes[O + "/sitemap.xml"] = httpx.Response(200, text=(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{u}</loc></url>" for u in SITEMAP) + "</urlset>"))
    c = httpx.Client(transport=_client(routes)._transport, follow_redirects=True)
    r = crawl_site(O, client=c, workers=1)
    assert r.sitemap_url == O + "/sitemap.xml"
    assert r.sitemap_urls == SITEMAP
    assert r.probes[url_key(O + "/old")].redirects   # manual hops recorded even on a follow client


def test_progress_callback_fires_per_page():
    seen = []
    crawl_site(O, client=_client(_site()), sitemap_urls=SITEMAP, workers=1,
               on_progress=lambda i, n, u: seen.append(i))
    assert seen == list(range(1, len(seen) + 1)) and len(seen) >= len(SITEMAP)
