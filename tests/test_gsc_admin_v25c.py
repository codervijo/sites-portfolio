"""Tests for v25.C — FILE-method GSC verification helpers in gsc_admin.py.

Covers:
  - get_verification_token(method="FILE") — request shape + token capture
  - get_verification_token(method="<bad>") — raises GSCAdminError
  - get_verification_token default is FILE (v25.A decision a)
  - write_verification_file happy path (Astro public/ exists)
  - write_verification_file raises when public/ missing (caller falls back)
  - write_verification_file is idempotent (re-write same content)
  - wait_for_verification_file_live succeeds first attempt
  - wait_for_verification_file_live succeeds after one retry
  - wait_for_verification_file_live exhausts budget (returns False)
  - wait_for_verification_file_live tolerates network errors mid-poll
  - verify_domain(method="FILE") — request shape (URL query + site payload)
  - verify_domain(method="FILE") timeout uses FILE-specific hint
  - verify_domain rejects unknown method values

OAuth is mocked at `gsc_admin._access_token`. No real GSC traffic.
"""
from __future__ import annotations

import json

import httpx
import pytest

from portfolio import gsc_admin
from portfolio.gsc_admin import (
    GSCAdminError,
    VerificationFailedError,
    VERIFICATION_METHOD_DNS_TXT,
    VERIFICATION_METHOD_FILE,
    _FILE_LIVE_INTERVALS_S,
    _PROPAGATION_INTERVALS_S,
    get_verification_token,
    verify_domain,
    wait_for_verification_file_live,
    write_verification_file,
)


@pytest.fixture(autouse=True)
def _mock_auth(monkeypatch):
    monkeypatch.setattr(gsc_admin, "_access_token", lambda: "stub-token")


# ---- get_verification_token (FILE method + default) ------------------


