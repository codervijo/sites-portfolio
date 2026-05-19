"""Tests for v11.H — `walk_cf_workers()` Cloudflare Workers walker.

Inserted 2026-05-19 after the real-fleet hand test against the
operator's CF account returned `/pages/projects: result: []` while
`/workers/scripts` returned the actual deployed sites
(`airsucks`, `cricketfansite`, …). v11.H queries the Workers
surface — `/workers/scripts` + `/workers/domains` — and emits rows
with `provider="cloudflare-workers"`.

Mocked at the httpx.Client layer per resolution 11.J. Workers
have no build pipeline so there's no `consecutive_failures` walk
in v11.H — `latest_deploy_status="DEPLOYED"` and timestamps come
from the script's `modified_on` field.
"""
from __future__ import annotations

from typing import Any

import pytest

from portfolio.hosting import (
    PROVIDER_CF_WORKERS,
    CFWorkersAuthError,
    CFWorkersWalkError,
    walk_cf_workers,
)


# ---- _FakeClient with multi-endpoint dispatch ---------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    """Keyed by `<Module>` substring in URL so tests can wire the
    `/workers/scripts` and `/workers/domains` endpoints independently."""

    def __init__(self, endpoint_responses: dict[str, dict]):
        self.responses = dict(endpoint_responses)
        self.calls: list[dict] = []

    def get(self, url: str, **kw) -> _FakeResponse:
        self.calls.append({
            "url": url, "params": kw.get("params"),
            "headers": kw.get("headers"),
        })
        for key, spec in self.responses.items():
            if key in url:
                return _FakeResponse(spec["status"], spec.get("body", {}))
        raise AssertionError(f"No fake response for URL: {url}")

    def close(self) -> None:
        pass


def _cf_envelope(result: Any, *, success: bool = True,
                 errors: list[str] | None = None) -> dict:
    return {
        "success": success, "errors": errors or [],
        "messages": [], "result": result,
    }


def _worker_script(*, slug: str, modified_on: str = "2026-05-19T00:17:22Z",
                   has_assets: bool = True) -> dict:
    return {
        "id": slug,
        "modified_on": modified_on,
        "created_on": "2026-05-12T03:38:22Z",
        "has_assets": has_assets,
    }


def _worker_domain(*, hostname: str, service: str,
                   environment: str = "production") -> dict:
    return {
        "id": f"dom-{hostname}-{service}",
        "hostname": hostname,
        "service": service,
        "environment": environment,
        "zone_id": "zone-abc",
        "zone_name": hostname.split(".", 1)[-1] if "." in hostname else hostname,
    }


# ---- walk_cf_workers error paths --------------------------------


def test_walk_cf_workers_empty_token_raises_auth_error():
    with pytest.raises(CFWorkersAuthError):
        walk_cf_workers("", "acct123", fleet_domains=set())


def test_walk_cf_workers_empty_account_id_raises_auth_error():
    with pytest.raises(CFWorkersAuthError):
        walk_cf_workers("cf-token", "", fleet_domains=set())


def test_walk_cf_workers_401_on_domains_raises_auth_error():
    """Domains endpoint is the matching layer — 401 there is fatal."""
    client = _FakeClient({
        "workers/domains": {"status": 401, "body": {}},
    })
    with pytest.raises(CFWorkersAuthError):
        walk_cf_workers(
            "cf-bad", "acct123",
            fleet_domains={"any.com"}, client=client,
        )


def test_walk_cf_workers_5xx_on_domains_raises_walk_error():
    client = _FakeClient({
        "workers/domains": {"status": 502, "body": {}},
    })
    with pytest.raises(CFWorkersWalkError):
        walk_cf_workers(
            "cf-good", "acct123",
            fleet_domains={"any.com"}, client=client,
        )


def test_walk_cf_workers_envelope_success_false_raises_walk_error():
    """200 with `success: false` is still a walk failure."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope(
            [], success=False, errors=[{"code": 10000, "message": "Auth error"}],
        )},
    })
    with pytest.raises(CFWorkersWalkError):
        walk_cf_workers(
            "cf-token", "acct123",
            fleet_domains=set(), client=client,
        )


def test_walk_cf_workers_non_json_raises_walk_error():
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": ValueError("not json")},
    })
    with pytest.raises(CFWorkersWalkError):
        walk_cf_workers(
            "cf-token", "acct123",
            fleet_domains=set(), client=client,
        )


def test_walk_cf_workers_401_on_scripts_raises_auth_error():
    """Even though the scripts call is non-critical, a 401 is
    elevated — same token failing on a sibling endpoint is a
    cross-walker auth signal worth surfacing."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks"),
        ])},
        "workers/scripts": {"status": 401, "body": {}},
    })
    with pytest.raises(CFWorkersAuthError):
        walk_cf_workers(
            "cf-token", "acct123",
            fleet_domains={"airsucks.com"}, client=client,
        )


# ---- walk_cf_workers happy paths --------------------------------


def test_walk_cf_workers_matches_fleet_domain():
    """One domain matched → one row with provider=cloudflare-workers,
    script slug as project_slug, modified_on as both deploy timestamps."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks",
                           modified_on="2026-05-19T00:17:22Z"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.domain == "airsucks.com"
    assert row.provider == PROVIDER_CF_WORKERS
    assert row.project_slug == "airsucks"
    assert row.latest_deploy_status == "DEPLOYED"
    assert row.latest_deploy_at is not None
    assert "2026-05-19" in row.latest_deploy_at
    assert row.last_successful_deploy_at == row.latest_deploy_at
    assert row.consecutive_failures == 0


