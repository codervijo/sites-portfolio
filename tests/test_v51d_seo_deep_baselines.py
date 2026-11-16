"""v51.D — baseline selection, site profile, text stats, comparison."""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from portfolio import gsc_detail_cache, seo_deep
from portfolio.seo_deep import (
    Contrast,
    GscSitemap,
    SiteProfile,
    SitemapShape,
    TextStats,
    UrlProbe,
    compare,
    crawl_site,
    pick_baselines,
    profile_site,
    sitemap_shape,
    text_stats,
)

O = "https://s.com"


@pytest.fixture(autouse=True)
def _iso(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    stacks = {}
    monkeypatch.setattr(seo_deep, "_stack_of", lambda d: stacks.get(d, (None, None)))
    return stacks


def _client(routes):
    def handler(request):
        return routes.get(str(request.url), httpx.Response(404))
    return httpx.Client(transport=httpx.MockTransport(handler))


def _page(text: str, links: str = "") -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/html"},
                          text=f"<html><head><title>T</title></head><body><p>{text}</p>{links}</body></html>")


def _cache(domain, states):
    gsc_detail_cache.save_snapshot(domain, {"v16c_inspections": [
        {"url": f"https://{domain}/{i}", "coverage_state": s} for i, s in enumerate(states)]})


IDX = "Submitted and indexed"
UNK = "URL is unknown to Google"


# ---------- pick_baselines ----------

def test_pick_requires_fully_indexed_and_min_inspected(_iso):
    _cache("good.com", [IDX] * 6)
    _cache("partial.com", [IDX] * 5 + [UNK])
    _cache("tiny.com", [IDX] * 3)
    picks = pick_baselines("t.com", candidates=["good.com", "partial.com", "tiny.com", "t.com"])
    assert [p.domain for p in picks] == ["good.com"]
    assert picks[0].reason.startswith("6/6 indexed")


def test_pick_ranks_same_framework_and_platform_first(_iso):
    _iso.update({"t.com": ("astro", "vercel"), "a.com": ("astro", "cf-pages"),
                 "b.com": ("astro", "vercel"), "c.com": ("vite-react", "vercel")})
    for d in ("a.com", "b.com", "c.com"):
        _cache(d, [IDX] * 10)
    _cache("a.com", [IDX] * 10)
    picks = pick_baselines("t.com", n=3, candidates=["a.com", "b.com", "c.com"])
    assert [p.domain for p in picks] == ["b.com", "a.com", "c.com"]
    assert "same framework + platform" in picks[0].reason
    assert "other stack" in picks[2].reason


def test_pick_override_wins_even_if_not_indexed(_iso):
    _cache("x.com", [UNK] * 2)
    picks = pick_baselines("t.com", override=["X.com"], candidates=[])
    assert [(p.domain, p.reason) for p in picks] == [("x.com", "operator --baseline")]


def test_pick_prefers_todays_deep_inspections(_iso):
    _cache("d.com", [UNK] * 6)                           # old sample says not indexed
    seo_deep.save_records("d.com", {f"https://d.com/{i}": {"status": "ok", "coverage_state": IDX}
                                    for i in range(6)})
    assert [p.domain for p in pick_baselines("t.com", candidates=["d.com"])] == ["d.com"]


# ---------- sitemap_shape ----------

