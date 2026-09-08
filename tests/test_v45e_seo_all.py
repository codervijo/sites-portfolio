"""v45.E — `project seo --all`: inspect every sitemap URL, not top-N.

The cap exists to bound URL-Inspection quota burn, so `--all` opts out
of it knowingly (estimate + confirm) rather than removing it. These
tests pin both halves: the no-cap plumbing, and the gate in front of it.
"""
from __future__ import annotations

import pytest
import typer

from portfolio import cli as cli_mod
from portfolio import seo_diagnose


class _Console:
    def __init__(self):
        self.lines: list[str] = []

    def print(self, *a, **k):
        self.lines.append(" ".join(str(x) for x in a))

    @property
    def text(self):
        return "\n".join(self.lines)


# --- fetch_sitemap_urls: limit=None means "all" -----------------------

def _sitemap_xml(n):
    locs = "".join(f"<url><loc>https://x.test/p{i}</loc></url>" for i in range(n))
    return f'<?xml version="1.0"?><urlset>{locs}</urlset>'


@pytest.fixture
def _serve(monkeypatch):
    """Serve robots.txt + a sitemap of N URLs to fetch_sitemap_urls."""
    def _install(n):
        import httpx
        from portfolio import gsc_recrawl

        def handler(request):
            path = request.url.path
            if path == "/robots.txt":
                return httpx.Response(
                    200, text="Sitemap: https://x.test/sitemap.xml")
            if path == "/sitemap.xml":
                return httpx.Response(
                    200, text=_sitemap_xml(n),
                    headers={"content-type": "application/xml"})
            return httpx.Response(404)

        real = httpx.Client

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(handler)
            return real(*a, **k)

        monkeypatch.setattr(httpx, "Client", _client)
        return gsc_recrawl.fetch_sitemap_urls
    return _install


def test_fetch_sitemap_urls_default_limit_caps(_serve):
    fetch = _serve(120)
    assert len(fetch("https://x.test", limit=50)) == 50


def test_fetch_sitemap_urls_none_limit_returns_all(_serve):
    fetch = _serve(120)
    assert len(fetch("https://x.test", limit=None)) == 120


def test_fetch_sitemap_urls_none_limit_on_small_sitemap(_serve):
    fetch = _serve(3)
    assert len(fetch("https://x.test", limit=None)) == 3


# --- fetch_coverage_details: top_n=None inspects everything -----------

def _patch_coverage(monkeypatch, n_urls):
    from portfolio import project_seo_diagnostics as psd
    urls = [f"https://x.test/p{i}" for i in range(n_urls)]
    monkeypatch.setattr(psd, "fetch_sitemap_urls",
                        lambda origin, limit=50: urls[:limit] if limit else urls)
    inspected: list[str] = []

    class _UI:
        coverage_state = "Submitted and indexed"
        indexing_state = "INDEXING_ALLOWED"
        verdict = "PASS"
        page_fetch_state = "SUCCESSFUL"
        last_crawl_time = None
        error = None

    def _inspect(service, prop, u):
        inspected.append(u)
        return _UI()

    monkeypatch.setattr(psd, "inspect_one_url", _inspect)
    return psd, inspected


def test_coverage_details_respects_top_n(monkeypatch):
    psd, inspected = _patch_coverage(monkeypatch, 100)
    out = psd.fetch_coverage_details(None, "sc-domain:x.test", top_n=10)
    assert len(out) == 10 and len(inspected) == 10


def test_coverage_details_top_n_none_inspects_all(monkeypatch):
    psd, inspected = _patch_coverage(monkeypatch, 100)
    out = psd.fetch_coverage_details(None, "sc-domain:x.test", top_n=None)
    assert len(out) == 100 and len(inspected) == 100


def test_quota_constant_is_exposed_for_the_estimate():
    from portfolio.project_seo_diagnostics import URL_INSPECTION_DAILY_QUOTA
    assert URL_INSPECTION_DAILY_QUOTA > 0


# --- render probe cap -------------------------------------------------

def test_render_probe_note_absent_when_uncapped(monkeypatch):
    """With no cap there is no 'sampled 20/116' note to make."""
    probed: list[str] = []
    urls = [f"https://x.test/p{i}" for i in range(60)]
    audit = seo_diagnose.SitemapAudit(
        reachable=True, url_count=len(urls),
        sitemap_url="https://x.test/sitemap.xml",
        submitted_to_gsc=True, page_urls=urls,
    )
    monkeypatch.setattr(seo_diagnose, "audit_sitemap", lambda *a, **k: audit)
    def _probe(u):
        probed.append(u)
        return seo_diagnose.RenderIssue(url=u, has_title=True, has_body_text=True)

    monkeypatch.setattr(seo_diagnose, "probe_render", _probe)
    monkeypatch.setattr(seo_diagnose, "_impressions_and_submitted",
                        lambda d: (0, True, []))
    monkeypatch.setattr(seo_diagnose, "_resolve_age", lambda d: 400)
    monkeypatch.setattr(seo_diagnose, "read_index_insights", lambda d: [])
    monkeypatch.setattr(seo_diagnose, "_content_configured", lambda d: True)

    diag = seo_diagnose.gather_seo_diagnosis("x.test", render_probe_cap=None)
    assert not any("sampled" in n for n in diag.notes)
    assert len(probed) == 61          # 60 sitemap URLs + the homepage

    probed.clear()
    diag = seo_diagnose.gather_seo_diagnosis("x.test", render_probe_cap=20)
    assert any("sampled 20/60" in n for n in diag.notes)
    assert len(probed) == 20