def test_walk_cf_workers_bare_host_normalize_www_variant():
    """`www.airsucks.com` in the domains list → row keyed at apex."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="www.airsucks.com", service="airsucks"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "airsucks.com"


def test_walk_cf_workers_unmatched_domain_dropped():
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="someone-elses.com", service="other"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert rows == []


def test_walk_cf_workers_preview_environment_dropped():
    """Domain entries for preview environments shouldn't emit rows —
    only production gets surfaced."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks",
                           environment="preview"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert rows == []


def test_walk_cf_workers_only_domain_filter():
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks"),
            _worker_domain(hostname="calcengine.site", service="calcengine"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks"),
            _worker_script(slug="calcengine"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com", "calcengine.site"},
        only_domain="calcengine.site",
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "calcengine.site"


def test_walk_cf_workers_dedups_repeated_hostname_service():
    """Same (hostname, service) showing up twice in the response (e.g.
    duplicate registrations on different zones) → only one row."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks"),
            _worker_domain(hostname="airsucks.com", service="airsucks"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert len(rows) == 1


def test_walk_cf_workers_scripts_fetch_failure_degrades_gracefully():
    """Scripts list fails with 5xx → rows still emit (matching is
    domain-driven) but `latest_deploy_at` stays None and `error` is set."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks"),
        ])},
        "workers/scripts": {"status": 503, "body": {}},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].latest_deploy_at is None
    assert rows[0].latest_deploy_status is None
    assert rows[0].error and "scripts list http 503" in rows[0].error


def test_walk_cf_workers_unknown_service_in_domain_emits_row_without_timestamp():
    """A domain mapped to a service that isn't in the scripts list → row
    still emits (the domain match drives emission). modified_on=None
    since we have no script metadata to pull from."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="ghost-script"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].project_slug == "ghost-script"
    assert rows[0].latest_deploy_at is None
    assert rows[0].latest_deploy_status is None


def test_walk_cf_workers_url_includes_account_id_and_uses_bearer():
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([])},
    })
    walk_cf_workers(
        "cf-token-abc", "acct-xyz",
        fleet_domains=set(), client=client,
    )
    domains_call = next(c for c in client.calls if "workers/domains" in c["url"])
    assert "/accounts/acct-xyz/workers/domains" in domains_call["url"]
    assert domains_call["headers"]["Authorization"] == "Bearer cf-token-abc"


def test_walk_cf_workers_no_pagination_params_sent():
    """v11.C lesson — these CF endpoints reject `page` / `per_page` with
    error 8000024. Walker must single-shot (no params)."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([])},
    })
    walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains=set(), client=client,
    )
    for call in client.calls:
        params = call.get("params") or {}
        assert "page" not in params, f"unexpected `page` in {call['url']}"
        assert "per_page" not in params, f"unexpected `per_page` in {call['url']}"


def test_walk_cf_workers_skips_non_string_hostnames_safely():
    """Defensive — if CF returns a malformed entry, skip it rather than
    crashing the walk."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            {"hostname": None, "service": "airsucks", "environment": "production"},
            {"hostname": "", "service": "airsucks", "environment": "production"},
            {"hostname": "airsucks.com", "service": None, "environment": "production"},
            _worker_domain(hostname="airsucks.com", service="airsucks"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"}, client=client,
    )
    # Only the well-formed entry produces a row.
    assert len(rows) == 1
    assert rows[0].domain == "airsucks.com"


def test_walk_cf_workers_multiple_matches_for_account():
    """Real-fleet shape — operator's CF account has many workers; each
    matched hostname emits its own row keyed at apex."""
    client = _FakeClient({
        "workers/domains": {"status": 200, "body": _cf_envelope([
            _worker_domain(hostname="airsucks.com", service="airsucks"),
            _worker_domain(hostname="cricketfansite.com", service="cricketfansite"),
            _worker_domain(hostname="donready.xyz", service="donready"),
        ])},
        "workers/scripts": {"status": 200, "body": _cf_envelope([
            _worker_script(slug="airsucks", modified_on="2026-05-19T00:17:22Z"),
            _worker_script(slug="cricketfansite", modified_on="2026-05-19T00:17:52Z"),
            _worker_script(slug="donready", modified_on="2026-05-19T00:12:41Z"),
        ])},
    })
    rows = walk_cf_workers(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com", "cricketfansite.com", "donready.xyz"},
        client=client,
    )
    assert {r.domain for r in rows} == {
        "airsucks.com", "cricketfansite.com", "donready.xyz",
    }
    assert all(r.provider == PROVIDER_CF_WORKERS for r in rows)
    assert all(r.latest_deploy_status == "DEPLOYED" for r in rows)