def test_sitemap_shape_index_lastmod_hosts():
    c = _client({
        O + "/sitemap-index.xml": httpx.Response(200, text=(
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<sitemap><loc>{O}/sitemap-0.xml</loc></sitemap></sitemapindex>')),
        O + "/sitemap-0.xml": httpx.Response(200, text=(
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'<url><loc>{O}/a</loc><lastmod>2026-01-01</lastmod></url>'
            '<url><loc>https://www.s.com/b</loc></url></urlset>')),
    })
    sh = sitemap_shape(O, O + "/sitemap-index.xml", c)
    assert sh.is_index and sh.child_count == 1 and sh.url_count == 2
    assert sh.lastmod_share == 0.5
    assert sh.loc_hosts == ["s.com", "www.s.com"]


def test_sitemap_shape_missing_file():
    assert sitemap_shape(O, None, _client({})).error == "no sitemap"


# ---------- text_stats ----------

def _p(text, url="u"):
    p = UrlProbe(url=url, status=200)
    toks = text.split()
    p.words = len(toks)
    p.shingles = frozenset(hash(" ".join(toks[i:i + 5])) for i in range(len(toks) - 4))
    return p


def test_text_stats_separates_template_from_unique():
    nav = " ".join(f"nav{i}" for i in range(40))
    pages = [_p(nav + " " + " ".join(f"p{k}w{i}" for i in range(40)), f"u{k}") for k in range(5)]
    ts = text_stats(pages)
    assert ts.pages == 5 and ts.median_words == 80
    assert 0.4 < ts.median_boilerplate_share < 0.6
    assert ts.median_unique_words < 50
    assert ts.near_duplicate_pages == 0


def test_text_stats_flags_near_duplicates():
    body = " ".join(f"w{i}" for i in range(60))
    pages = [_p(body, "a"), _p(body + " extra", "b"), _p(" ".join(f"z{i}" for i in range(60)), "c")]
    assert text_stats(pages).near_duplicate_pages == 2


def test_text_stats_empty():
    assert text_stats([]).pages == 0


def test_probe_carries_words_and_shingles():
    words = " ".join(f"w{i}" for i in range(20))
    r = crawl_site(O, client=_client({O + "/": _page(words)}), sitemap_urls=[O + "/"], workers=1)
    p = r.probes[seo_deep.url_key(O + "/")]
    assert p.words == 20 and len(p.shingles) == 16


# ---------- profile + compare ----------

def test_profile_site_from_crawl(_iso):
    routes = {
        O + "/robots.txt": httpx.Response(404),
        O + "/": _page("home " * 50, '<a href="/a">a</a>'),
        O + "/a": _page("a " * 50, '<a href="/b">b</a>'),
        O + "/b": _page("b " * 50),
    }
    c = _client(routes)
    cr = crawl_site(O, client=c, sitemap_urls=[O + "/", O + "/a", O + "/b"], workers=1)
    prof = profile_site("s.com", cr, client=c)
    assert prof.sitemap_urls == 3 and prof.orphans == 0
    assert prof.home_outlinks == 1
    assert prof.share_linked_from_home == 0.5
    assert prof.median_depth == 1 and prof.max_depth == 2
    assert prof.median_inbound == 1
    assert prof.gsc_sitemaps is None              # no service → not fetched


def _prof(domain, **kw) -> SiteProfile:
    base = dict(domain=domain, framework="astro", platform="vercel", age_days=100,
                indexed=10, inspected=10, index_source="x",
                sitemap=SitemapShape(file_url="f", url_count=10), gsc_sitemaps=[],
                sitemap_urls=10, probed=10, crawl_capped=False, non_200=0, redirected=0,
                noindex=0, robots_blocked=0, empty_shells=0, canonical_kinds={"self": 10},
                home_outlinks=20, share_linked_from_home=0.5, median_depth=1.0, max_depth=2,
                orphans=0, unreachable=0, median_inbound=8.0, linked_not_in_sitemap=0,
                text=TextStats(10, 800, 700, 0.1, 0))
    base.update(kw)
    return SiteProfile(**base)


def _by(cs: list[Contrast]) -> dict[str, Contrast]:
    return {c.signal: c for c in cs}


def test_compare_flags_only_out_of_range_on_bad_side():
    t = _prof("t.com", indexed=1, median_inbound=3.0,
              text=TextStats(10, 2000, 1900, 0.01, 0), age_days=999)
    bs = [_prof("a.com"), _prof("b.com", median_inbound=6.0)]
    c = _by(compare(t, bs))
    assert c["index_rate"].worse
    assert c["median_inbound"].worse
    assert c["median_words"].outside and not c["median_words"].worse   # more words: outside, not worse
    assert c["age_days"].outside and not c["age_days"].worse          # better = none
    assert not c["orphan_share"].outside


def test_compare_gsc_sitemap_age_signals():
    now = datetime.now(timezone.utc)
    iso = lambda d: (now - timedelta(days=d)).isoformat().replace("+00:00", "Z")
    g = lambda sub, dl: [GscSitemap("p", iso(sub), iso(dl), False, True, 0, 0, 10)]
    t = _prof("t.com", gsc_sitemaps=g(40, 1))
    bs = [_prof("a.com", gsc_sitemaps=g(150, 6)), _prof("b.com", gsc_sitemaps=g(150, 9))]
    c = _by(compare(t, bs))
    assert c["gsc_sitemap_days"].target == 40 and c["gsc_sitemap_days"].outside
    assert c["gsc_downloaded_days"].target == 1 and not c["gsc_downloaded_days"].worse


def test_compare_no_baselines_marks_nothing():
    assert not any(c.outside for c in compare(_prof("t.com"), []))


def test_categorical_notes():
    t = _prof("t.com", platform="vercel",
              sitemap=SitemapShape(file_url="https://t.com/sitemap-index.xml", is_index=True,
                                   loc_hosts=["t.com", "www.t.com"]),
              gsc_sitemaps=[GscSitemap("https://t.com/sitemap.xml", None, None, True, False, 1, 0, 3)])
    notes = seo_deep.categorical_notes(t, [_prof("a.com", platform="cf-pages")])
    joined = "\n".join(notes)
    assert "platform: t.com=vercel" in joined
    assert "2 hosts" in joined
    assert "≠ the live one" in joined
    assert "pending=True errors=1" in joined


# ---------- repo age (BUG-105 stand-in) ----------

def test_repo_age_uses_root_commit_not_newest(monkeypatch, tmp_path):
    from portfolio import project
    repo = tmp_path / "s.com"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
    run = lambda *a, date: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True,
                                          env={**env, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date})
    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    new = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    run("init", "-q", date=old)
    run("commit", "-q", "--allow-empty", "-m", "first", date=old)
    run("commit", "-q", "--allow-empty", "-m", "second", date=new)
    monkeypatch.setattr(project, "SITES_ROOT", tmp_path)
    monkeypatch.setattr("portfolio.data.load_domains", lambda *a, **k: [])
    assert seo_deep._repo_age_days("s.com") in (199, 200)
