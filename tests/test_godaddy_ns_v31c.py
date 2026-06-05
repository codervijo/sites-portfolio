"""v31.C — GoDaddy nameserver get/set (`new deploy` Step 4 NS auto-push)."""
from __future__ import annotations

import httpx
import pytest

from portfolio import godaddy


def _client(handler):
    return httpx.Client(base_url=godaddy.API_BASE,
                        transport=httpx.MockTransport(handler))


# ---- get_nameservers ----


def test_get_nameservers_sorted_lowercased_deduped():
    def handler(req):
        assert req.url.path == "/v1/domains/a.com"
        return httpx.Response(200, json={
            "nameServers": ["NS2.Cloudflare.com", "ns1.cloudflare.com",
                            "ns1.cloudflare.com"],
        })
    out = godaddy.get_nameservers(
        "a.com", api_key="K", secret="S", client=_client(handler))
    assert out == ["ns1.cloudflare.com", "ns2.cloudflare.com"]


def test_get_nameservers_empty_when_absent():
    out = godaddy.get_nameservers(
        "a.com", api_key="K", secret="S",
        client=_client(lambda r: httpx.Response(200, json={})))
    assert out == []


def test_get_nameservers_non_list_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.get_nameservers(
            "a.com", api_key="K", secret="S",
            client=_client(lambda r: httpx.Response(
                200, json={"nameServers": "ns1.example.com"})))


def test_get_nameservers_auth_error_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.get_nameservers(
            "a.com", api_key="K", secret="S",
            client=_client(lambda r: httpx.Response(403, text="forbidden")))


# ---- set_nameservers ----


def test_set_nameservers_puts_expected_body():
    seen = {}

    def handler(req):
        seen["method"] = req.method
        seen["path"] = req.url.path
        import json
        seen["body"] = json.loads(req.content)
        return httpx.Response(200)

    godaddy.set_nameservers(
        "a.com", api_key="K", secret="S",
        ns_list=["ns1.cloudflare.com", "ns2.cloudflare.com"],
        client=_client(handler))
    assert seen["method"] == "PUT"
    assert seen["path"] == "/v1/domains/a.com"
    assert seen["body"] == {
        "nameServers": ["ns1.cloudflare.com", "ns2.cloudflare.com"]}


def test_set_nameservers_refuses_empty_list():
    # Guard fires before any HTTP — a handler that would fail the test if hit.
    def handler(req):  # pragma: no cover - must not be called
        raise AssertionError("HTTP should not be issued for an empty NS list")
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.set_nameservers(
            "a.com", api_key="K", secret="S", ns_list=[],
            client=_client(handler))


def test_set_nameservers_error_status_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.set_nameservers(
            "a.com", api_key="K", secret="S", ns_list=["ns1.cloudflare.com"],
            client=_client(lambda r: httpx.Response(422, text="bad ns")))


def test_set_nameservers_rate_limit_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.set_nameservers(
            "a.com", api_key="K", secret="S", ns_list=["ns1.cloudflare.com"],
            client=_client(lambda r: httpx.Response(429)))
