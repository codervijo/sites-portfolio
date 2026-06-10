"""v32.F — pending-verification / 1014 resilience.

Two pieces:
  - CF helpers `get_pages_domain_status` + `delete_pages_custom_domain`
    (the read + the detach used by `--repair`).
  - The watch loop names a stuck custom domain `pending_verification`
    (with a `--repair` pointer) instead of a generic `timeout` when
    zone+build are green but the apex never serves.

All HTTP stubbed via `httpx.MockTransport` / monkeypatch.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import cloudflare
from portfolio.cli import _deploy_watch_loop
from portfolio.cloudflare import (
    API_BASE,
    CloudflareAPIError,
    ZoneInfo,
    delete_pages_custom_domain,
    get_pages_domain_status,
)


def _client_for(handler) -> httpx.Client:
    return httpx.Client(
        base_url=API_BASE, transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer t", "Content-Type": "application/json"},
    )


# ---- get_pages_domain_status ----


def test_domain_status_active():
    def handler(req):
        assert req.url.path.endswith("/pages/projects/scope/domains/scope.xyz")
        return httpx.Response(200, json={"success": True,
                                         "result": {"status": "active"}})
    assert get_pages_domain_status(
        "scope", "scope.xyz", account_id="a", client=_client_for(handler)
    ) == "active"


def test_domain_status_pending():
    assert get_pages_domain_status(
        "scope", "scope.xyz", account_id="a",
        client=_client_for(lambda r: httpx.Response(
            200, json={"success": True, "result": {"status": "pending"}})),
    ) == "pending"


def test_domain_status_404_returns_none():
    assert get_pages_domain_status(
        "scope", "scope.xyz", account_id="a",
        client=_client_for(lambda r: httpx.Response(404, json={})),
    ) is None


def test_domain_status_error_raises():
    with pytest.raises(CloudflareAPIError):
        get_pages_domain_status(
            "scope", "scope.xyz", account_id="a",
            client=_client_for(lambda r: httpx.Response(500, text="boom")))


# ---- delete_pages_custom_domain ----


def test_delete_custom_domain_ok():
    seen = {}

    def handler(r):
        seen["method"] = r.method
        seen["path"] = r.url.path
        return httpx.Response(200, json={"success": True})

    assert delete_pages_custom_domain(
        "scope", "scope.xyz", account_id="a", client=_client_for(handler)) is True
    # Guard verb + path (not just the 200): a wrong method/route would 404 live.
    assert seen["method"] == "DELETE"
    assert seen["path"].endswith("/accounts/a/pages/projects/scope/domains/scope.xyz")


def test_delete_custom_domain_404_is_false():
    assert delete_pages_custom_domain(
        "scope", "scope.xyz", account_id="a",
        client=_client_for(lambda r: httpx.Response(404, json={})),
    ) is False


def test_delete_custom_domain_error_raises():
    with pytest.raises(CloudflareAPIError):
        delete_pages_custom_domain(
            "scope", "scope.xyz", account_id="a",
            client=_client_for(lambda r: httpx.Response(500, text="x")))


# ---- watch loop: pending_verification ----


def _zone(status):
    return ZoneInfo(zone_id="z1", name="scope.xyz",
                    name_servers=["a.ns", "b.ns"], status=status, created=False)


def test_watch_returns_pending_verification(monkeypatch):
    """Zone active + build success, but the apex stays 403 (1014) and the
    custom domain reads 'pending' → pending_verification, not timeout."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone("active"))
    monkeypatch.setattr(cloudflare, "latest_deployment_status",
                        lambda slug, **kw: ("deploy", "success", "d1"))
    monkeypatch.setattr(cloudflare, "get_pages_domain_status",
                        lambda slug, dom, **kw: "pending")

    class _403:
        status_code = 403
        url = "https://scope.xyz/"
    monkeypatch.setattr("httpx.head", lambda url, **kw: _403())

    t = {"now": 0.0}
    result = _deploy_watch_loop(
        domain="scope.xyz", zone_id="z1", slug="scope",
        cf_account="a", cf_surface="pages",
        timeout_s=10, interval_s=10,
        sleep=lambda s: t.__setitem__("now", t["now"] + s),
        monotonic=lambda: t["now"],
    )
    assert result == "pending_verification"


def test_watch_still_times_out_when_domain_active(monkeypatch):
    """If the custom domain reads 'active' (so the stuck-ness is elsewhere),
    fall back to the generic timeout rather than mislabeling it."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone("active"))
    monkeypatch.setattr(cloudflare, "latest_deployment_status",
                        lambda slug, **kw: ("deploy", "success", "d1"))
    monkeypatch.setattr(cloudflare, "get_pages_domain_status",
                        lambda slug, dom, **kw: "active")

    class _403:
        status_code = 403
        url = "https://scope.xyz/"
    monkeypatch.setattr("httpx.head", lambda url, **kw: _403())

    t = {"now": 0.0}
    result = _deploy_watch_loop(
        domain="scope.xyz", zone_id="z1", slug="scope",
        cf_account="a", cf_surface="pages",
        timeout_s=10, interval_s=10,
        sleep=lambda s: t.__setitem__("now", t["now"] + s),
        monotonic=lambda: t["now"],
    )
    assert result == "timeout"
