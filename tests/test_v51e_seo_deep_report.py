"""v51.E — findings, per-URL status, JSON report, `project seo --deep`,
and the folded bugs BUG-099 (per-state wording) + BUG-100 (headline)."""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from rich.console import Console

from portfolio import gsc_detail_cache, seo_deep
from portfolio.seo_deep import (
    Comparison,
    Contrast,
    GscSitemap,
    SweepResult,
    build_report,
    crawl_site,
    derive_findings,
    prioritized_fixes,
    save_report,
    url_statuses,
)

O = "https://s.com"
IDX = "Submitted and indexed"
UNK = "URL is unknown to Google"


@pytest.fixture(autouse=True)
def _tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    monkeypatch.setattr(seo_deep, "_stack_of", lambda d: ("astro", "vercel"))


def _client(routes):
    def handler(request):
        return routes.get(str(request.url), httpx.Response(404))
    return httpx.Client(transport=httpx.MockTransport(handler))


def _page(links="", head="", text="w " * 60, **hdr):
    return httpx.Response(200, headers={"content-type": "text/html", **hdr},
                          text=f"<html><head><title>T</title>{head}</head><body><p>{text}</p>{links}</body></html>")


def _site(**overrides):
    routes = {
        O + "/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /blocked\n"),
        O + "/": _page('<a href="/a">a</a><a href="/b">b</a><a href="/blocked">x</a>'
                       '<a href="/noidx">n</a><a href="/moved">m</a>'),
        O + "/a": _page('<a href="/b">b</a>'),
        O + "/b": _page(),
        O + "/blocked": _page(),
        O + "/noidx": _page(head='<meta name="robots" content="noindex">'),
        O + "/moved": httpx.Response(301, headers={"location": "/b"}),
        O + "/orphan": _page(),
    }
    routes.update(overrides)
    return routes


SM = [O + "/", O + "/a", O + "/b", O + "/blocked", O + "/noidx", O + "/moved", O + "/orphan"]


def _crawl(**ov):
    return crawl_site(O, client=_client(_site(**ov)), sitemap_urls=SM, workers=1)


def _rec(state, *, crawl=None, refs=(), sitemaps=(), gc=None, uc=None):
    return {"status": "ok", "coverage_state": state, "last_crawl_time": crawl,
            "referring_urls": list(refs), "sitemaps": list(sitemaps),
            "google_canonical": gc, "user_canonical": uc}


def _sweep(records):
    return SweepResult(property_url="sc-domain:s.com", records=records, inspected=len(records))


def _ids(fs):
    return [f.id for f in fs]


# ---------- confirmed crawl findings ----------

def test_confirmed_crawl_findings_from_observed_problems():
    cr = _crawl()
    fs = derive_findings(cr, None, None, url_statuses(cr, {}))
    by = {f.id: f for f in fs}
    assert by["robots-blocked"].urls == [O + "/blocked"]
    assert by["noindex"].urls == [O + "/noidx"]
    assert by["redirects"].urls == [O + "/moved"]
    assert by["orphans"].urls == [O + "/orphan"]
    assert all(f.tier == "confirmed" for f in fs)
    # No inspection data → no discovery inference, no guessing.
    assert "not-discovered" not in by


def test_clean_site_no_findings():
    routes = {O + "/robots.txt": httpx.Response(404), O + "/": _page('<a href="/a">a</a>'),
              O + "/a": _page('<a href="/">h</a>')}
    cr = crawl_site(O, client=_client(routes), sitemap_urls=[O + "/", O + "/a"], workers=1)
    assert derive_findings(cr, None, None, url_statuses(cr, {})) == []


def test_robots_unreachable_and_no_sitemap_are_site_wide():
    cr = crawl_site(O, client=_client({O + "/robots.txt": httpx.Response(503),
                                       O + "/": _page()}), sitemap_urls=[], workers=1)
    ids = _ids(derive_findings(cr, None, None, []))
    assert "robots-unreachable" in ids and "sitemap-unreachable" in ids


def test_empty_shell_and_canonical_findings():
    routes = {O + "/robots.txt": httpx.Response(404),
              O + "/": _page('<a href="/spa">s</a><a href="/c">c</a>'),
              O + "/spa": httpx.Response(200, headers={"content-type": "text/html"},
                                         text="<html><head></head><body><div id=root></div></body></html>"),
              O + "/c": _page(head='<link rel="canonical" href="/">')}
    cr = crawl_site(O, client=_client(routes), sitemap_urls=[O + "/", O + "/spa", O + "/c"], workers=1)
    ids = _ids(derive_findings(cr, None, None, url_statuses(cr, {})))
    assert "empty-shell" in ids and "canonical-elsewhere" in ids


