"""v31.A — GoDaddy Management API client + apikeys wiring."""
from __future__ import annotations

import httpx
import pytest

from portfolio import apikeys, godaddy


def _client(handler):
    return httpx.Client(base_url=godaddy.API_BASE, transport=httpx.MockTransport(handler))


# ---- client construction (auth header) ----


def test_build_client_carries_sso_key_header():
    c = godaddy._build_client("K", "S")
    try:
        assert c.headers["Authorization"] == "sso-key K:S"
    finally:
        c.close()


# ---- list_domains ----


def test_list_domains_single_page():
    def handler(req):
        assert req.url.path == "/v1/domains"
        return httpx.Response(200, json=[
            {"domain": "a.com", "status": "ACTIVE", "expires": "2027-01-01", "renewAuto": True},
        ])
    out = godaddy.list_domains(api_key="K", secret="S", client=_client(handler))
    assert len(out) == 1 and out[0]["domain"] == "a.com"


def test_list_domains_paginates_until_short_page():
    pages = [
        [{"domain": "d0.com"}, {"domain": "d1.com"}],  # full page (limit 2) → continue
        [{"domain": "last.com"}],                      # short page → stop
    ]
    calls = {"n": 0}

    def handler(req):
        i = calls["n"]
        calls["n"] += 1
        return httpx.Response(200, json=pages[i] if i < len(pages) else [])

    out = godaddy.list_domains(api_key="K", secret="S", client=_client(handler), page_limit=2)
    assert [d["domain"] for d in out] == ["d0.com", "d1.com", "last.com"]


def test_list_domains_auth_error_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.list_domains(api_key="K", secret="S",
                             client=_client(lambda r: httpx.Response(403, text="forbidden")))


def test_list_domains_rate_limit_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.list_domains(api_key="K", secret="S",
                             client=_client(lambda r: httpx.Response(429)))


# ---- get_domain ----


def test_get_domain_returns_detail():
    def handler(req):
        assert req.url.path == "/v1/domains/example.com"
        return httpx.Response(200, json={
            "domain": "example.com", "status": "ACTIVE", "expires": "2027-08-07",
            "renewAuto": False, "nameServers": ["ns1.x", "ns2.x"],
        })
    d = godaddy.get_domain("example.com", api_key="K", secret="S", client=_client(handler))
    assert d["nameServers"] == ["ns1.x", "ns2.x"] and d["renewAuto"] is False


def test_get_domain_404_raises():
    with pytest.raises(godaddy.GoDaddyError):
        godaddy.get_domain("nope.com", api_key="K", secret="S",
                           client=_client(lambda r: httpx.Response(404)))


# ---- apikeys wiring ----


def test_godaddy_keys_in_known_keys():
    assert "GODADDY_API_KEY" in apikeys.KNOWN_KEYS
    assert "GODADDY_API_SECRET" in apikeys.KNOWN_KEYS


def test_probe_godaddy_missing_when_unset():
    assert apikeys._probe_godaddy("", "").status == "missing"
    assert apikeys._probe_godaddy("K", "").status == "missing"
