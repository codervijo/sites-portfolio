"""Suite-wide isolation.

GA4 (v49.B): once the operator's real GA4 sign-in exists
(`~/lamill/ga4/token.json` + `GA4_ACCOUNT_ID`), any test that runs
`bootstrap()` without stubbing would create REAL GA4 properties — that
happened on 2026-11-09 (19 junk properties). Every test therefore starts
with GA4 pointed at an empty temp dir (`has_token()` → False) and with the
HTTP client refusing to reach Google. Tests that exercise GA4 monkeypatch
`has_token` / `_client` themselves; those overrides run after this fixture.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_ga4(monkeypatch, tmp_path_factory):
    from portfolio import ga4_admin

    d = tmp_path_factory.mktemp("ga4")
    monkeypatch.setattr(ga4_admin, "CONFIG_DIR", d)
    monkeypatch.setattr(ga4_admin, "CREDENTIALS_PATH", d / "credentials.json")
    monkeypatch.setattr(ga4_admin, "TOKEN_PATH", d / "token.json")

    def _no_network(client=None):
        if client is not None:
            return client
        raise RuntimeError("tests must not call the real GA4 Admin API — stub ga4_admin._client")

    monkeypatch.setattr(ga4_admin, "_client", _no_network)


@pytest.fixture(autouse=True)
def _isolate_email_routing(monkeypatch):
    """v50.B: CHECK_165 runs on any domain-shaped dir. Tests must never reach
    the real Cloudflare Email Routing API or public DNS — stub
    `email_routing.inspect` / pass clients instead."""
    from portfolio import email_routing

    def _no_network(*a, **k):
        raise email_routing.EmailRoutingError(
            "tests must not call the real Cloudflare Email Routing API — stub it")

    monkeypatch.setattr(email_routing, "inspect", _no_network)
    monkeypatch.setattr(email_routing, "public_mx", _no_network)