# ---------- discovery inference (inspections) ----------

def _gsc_cmp(cr, sub_days=40, dl_days=1, base_sub=(150, 150)):
    now = datetime.now(timezone.utc)
    iso = lambda d: (now - timedelta(days=d)).isoformat()
    prof = seo_deep.profile_site("s.com", cr, client=_client(_site()))
    prof.gsc_sitemaps = [GscSitemap(O + "/sitemap.xml", iso(sub_days), iso(dl_days),
                                    False, False, 0, 0, len(SM))]
    cr.sitemap_url = O + "/sitemap.xml"
    contrasts = [Contrast("gsc_sitemap_days", "days", sub_days,
                          {f"b{i}.com": v for i, v in enumerate(base_sub)}, "none", True, False)]
    return Comparison(prof, [], [], contrasts, [])


def test_not_discovered_is_likely_with_corroboration():
    cr = _crawl()
    recs = {u: _rec(UNK) for u in SM}
    recs[O + "/"] = _rec(IDX, crawl="2026-10-26T00:00:00+00:00")
    cmp = _gsc_cmp(cr)
    fs = derive_findings(cr, _sweep(recs), cmp, url_statuses(cr, recs))
    nd = next(f for f in fs if f.id == "not-discovered")
    assert nd.tier == "likely" and nd.affected == len(SM) - 1 and nd.impact == "high"
    assert any("last downloaded the sitemap 1 day" in e for e in nd.evidence)
    assert not any("baselines' sitemaps" in e for e in nd.evidence)   # lastSubmitted ≠ first contact
    assert any("homepage last crawled 2026-10-26" in e for e in nd.evidence)


def test_empty_sitemap_field_everywhere_is_not_evidence():
    cr = _crawl()
    recs = {u: _rec(UNK) for u in SM}
    fs = derive_findings(cr, _sweep(recs), None, url_statuses(cr, recs))
    nd = next(f for f in fs if f.id == "not-discovered")
    assert nd.tier == "possible"                 # only the coverage signal
    assert not any("sitemap" in e and "ties" in e for e in nd.evidence)


def test_mixed_sitemap_ties_count_as_evidence():
    cr = _crawl()
    recs = {u: _rec(UNK) for u in SM}
    recs[O + "/"] = _rec(IDX, sitemaps=[O + "/sitemap.xml"], crawl="2026-11-01T00:00:00+00:00")
    nd = next(f for f in derive_findings(cr, _sweep(recs), None, url_statuses(cr, recs))
              if f.id == "not-discovered")
    assert nd.tier == "likely"
    assert any("ties 1 inspected URL(s) to the sitemap" in e for e in nd.evidence)


def test_crawled_not_indexed_tier_rises_with_content_contrast():
    cr = _crawl()
    recs = {u: _rec("Crawled - currently not indexed", crawl="2026-11-01T00:00:00+00:00") for u in SM}
    plain = next(f for f in derive_findings(cr, _sweep(recs), None, url_statuses(cr, recs))
                 if f.id == "crawled-not-indexed")
    assert plain.tier == "possible"
    cmp = _gsc_cmp(cr)
    cmp.contrasts.append(Contrast("median_unique_words", "non-template words", 100.0,
                                  {"b.com": 700.0}, "higher", True, True))
    rich_ = next(f for f in derive_findings(cr, _sweep(recs), cmp, url_statuses(cr, recs))
                 if f.id == "crawled-not-indexed")
    assert rich_.tier == "likely"


def test_google_canonical_differs_is_confirmed():
    cr = _crawl()
    recs = {O + "/a": _rec(IDX, gc=O + "/b", uc=O + "/a")}
    fs = derive_findings(cr, _sweep(recs), None, url_statuses(cr, recs))
    assert "google-canonical-differs" in _ids(fs)


def test_gsc_sitemap_findings():
    cr = _crawl()
    cmp = _gsc_cmp(cr)
    cmp.target.gsc_sitemaps = []
    assert "gsc-no-sitemap" in _ids(derive_findings(cr, None, cmp, []))
    cmp.target.gsc_sitemaps = [GscSitemap(O + "/old.xml", None, None, True, False, 2, 0, 3)]
    ids = _ids(derive_findings(cr, None, cmp, []))
    assert "gsc-sitemap-mismatch" in ids and "gsc-sitemap-state" in ids