def test_get_verification_token_default_is_file_method():
    """v25.A decision (a) — FILE is the default. Verifies the request
    shape (SITE type + https URL identifier) and that the returned
    filename comes back unchanged."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"token": "google1234abc.html", "method": "FILE"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = get_verification_token("example.com", client=client)

    assert token == "google1234abc.html"
    assert seen["body"]["verificationMethod"] == "FILE"
    assert seen["body"]["site"] == {
        "type": "SITE",
        "identifier": "https://example.com/",
    }


def test_get_verification_token_explicit_file_method():
    """Same as above but with method explicit — pins the API shape."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["verificationMethod"] == "FILE"
        assert body["site"]["type"] == "SITE"
        return httpx.Response(
            200, json={"token": "googleABC.html", "method": "FILE"},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = get_verification_token(
        "example.com", method=VERIFICATION_METHOD_FILE, client=client,
    )
    assert token == "googleABC.html"


def test_get_verification_token_unknown_method_raises():
    """Caller passes a bogus method string — fail before hitting Google
    (cheap validation, clear error)."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(GSCAdminError, match="Unknown verification method"):
        get_verification_token("example.com", method="HTML_META", client=client)


# ---- write_verification_file ----------------------------------------


def test_write_verification_file_creates_file_with_google_spec_body(tmp_path):
    """Google's spec: file body is `google-site-verification: <token>\\n`."""
    public = tmp_path / "public"
    public.mkdir()

    path = write_verification_file(tmp_path, "google1234abc.html")

    assert path == public / "google1234abc.html"
    assert path.is_file()
    assert path.read_text() == "google-site-verification: google1234abc.html\n"


def test_write_verification_file_raises_when_no_public_dir(tmp_path):
    """HG static-only / non-Astro projects don't have public/. Caller
    sees this error and falls back to DNS_TXT method."""
    # tmp_path exists but no public/ subdir
    with pytest.raises(GSCAdminError, match="public/ dir"):
        write_verification_file(tmp_path, "googleABC.html")


def test_write_verification_file_is_idempotent(tmp_path):
    """Re-running deploy re-runs Step 9 → write happens twice. Same
    content both times (no content drift)."""
    public = tmp_path / "public"
    public.mkdir()

    p1 = write_verification_file(tmp_path, "googleXYZ.html")
    body_1 = p1.read_text()
    p2 = write_verification_file(tmp_path, "googleXYZ.html")
    body_2 = p2.read_text()

    assert p1 == p2
    assert body_1 == body_2


# ---- wait_for_verification_file_live --------------------------------


def test_wait_for_verification_file_live_succeeds_first_attempt():
    """File already live (CF auto-deploy finished in <5s) — single HEAD
    returns 200, no sleeps."""
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.method == "HEAD"
        assert "example.com/googleABC.html" in str(request.url)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ok = wait_for_verification_file_live(
        "example.com", "googleABC.html",
        client=client, sleep=lambda s: sleeps.append(s),
    )
    assert ok is True
    assert calls["n"] == 1
    assert sleeps == []


def test_wait_for_verification_file_live_succeeds_after_one_retry():
    """File reachable on 2nd HEAD (deploy completed during the first
    interval). Exactly one sleep, then success."""
    sleeps: list[float] = []
    responses = iter([
        httpx.Response(404),
        httpx.Response(200),
    ])

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ok = wait_for_verification_file_live(
        "example.com", "googleABC.html",
        client=client, sleep=lambda s: sleeps.append(s),
    )
    assert ok is True
    assert sleeps == [_FILE_LIVE_INTERVALS_S[0]]


def test_wait_for_verification_file_live_exhausts_budget_returns_false():
    """File never goes live within the poll budget. Returns False so
    caller can soft-fail Step 9 (deploy not ready; operator re-runs
    later)."""
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ok = wait_for_verification_file_live(
        "example.com", "googleABC.html",
        client=client, sleep=lambda s: sleeps.append(s),
    )
    assert ok is False
    assert calls["n"] == len(_FILE_LIVE_INTERVALS_S) + 1
    assert sleeps == list(_FILE_LIVE_INTERVALS_S)


def test_wait_for_verification_file_live_tolerates_network_errors():
    """Transient connection error mid-poll shouldn't abort the loop
    — treat as "not reachable yet" and retry. Eventually 200."""
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if not sleeps:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ok = wait_for_verification_file_live(
        "example.com", "googleABC.html",
        client=client, sleep=lambda s: sleeps.append(s),
    )
    assert ok is True
    assert len(sleeps) == 1


# ---- verify_domain with method=FILE ---------------------------------


def test_verify_domain_file_method_request_shape():
    """v25.C — `verify_domain(method=FILE)` POSTs to
    `webResource?verificationMethod=FILE` with SITE-type identifier."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "verified"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verify_domain(
        "example.com",
        method=VERIFICATION_METHOD_FILE,
        client=client,
        sleep=lambda s: None,
    )
    assert "verificationMethod=FILE" in seen["url"]
    assert seen["body"]["site"] == {
        "type": "SITE", "identifier": "https://example.com/",
    }


def test_verify_domain_file_timeout_uses_file_specific_hint():
    """When FILE-method verify exhausts budget, the operator-facing hint
    mentions the file/edge-cache cause — not "TXT propagation"."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Failed to verify the site")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(VerificationFailedError) as exc:
        verify_domain(
            "example.com",
            method=VERIFICATION_METHOD_FILE,
            client=client,
            sleep=lambda s: None,
        )
    msg = str(exc.value)
    assert "FILE verification" in msg
    assert "Verification file" in msg or "edge cache" in msg.lower()


def test_verify_domain_rejects_unknown_method():
    """Cheap validation up front — caller passes a typo."""
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    with pytest.raises(GSCAdminError, match="Unknown verification method"):
        verify_domain(
            "example.com", method="HTML_META", client=client,
        )


def test_verify_domain_dns_txt_still_works():
    """v24.B regression — explicit method=DNS_TXT preserves the old
    request shape (INET_DOMAIN identifier + verificationMethod=DNS_TXT)."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "verified"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    verify_domain(
        "example.com",
        method=VERIFICATION_METHOD_DNS_TXT,
        client=client,
        sleep=lambda s: None,
    )
    assert "verificationMethod=DNS_TXT" in seen["url"]
    assert seen["body"]["site"] == {
        "type": "INET_DOMAIN", "identifier": "example.com",
    }