# --- the --all gate ---------------------------------------------------

def _patch_count(monkeypatch, n):
    from portfolio import gsc_recrawl
    monkeypatch.setattr(gsc_recrawl, "fetch_sitemap_urls",
                        lambda origin, limit=50: [f"u{i}" for i in range(n)])


def test_small_run_needs_no_confirm(monkeypatch):
    _patch_count(monkeypatch, 12)
    monkeypatch.setattr(typer, "confirm",
                        lambda *a, **k: pytest.fail("should not prompt"))
    c = _Console()
    assert cli_mod._confirm_all_scope("x.test", yes=False, console=c) == 12
    assert "12 sitemap URL(s)" in c.text


def test_large_run_confirms_and_reports_cost(monkeypatch):
    _patch_count(monkeypatch, 116)
    asked = []
    monkeypatch.setattr(typer, "confirm",
                        lambda msg, **k: asked.append(msg) or True)
    c = _Console()
    assert cli_mod._confirm_all_scope("x.test", yes=False, console=c) == 116
    assert asked and "116" in asked[0]
    assert "116 URL Inspection call(s)" in c.text
    assert "% of the" in c.text          # quota percentage shown


def test_declining_returns_none_so_caller_falls_back(monkeypatch):
    _patch_count(monkeypatch, 116)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: False)
    c = _Console()
    assert cli_mod._confirm_all_scope("x.test", yes=False, console=c) is None
    assert "falling back" in c.text


def test_yes_skips_the_prompt(monkeypatch):
    _patch_count(monkeypatch, 500)
    monkeypatch.setattr(typer, "confirm",
                        lambda *a, **k: pytest.fail("should not prompt"))
    assert cli_mod._confirm_all_scope(
        "x.test", yes=True, console=_Console()) == 500


def test_unreachable_sitemap_proceeds_uncapped_not_crash(monkeypatch):
    from portfolio import gsc_recrawl

    def _boom(origin, limit=50):
        raise gsc_recrawl.RecrawlError("no sitemap reachable")

    monkeypatch.setattr(gsc_recrawl, "fetch_sitemap_urls", _boom)
    c = _Console()
    assert cli_mod._confirm_all_scope("x.test", yes=False, console=c) == 0
    assert "could not read the sitemap" in c.text


def test_empty_sitemap_is_reported_not_crash(monkeypatch):
    _patch_count(monkeypatch, 0)
    c = _Console()
    assert cli_mod._confirm_all_scope("x.test", yes=False, console=c) == 0
    assert "empty" in c.text


def test_threshold_is_the_documented_boundary(monkeypatch):
    """At the threshold: no prompt. One past it: prompt."""
    n = cli_mod._ALL_CONFIRM_THRESHOLD
    _patch_count(monkeypatch, n)
    monkeypatch.setattr(typer, "confirm",
                        lambda *a, **k: pytest.fail("should not prompt"))
    assert cli_mod._confirm_all_scope("x.test", yes=False, console=_Console()) == n

    _patch_count(monkeypatch, n + 1)
    monkeypatch.setattr(typer, "confirm", lambda *a, **k: True)
    assert cli_mod._confirm_all_scope(
        "x.test", yes=False, console=_Console()) == n + 1


# --- progress line honesty --------------------------------------------

def test_progress_line_says_every_url_when_uncapped(monkeypatch):
    from portfolio import gsc_detail_cache, project_seo_diagnostics as psd
    monkeypatch.setattr(gsc_detail_cache, "latest_snapshot", lambda d: None)
    monkeypatch.setattr(psd, "build_diagnostics",
                        lambda d, top_n=10: (_ for _ in ()).throw(
                            RuntimeError("stop after the print")))
    c = _Console()
    cli_mod._run_project_seo_diagnostics("x.test", top_n=None,
                                         refresh=True, console=c)
    assert "every sitemap URL" in c.text


def test_progress_line_says_top_n_when_capped(monkeypatch):
    from portfolio import gsc_detail_cache, project_seo_diagnostics as psd
    monkeypatch.setattr(gsc_detail_cache, "latest_snapshot", lambda d: None)
    monkeypatch.setattr(psd, "build_diagnostics",
                        lambda d, top_n=10: (_ for _ in ()).throw(
                            RuntimeError("stop after the print")))
    c = _Console()
    cli_mod._run_project_seo_diagnostics("x.test", top_n=10,
                                         refresh=True, console=c)
    assert "top 10" in c.text


