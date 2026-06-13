"""CHECK_159 — every sitemap <loc> URL must use the apex host (no www)."""
from __future__ import annotations

from pathlib import Path

import portfolio.checks.seo.check_159_sitemap_host_is_apex as mod
from portfolio.checks.seo._live import LiveFetchError


def _site(tmp_path: Path) -> str:
    d = tmp_path / "calcengine.site"
    d.mkdir()
    return str(d)


def _patch(monkeypatch, *, origin="https://calcengine.site", urls):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: True)
    monkeypatch.setattr(mod, "resolve_live_url", lambda p: origin)
    if isinstance(urls, Exception):
        def _boom(o):
            raise urls
        monkeypatch.setattr(mod, "get_sitemap_urls", _boom)
    else:
        monkeypatch.setattr(mod, "get_sitemap_urls", lambda o: urls)


def test_pass_all_locs_apex(tmp_path, monkeypatch):
    _patch(monkeypatch, urls=[
        "https://calcengine.site/", "https://calcengine.site/about"])
    r = mod.run(_site(tmp_path))
    assert r.status == "pass", r.message


def test_fail_www_loc(tmp_path, monkeypatch):
    _patch(monkeypatch, urls=[
        "https://calcengine.site/", "https://www.calcengine.site/about"])
    r = mod.run(_site(tmp_path))
    assert r.status == "fail"
    assert "www.calcengine.site" in r.message
    assert "1/2" in r.message


def test_warn_sitemap_unreachable(tmp_path, monkeypatch):
    _patch(monkeypatch, urls=LiveFetchError("no sitemap"))
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"
    assert "unreachable" in r.message


def test_warn_sitemap_empty(tmp_path, monkeypatch):
    _patch(monkeypatch, urls=[])
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"
    assert "empty" in r.message


def test_warn_no_live_url(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_is_web_project", lambda p: True)
    monkeypatch.setattr(mod, "resolve_live_url", lambda p: None)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"


def test_metadata():
    assert mod.CHECK_ID == "CHECK_159"
    assert mod.SEVERITY == "error"
    assert mod.CATEGORY == "seo"
