"""Tests for v11.C — `walk_cf_pages()` Cloudflare Pages walker.

Mirrors `tests/test_hosting_vercel.py` — same _FakeClient pattern,
mocked at the httpx.Client layer per resolution 11.J. The differences
from Vercel are in the CF API envelope shape (`{success, errors,
result, result_info}`) and the deploy-state model (`latest_stage`
rather than a single `state` field).
"""
from __future__ import annotations

from typing import Any

import pytest

from portfolio.hosting import (
    MAX_DEPLOY_LOOKBACK,
    PROVIDER_CF_PAGES,
    CFPagesAuthError,
    CFPagesWalkError,
    _cf_project_custom_domains,
    _classify_cf_deploys,
    walk_cf_pages,
)


# ---- _FakeClient + helpers (parallel to Vercel tests) -------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, **kw) -> _FakeResponse:
        self.calls.append({
            "url": url, "params": kw.get("params"),
            "headers": kw.get("headers"),
        })
        if not self.responses:
            raise AssertionError(f"_FakeClient ran out of responses at {url}")
        spec = self.responses.pop(0)
        return _FakeResponse(spec["status"], spec.get("body", {}))

    def close(self) -> None:
        pass


def _cf_envelope(
    result: list[dict],
    *,
    total_pages: int | None = None,
    success: bool = True,
    errors: list[str] | None = None,
) -> dict:
    body: dict = {
        "success": success,
        "errors": errors or [],
        "messages": [],
        "result": result,
    }
    if total_pages is not None:
        body["result_info"] = {
            "page": 1, "per_page": 25, "count": len(result),
            "total_pages": total_pages,
        }
    return body


def _cf_project(*, name: str, domains: list[str], project_id: str = "") -> dict:
    return {"id": project_id or f"cf-{name}", "name": name, "domains": domains}


def _cf_deploy(*, stage_name: str, stage_status: str,
               created_on: str = "2026-05-18T16:12:00Z") -> dict:
    return {
        "created_on": created_on,
        "latest_stage": {"name": stage_name, "status": stage_status},
    }


# ---- _cf_project_custom_domains ---------------------------------


def test_cf_project_custom_domains_extracts_list():
    project = _cf_project(name="airsucks", domains=["airsucks.com", "www.airsucks.com"])
    assert _cf_project_custom_domains(project) == ["airsucks.com", "www.airsucks.com"]


def test_cf_project_custom_domains_handles_missing_field():
    """Some CF projects (newly created, no custom domain yet) have an
    empty `domains` list — handle that without raising."""
    project = {"id": "x", "name": "y"}
    assert _cf_project_custom_domains(project) == []


def test_cf_project_custom_domains_filters_non_strings():
    project = {"id": "x", "name": "y", "domains": ["good.com", None, 42]}
    assert _cf_project_custom_domains(project) == ["good.com"]


# ---- _classify_cf_deploys ---------------------------------------


def test_classify_cf_deploys_empty_returns_zeros():
    assert _classify_cf_deploys([]) == (None, None, None, 0)


def test_classify_cf_deploys_latest_success_anchors_history():
    """The most recent deploy is (deploy, success) → status=SUCCESS,
    last_successful = its timestamp, consec_failures=0."""
    deploys = [_cf_deploy(stage_name="deploy", stage_status="success",
                          created_on="2026-05-18T16:00:00Z")]
    status, latest_at, last_success, consec = _classify_cf_deploys(deploys)
    assert status == "SUCCESS"
    assert latest_at and "2026-05-18" in latest_at
    assert last_success == latest_at
    assert consec == 0


def test_classify_cf_deploys_failure_then_success():
    """Two failures (any stage with status=failure), then a deploy/success
    → consecutive_failures=2."""
    deploys = [
        _cf_deploy(stage_name="build", stage_status="failure",
                   created_on="2026-05-18T16:30:00Z"),
        _cf_deploy(stage_name="deploy", stage_status="failure",
                   created_on="2026-05-18T16:20:00Z"),
        _cf_deploy(stage_name="deploy", stage_status="success",
                   created_on="2026-05-18T16:00:00Z"),
    ]
    status, _, last_success, consec = _classify_cf_deploys(deploys)
    assert status == "FAILURE"
    assert consec == 2
    assert last_success is not None