# --- progress reporting (uncapped runs take minutes) -------------------

def test_coverage_reports_progress_per_url(monkeypatch):
    psd, _ = _patch_coverage(monkeypatch, 30)
    seen: list[tuple[int, int]] = []
    psd.fetch_coverage_details(None, "sc-domain:x.test", top_n=None,
                               progress_callback=lambda i, n, u: seen.append((i, n)))
    assert seen[0] == (1, 30) and seen[-1] == (30, 30)


def test_coverage_progress_callback_is_optional(monkeypatch):
    psd, _ = _patch_coverage(monkeypatch, 5)
    assert len(psd.fetch_coverage_details(
        None, "sc-domain:x.test", top_n=None)) == 5


def test_render_probe_reports_progress(monkeypatch):
    urls = [f"https://x.test/p{i}" for i in range(10)]
    audit = seo_diagnose.SitemapAudit(
        reachable=True, url_count=len(urls),
        sitemap_url="https://x.test/sitemap.xml",
        submitted_to_gsc=True, page_urls=urls)
    monkeypatch.setattr(seo_diagnose, "audit_sitemap", lambda *a, **k: audit)
    monkeypatch.setattr(
        seo_diagnose, "probe_render",
        lambda u: seo_diagnose.RenderIssue(url=u, has_title=True,
                                           has_body_text=True))
    monkeypatch.setattr(seo_diagnose, "_impressions_and_submitted",
                        lambda d: (0, True, []))
    monkeypatch.setattr(seo_diagnose, "_resolve_age", lambda d: 400)
    monkeypatch.setattr(seo_diagnose, "read_index_insights", lambda d: [])
    monkeypatch.setattr(seo_diagnose, "_content_configured", lambda d: True)

    seen: list[tuple[int, int]] = []
    diag = seo_diagnose.gather_seo_diagnosis(
        "x.test", render_probe_cap=None,
        progress_callback=lambda i, n, u: seen.append((i, n)))
    assert seen[-1] == (11, 11)          # 10 sitemap URLs + homepage
    assert diag.render_probed == 11


def test_spinner_counter_noun_defaults_to_domains_and_is_overridable(capsys):
    from portfolio.console import spinner_counter
    with spinner_counter("Doing things", 5):
        pass
    with spinner_counter("Doing things", 5, noun="URLs"):
        pass
    out = capsys.readouterr().out
    # Off-TTY under pytest, so both start notices are printed.
    assert "5 domains" in out and "5 URLs" in out


# --- cache must not satisfy a wider request than it covers -------------

def _cached(monkeypatch, n_covered, *, built):
    from portfolio import cli as c, gsc_detail_cache as gc
    snap = type("S", (), {"name": "2026-09-08.json"})()
    monkeypatch.setattr(gc, "latest_snapshot", lambda d: snap)
    monkeypatch.setattr(gc, "is_stale", lambda s: False)
    monkeypatch.setattr(gc, "load_snapshot",
                        lambda s: type("D", (), {"coverage": list(range(n_covered))})())
    monkeypatch.setattr(c, "_render_project_seo_diagnostics",
                        lambda d, con: built.append("render"))
    from portfolio import project_seo_diagnostics as psd
    monkeypatch.setattr(gc, "save_snapshot", lambda *a, **k: None)

    def _build(*a, **k):
        built.append("fetch")
        return psd.ProjectSeoDiagnostics(
            domain="x.test", property_url="sc-domain:x.test",
            not_registered=False, sitemaps=[], coverage=[], hints=[],
            fetched_at="2026-09-08T00:00:00+00:00")

    monkeypatch.setattr(psd, "build_diagnostics", _build)


def test_top10_cache_does_not_satisfy_all(monkeypatch):
    """The reported bug: --all reused a 10-URL cache and showed 10 rows."""
    built = []
    _cached(monkeypatch, 10, built=built)
    c = _Console()
    cli_mod._run_project_seo_diagnostics("x.test", top_n=None, refresh=False,
                                         console=c, expected_urls=116)
    assert built[0] == "fetch"          # cache rejected, GSC re-queried
    assert "too few for --all" in c.text


def test_full_cache_satisfies_all(monkeypatch):
    built = []
    _cached(monkeypatch, 116, built=built)
    cli_mod._run_project_seo_diagnostics("x.test", top_n=None, refresh=False,
                                         console=_Console(), expected_urls=116)
    assert built == ["render"]         # served from cache, no fetch


def test_all_with_unknown_size_distrusts_cache(monkeypatch):
    built = []
    _cached(monkeypatch, 10, built=built)
    cli_mod._run_project_seo_diagnostics("x.test", top_n=None, refresh=False,
                                         console=_Console(), expected_urls=0)
    assert built[0] == "fetch"


def test_capped_request_still_uses_cache(monkeypatch):
    built = []
    _cached(monkeypatch, 10, built=built)
    cli_mod._run_project_seo_diagnostics("x.test", top_n=10, refresh=False,
                                         console=_Console())
    assert built == ["render"]         # capped request, cache is enough
