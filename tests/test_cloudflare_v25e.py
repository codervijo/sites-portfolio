"""Tests for v25.E — `probe_zone_cache_purge` + `probe_zone_settings_edit`
in cloudflare.py. Mirrors the v25.B test shape (test_cloudflare_v25b.py).

Closes the 2026-05-27 check-token gap: pre-fix, `diagnose_token` only
probed DNS:Edit per zone, so a token missing Zone:Cache Purge or Zone
Settings:Edit returned ✓ from `settings cloudflare check-token` and
then 401'd mid-fix (CHECK_057, CHECK_150).

All HTTP stubbed via `httpx.MockTransport`.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio.cloudflare import (
    API_BASE,
    CloudflareAPIError,
    ZoneWriteProbe,
    probe_zone_cache_purge,
    probe_zone_settings_edit,
)


def _client_for(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=API_BASE,
        transport=transport,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )


# ---- probe_zone_cache_purge ----


def test_cache_purge_probe_400_returns_can_write_true():
    """CF rejects the empty `files` payload → auth passed."""
    def handler(req):
        assert req.method == "POST"
        assert req.url.path.endswith("/zones/zoneABC/purge_cache")
        return httpx.Response(400, json={
            "success": False,
            "errors": [{"code": 1015, "message": "files array empty"}],
        })

    client = _client_for(handler)
    result = probe_zone_cache_purge("zoneABC", client=client)
    assert isinstance(result, ZoneWriteProbe)
    assert result.can_write is True
    assert result.missing_scope is None


def test_cache_purge_probe_200_returns_can_write_true():
    """If CF accepts an empty purge as a no-op (200), it's still
    auth-confirming and state-neutral."""
    def handler(req):
        return httpx.Response(200, json={"success": True, "result": {}})

    client = _client_for(handler)
    result = probe_zone_cache_purge("zoneABC", client=client)
    assert result.can_write is True
    assert result.missing_scope is None


def test_cache_purge_probe_403_returns_can_write_false():
    """Token lacks Zone:Cache Purge on this zone — kwizicle.com case."""
    def handler(req):
        return httpx.Response(403, json={
            "success": False,
            "errors": [{"code": 10000, "message": "Authentication error"}],
        })

    client = _client_for(handler)
    result = probe_zone_cache_purge("zoneABC", client=client)
    assert result.can_write is False
    assert result.missing_scope is not None
    assert "Cache Purge" in result.missing_scope


def test_cache_purge_probe_401_returns_can_write_false_with_token_hint():
    def handler(req):
        return httpx.Response(401, json={"success": False})

    client = _client_for(handler)
    result = probe_zone_cache_purge("zoneABC", client=client)
    assert result.can_write is False
    assert "CF_API_TOKEN" in (result.missing_scope or "")


def test_cache_purge_probe_404_raises():
    def handler(req):
        return httpx.Response(404, json={"success": False})

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="zone not found"):
        probe_zone_cache_purge("zoneXYZ", client=client)


def test_cache_purge_probe_5xx_raises():
    def handler(req):
        return httpx.Response(503, text="Service Unavailable")

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="HTTP 503"):
        probe_zone_cache_purge("zoneABC", client=client)


def test_cache_purge_probe_request_uses_empty_files_array():
    """Pinning the probe payload — the test confirms we send the
    intended no-op payload, not a real purge request."""
    seen = []

    def handler(req):
        import json
        seen.append(json.loads(req.content.decode()))
        return httpx.Response(400, json={"success": False})

    client = _client_for(handler)
    probe_zone_cache_purge("zoneABC", client=client)
    assert seen == [{"files": []}]


# ---- probe_zone_settings_edit ----


def test_zone_settings_probe_400_returns_can_write_true():
    """CF rejects the bogus enum value → auth passed."""
    def handler(req):
        assert req.method == "PATCH"
        assert req.url.path.endswith(
            "/zones/zoneABC/settings/development_mode"
        )
        return httpx.Response(400, json={
            "success": False,
            "errors": [{"code": 1006, "message": "Invalid value for setting"}],
        })

    client = _client_for(handler)
    result = probe_zone_settings_edit("zoneABC", client=client)
    assert result.can_write is True
    assert result.missing_scope is None


def test_zone_settings_probe_403_returns_can_write_false():
    """Token lacks Zone Settings:Edit on this zone — blocks CHECK_150."""
    def handler(req):
        return httpx.Response(403, json={"success": False})

    client = _client_for(handler)
    result = probe_zone_settings_edit("zoneABC", client=client)
    assert result.can_write is False
    assert "Zone Settings:Edit" in (result.missing_scope or "")


def test_zone_settings_probe_401_returns_can_write_false_with_token_hint():
    def handler(req):
        return httpx.Response(401, json={"success": False})

    client = _client_for(handler)
    result = probe_zone_settings_edit("zoneABC", client=client)
    assert result.can_write is False
    assert "CF_API_TOKEN" in (result.missing_scope or "")


def test_zone_settings_probe_404_raises():
    def handler(req):
        return httpx.Response(404, json={"success": False})

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="zone or setting not found"):
        probe_zone_settings_edit("zoneXYZ", client=client)


def test_zone_settings_probe_unexpected_200_raises():
    """If CF ever accepts the bogus enum (shouldn't happen — value is
    validated as on/off), raise so the probe gets re-pointed at a
    different setting before any real harm. Defensive surface — fails
    loud rather than silently passing a state-changing probe."""
    def handler(req):
        return httpx.Response(200, json={"success": True})

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="HTTP 200"):
        probe_zone_settings_edit("zoneABC", client=client)


def test_zone_settings_probe_request_uses_bogus_enum():
    seen = []

    def handler(req):
        import json
        seen.append((req.method, json.loads(req.content.decode())))
        return httpx.Response(400, json={"success": False})

    client = _client_for(handler)
    probe_zone_settings_edit("zoneABC", client=client)
    assert seen == [("PATCH", {"value": "invalid"})]