def test_classify_cf_deploys_in_flight_not_counted():
    """`active` / `queued` / `idle` stages don't bump consec_failures —
    they're in-flight (resolution 11.D semantics, same as Vercel's
    BUILDING/QUEUED/INITIALIZING)."""
    deploys = [
        _cf_deploy(stage_name="build", stage_status="active",
                   created_on="2026-05-18T16:30:00Z"),
        _cf_deploy(stage_name="queued", stage_status="idle",
                   created_on="2026-05-18T16:20:00Z"),
        _cf_deploy(stage_name="deploy", stage_status="failure",
                   created_on="2026-05-18T16:10:00Z"),
        _cf_deploy(stage_name="deploy", stage_status="success",
                   created_on="2026-05-18T16:00:00Z"),
    ]
    status, _, _, consec = _classify_cf_deploys(deploys)
    assert status == "IN_PROGRESS"
    assert consec == 1  # only the explicit failure


def test_classify_cf_deploys_runaway_failures_no_success():
    """MAX_DEPLOY_LOOKBACK failures with no success in the window —
    consec_failures = N. Renderer surfaces this as the runaway glyph."""
    deploys = [
        _cf_deploy(stage_name="build", stage_status="failure",
                   created_on=f"2026-05-{18 - i:02d}T16:00:00Z")
        for i in range(MAX_DEPLOY_LOOKBACK)
    ]
    status, _, last_success, consec = _classify_cf_deploys(deploys)
    assert status == "FAILURE"
    assert last_success is None
    assert consec == MAX_DEPLOY_LOOKBACK


def test_classify_cf_deploys_handles_missing_stage_safely():
    """A deploy with no `latest_stage` field shouldn't crash — counts
    as in-flight (status unknown)."""
    deploys = [{"created_on": "2026-05-18T16:00:00Z"}]
    status, _, last_success, consec = _classify_cf_deploys(deploys)
    assert status == "IN_PROGRESS"
    assert last_success is None
    assert consec == 0


def test_classify_cf_deploys_malformed_timestamp_returns_none():
    """`created_on` not a parseable ISO string → timestamp fields stay
    None, but classification still runs."""
    deploys = [{"created_on": "not-a-date",
                "latest_stage": {"name": "deploy", "status": "success"}}]
    status, latest_at, last_success, consec = _classify_cf_deploys(deploys)
    assert status == "SUCCESS"
    assert latest_at is None
    assert last_success is None
    assert consec == 0


# ---- walk_cf_pages error paths ---------------------------------


def test_walk_cf_pages_empty_token_raises_auth_error():
    with pytest.raises(CFPagesAuthError):
        walk_cf_pages("", "acct123", fleet_domains=set())


def test_walk_cf_pages_empty_account_id_raises_auth_error():
    """Both token and account_id are required; missing either is an
    auth-equivalent failure."""
    with pytest.raises(CFPagesAuthError):
        walk_cf_pages("cf-token", "", fleet_domains=set())


def test_walk_cf_pages_401_raises_auth_error():
    client = _FakeClient([{"status": 401, "body": {}}])
    with pytest.raises(CFPagesAuthError):
        walk_cf_pages("cf-bad", "acct123", fleet_domains=set(), client=client)


def test_walk_cf_pages_5xx_raises_walk_error():
    client = _FakeClient([{"status": 502, "body": {}}])
    with pytest.raises(CFPagesWalkError):
        walk_cf_pages("cf-good", "acct123", fleet_domains=set(), client=client)


def test_walk_cf_pages_envelope_success_false_raises_walk_error():
    """CF responses can be HTTP 200 with `success: false` (e.g.
    expired/scoped token). Treat envelope-failure as walk error."""
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope(
            [], success=False, errors=[{"code": 10001, "message": "Authentication error"}],
        )},
    ])
    with pytest.raises(CFPagesWalkError):
        walk_cf_pages("cf-token", "acct123", fleet_domains=set(), client=client)


def test_walk_cf_pages_non_json_raises_walk_error():
    client = _FakeClient([{"status": 200, "body": ValueError("not json")}])
    with pytest.raises(CFPagesWalkError):
        walk_cf_pages("cf-token", "acct123", fleet_domains=set(), client=client)


# ---- walk_cf_pages happy paths ---------------------------------