def test_weak_links_tier_counts_signals():
    cr = _crawl()
    cmp = _gsc_cmp(cr)
    one = Contrast("median_inbound", "links in", 2.0, {"b.com": 9.0}, "higher", True, True)
    cmp.contrasts = [one]
    f = next(f for f in derive_findings(cr, None, cmp, []) if f.id == "weak-internal-links")
    assert f.tier == "possible"
    cmp.contrasts = [one, Contrast("median_depth", "depth", 5.0, {"b.com": 2.0}, "lower", True, True)]
    f = next(f for f in derive_findings(cr, None, cmp, []) if f.id == "weak-internal-links")
    assert f.tier == "likely"


# ---------- ranking ----------

def test_findings_ranked_tier_then_affected_fixes_by_impact():
    cr = _crawl()
    recs = {u: _rec(UNK) for u in SM}
    recs[O + "/"] = _rec(IDX, sitemaps=["x"], crawl="2026-11-01T00:00:00+00:00")
    fs = derive_findings(cr, _sweep(recs), None, url_statuses(cr, recs))
    tiers = [f.tier for f in fs]
    assert tiers == sorted(tiers, key=lambda t: {"confirmed": 0, "likely": 1, "possible": 2}[t])
    fixes = prioritized_fixes(fs)
    assert [f.impact for f in fixes] == sorted(
        [f.impact for f in fixes], key=lambda i: {"high": 0, "medium": 1, "low": 2}[i])


# ---------- per-URL status ----------

def test_url_status_discovery_stage_and_meaning():
    cr = _crawl()
    recs = {O + "/": _rec(IDX, crawl="2026-11-01T00:00:00+00:00"),
            O + "/a": _rec("Crawled - currently not indexed", crawl="2026-11-01T00:00:00+00:00"),
            O + "/b": _rec(UNK),
            O + "/noidx": _rec("Discovered - currently not indexed")}
    st = {s.url: s for s in url_statuses(cr, recs)}
    assert st[O + "/"].discovery == "indexed" and st[O + "/"].coverage_meaning == ""
    assert st[O + "/a"].discovery == "crawled" and "chose not to index" in st[O + "/a"].coverage_meaning
    assert st[O + "/b"].discovery == "unknown"
    assert st[O + "/noidx"].discovery == "known"
    assert st[O + "/orphan"].discovery == "not-inspected"
    assert st[O + "/b"].inbound == 2 and st[O + "/b"].depth == 1   # / and /a (/moved → /b is from / too)


# ---------- report ----------

def test_report_json_schema_and_atomic_save(tmp_path):
    cr = _crawl()
    sw = SweepResult(property_url="p", records={}, not_inspected=[O + "/a"], stopped_reason="budget")
    rep = build_report("s.com", cr, sweep=sw, comparison=None, property_url="p")
    js = rep.to_json()
    assert js["schema"] == "seo-deep-v1" and js["domain"] == "s.com"
    assert len(js["urls"]) == len(SM) and {"discovery", "coverage_state"} <= set(js["urls"][0])
    assert js["fixes"] and set(js["fixes"]) == {f["id"] for f in js["findings"]}
    assert any("not inspected (budget)" in n for n in js["notes"])
    p = save_report(rep, tmp_path / "r" / "x.json")
    assert json.loads(p.read_text())["schema"] == "seo-deep-v1"
    assert not list((tmp_path / "r").glob("*.tmp"))


def test_render_report_smoke():
    from portfolio.research_render import render_seo_deep
    cr = _crawl()
    recs = {u: _rec(UNK) for u in SM}
    rep = build_report("s.com", cr, sweep=_sweep(recs), comparison=None, property_url="p")
    buf = io.StringIO()
    render_seo_deep(rep, Console(file=buf, width=160))
    out = buf.getvalue()
    assert "Findings" in out and "Fixes" in out and "Per-URL status" in out
    assert "lamill applies none of these" in out


# ---------- CLI ----------

