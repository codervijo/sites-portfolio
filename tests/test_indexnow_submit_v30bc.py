"""v30.B/C — IndexNow submission: ledger, sitemap fetch, POST client, CHECK_154.

Network is mocked (`httpx.MockTransport`); the ledger store is redirected to a
tmp dir so tests never touch `data/index/`.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import indexnow
from portfolio.checks.deploy import check_154_indexnow_submitted as chk
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

_BASE = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'


@pytest.fixture(autouse=True)
def _isolate_index_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(indexnow, "INDEX_DIR", tmp_path / "_indexstore")


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# ---- ledger ----


def test_ledger_append_and_urls():
    indexnow.append_ledger("example.com", ["https://example.com/a", "https://example.com/b"])
    assert indexnow.ledger_urls("example.com") == {
        "https://example.com/a", "https://example.com/b"}


def test_new_urls_excludes_ledgered_and_dedupes():
    indexnow.append_ledger("example.com", ["https://example.com/a"])
    out = indexnow.new_urls("example.com",
                            ["https://example.com/a", "https://example.com/b", "https://example.com/b"])
    assert out == ["https://example.com/b"]


def test_ledger_empty_when_absent():
    assert indexnow.load_ledger("nope.com") == []


# ---- sitemap fetch ----


def test_fetch_sitemap_urlset():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="Sitemap: https://example.com/sitemap.xml")
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text="<urlset><url><loc>https://example.com/a</loc></url>"
                                            "<url><loc>https://example.com/b</loc></url></urlset>")
        return httpx.Response(404)
    assert indexnow.fetch_sitemap_urls("example.com", client=_client(handler)) == [
        "https://example.com/a", "https://example.com/b"]


def test_fetch_sitemap_index_expands_children():
    def handler(req):
        p = req.url.path
        if p == "/robots.txt":
            return httpx.Response(200, text="Sitemap: https://example.com/sitemap-index.xml")
        if p == "/sitemap-index.xml":
            return httpx.Response(200, text="<sitemapindex><sitemap>"
                                            "<loc>https://example.com/sitemap-0.xml</loc></sitemap></sitemapindex>")
        if p == "/sitemap-0.xml":
            return httpx.Response(200, text="<urlset><url><loc>https://example.com/x</loc></url></urlset>")
        return httpx.Response(404)
    assert indexnow.fetch_sitemap_urls("example.com", client=_client(handler)) == ["https://example.com/x"]


def test_fetch_sitemap_fallback_when_no_robots_sitemap_line():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text="<urlset><url><loc>https://example.com/a</loc></url></urlset>")
        return httpx.Response(404)
    assert indexnow.fetch_sitemap_urls("example.com", client=_client(handler)) == ["https://example.com/a"]


# ---- submit_urls ----


def test_submit_success_returns_count():
    captured = {}
    def handler(req):
        captured["body"] = req.content.decode()
        return httpx.Response(200)
    n = indexnow.submit_urls("example.com", "k", ["https://example.com/a"], client=_client(handler))
    assert n == 1 and "urlList" in captured["body"]


def test_submit_empty_is_zero():
    assert indexnow.submit_urls("example.com", "k", []) == 0


def test_submit_permanent_4xx_raises_indexnowerror():
    with pytest.raises(indexnow.IndexNowError):
        indexnow.submit_urls("example.com", "k", ["https://example.com/a"],
                             client=_client(lambda r: httpx.Response(403, text="bad key")))


def test_submit_429_is_transient():
    with pytest.raises(httpx.HTTPStatusError):
        indexnow.submit_urls("example.com", "k", ["https://example.com/a"],
                             client=_client(lambda r: httpx.Response(429)))


# ---- key_is_live ----


def test_key_is_live_true():
    assert indexnow.key_is_live("example.com", "thekey",
                                client=_client(lambda r: httpx.Response(200, text="thekey\n"))) is True


def test_key_is_live_mismatch():
    assert indexnow.key_is_live("example.com", "thekey",
                                client=_client(lambda r: httpx.Response(200, text="other"))) is False


# ---- CHECK_154 + fixer ----


def _site(tmp_path, *, enabled=True, key="abc123"):
    idx = f'\n[index]\nindexnow_key = "{key}"\nindexnow_enabled = {"true" if enabled else "false"}\n'
    (tmp_path / LAMILL_TOML_FILENAME).write_text(_BASE + idx)
    (tmp_path / "package.json").write_text('{"name":"x"}')
    return tmp_path


def test_check_pass_when_not_provisioned(tmp_path):
    (tmp_path / LAMILL_TOML_FILENAME).write_text(_BASE)
    (tmp_path / "package.json").write_text("{}")
    assert chk.run(str(tmp_path)).status == "pass"


def test_check_warns_on_pending(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **k: ["https://x/a"])
    assert chk.run(str(tmp_path)).status == "warn"


def test_check_pass_when_all_submitted(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **k: ["https://x/a"])
    indexnow.append_ledger(tmp_path.name, ["https://x/a"])
    assert chk.run(str(tmp_path)).status == "pass"


def test_check_pass_when_sitemap_unreachable(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **k: [])
    assert chk.run(str(tmp_path)).status == "pass"


def test_fix_dry_run_no_submit(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **k: ["https://x/a"])
    monkeypatch.setattr(indexnow, "submit_urls", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no submit in dry-run")))
    assert chk.fix_tier_1.apply(tmp_path, True, False).status == "would-fix"


def test_fix_manual_when_key_not_live(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **k: ["https://x/a"])
    monkeypatch.setattr(indexnow, "key_is_live", lambda d, key, **k: False)
    assert chk.fix_tier_1.apply(tmp_path, False, False).status == "manual"


def test_fix_submits_then_ledger_gated(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **k: ["https://x/a", "https://x/b"])
    monkeypatch.setattr(indexnow, "key_is_live", lambda d, key, **k: True)
    captured = {}
    monkeypatch.setattr(indexnow, "submit_urls",
                        lambda domain, key, urls, **k: captured.update(urls=urls) or len(urls))
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "fixed"
    assert captured["urls"] == ["https://x/a", "https://x/b"]
    # ledger now records them → a second run pings nothing
    assert chk.fix_tier_1.apply(tmp_path, False, False).status == "nothing-to-do"
