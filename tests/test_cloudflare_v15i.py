"""Tests for v15.I CF helpers in cloudflare.py.

Covers:
  - ensure_zone (existing zone via resolve_zone_id + GET, new zone via POST)
  - get_pages_project (200 + 404)
  - create_pages_project_with_git (200/201 + error mapping for GH App missing)
  - attach_pages_custom_domain (GET-then-POST idempotency)
  - latest_deployment_status + poll_build (success / failure / timeout)

All HTTP stubbed via `httpx.MockTransport`.
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from portfolio import cloudflare
from portfolio.cloudflare import (
    API_BASE,
    CloudflareAPIError,
    PagesProject,
    ZoneInfo,
    attach_pages_custom_domain,
    create_pages_project_with_git,
    ensure_zone,
    get_pages_project,
    latest_deployment_status,
    poll_build,
)


def _client_for(handler) -> httpx.Client:
    """Build a CF Client with auth header + a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=API_BASE,
        transport=transport,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )


# ---- ensure_zone ----


def test_ensure_zone_existing(tmp_path, monkeypatch):
    """When the zone is cacheable + already exists, ensure_zone
    fetches the full record (NS + status) without calling POST /zones."""
    # Stub cache to miss.
    monkeypatch.setattr(cloudflare, "_load_zones_cache", lambda: {})
    monkeypatch.setattr(cloudflare, "_save_zones_cache", lambda m: None)

    captured = []

    def handler(req):
        captured.append((req.method, str(req.url.path)))
        if req.method == "GET" and req.url.path.endswith("/zones"):
            return httpx.Response(200, json={
                "success": True,
                "result": [{"id": "zone123"}],
            })
        if req.method == "GET" and req.url.path.endswith("/zones/zone123"):
            return httpx.Response(200, json={
                "success": True,
                "result": {
                    "name": "example.com",
                    "name_servers": ["dom.ns.cloudflare.com", "kristina.ns.cloudflare.com"],
                    "status": "active",
                },
            })
        return httpx.Response(404, text=f"unexpected {req.method} {req.url.path}")

    client = _client_for(handler)
    info = ensure_zone("example.com", account_id="acct1", client=client)
    assert info.zone_id == "zone123"
    assert info.name == "example.com"
    assert info.name_servers == ["dom.ns.cloudflare.com", "kristina.ns.cloudflare.com"]
    assert info.status == "active"
    assert info.created is False


def test_ensure_zone_creates_new(monkeypatch):
    """resolve_zone_id raises 'No CF zone found' → ensure_zone POSTs."""
    monkeypatch.setattr(cloudflare, "_load_zones_cache", lambda: {})
    saved = {}
    monkeypatch.setattr(cloudflare, "_save_zones_cache",
                        lambda m: saved.update(m))

    def handler(req):
        if req.method == "GET" and req.url.path.endswith("/zones"):
            # Empty result → triggers "No CF zone found" error.
            return httpx.Response(200, json={"success": True, "result": []})
        if req.method == "POST" and req.url.path.endswith("/zones"):
            return httpx.Response(201, json={
                "success": True,
                "result": {
                    "id": "zone456",
                    "name": "newdomain.com",
                    "name_servers": ["a.ns.cloudflare.com", "b.ns.cloudflare.com"],
                    "status": "pending",
                },
            })
        return httpx.Response(404)

    client = _client_for(handler)
    info = ensure_zone("newdomain.com", account_id="acct1", client=client)
    assert info.created is True
    assert info.status == "pending"
    assert info.name_servers == ["a.ns.cloudflare.com", "b.ns.cloudflare.com"]
    assert saved.get("newdomain.com") == "zone456"


def test_ensure_zone_missing_account_id_when_create_needed(monkeypatch):
    monkeypatch.setattr(cloudflare, "_load_zones_cache", lambda: {})

    def handler(req):
        return httpx.Response(200, json={"success": True, "result": []})

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="no account_id supplied"):
        ensure_zone("newdomain.com", account_id=None, client=client)


# ---- get_pages_project ----


def test_get_pages_project_exists():
    def handler(req):
        if req.url.path.endswith("/accounts/acct/pages/projects/agesdk-dev"):
            return httpx.Response(200, json={
                "success": True,
                "result": {
                    "name": "agesdk-dev",
                    "domains": ["agesdk.dev"],
                    "production_branch": "main",
                    "source": {
                        "type": "github",
                        "config": {"owner": "codervijo", "repo_name": "agesdk-dev"},
                    },
                },
            })
        return httpx.Response(404)

    client = _client_for(handler)
    p = get_pages_project("agesdk-dev", account_id="acct", client=client)
    assert p is not None
    assert p.name == "agesdk-dev"
    assert "agesdk.dev" in p.domains
    assert p.source_owner == "codervijo"
    assert p.production_branch == "main"


def test_get_pages_project_404():
    def handler(req):
        return httpx.Response(404, text="not found")

    client = _client_for(handler)
    assert get_pages_project("missing", account_id="acct", client=client) is None


def test_get_pages_project_500_raises():
    def handler(req):
        return httpx.Response(500, text="boom")

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="HTTP 500"):
        get_pages_project("agesdk-dev", account_id="acct", client=client)


# ---- create_pages_project_with_git ----


