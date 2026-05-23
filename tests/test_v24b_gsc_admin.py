"""Tests for v24.B — gsc_admin.py (Site Verification + Webmasters API
client used by `new deploy` at Step 9+ to auto-provision GSC properties).

All HTTP stubbed via `httpx.MockTransport`. OAuth is mocked at the
`gsc_admin._access_token` boundary so we never need real GSC
credentials in the suite.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from portfolio import gsc_admin
from portfolio.gsc_admin import (
    GSCAdminError,
    VerificationFailedError,
    _PROPAGATION_INTERVALS_S,
    add_site,
    get_verification_token,
    list_sites,
    list_sitemaps,
    submit_sitemap,
    verify_domain,
)


@pytest.fixture(autouse=True)
def _mock_auth(monkeypatch):
    """All tests use a stub access token so no real GSC auth fires."""
    monkeypatch.setattr(gsc_admin, "_access_token", lambda: "stub-token")


# ---- get_verification_token ----------------------------------------


def test_get_verification_token_returns_txt_value():
    """v25.C — DNS_TXT path preserved as explicit method. (Default
    changed to FILE in v25.C; this test pins the DNS_TXT request
    shape Google's Site Verification API expects.)"""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/siteVerification/v1/token"
        body = json.loads(request.content)
        assert body["verificationMethod"] == "DNS_TXT"
        assert body["site"] == {
            "type": "INET_DOMAIN",
            "identifier": "example.com",
        }
        return httpx.Response(
            200,
            json={
                "token": "google-site-verification=hX9abc...",
                "method": "DNS_TXT",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = get_verification_token("example.com", method="DNS_TXT", client=client)
    assert token == "google-site-verification=hX9abc..."


def test_get_verification_token_raises_on_403():
    """Insufficient scope (operator's token still on old
    webmasters.readonly) → GSCAdminError with the HTTP detail so the
    deploy pipeline can surface the re-consent hint."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"status": "PERMISSION_DENIED"}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError, match="HTTP 403"):
        get_verification_token("example.com", client=client)


def test_get_verification_token_raises_on_empty_token():
    """Defensive: 200 but the response is missing `token`. Don't
    return an empty string that downstream would write as the TXT
    value."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"method": "DNS_TXT"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError, match="empty token"):
        get_verification_token("example.com", client=client)


# ---- verify_domain (with poll loop) -------------------------------


def test_verify_domain_succeeds_first_attempt():
    """TXT was already in DNS and propagated — first call returns
    200, no sleeps."""
    sleeps: list[int] = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"id": "abc"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verify_domain(
        "example.com", client=client,
        sleep=lambda s: sleeps.append(s),
    )
    assert call_count["n"] == 1
    assert sleeps == []  # no propagation wait needed


def test_verify_domain_succeeds_after_one_propagation_wait():
    """DNS hadn't propagated on first call (400); succeeds on second.
    Should sleep exactly the first interval."""
    sleeps: list[int] = []
    responses = iter([
        httpx.Response(400, text="Failed to verify the site"),
        httpx.Response(200, json={"id": "abc"}),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verify_domain(
        "example.com", client=client,
        sleep=lambda s: sleeps.append(s),
    )
    assert sleeps == [_PROPAGATION_INTERVALS_S[0]]


def test_verify_domain_exhausts_poll_budget():
    """DNS never propagates — all attempts return 400. Final state
    raises VerificationFailedError with the operator-action hint."""
    sleeps: list[int] = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(400, text="Failed to verify the site")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(VerificationFailedError) as exc_info:
        verify_domain(
            "example.com", client=client,
            sleep=lambda s: sleeps.append(s),
        )

    # Should have tried len(intervals) + 1 = 5 times, slept 4 times.
    assert call_count["n"] == len(_PROPAGATION_INTERVALS_S) + 1
    assert sleeps == list(_PROPAGATION_INTERVALS_S)
    msg = str(exc_info.value)
    assert "60s of polling" in msg  # sum(5+10+20+25)=60
    assert "lamill new deploy" in msg


def test_verify_domain_403_insufficient_scope_does_not_poll():
    """insufficient_scope 403 is a permanent error (operator needs to
    re-consent OAuth), not a propagation issue. Raise immediately
    without burning the poll budget."""
    sleeps: list[int] = []
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            403, text='{"error":{"message":"insufficient_scope"}}',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError, match="insufficient_scope"):
        verify_domain(
            "example.com", client=client,
            sleep=lambda s: sleeps.append(s),
        )

    assert call_count["n"] == 1  # didn't retry
    assert sleeps == []


def test_verify_domain_actionable_hint_in_403_message():
    """The 403 error should include the `lamill settings gsc auth
    --force` re-consent hint so operator knows what to do."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, text='{"error":{"message":"insufficient_scope"}}',
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError) as exc_info:
        verify_domain("example.com", client=client, sleep=lambda s: None)
    msg = str(exc_info.value)
    assert "lamill settings gsc auth --force" in msg


# ---- add_site -----------------------------------------------------


def test_add_site_returns_true_when_newly_added():
    """Property not in sites.list() → PUT succeeds → return True."""
    calls: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # raw_path is the wire form (URL-encoded). httpx decodes for
        # `.path` so use raw_path to verify the encoding we want.
        calls.append((request.method, request.url.raw_path))
        if request.method == "GET":
            # Idempotency probe — returns empty list (no existing properties)
            return httpx.Response(200, json={})
        if request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = add_site("example.com", client=client)
    assert result is True
    assert calls[0] == ("GET", b"/webmasters/v3/sites")
    # PUT path URL-encodes the colon in sc-domain:
    assert calls[1] == (
        "PUT", b"/webmasters/v3/sites/sc-domain%3Aexample.com",
    )


def test_add_site_returns_false_when_already_exists():
    """Idempotency: property already in sites.list() → no PUT, return False."""
    put_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "siteEntry": [
                        {
                            "siteUrl": "sc-domain:example.com",
                            "permissionLevel": "siteOwner",
                        }
                    ]
                },
            )
        if request.method == "PUT":
            put_count["n"] += 1
            return httpx.Response(204)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = add_site("example.com", client=client)
    assert result is False
    assert put_count["n"] == 0  # PUT skipped


def test_add_site_raises_on_put_403():
    """PUT 403 (unverified domain — caller forgot verify_domain step)
    → GSCAdminError so the deploy pipeline can surface it."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={})
        return httpx.Response(403, text="Domain not verified")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError, match="HTTP 403"):
        add_site("example.com", client=client)


def test_list_sites_returns_site_entries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "siteEntry": [
                    {"siteUrl": "sc-domain:a.com", "permissionLevel": "siteOwner"},
                    {"siteUrl": "https://b.com/", "permissionLevel": "siteOwner"},
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sites = list_sites(client=client)
    assert len(sites) == 2
    assert sites[0]["siteUrl"] == "sc-domain:a.com"


# ---- submit_sitemap -----------------------------------------------


def test_submit_sitemap_returns_true_when_newly_submitted():
    calls: list[tuple[str, bytes]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.raw_path))
        if request.method == "GET":
            return httpx.Response(200, json={})  # no sitemaps yet
        if request.method == "PUT":
            return httpx.Response(204)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = submit_sitemap(
        "example.com", "https://example.com/sitemap.xml", client=client,
    )
    assert result is True
    # Sitemap PUT path includes both encoded site URI and sitemap URL.
    assert b"/sitemaps/" in calls[1][1]
    # `:` and `/` should be URL-encoded inside the path component
    # (httpx's raw_path is bytes — wire form).
    assert b"https%3A%2F%2Fexample.com%2Fsitemap.xml" in calls[1][1]


def test_submit_sitemap_returns_false_when_already_submitted():
    """Idempotency: sitemap URL already in list → no PUT, return False."""
    put_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "sitemap": [
                        {
                            "path": "https://example.com/sitemap.xml",
                            "lastSubmitted": "2026-05-20T00:00:00Z",
                        }
                    ]
                },
            )
        if request.method == "PUT":
            put_count["n"] += 1
            return httpx.Response(204)
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = submit_sitemap(
        "example.com", "https://example.com/sitemap.xml", client=client,
    )
    assert result is False
    assert put_count["n"] == 0


def test_submit_sitemap_raises_on_put_404():
    """GSC returns 404 when the sitemap URL doesn't actually resolve.
    Surface as GSCAdminError so deploy pipeline can soft-skip with a
    "site doesn't expose /sitemap.xml" hint."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={})
        return httpx.Response(404, text="Sitemap not accessible")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GSCAdminError, match="HTTP 404"):
        submit_sitemap(
            "example.com", "https://example.com/sitemap.xml", client=client,
        )


def test_list_sitemaps_returns_path_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "sitemap": [
                    {
                        "path": "https://example.com/sitemap.xml",
                        "lastSubmitted": "2026-05-20T00:00:00Z",
                        "errors": 0,
                        "warnings": 0,
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sitemaps = list_sitemaps("example.com", client=client)
    assert sitemaps[0]["path"] == "https://example.com/sitemap.xml"
    assert sitemaps[0]["lastSubmitted"] == "2026-05-20T00:00:00Z"


# ---- gsc.py SCOPES bump -------------------------------------------


def test_gsc_scopes_include_webmasters_write_and_siteverification():
    """v24.B locked decision (e) — gsc.SCOPES bumped from
    webmasters.readonly to webmasters + siteverification. Verify the
    constant matches so the OAuth flow requests the right scopes."""
    from portfolio import gsc
    assert "https://www.googleapis.com/auth/webmasters" in gsc.SCOPES
    assert "https://www.googleapis.com/auth/siteverification" in gsc.SCOPES
    # Old readonly scope is intentionally dropped — `webmasters` is a
    # superset so all read paths still work.
    assert "https://www.googleapis.com/auth/webmasters.readonly" not in gsc.SCOPES
