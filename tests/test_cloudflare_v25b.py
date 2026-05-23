"""Tests for v25.B `probe_zone_write_capability` in cloudflare.py.

Covers the six response paths the probe distinguishes:
  - 403 → can_write=False (token lacks DNS:Edit on this zone)
  - 400 → can_write=True (auth passed; deliberately-invalid TTL rejected)
  - 401 → can_write=False (token globally invalid)
  - 200 with stray record → can_write=True + cleanup DELETE fires
  - 404 → raises CloudflareAPIError (zone not found)
  - 5xx → raises CloudflareAPIError (transient / unexpected)

Plus one request-shape test confirming the probe POSTs an invalid TTL.

All HTTP stubbed via `httpx.MockTransport`.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio.cloudflare import (
    API_BASE,
    CloudflareAPIError,
    ZoneWriteProbe,
    probe_zone_write_capability,
)


def _client_for(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=API_BASE,
        transport=transport,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )


def test_probe_403_returns_can_write_false():
    """Token lacks DNS:Edit on this zone — surface missing_scope."""
    def handler(req):
        assert req.method == "POST"
        assert req.url.path.endswith("/zones/zoneABC/dns_records")
        return httpx.Response(403, json={
            "success": False,
            "errors": [{"code": 10000, "message": "Authentication error"}],
        })

    client = _client_for(handler)
    result = probe_zone_write_capability("zoneABC", client=client)
    assert isinstance(result, ZoneWriteProbe)
    assert result.can_write is False
    assert result.missing_scope is not None
    assert "DNS:Edit" in result.missing_scope


def test_probe_400_returns_can_write_true():
    """Auth passed; CF rejected the deliberately-invalid TTL=2.
    can_write=True; missing_scope=None."""
    def handler(req):
        return httpx.Response(400, json={
            "success": False,
            "errors": [{
                "code": 1004,
                "message": "DNS Validation Error: TTL must be between 60 and 86400 seconds, or 1 for automatic.",
            }],
        })

    client = _client_for(handler)
    result = probe_zone_write_capability("zoneABC", client=client)
    assert result.can_write is True
    assert result.missing_scope is None


def test_probe_401_returns_can_write_false_with_token_hint():
    """Token globally invalid — distinct from 403 (zone-scoped)."""
    def handler(req):
        return httpx.Response(401, json={
            "success": False,
            "errors": [{"code": 10000, "message": "Invalid token"}],
        })

    client = _client_for(handler)
    result = probe_zone_write_capability("zoneABC", client=client)
    assert result.can_write is False
    assert result.missing_scope is not None
    assert "CF_API_TOKEN" in result.missing_scope


def test_probe_200_unexpected_creation_cleans_up():
    """If the probe payload somehow gets accepted (future API change?),
    the resulting record is deleted to honor the "no state change"
    contract. can_write=True."""
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path))
        if req.method == "POST":
            return httpx.Response(200, json={
                "success": True,
                "result": {"id": "stray123", "type": "TXT"},
            })
        if req.method == "DELETE":
            return httpx.Response(200, json={
                "success": True,
                "result": {"id": "stray123"},
            })
        return httpx.Response(404)

    client = _client_for(handler)
    result = probe_zone_write_capability("zoneABC", client=client)
    assert result.can_write is True
    # Cleanup DELETE fired.
    methods = [m for m, _ in seen]
    assert "DELETE" in methods
    delete_path = next(p for m, p in seen if m == "DELETE")
    assert delete_path.endswith("/dns_records/stray123")


def test_probe_404_raises():
    """Zone not found — surfaces as CloudflareAPIError so caller
    distinguishes from auth gap."""
    def handler(req):
        return httpx.Response(404, json={
            "success": False,
            "errors": [{"code": 7003, "message": "Could not route to /zones/.../dns_records"}],
        })

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError) as exc:
        probe_zone_write_capability("zoneABC", client=client)
    assert "404" in str(exc.value)
    assert "zone" in str(exc.value).lower()


def test_probe_500_raises():
    """Transient CF outage — propagate so caller can decide retry vs abort."""
    def handler(req):
        return httpx.Response(500, text="bad gateway")

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError) as exc:
        probe_zone_write_capability("zoneABC", client=client)
    assert "500" in str(exc.value)


def test_probe_request_uses_invalid_ttl():
    """The probe deliberately sends TTL=2 — invalid per CF spec
    (must be 1 or 60-86400). This ensures validation rejects the
    write, so we never actually create a record on tokens that have
    write permission."""
    import json as _json
    captured = {}

    def handler(req):
        captured["method"] = req.method
        captured["body"] = _json.loads(req.content.decode())
        # Simulate CF rejecting the bogus TTL with 400.
        return httpx.Response(400, json={"success": False, "errors": []})

    client = _client_for(handler)
    probe_zone_write_capability("zoneXYZ", client=client)
    assert captured["method"] == "POST"
    assert captured["body"]["ttl"] == 2
    assert captured["body"]["type"] == "TXT"
    assert "probe" in captured["body"]["name"].lower()


def test_probe_zonewriteprobe_unpacking():
    """ZoneWriteProbe is a dataclass; ensure the fields are accessible
    by name (rather than tuple positional unpack) so future expansion
    is safe."""
    probe = ZoneWriteProbe(can_write=True, missing_scope=None)
    assert probe.can_write is True
    assert probe.missing_scope is None

    failing = ZoneWriteProbe(can_write=False, missing_scope="X")
    assert failing.can_write is False
    assert failing.missing_scope == "X"
