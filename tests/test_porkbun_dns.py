"""Tests for v15.I — Porkbun nameserver get/update helpers.

All HTTP calls stubbed via `httpx.MockTransport`.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from portfolio.porkbun_dns import (
    PORKBUN_API,
    PorkbunDnsError,
    get_porkbun_ns,
    ns_matches,
    update_porkbun_ns,
)


def _mock_post(handler) -> httpx.Client:
    """Build a Client that intercepts POST calls via `handler(request) → Response`."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


# ---- ns_matches ----


def test_ns_matches_case_insensitive():
    assert ns_matches(
        ["NS1.example.com", "ns2.EXAMPLE.com"],
        ["ns1.example.com", "ns2.example.com"],
    )


def test_ns_matches_order_independent():
    assert ns_matches(["b.ns", "a.ns"], ["a.ns", "b.ns"])


def test_ns_matches_difference():
    assert not ns_matches(["a.ns", "b.ns"], ["a.ns", "c.ns"])


# ---- get_porkbun_ns ----


def test_get_ns_happy(monkeypatch):
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        captured["json"] = req.read().decode()
        return httpx.Response(200, json={
            "status": "SUCCESS",
            "ns": ["DOM.NS.cloudflare.com", "kristina.ns.cloudflare.com"],
        })

    monkeypatch.setattr(httpx, "post", lambda url, **kw: handler(httpx.Request("POST", url, **{k: v for k, v in kw.items() if k != "timeout"})))
    ns = get_porkbun_ns("example.com", api_key="k", secret="s")
    # Sorted + lowercased.
    assert ns == ["dom.ns.cloudflare.com", "kristina.ns.cloudflare.com"]
    assert "getNs/example.com" in captured["url"]


def test_get_ns_missing_creds():
    with pytest.raises(PorkbunDnsError, match="missing PORKBUN_API_KEY"):
        get_porkbun_ns("example.com", api_key="", secret="s")


def test_get_ns_non_200(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(503, text="server down"))
    with pytest.raises(PorkbunDnsError, match="HTTP 503"):
        get_porkbun_ns("example.com", api_key="k", secret="s")


def test_get_ns_non_success_status(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(200, json={"status": "ERROR", "message": "domain not found"}))
    with pytest.raises(PorkbunDnsError, match="status != SUCCESS"):
        get_porkbun_ns("example.com", api_key="k", secret="s")


def test_get_ns_network_error(monkeypatch):
    def fail(*a, **kw):
        raise httpx.ConnectError("dns failure")
    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(PorkbunDnsError, match="network error"):
        get_porkbun_ns("example.com", api_key="k", secret="s")


# ---- update_porkbun_ns ----


def test_update_ns_happy(monkeypatch):
    captured = {}

    def handler(req):
        captured["body"] = req.read().decode()
        return httpx.Response(200, json={"status": "SUCCESS"})

    def post_shim(url, **kw):
        return handler(httpx.Request("POST", url, **{k: v for k, v in kw.items() if k != "timeout"}))

    monkeypatch.setattr(httpx, "post", post_shim)
    update_porkbun_ns("example.com", api_key="k", secret="s",
                     ns_list=["dom.ns.cloudflare.com", "kristina.ns.cloudflare.com"])
    assert "dom.ns.cloudflare.com" in captured["body"]


def test_update_ns_empty_list_refuses():
    with pytest.raises(PorkbunDnsError, match="refusing to update NS to empty"):
        update_porkbun_ns("example.com", api_key="k", secret="s", ns_list=[])


def test_update_ns_missing_creds():
    with pytest.raises(PorkbunDnsError, match="missing PORKBUN_API_KEY"):
        update_porkbun_ns("example.com", api_key="", secret="s", ns_list=["a.b"])


def test_update_ns_failure_status(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(200, json={"status": "ERROR", "message": "invalid"}))
    with pytest.raises(PorkbunDnsError, match="status != SUCCESS"):
        update_porkbun_ns("example.com", api_key="k", secret="s", ns_list=["a.b"])
