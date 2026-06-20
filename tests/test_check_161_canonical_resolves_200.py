"""CHECK_161 — a page's canonical must resolve 200 (not a 3xx redirect).

Live machinery is monkeypatched on the check module; `parse_canonical` runs
for real against stubbed HTML. `fetch_status_no_redirect` is stubbed to return
the canonical URL's status (the bug: a canonical that 308-redirects).
"""
from __future__ import annotations

from pathlib import Path

import portfolio.checks.seo.check_161_canonical_resolves_200 as mod
from portfolio.checks.seo._live import LiveFetchError


def _site(tmp_path: Path) -> str:
    d = tmp_path / "earnlog.xyz"
    d.mkdir()
    return str(d)


def _page(canonical: str | None) -> str:
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return f"<html><head>{link}</head><body>hi</body></html>"


def _patch(monkeypatch, *, origin="https://earnlog.xyz", urls, pages, statuses):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: True)
    monkeypatch.setattr(mod, "resolve_live_url", lambda p: origin)
    monkeypatch.setattr(mod, "get_sitemap_urls", lambda o: urls)

    def _fetch(url, **kw):
        v = pages[url]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(mod, "fetch_html", _fetch)

    def _status(url, **kw):
        v = statuses[url]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(mod, "fetch_status_no_redirect", _status)


def test_pass_canonicals_resolve_200(tmp_path, monkeypatch):
    # canonical of /calculator/ is /calculator/ → 200. Correct.
    urls = ["https://earnlog.xyz/", "https://earnlog.xyz/calculator/"]
    pages = {u: _page(u) for u in urls}
    statuses = {u: 200 for u in urls}
    _patch(monkeypatch, urls=urls, pages=pages, statuses=statuses)
    r = mod.run(_site(tmp_path))
    assert r.status == "pass", r.message


def test_fail_canonical_308_redirects(tmp_path, monkeypatch):
    # the bug: /calculator/ declares canonical /calculator (no slash) → 308.
    urls = ["https://earnlog.xyz/", "https://earnlog.xyz/calculator/"]
    pages = {
        "https://earnlog.xyz/": _page("https://earnlog.xyz/"),
        "https://earnlog.xyz/calculator/": _page("https://earnlog.xyz/calculator"),
    }
    statuses = {
        "https://earnlog.xyz/": 200,
        "https://earnlog.xyz/calculator": 308,   # canonical redirects
    }
    _patch(monkeypatch, urls=urls, pages=pages, statuses=statuses)
    r = mod.run(_site(tmp_path))
    assert r.status == "fail"
    assert "308" in r.message
    assert "/calculator" in r.message


def test_fail_canonical_404_broken(tmp_path, monkeypatch):
    urls = ["https://earnlog.xyz/about/"]
    pages = {"https://earnlog.xyz/about/": _page("https://earnlog.xyz/old-about")}
    statuses = {"https://earnlog.xyz/old-about": 404}
    _patch(monkeypatch, urls=urls, pages=pages, statuses=statuses)
    r = mod.run(_site(tmp_path))
    assert r.status == "fail"
    assert "404" in r.message


def test_missing_canonical_is_not_this_checks_problem(tmp_path, monkeypatch):
    urls = ["https://earnlog.xyz/"]
    pages = {"https://earnlog.xyz/": _page(None)}
    statuses: dict = {}
    _patch(monkeypatch, urls=urls, pages=pages, statuses=statuses)
    r = mod.run(_site(tmp_path))
    assert r.status == "pass"  # missing canonical → CHECK_072, not this


def test_network_flake_on_canonical_does_not_false_fail(tmp_path, monkeypatch):
    urls = ["https://earnlog.xyz/calculator/"]
    pages = {"https://earnlog.xyz/calculator/": _page("https://earnlog.xyz/calculator")}
    statuses = {"https://earnlog.xyz/calculator": LiveFetchError("timeout")}
    _patch(monkeypatch, urls=urls, pages=pages, statuses=statuses)
    r = mod.run(_site(tmp_path))
    assert r.status == "pass"  # flake skipped, not a false fail


def test_warn_no_live_url(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: True)
    monkeypatch.setattr(mod, "resolve_live_url", lambda p: None)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"


def test_warn_not_web_project(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: False)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"


def test_metadata():
    assert mod.CHECK_ID == "CHECK_161"
    assert mod.SEVERITY == "error"
    assert mod.CATEGORY == "seo"
