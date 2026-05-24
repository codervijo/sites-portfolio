"""Tests for v25.D — comprehensive CF token diagnostic + GSC 403 parsing.

Covers:
  - cloudflare.diagnose_token happy path (all permissions present)
  - diagnose_token: account-permission gap (Pages:Edit missing)
  - diagnose_token: zone-permission gap (DNS:Edit missing on one zone)
  - diagnose_token: token-invalid (HTTP 401 from /user/tokens/verify)
  - diagnose_token: zone enumeration fails
  - gsc_admin.classify_403: ACCESS_TOKEN_SCOPE_INSUFFICIENT branch
  - gsc_admin.classify_403: SERVICE_DISABLED with consumer project
  - gsc_admin.classify_403: SERVICE_DISABLED without consumer
  - gsc_admin.classify_403: REFRESH_TOKEN_REVOKED branch
  - gsc_admin.classify_403: unknown 403 → UNKNOWN cause
  - gsc_admin.classify_403: message-text fallback (no details array)
  - gsc_admin.classify_403: malformed JSON gracefully handled

All HTTP stubbed via httpx.MockTransport. No real CF or Google traffic.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import cloudflare, gsc_admin
from portfolio.cloudflare import (
    API_BASE,
    AccountDiag,
    CloudflareAPIError,
    TokenDiagnostic,
    ZoneDiag,
    diagnose_token,
)
from portfolio.gsc_admin import (
    GSC_403_INSUFFICIENT_SCOPE,
    GSC_403_INVALID_GRANT,
    GSC_403_SERVICE_DISABLED,
    GSC_403_UNKNOWN,
    classify_403,
)


def _client_for(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=API_BASE,
        transport=transport,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )


# ---- diagnose_token --------------------------------------------------


def test_diagnose_token_happy_path():
    """All probes succeed; no missing permissions."""
    def handler(req):
        path = req.url.path
        if path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={
                "success": True,
                "result": {"status": "active", "id": "tok1"},
            })
        if path == "/client/v4/accounts":
            return httpx.Response(200, json={
                "success": True,
                "result": [{"id": "acct1", "name": "TestAccount"}],
            })
        if path.endswith("/pages/projects"):
            return httpx.Response(200, json={"success": True, "result": []})
        if path.endswith("/workers/services"):
            return httpx.Response(200, json={"success": True, "result": []})
        if path == "/client/v4/accounts/acct1":
            return httpx.Response(200, json={"success": True, "result": {"id": "acct1"}})
        if path == "/client/v4/zones":
            return httpx.Response(200, json={
                "success": True,
                "result": [{"id": "zone1", "name": "example.com"}],
            })
        if req.method == "POST" and "/dns_records" in path:
            # write-probe with TTL=2 — return 400 (auth passed, validation rejected)
            return httpx.Response(400, json={
                "success": False, "errors": [{"code": 9021, "message": "TTL invalid"}],
            })
        return httpx.Response(404, text=f"unexpected {req.method} {path}")

    client = _client_for(handler)
    diag = diagnose_token(client=client)

    assert isinstance(diag, TokenDiagnostic)
    assert diag.valid is True
    assert diag.token_status == "active"
    assert len(diag.accounts) == 1
    assert diag.accounts[0].name == "TestAccount"
    assert diag.accounts[0].has_pages_edit is True
    assert diag.accounts[0].has_workers_edit is True
    assert diag.accounts[0].has_account_settings_read is True
    assert len(diag.zones) == 1
    assert diag.zones[0].name == "example.com"
    assert diag.zones[0].has_dns_edit is True
    assert diag.missing_account_permissions == []
    assert diag.missing_zone_permissions == []


def test_diagnose_token_pages_edit_missing():
    """Pages probe returns 403 → has_pages_edit=False + entry in
    missing_account_permissions."""
    def handler(req):
        path = req.url.path
        if path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"success": True, "result": {"status": "active"}})
        if path == "/client/v4/accounts":
            return httpx.Response(200, json={
                "success": True,
                "result": [{"id": "acct1", "name": "TestAccount"}],
            })
        if path.endswith("/pages/projects"):
            return httpx.Response(403, json={"success": False})
        if path.endswith("/workers/services"):
            return httpx.Response(200, json={"success": True, "result": []})
        if path == "/client/v4/accounts/acct1":
            return httpx.Response(200, json={"success": True, "result": {}})
        if path == "/client/v4/zones":
            return httpx.Response(200, json={"success": True, "result": []})
        return httpx.Response(404)

    client = _client_for(handler)
    diag = diagnose_token(client=client)

    assert diag.accounts[0].has_pages_edit is False
    assert any("Pages:Edit" in p for p in diag.missing_account_permissions)


def test_diagnose_token_zone_dns_edit_missing():
    """One zone's write-probe returns 403 → entry in missing_zone_permissions."""
    def handler(req):
        path = req.url.path
        if path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"success": True, "result": {"status": "active"}})
        if path == "/client/v4/accounts":
            return httpx.Response(200, json={"success": True, "result": []})
        if path == "/client/v4/zones":
            return httpx.Response(200, json={
                "success": True,
                "result": [
                    {"id": "zoneA", "name": "alpha.example"},
                    {"id": "zoneB", "name": "beta.example"},
                ],
            })
        if req.method == "POST" and "/zones/zoneA/dns_records" in path:
            return httpx.Response(400, json={"success": False})  # has DNS:Edit
        if req.method == "POST" and "/zones/zoneB/dns_records" in path:
            return httpx.Response(403, json={"success": False})  # missing
        return httpx.Response(404)

    client = _client_for(handler)
    diag = diagnose_token(client=client)

    assert len(diag.zones) == 2
    has_dns = {z.name: z.has_dns_edit for z in diag.zones}
    assert has_dns == {"alpha.example": True, "beta.example": False}
    assert diag.missing_zone_permissions == [("beta.example", "DNS:Edit")]


