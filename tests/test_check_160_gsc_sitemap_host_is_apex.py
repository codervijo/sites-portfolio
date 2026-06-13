"""CHECK_160 — GSC property + registered sitemaps must use the apex host.

The cached-GSC-detail loader is monkeypatched on the check module's
`gsc_detail_cache` reference; we feed snapshot dicts directly.
"""
from __future__ import annotations

from pathlib import Path

import portfolio.checks.seo.check_160_gsc_sitemap_host_is_apex as mod


def _site(tmp_path: Path) -> str:
    d = tmp_path / "calcengine.site"
    d.mkdir()
    return str(d)


def _patch(monkeypatch, snap):
    # snap=None → no cached snapshot at all.
    monkeypatch.setattr(mod.gsc_detail_cache, "latest_snapshot",
                        lambda dom: (None if snap is None else Path("x.json")))
    monkeypatch.setattr(mod.gsc_detail_cache, "load_snapshot", lambda p: snap)


def test_pass_domain_property_apex_sitemap(tmp_path, monkeypatch):
    _patch(monkeypatch, {
        "property_url": "sc-domain:calcengine.site",
        "sitemaps": [{"full_url": "https://calcengine.site/sitemap-index.xml"}],
    })
    r = mod.run(_site(tmp_path))
    assert r.status == "pass", r.message


def test_fail_www_sitemap_registered(tmp_path, monkeypatch):
    _patch(monkeypatch, {
        "property_url": "sc-domain:calcengine.site",
        "sitemaps": [
            {"full_url": "https://calcengine.site/sitemap-index.xml"},
            {"full_url": "https://www.calcengine.site/sitemap.xml"},  # stale www
        ],
    })
    r = mod.run(_site(tmp_path))
    assert r.status == "fail"
    assert "www.calcengine.site" in r.message


def test_fail_url_prefix_property_on_www(tmp_path, monkeypatch):
    _patch(monkeypatch, {
        "property_url": "https://www.calcengine.site/",
        "sitemaps": [{"full_url": "https://calcengine.site/sitemap-index.xml"}],
    })
    r = mod.run(_site(tmp_path))
    assert r.status == "fail"
    assert "property" in r.message


def test_warn_no_cache(tmp_path, monkeypatch):
    _patch(monkeypatch, None)
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"
    assert "no cached GSC detail" in r.message


def test_warn_not_registered(tmp_path, monkeypatch):
    _patch(monkeypatch, {"not_registered": True})
    r = mod.run(_site(tmp_path))
    assert r.status == "warn"
    assert "not registered" in r.message


def test_relative_sitemap_path_is_hostless_ok(tmp_path, monkeypatch):
    # A SitemapDetail with only a relative `path` (no full_url) has no host
    # to judge → must not false-fail.
    _patch(monkeypatch, {
        "property_url": "sc-domain:calcengine.site",
        "sitemaps": [{"path": "/sitemap-index.xml"}],
    })
    r = mod.run(_site(tmp_path))
    assert r.status == "pass", r.message


def test_metadata():
    assert mod.CHECK_ID == "CHECK_160"
    assert mod.SEVERITY == "error"
    assert mod.CATEGORY == "seo"
