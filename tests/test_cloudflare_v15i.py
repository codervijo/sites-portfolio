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


def test_get_pages_project_captures_suffixed_subdomain():
    """Regression (scopeguard.xyz, 2026-05-31): CF can assign a project a
    *.pages.dev hostname that ISN'T `<name>.pages.dev` (random suffix on
    name collision). The apex CNAME must target this real `subdomain`, so
    the parser must surface it. Pointing the CNAME at `<slug>.pages.dev`
    instead caused a permanent CF 1014."""
    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "result": {
                "name": "scopeguard",
                "domains": ["scopeguard.xyz"],
                "production_branch": "main",
                "subdomain": "scopeguard-abu.pages.dev",
                "source": {"type": "github",
                           "config": {"owner": "codervijo", "repo_name": "scopeguard"}},
            },
        })

    p = get_pages_project("scopeguard", account_id="acct", client=_client_for(handler))
    assert p is not None
    assert p.subdomain == "scopeguard-abu.pages.dev"
    # the slug guess would have been wrong:
    assert p.subdomain != f"{p.name}.pages.dev"


def test_get_pages_project_subdomain_absent_is_none():
    def handler(req):
        return httpx.Response(200, json={
            "success": True,
            "result": {"name": "x", "domains": [], "production_branch": "main",
                       "source": {"type": "github", "config": {}}},
        })

    p = get_pages_project("x", account_id="acct", client=_client_for(handler))
    assert p is not None and p.subdomain is None


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


def test_trigger_pages_deployment_returns_deployment_id():
    """v25 follow-up (2026-05-23) — explicit deployment trigger after
    Pages-project creation. CF's POST /pages/projects (in Step 5)
    doesn't auto-build the way the dashboard wizard does, so without
    this trigger fresh deploys end up project-created-but-never-built."""
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, req.content.decode() if req.content else ""))
        assert req.method == "POST"
        assert req.url.path.endswith("/pages/projects/myproj/deployments")
        return httpx.Response(200, json={
            "success": True,
            "result": {"id": "dep_abc123", "stage": "queued"},
        })

    from portfolio.cloudflare import trigger_pages_deployment
    client = _client_for(handler)
    dep_id = trigger_pages_deployment(
        "myproj", account_id="acct", branch="main", client=client,
    )
    assert dep_id == "dep_abc123"
    assert len(seen) == 1
    # Body should include branch.
    import json as _json
    assert _json.loads(seen[0][2]) == {"branch": "main"}


def test_trigger_pages_deployment_raises_on_non_2xx():
    def handler(req):
        return httpx.Response(404, json={
            "success": False,
            "errors": [{"code": 1, "message": "project not found"}],
        })

    from portfolio.cloudflare import trigger_pages_deployment
    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="HTTP 404"):
        trigger_pages_deployment(
            "missing", account_id="acct", client=client,
        )


def test_attach_custom_domain_handles_400_code_8000018_as_already_added():
    """2026-05-23 — CF returns 400 + error code 8000018 ('You have
    already added this custom domain') when the domain was attached
    on a prior deploy but isn't in the project's `domains[]` array
    (transient/pending state). The GET-then-POST idempotency probe
    misses it, but the POST response carries the right signal —
    treat as success (already attached), not failure."""
    def handler(req):
        if req.method == "GET" and "/pages/projects/myproj" in req.url.path:
            # Project exists but `domains[]` doesn't include our hostname.
            return httpx.Response(200, json={
                "success": True,
                "result": {
                    "name": "myproj",
                    "domains": [],          # empty — domain not visible here
                    "production_branch": "main",
                    "source": None,
                    "latest_deployment": None,
                },
            })
        if req.method == "POST" and "/domains" in req.url.path:
            # CF rejects because the domain IS attached, just not in
            # the array our GET saw.
            return httpx.Response(400, json={
                "result": None,
                "success": False,
                "errors": [{
                    "code": 8000018,
                    "message": "You have already added this custom domain. "
                               "Select another custom domain or check your "
                               "project configuration.",
                }],
                "messages": [],
            })
        return httpx.Response(404)

    client = _client_for(handler)
    attached = attach_pages_custom_domain(
        "myproj", "permittruck.xyz", account_id="acct", client=client,
    )
    # `attached=False` means "already attached" (no work to do); the
    # CLI renders this as `✓ permittruck.xyz already attached, skipping`.
    assert attached is False


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


# ---- v15.R — DNS records list/delete + conflict purge ----


def test_list_dns_records():
    from portfolio.cloudflare import list_dns_records

    def handler(req):
        if req.method == "GET" and req.url.path.endswith("/zones/z1/dns_records"):
            return httpx.Response(200, json={
                "success": True,
                "result": [
                    {"id": "r1", "type": "A", "name": "example.com",
                     "content": "1.2.3.4", "proxied": True},
                    {"id": "r2", "type": "CNAME", "name": "www.example.com",
                     "content": "example.com", "proxied": False},
                ],
            })
        return httpx.Response(404)

    client = _client_for(handler)
    records = list_dns_records("z1", client=client)
    assert len(records) == 2
    assert records[0].type == "A"
    assert records[0].name == "example.com"
    assert records[0].content == "1.2.3.4"