def test_create_pages_project_happy():
    captured = {}

    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/accounts/acct/pages/projects"):
            import json
            captured["body"] = json.loads(req.read())
            return httpx.Response(201, json={
                "success": True,
                "result": {
                    "name": "agesdk-dev",
                    "domains": [],
                    "production_branch": "main",
                    "source": {
                        "type": "github",
                        "config": {"owner": "codervijo", "repo_name": "agesdk-dev"},
                    },
                },
            })
        return httpx.Response(404)

    client = _client_for(handler)
    p = create_pages_project_with_git(
        "agesdk-dev",
        account_id="acct",
        gh_owner="codervijo",
        gh_repo="agesdk-dev",
        client=client,
    )
    assert p.created is True
    assert p.name == "agesdk-dev"
    body = captured["body"]
    assert body["name"] == "agesdk-dev"
    assert body["production_branch"] == "main"
    assert body["source"]["type"] == "github"
    assert body["source"]["config"]["owner"] == "codervijo"
    assert body["build_config"]["build_command"] == "pnpm run build"
    assert body["build_config"]["destination_dir"] == "dist"


def test_create_pages_project_github_app_missing_error():
    """When CF returns the GH-App-not-connected error, surface the
    operator-actionable dashboard link in the exception message."""
    def handler(req):
        return httpx.Response(400, text=(
            '{"success":false,"errors":[{"code":8000007,"message":'
            '"GitHub integration not installed for this account"}]}'
        ))

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="GitHub App not connected"):
        create_pages_project_with_git(
            "agesdk-dev",
            account_id="acct",
            gh_owner="codervijo",
            gh_repo="agesdk-dev",
            client=client,
        )


# ---- attach_pages_custom_domain ----


def test_attach_custom_domain_new():
    """GET project returns domains=[]; attach POSTs new."""
    posted = {"count": 0}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={
                "success": True,
                "result": {
                    "name": "agesdk-dev",
                    "domains": [],
                    "production_branch": "main",
                    "source": {"config": {}},
                },
            })
        if req.method == "POST" and "/domains" in req.url.path:
            posted["count"] += 1
            return httpx.Response(201, json={"success": True, "result": {"id": "d1"}})
        return httpx.Response(404)

    client = _client_for(handler)
    attached = attach_pages_custom_domain(
        "agesdk-dev", "agesdk.dev", account_id="acct", client=client,
    )
    assert attached is True
    assert posted["count"] == 1


def test_attach_custom_domain_already_present():
    """GET returns domains=['agesdk.dev']; attach should skip POST."""
    posted = {"count": 0}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={
                "success": True,
                "result": {
                    "name": "agesdk-dev",
                    "domains": ["agesdk.dev"],
                    "production_branch": "main",
                    "source": {"config": {}},
                },
            })
        if req.method == "POST":
            posted["count"] += 1
            return httpx.Response(201, json={"success": True, "result": {}})
        return httpx.Response(404)

    client = _client_for(handler)
    attached = attach_pages_custom_domain(
        "agesdk-dev", "agesdk.dev", account_id="acct", client=client,
    )
    assert attached is False
    assert posted["count"] == 0


def test_attach_custom_domain_project_missing():
    """GET project returns 404 → raise so operator sees the cause."""
    def handler(req):
        return httpx.Response(404)

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="doesn't exist"):
        attach_pages_custom_domain(
            "missing", "agesdk.dev", account_id="acct", client=client,
        )


# ---- latest_deployment_status + poll_build ----


def test_latest_deployment_status_success():
    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "result": [{
                "id": "dep123",
                "latest_stage": {"name": "deploy", "status": "success"},
            }],
        })

    client = _client_for(handler)
    stage, status, dep_id = latest_deployment_status(
        "agesdk-dev", account_id="acct", client=client,
    )
    assert stage == "deploy"
    assert status == "success"
    assert dep_id == "dep123"


def test_latest_deployment_status_empty():
    def handler(req):
        return httpx.Response(200, json={"success": True, "result": []})

    client = _client_for(handler)
    stage, status, dep_id = latest_deployment_status(
        "agesdk-dev", account_id="acct", client=client,
    )
    assert stage == ""
    assert status is None
    assert dep_id is None


def test_poll_build_terminal_quickly(monkeypatch):
    """poll_build should return immediately when first poll returns success."""
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "result": [{
                "id": "dep1",
                "latest_stage": {"name": "deploy", "status": "success"},
            }],
        })

    client = _client_for(handler)
    final, dep_id = poll_build(
        "agesdk-dev", account_id="acct", timeout_s=10, interval_s=1,
        client=client,
    )
    assert final == "success"
    assert dep_id == "dep1"


def test_poll_build_polls_until_terminal(monkeypatch):
    """First poll = building, second = success."""
    monkeypatch.setattr(time, "sleep", lambda s: None)
    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        status = "active" if state["calls"] == 1 else "success"
        return httpx.Response(200, json={
            "success": True,
            "result": [{
                "id": "dep1",
                "latest_stage": {"name": "build", "status": status},
            }],
        })

    client = _client_for(handler)
    captured = []

    def on_status(stage, status):
        captured.append((stage, status))

    final, dep_id = poll_build(
        "agesdk-dev", account_id="acct", timeout_s=10, interval_s=1,
        client=client, on_status=on_status,
    )
    assert final == "success"
    assert state["calls"] == 2
    assert captured == [("build", "active"), ("build", "success")]


def test_poll_build_timeout(monkeypatch):
    """When status stays non-terminal, poll_build returns last
    observed status (or 'timeout' if never observed)."""
    # Make sleep deterministic: each call advances monotonic by 100s.
    state = {"now": 0.0}

    def fake_monotonic():
        return state["now"]

    def fake_sleep(s):
        state["now"] += 100

    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    monkeypatch.setattr(time, "sleep", fake_sleep)

    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "result": [{
                "id": "depX",
                "latest_stage": {"name": "build", "status": "active"},
            }],
        })

    client = _client_for(handler)
    final, dep_id = poll_build(
        "agesdk-dev", account_id="acct", timeout_s=200, interval_s=50,
        client=client,
    )
    # Last-observed status, even non-terminal.
    assert final == "active"
    assert dep_id == "depX"