def test_diagnose_token_invalid_token():
    """/user/tokens/verify returns 401 → valid=False with hint."""
    def handler(req):
        return httpx.Response(401, json={"success": False})

    client = _client_for(handler)
    diag = diagnose_token(client=client)

    assert diag.valid is False
    assert diag.token_status == "invalid"
    assert diag.accounts == []
    assert any("token rejected" in p.lower() for p in diag.missing_account_permissions)


def test_diagnose_token_accounts_list_403():
    """/accounts returns 403 → token can't enumerate; per-zone probes
    still attempt."""
    def handler(req):
        path = req.url.path
        if path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"success": True, "result": {"status": "active"}})
        if path == "/client/v4/accounts":
            return httpx.Response(403, json={"success": False})
        if path == "/client/v4/zones":
            return httpx.Response(200, json={"success": True, "result": []})
        return httpx.Response(404)

    client = _client_for(handler)
    diag = diagnose_token(client=client)

    assert diag.accounts == []
    assert any("/accounts list returned HTTP 403" in p for p in diag.missing_account_permissions)


# ---- gsc_admin.classify_403 -----------------------------------------


def test_classify_403_access_token_scope_insufficient():
    body = """{
        "error": {
            "code": 403,
            "message": "Request had insufficient authentication scopes.",
            "status": "PERMISSION_DENIED",
            "details": [{
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
                "domain": "googleapis.com"
            }]
        }
    }"""
    cause, hint = classify_403(body)
    assert cause == GSC_403_INSUFFICIENT_SCOPE
    assert "lamill settings gsc auth --force" in hint


def test_classify_403_service_disabled_with_project():
    """SERVICE_DISABLED branch — surface the GCP console URL with
    project pre-populated."""
    body = """{
        "error": {
            "code": 403,
            "message": "Site Verification API has not been used in project 123456789 before or it is disabled.",
            "status": "PERMISSION_DENIED",
            "details": [{
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "SERVICE_DISABLED",
                "domain": "googleapis.com",
                "metadata": {
                    "service": "siteverification.googleapis.com",
                    "consumer": "projects/123456789"
                }
            }]
        }
    }"""
    cause, hint = classify_403(body)
    assert cause == GSC_403_SERVICE_DISABLED
    assert "123456789" in hint
    assert "siteverification.googleapis.com/overview" in hint
    assert "?project=123456789" in hint


def test_classify_403_service_disabled_without_project():
    """SERVICE_DISABLED without consumer metadata — generic URL,
    no project query param."""
    body = """{
        "error": {
            "details": [{
                "reason": "SERVICE_DISABLED"
            }]
        }
    }"""
    cause, hint = classify_403(body)
    assert cause == GSC_403_SERVICE_DISABLED
    assert "Site Verification API not enabled" in hint
    assert "?project=" not in hint


def test_classify_403_refresh_token_revoked():
    body = """{
        "error": {
            "details": [{
                "reason": "REFRESH_TOKEN_REVOKED"
            }]
        }
    }"""
    cause, hint = classify_403(body)
    assert cause == GSC_403_INVALID_GRANT
    assert "lamill settings gsc auth --force" in hint


def test_classify_403_unknown_reason():
    body = """{
        "error": {
            "message": "Permission denied for some other reason.",
            "details": [{
                "reason": "SOMETHING_NEW"
            }]
        }
    }"""
    cause, hint = classify_403(body)
    assert cause == GSC_403_UNKNOWN
    assert "Permission denied" in hint


def test_classify_403_message_fallback_no_details():
    """Older API responses may omit `details`. Fall back to message-text
    keyword matching."""
    body = """{
        "error": {
            "message": "Request had insufficient authentication scopes."
        }
    }"""
    cause, hint = classify_403(body)
    assert cause == GSC_403_INSUFFICIENT_SCOPE


def test_classify_403_malformed_json_returns_unknown():
    """Defensive: if the body isn't valid JSON, return UNKNOWN with
    raw text in hint. Don't crash the deploy."""
    cause, hint = classify_403("not actually json {")
    assert cause == GSC_403_UNKNOWN