def test_delete_dns_record():
    from portfolio.cloudflare import delete_dns_record

    def handler(req):
        if req.method == "DELETE" and req.url.path.endswith("/zones/z1/dns_records/r99"):
            return httpx.Response(200, json={"success": True, "result": {"id": "r99"}})
        return httpx.Response(404)

    client = _client_for(handler)
    delete_dns_record("z1", "r99", client=client)  # no return value; no exception = pass


def test_purge_conflicting_root_records_removes_a_aaaa_cname_on_root_and_wildcard():
    from portfolio.cloudflare import purge_conflicting_root_records

    deleted_ids: list[str] = []

    def handler(req):
        if req.method == "GET" and req.url.path.endswith("/zones/z1/dns_records"):
            return httpx.Response(200, json={
                "success": True,
                "result": [
                    # All conflicting (root + wildcard + www, A/AAAA/CNAME):
                    {"id": "r1", "type": "A", "name": "agesdk.dev",
                     "content": "44.227.76.166", "proxied": True},
                    {"id": "r2", "type": "AAAA", "name": "agesdk.dev",
                     "content": "::1", "proxied": True},
                    {"id": "r3", "type": "CNAME", "name": "*.agesdk.dev",
                     "content": "pixie.porkbun.com", "proxied": True},
                    {"id": "r4", "type": "CNAME", "name": "www.agesdk.dev",
                     "content": "pixie.porkbun.com", "proxied": True},
                    # NOT conflicting — preserved:
                    {"id": "r5", "type": "MX", "name": "agesdk.dev",
                     "content": "mail.example.com", "proxied": False},
                    {"id": "r6", "type": "TXT", "name": "agesdk.dev",
                     "content": "v=spf1 ...", "proxied": False},
                    {"id": "r7", "type": "A", "name": "blog.agesdk.dev",
                     "content": "5.6.7.8", "proxied": True},  # subdomain, not root
                ],
            })
        if req.method == "DELETE":
            rec_id = req.url.path.rsplit("/", 1)[-1]
            deleted_ids.append(rec_id)
            return httpx.Response(200, json={"success": True, "result": {"id": rec_id}})
        return httpx.Response(404)

    client = _client_for(handler)
    deleted = purge_conflicting_root_records("z1", "agesdk.dev", client=client)
    # Only r1-r4 deleted (root A, root AAAA, wildcard CNAME, www CNAME).
    assert sorted(deleted_ids) == ["r1", "r2", "r3", "r4"]
    assert len(deleted) == 4
    # MX/TXT/blog-subdomain preserved.
    assert "r5" not in deleted_ids
    assert "r6" not in deleted_ids
    assert "r7" not in deleted_ids


def test_purge_conflicting_root_records_empty_when_clean_zone():
    from portfolio.cloudflare import purge_conflicting_root_records

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={
                "success": True,
                "result": [
                    {"id": "r1", "type": "TXT", "name": "example.com",
                     "content": "v=spf1 ...", "proxied": False},
                ],
            })
        return httpx.Response(404)

    client = _client_for(handler)
    deleted = purge_conflicting_root_records("z1", "example.com", client=client)
    assert deleted == []


# ---- v15.P — Workers Service detection + custom domain attach ----


def test_get_workers_service_200():
    from portfolio.cloudflare import get_workers_service

    def handler(req):
        if req.url.path.endswith("/accounts/acct/workers/services/agesdk"):
            return httpx.Response(200, json={
                "success": True,
                "result": {
                    "id": "agesdk",
                    "modified_on": "2026-05-21T05:46:00Z",
                    "default_environment": {
                        "environment": "production",
                        "script": {
                            "id": "agesdk",
                            "has_assets": True,
                            "compatibility_date": "2026-05-20",
                            "deployment_id": "dep-abc",
                        },
                    },
                },
            })
        return httpx.Response(404)

    client = _client_for(handler)
    info = get_workers_service("agesdk", account_id="acct", client=client)
    assert info is not None
    assert info.name == "agesdk"
    assert info.has_assets is True
    assert info.compatibility_date == "2026-05-20"


def test_get_workers_service_404():
    from portfolio.cloudflare import get_workers_service

    def handler(req):
        return httpx.Response(404)

    client = _client_for(handler)
    assert get_workers_service("missing", account_id="acct", client=client) is None


def test_attach_workers_custom_domain_put_body():
    from portfolio.cloudflare import attach_workers_custom_domain

    captured = {}

    def handler(req):
        if req.method == "PUT" and req.url.path.endswith("/accounts/acct/workers/domains"):
            import json as _json
            captured["body"] = _json.loads(req.read())
            return httpx.Response(200, json={
                "success": True,
                "result": {"id": "dom1", "hostname": "agesdk.dev", "service": "agesdk"},
            })
        return httpx.Response(404)

    client = _client_for(handler)
    attached = attach_workers_custom_domain(
        "agesdk", "agesdk.dev",
        account_id="acct",
        zone_id="zone123",
        client=client,
    )
    assert attached is True
    body = captured["body"]
    assert body["service"] == "agesdk"
    assert body["hostname"] == "agesdk.dev"
    assert body["zone_id"] == "zone123"
    assert body["environment"] == "production"


