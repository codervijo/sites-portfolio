"""CHECK_158 — canonical host must equal the apex (no www).

Live machinery (`resolve_live_url` / `get_sitemap_urls` / `fetch_html`) is
monkeypatched on the check module; `parse_canonical` runs for real against
the stubbed HTML. The apex is the repo dir name.
"""
from __future__ import annotations

from pathlib import Path

import portfolio.checks.seo.check_158_canonical_host_is_apex as mod
from portfolio.checks.seo._live import LiveFetchError


def _site(tmp_path: Path) -> str:
    d = tmp_path / "calcengine.site"
    d.mkdir()
    return str(d)


def _page(canonical: str | None) -> str:
    link = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return f"<html><head>{link}</head><body>hi</body></html>"


def _patch(monkeypatch, *, origin="https://calcengine.site", urls, pages):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: True)
    monkeypatch.setattr(mod, "resolve_live_url", lambda p: origin)
    monkeypatch.setattr(mod, "get_sitemap_urls", lambda o: urls)

    def _fetch(url, **kw):
        v = pages[url]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(mod, "fetch_html", _fetch)


def test_pass_all_canonicals_apex(tmp_path, monkeypatch):
    urls = ["https://calcengine.site/", "https://calcengine.site/about"]
    pages = {u: _page(u) for u in urls}
    _patch(monkeypatch, urls=urls, pages=pages)
    r = mod.run(_site(tmp_path))
    assert r.status == "pass", r.message
    assert "== apex" in r.message


def test_fail_canonical_points_at_www(tmp_path, monkeypatch):
    urls = ["https://calcengine.site/", "https://calcengine.site/about"]
    pages = {
        "https://calcengine.site/": _page("https://calcengine.site/"),
        "https://calcengine.site/about": _page("https://www.calcengine.site/about"),
    }
    _patch(monkeypatch, urls=urls, pages=pages)
    r = mod.run(_site(tmp_path))
    assert r.status == "fail"
    assert "www.calcengine.site" in r.message


def test_missing_canonical_is_not_this_checks_problem(tmp_path, monkeypatch):
    urls = ["https://calcengine.site/"]
    pages = {"https://calcengine.site/": _page(None)}
    _patch(monkeypatch, urls=urls, pages=pages)
    r = mod.run(_site(tmp_path))
    assert r.status == "pass"  # missing canonical → CHECK_072, not a fail here


def test_warn_no_live_url(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: True)
    monkeypatch.setattr(mod, "resolve_live_url", lambda p: None)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"
    assert "no live URL" in r.message


def test_warn_not_web_project(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: False)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"


def test_warn_all_urls_unreachable(tmp_path, monkeypatch):
    urls = ["https://calcengine.site/"]
    pages = {"https://calcengine.site/": LiveFetchError("boom")}
    _patch(monkeypatch, urls=urls, pages=pages)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"
    assert "unreachable" in r.message


def test_metadata():
    assert mod.CHECK_ID == "CHECK_158"
    assert mod.SEVERITY == "error"
    assert mod.CATEGORY == "seo"
