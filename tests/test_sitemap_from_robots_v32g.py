"""v32.G — submit the site's ACTUAL sitemap (from robots.txt), not an assumed
`/sitemap.xml`. @astrojs/sitemap emits `/sitemap-index.xml` and writes it into
robots.txt; the SPA catch-all serves HTML for `/sitemap.xml`, so the assumed
URL produced fleet-wide GSC parse errors. `resolve_sitemap_url` reads the
robots.txt `Sitemap:` line (fallback `/sitemap.xml`); `delete_sitemap` clears
a stale entry. See bugs.md 2026-06-05.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import gsc_admin
from portfolio.gsc_admin import (
    GSCAdminError,
    delete_sitemap,
    resolve_sitemap_url,
)


def _robots_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---- resolve_sitemap_url ----


def test_reads_sitemap_index_from_robots():
    def handler(req):
        assert req.url.path == "/robots.txt"
        return httpx.Response(200, text=(
            "User-agent: *\nAllow: /\n"
            "Sitemap: https://drdebug.dev/sitemap-index.xml\n"))
    assert resolve_sitemap_url("drdebug.dev", client=_robots_client(handler)) \
        == "https://drdebug.dev/sitemap-index.xml"


def test_first_sitemap_line_wins():
    def handler(req):
        return httpx.Response(200, text=(
            "Sitemap: https://x.com/sitemap-index.xml\n"
            "Sitemap: https://x.com/other.xml\n"))
    assert resolve_sitemap_url("x.com", client=_robots_client(handler)) \
        == "https://x.com/sitemap-index.xml"


def test_case_insensitive_sitemap_directive():
    def handler(req):
        return httpx.Response(200, text="sitemap: https://x.com/s-index.xml\n")
    assert resolve_sitemap_url("x.com", client=_robots_client(handler)) \
        == "https://x.com/s-index.xml"


def test_fallback_when_no_sitemap_line():
    def handler(req):
        return httpx.Response(200, text="User-agent: *\nDisallow:\n")
    assert resolve_sitemap_url("x.com", client=_robots_client(handler)) \
        == "https://x.com/sitemap.xml"


def test_fallback_when_robots_404():
    assert resolve_sitemap_url(
        "x.com", client=_robots_client(lambda r: httpx.Response(404)),
    ) == "https://x.com/sitemap.xml"


def test_fallback_when_robots_unreachable(monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("no dns")
    monkeypatch.setattr(httpx, "get", boom)
    assert resolve_sitemap_url("x.com") == "https://x.com/sitemap.xml"


# ---- delete_sitemap ----


def test_delete_sitemap_removes_listed_entry():
    calls = {"delete": 0}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"sitemap": [
                {"path": "https://x.com/sitemap.xml"}]})
        if req.method == "DELETE":
            calls["delete"] += 1
            return httpx.Response(204)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert delete_sitemap(
        "x.com", "https://x.com/sitemap.xml", client=client) is True
    assert calls["delete"] == 1


def test_delete_sitemap_idempotent_when_absent():
    calls = {"delete": 0}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"sitemap": [
                {"path": "https://x.com/sitemap-index.xml"}]})
        calls["delete"] += 1
        return httpx.Response(204)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    # Asking to delete a URL that isn't listed → no DELETE, returns False.
    assert delete_sitemap(
        "x.com", "https://x.com/sitemap.xml", client=client) is False
    assert calls["delete"] == 0


def test_delete_sitemap_raises_on_error():
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"sitemap": [
                {"path": "https://x.com/sitemap.xml"}]})
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError):
        delete_sitemap("x.com", "https://x.com/sitemap.xml", client=client)