def test_attach_workers_custom_domain_skips_put_when_already_attached():
    """v15.Q — GET-then-PUT idempotency. When the (hostname, service)
    pair already exists in the workers/domains list, skip PUT entirely
    (returns False) — avoids 403s for operators who attached via
    dashboard but lack write permission for the PUT endpoint."""
    from portfolio.cloudflare import attach_workers_custom_domain

    put_calls = {"n": 0}

    def handler(req):
        if req.method == "GET" and req.url.path.endswith("/accounts/acct/workers/domains"):
            return httpx.Response(200, json={
                "success": True,
                "result": [
                    {"hostname": "agesdk.dev", "service": "agesdk",
                     "zone_id": "zone123", "id": "existing-mapping"},
                ],
            })
        if req.method == "PUT":
            put_calls["n"] += 1
            return httpx.Response(403, text="should-not-be-called")
        return httpx.Response(404)

    client = _client_for(handler)
    attached = attach_workers_custom_domain(
        "agesdk", "agesdk.dev",
        account_id="acct",
        zone_id="zone123",
        client=client,
    )
    assert attached is False  # Already attached.
    assert put_calls["n"] == 0  # PUT was NOT called.


def test_attach_workers_custom_domain_403_raises():
    from portfolio.cloudflare import attach_workers_custom_domain, CloudflareAPIError

    def handler(req):
        return httpx.Response(403, text='{"success":false,"errors":[]}')

    client = _client_for(handler)
    with pytest.raises(CloudflareAPIError, match="HTTP 403"):
        attach_workers_custom_domain(
            "agesdk", "agesdk.dev",
            account_id="acct",
            zone_id="zone123",
            client=client,
        )


# ---- v15.N — probe_token_scopes ----


def test_probe_token_scopes_all_ok():
    """Happy path — every probe returns 200, scope_report.ok=True."""
    from portfolio.cloudflare import probe_token_scopes

    def handler(req):
        if req.url.path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={
                "success": True,
                "result": {"id": "tok1", "status": "active"},
            })
        if req.url.path.endswith("/accounts/acct/pages/projects"):
            return httpx.Response(200, json={"success": True, "result": []})
        if req.url.path.endswith("/zones"):
            return httpx.Response(200, json={"success": True, "result": []})
        if req.url.path.endswith("/accounts/acct"):
            return httpx.Response(200, json={"success": True, "result": {}})
        return httpx.Response(404)

    client = _client_for(handler)
    report = probe_token_scopes(account_id="acct", client=client)
    assert report.ok
    assert report.pages_read_ok
    assert report.zone_read_ok
    assert report.account_settings_read_ok
    assert report.missing == []


def test_probe_token_scopes_pages_403():
    """Operator's actual failure mode — Pages access not granted."""
    from portfolio.cloudflare import probe_token_scopes

    def handler(req):
        if req.url.path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"success": True, "result": {"id": "t"}})
        if "pages/projects" in req.url.path:
            return httpx.Response(403, json={"success": False, "errors": []})
        # Zone + account fine.
        return httpx.Response(200, json={"success": True, "result": []})

    client = _client_for(handler)
    report = probe_token_scopes(account_id="acct", client=client)
    assert not report.ok
    assert not report.pages_read_ok
    assert any("Cloudflare Pages:Edit" in m for m in report.missing)


def test_probe_token_scopes_invalid_token():
    """401 on /user/tokens/verify short-circuits — no further probes."""
    from portfolio.cloudflare import probe_token_scopes

    def handler(req):
        if req.url.path.endswith("/user/tokens/verify"):
            return httpx.Response(401, text="unauthorized")
        return httpx.Response(500, text="should not be called")

    client = _client_for(handler)
    report = probe_token_scopes(account_id="acct", client=client)
    assert not report.ok
    assert any("token-invalid" in m for m in report.missing)
    assert not report.pages_read_ok
    assert not report.zone_read_ok


def test_probe_token_scopes_zone_403():
    """Zone:Edit missing — token can't create zones."""
    from portfolio.cloudflare import probe_token_scopes

    def handler(req):
        if req.url.path.endswith("/user/tokens/verify"):
            return httpx.Response(200, json={"success": True, "result": {"id": "t"}})
        if req.url.path.endswith("/accounts/acct/pages/projects"):
            return httpx.Response(200, json={"success": True, "result": []})
        if req.url.path.endswith("/zones"):
            return httpx.Response(403, text="forbidden")
        return httpx.Response(200, json={"success": True, "result": []})

    client = _client_for(handler)
    report = probe_token_scopes(account_id="acct", client=client)
    assert not report.ok
    assert report.pages_read_ok
    assert not report.zone_read_ok
    assert any("Zone:Edit" in m for m in report.missing)


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