def test_walk_cf_pages_matches_fleet_domain():
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="airsucks", domains=["airsucks.com"]),
        ], total_pages=1)},
        {"status": 200, "body": _cf_envelope([
            _cf_deploy(stage_name="deploy", stage_status="success",
                       created_on="2026-05-18T16:00:00Z"),
        ])},
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"},
        client=client,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.domain == "airsucks.com"
    assert row.provider == PROVIDER_CF_PAGES
    assert row.project_slug == "airsucks"
    assert row.latest_deploy_status == "SUCCESS"
    assert row.consecutive_failures == 0


def test_walk_cf_pages_bare_host_normalizes_www_variant():
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="airsucks", domains=["www.airsucks.com"]),
        ], total_pages=1)},
        {"status": 200, "body": _cf_envelope([])},
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"},
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "airsucks.com"


def test_walk_cf_pages_pages_dev_default_host_filtered_by_fleet_intersect():
    """The auto-assigned `<slug>.pages.dev` host isn't in fleet_domains
    (unless the operator explicitly adds it). So projects emit rows
    only for their custom domains, not for the pages.dev default."""
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="airsucks", domains=["airsucks.pages.dev"]),
        ], total_pages=1)},
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"},   # NOT airsucks.pages.dev
        client=client,
    )
    assert rows == []


def test_walk_cf_pages_unmatched_project_dropped():
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="unowned", domains=["someone-elses.com"]),
        ], total_pages=1)},
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"},
        client=client,
    )
    assert rows == []


def test_walk_cf_pages_single_shot_no_pagination_params():
    """CF Pages's `/projects` endpoint rejects `?page=N&per_page=N`
    with API error 8000024 (resolution forced by the 2026-05-19 hand
    test against operator's real CF account). Walker must NOT send
    those params — single-shot fetch returns all projects.

    All projects from one call → emit rows for every fleet match.
    """
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="airsucks", domains=["airsucks.com"]),
            _cf_project(name="calcengine", domains=["calcengine.site"]),
        ])},
        {"status": 200, "body": _cf_envelope([
            _cf_deploy(stage_name="deploy", stage_status="success"),
        ])},
        {"status": 200, "body": _cf_envelope([
            _cf_deploy(stage_name="deploy", stage_status="success"),
        ])},
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com", "calcengine.site"},
        client=client,
    )
    assert {r.domain for r in rows} == {"airsucks.com", "calcengine.site"}
    # First (projects-list) call carries NO pagination params.
    projects_call = client.calls[0]
    params = projects_call.get("params") or {}
    assert "page" not in params, f"unexpected `page` param: {params}"
    assert "per_page" not in params, f"unexpected `per_page` param: {params}"


def test_walk_cf_pages_only_domain_filter():
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="airsucks", domains=["airsucks.com"]),
            _cf_project(name="calcengine", domains=["calcengine.site"]),
        ], total_pages=1)},
        {"status": 200, "body": _cf_envelope([])},
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com", "calcengine.site"},
        only_domain="calcengine.site",
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "calcengine.site"


def test_walk_cf_pages_per_project_deploy_failure_records_error():
    """A 5xx on the per-project deployments call attaches `error=`
    to the row but the walker keeps going."""
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([
            _cf_project(name="airsucks", domains=["airsucks.com"]),
        ], total_pages=1)},
        {"status": 503, "body": {}},  # deployments list 5xx
    ])
    rows = walk_cf_pages(
        "cf-token", "acct123",
        fleet_domains={"airsucks.com"},
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].error and "503" in rows[0].error
    assert rows[0].latest_deploy_status is None


def test_walk_cf_pages_url_includes_account_id():
    """The CF projects-list URL must embed the account_id — verifies
    the walker isn't hardcoding an account scope."""
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([], total_pages=1)},
    ])
    walk_cf_pages("cf-token", "abc123def", fleet_domains=set(), client=client)
    assert "/accounts/abc123def/pages/projects" in client.calls[0]["url"]


def test_walk_cf_pages_authorization_header_uses_bearer():
    client = _FakeClient([
        {"status": 200, "body": _cf_envelope([], total_pages=1)},
    ])
    walk_cf_pages("cf-token-xyz", "acct123", fleet_domains=set(), client=client)
    assert client.calls[0]["headers"]["Authorization"] == "Bearer cf-token-xyz"