def _stub_cli(monkeypatch, *, fail_preflight=False):
    from portfolio import seo_deep as sd

    def _open(domain):
        if fail_preflight:
            raise sd.GscUnavailable("no internet — check Wi-Fi")
        return object(), "sc-domain:s.com"
    monkeypatch.setattr(sd, "open_gsc", _open)
    real_crawl = sd.crawl_site
    monkeypatch.setattr(sd, "crawl_site", lambda origin, **kw: real_crawl(
        O, client=_client(_site()), sitemap_urls=SM, workers=1))
    monkeypatch.setattr(sd, "sweep_inspections", lambda d, urls, **kw: _sweep(
        {u: _rec(UNK) for u in urls}))
    real_cmp = sd.compare_with_baselines
    monkeypatch.setattr(sd, "compare_with_baselines", lambda *a, **k: real_cmp(
        *a, **{**k, "client": _client(_site())}))
    saved = {}
    monkeypatch.setattr(sd, "save_report", lambda rep, path=None: saved.setdefault("r", rep) and "/tmp/x.json")
    return saved


def test_cli_deep_json_is_valid_on_stdout(monkeypatch):
    from typer.testing import CliRunner
    from portfolio.cli import app
    _stub_cli(monkeypatch)
    res = CliRunner().invoke(app, ["project", "seo", "s.com", "--deep", "--json", "--yes"])
    assert res.exit_code == 0, res.output
    js = json.loads(res.stdout)
    assert js["schema"] == "seo-deep-v1" and js["inspection"]["inspected"] == len(SM)
    assert "✓ Search Console ready" in res.stderr


def test_cli_deep_human_render(monkeypatch):
    from typer.testing import CliRunner
    from portfolio.cli import app
    _stub_cli(monkeypatch)
    res = CliRunner().invoke(app, ["project", "seo", "s.com", "--deep", "--yes"])
    assert res.exit_code == 0, res.output
    assert "why Google isn't indexing it" in res.output and "Findings" in res.output


def test_cli_deep_preflight_failure_exits_red(monkeypatch):
    from typer.testing import CliRunner
    from portfolio.cli import app
    _stub_cli(monkeypatch, fail_preflight=True)
    res = CliRunner().invoke(app, ["project", "seo", "s.com", "--deep"])
    assert res.exit_code == 1
    assert "✗ Preflight: Google Search Console — no internet" in res.output


# ---------- BUG-099 / BUG-100 ----------

def test_bug099_unknown_url_not_called_known():
    from portfolio.seo_diagnose import IndexInsight, compute_state
    _, blockers = compute_state(
        origin=O, impressions=0, site_age_days=400, sitemap_audit=None,
        index_insights=[
            IndexInsight(O + "/a", "url_is_unknown_to_google", UNK, "NEUTRAL", None),
            IndexInsight(O + "/n", "excluded_by_noindex_tag", "Excluded by ‘noindex’ tag", "EXCLUDED", "2026-11-01"),
        ])
    by = {b.title.split('"')[0].strip(): b for b in blockers}
    a = by[O + "/a"]
    assert "hasn't discovered" in a.detail and "known to Google" not in a.detail
    n = by[O + "/n"]
    assert "noindex" in n.detail and "Remove it from the sitemap" in n.next_action
    assert "Improve the page" not in n.next_action


def test_bug099_homepage_unknown_on_old_site_not_called_crawled():
    from portfolio.seo_diagnose import IndexInsight, compute_state
    _, blockers = compute_state(
        origin=O, impressions=0, site_age_days=400, sitemap_audit=None,
        index_insights=[IndexInsight(O + "/", "url_is_unknown_to_google", UNK, "NEUTRAL", None)])
    home = next(b for b in blockers if b.title.startswith("Homepage"))
    assert home.kind == "blocker" and "crawled the homepage" not in home.detail


def test_coverage_text_accepts_human_text_and_has_default():
    from portfolio.seo_diagnose import coverage_text
    assert "chose not to index" in coverage_text("Crawled - currently not indexed")[0]
    assert coverage_text("Some future state")[1].startswith("Check the URL")


@pytest.mark.parametrize("full,expect", [(True, "all 2 sitemap URLs inspected"),
                                         (False, "top 2 inspected")])
def test_bug100_coverage_headline(full, expect):
    from portfolio.research_render import _render_project_seo_diagnostics
    buf = io.StringIO()
    diag = {"domain": "s.com", "property_url": "p", "sitemaps": [], "hints": [],
            "coverage": [{"url": O + "/", "coverage_state": "submitted_indexed"},
                         {"url": O + "/a", "coverage_state": "crawled_not_indexed"}]}
    _render_project_seo_diagnostics(diag, Console(file=buf, width=160), full=full)
    assert expect in buf.getvalue()
