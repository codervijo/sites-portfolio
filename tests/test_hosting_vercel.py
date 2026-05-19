"""Tests for v11.B — `walk_vercel()` Vercel projects/deployments walker.

Resolution 11.J: mock at the `httpx.Client` layer; no real Vercel API
calls in CI. Each test wires a `_FakeClient` with a queue of canned
responses; `walk_vercel(client=...)` consumes the queue.
"""
from __future__ import annotations

from typing import Any

import pytest

from portfolio.hosting import (
    MAX_DEPLOY_LOOKBACK,
    PROVIDER_VERCEL,
    VercelAuthError,
    VercelWalkError,
    _bare_host,
    _classify_deploys,
    _project_custom_domains,
    walk_vercel,
)


# ---- _FakeClient + helpers ----------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    """Stand-in for httpx.Client. Each call to `.get()` pops one
    pre-loaded response and records the URL/params/headers it was called
    with for assertion in the test."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, **kw) -> _FakeResponse:
        self.calls.append({
            "url": url,
            "params": kw.get("params"),
            "headers": kw.get("headers"),
        })
        if not self.responses:
            raise AssertionError(f"_FakeClient ran out of responses at {url}")
        spec = self.responses.pop(0)
        return _FakeResponse(spec["status"], spec.get("body", {}))

    def close(self) -> None:
        pass


def _projects_page(projects: list[dict], *, next_cursor: int | None = None) -> dict:
    """Build a fake `/v9/projects` response body."""
    pagination: dict = {"count": len(projects)}
    if next_cursor is not None:
        pagination["next"] = next_cursor
    return {"projects": projects, "pagination": pagination}


def _vercel_project(
    *,
    project_id: str,
    name: str,
    alias: list[str] | None,
) -> dict:
    """Minimal Vercel project payload — only the fields the walker reads."""
    targets: dict[str, dict] = {}
    if alias is not None:
        targets["production"] = {"alias": alias}
    return {"id": project_id, "name": name, "targets": targets}


def _deployments_page(deployments: list[dict]) -> dict:
    return {"deployments": deployments}


def _vercel_deploy(*, state: str, created_ms: int) -> dict:
    return {"state": state, "created": created_ms}


# ---- _bare_host -----------------------------------------------------


def test_bare_host_strips_www_and_lowercases():
    assert _bare_host("www.Example.COM") == "example.com"
    assert _bare_host("example.com") == "example.com"
    assert _bare_host("  Example.com  ") == "example.com"


def test_bare_host_doesnt_strip_wwwx():
    """Only the literal `www.` prefix is dropped — `wwwx.foo` keeps its host."""
    assert _bare_host("wwwx.example.com") == "wwwx.example.com"


# ---- _project_custom_domains --------------------------------------


def test_project_custom_domains_extracts_alias():
    project = _vercel_project(
        project_id="prj_1", name="ex", alias=["example.com", "www.example.com"]
    )
    assert _project_custom_domains(project) == ["example.com", "www.example.com"]


def test_project_custom_domains_handles_no_production_target():
    project = {"id": "prj_2", "name": "preview-only", "targets": {}}
    assert _project_custom_domains(project) == []


def test_project_custom_domains_handles_missing_targets_key():
    """Defensive — newer/older Vercel projects might omit `targets`."""
    project = {"id": "prj_3", "name": "weird"}
    assert _project_custom_domains(project) == []


def test_project_custom_domains_filters_non_strings():
    """Resilient against unexpected shapes — drop non-string entries."""
    project = {
        "id": "prj_4", "name": "junk",
        "targets": {"production": {"alias": ["good.com", None, 42, ""]}},
    }
    assert _project_custom_domains(project) == ["good.com"]


# ---- _classify_deploys --------------------------------------------


def test_classify_deploys_empty_returns_zeros():
    assert _classify_deploys([]) == (None, None, None, 0)


def test_classify_deploys_latest_ready():
    deploys = [_vercel_deploy(state="READY", created_ms=1700000000000)]
    status, latest_at, last_success, consec = _classify_deploys(deploys)
    assert status == "READY"
    assert latest_at and "2023-" in latest_at
    assert last_success == latest_at
    assert consec == 0


def test_classify_deploys_counts_failures_before_success():
    """Two ERROR deploys, then a READY → consecutive_failures=2,
    last_successful_at = the READY's timestamp."""
    deploys = [
        _vercel_deploy(state="ERROR", created_ms=1700000020000),
        _vercel_deploy(state="ERROR", created_ms=1700000010000),
        _vercel_deploy(state="READY", created_ms=1700000000000),
    ]
    status, latest_at, last_success, consec = _classify_deploys(deploys)
    assert status == "ERROR"
    assert consec == 2
    assert last_success is not None and "2023-" in last_success


def test_classify_deploys_in_flight_states_not_counted():
    """BUILDING / INITIALIZING / QUEUED are in-flight, not failures —
    they don't bump consecutive_failures."""
    deploys = [
        _vercel_deploy(state="BUILDING", created_ms=1700000030000),
        _vercel_deploy(state="INITIALIZING", created_ms=1700000020000),
        _vercel_deploy(state="ERROR", created_ms=1700000010000),
        _vercel_deploy(state="READY", created_ms=1700000000000),
    ]
    status, _, last_success, consec = _classify_deploys(deploys)
    assert status == "BUILDING"
    assert consec == 1  # only the ERROR counted
    assert last_success is not None


def test_classify_deploys_canceled_counts_as_failure():
    deploys = [
        _vercel_deploy(state="CANCELED", created_ms=1700000010000),
        _vercel_deploy(state="READY", created_ms=1700000000000),
    ]
    _, _, _, consec = _classify_deploys(deploys)
    assert consec == 1


def test_classify_deploys_runaway_failures_no_ready():
    """All MAX_DEPLOY_LOOKBACK deploys are ERROR — consec == N. The
    renderer at slice H will surface this as the runaway-failures
    glyph per resolution 11.D's two-tier semantics."""
    deploys = [
        _vercel_deploy(state="ERROR", created_ms=1700000000000 + i * 1000)
        for i in range(MAX_DEPLOY_LOOKBACK)
    ]
    _, _, last_success, consec = _classify_deploys(deploys)
    assert last_success is None
    assert consec == MAX_DEPLOY_LOOKBACK


def test_classify_deploys_falls_back_to_readyState_field():
    """Vercel's older API uses `readyState`; newer uses `state`. The
    walker should accept either."""
    deploys = [{"readyState": "READY", "created": 1700000000000}]
    status, _, last_success, consec = _classify_deploys(deploys)
    assert status == "READY"
    assert last_success is not None
    assert consec == 0


# ---- walk_vercel error paths --------------------------------------


def test_walk_vercel_empty_token_raises_auth_error():
    """Resolution 11.H — 401 raises VercelAuthError so the orchestrator
    can skip the entire walker. An empty token short-circuits before
    any network call."""
    with pytest.raises(VercelAuthError):
        walk_vercel("", fleet_domains={"any.com"})


def test_walk_vercel_401_raises_auth_error():
    client = _FakeClient([{"status": 401, "body": {}}])
    with pytest.raises(VercelAuthError):
        walk_vercel("vc-revoked", fleet_domains={"any.com"}, client=client)


def test_walk_vercel_5xx_on_projects_list_raises_walk_error():
    """A 5xx on the projects-list call BEFORE any project is processed
    is unrecoverable — orchestrator gets a clean signal to abort."""
    client = _FakeClient([{"status": 502, "body": {}}])
    with pytest.raises(VercelWalkError):
        walk_vercel("vc-good", fleet_domains={"any.com"}, client=client)


def test_walk_vercel_non_json_response_raises_walk_error():
    """Resilient against weird CDN errors mid-walk — non-JSON 200 still
    aborts cleanly rather than KeyErroring deep in the parse logic."""
    client = _FakeClient([{"status": 200, "body": ValueError("not json")}])
    with pytest.raises(VercelWalkError):
        walk_vercel("vc-good", fleet_domains={"any.com"}, client=client)


# ---- walk_vercel happy paths --------------------------------------


def test_walk_vercel_matches_fleet_domain():
    """Single project matches a fleet domain → one HostingRow with the
    expected provider + project metadata + deploy classification."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_1", name="airsucks",
                            alias=["airsucks.com"]),
        ])},
        {"status": 200, "body": _deployments_page([
            _vercel_deploy(state="READY", created_ms=1700000000000),
        ])},
    ])
    rows = walk_vercel("vc-token", fleet_domains={"airsucks.com"}, client=client)

    assert len(rows) == 1
    row = rows[0]
    assert row.domain == "airsucks.com"
    assert row.provider == PROVIDER_VERCEL
    assert row.project_slug == "airsucks"
    assert row.project_id == "prj_1"
    assert row.latest_deploy_status == "READY"
    assert row.consecutive_failures == 0


def test_walk_vercel_bare_host_normalizes_www_variant():
    """Resolution 11.E — `www.airsucks.com` in the project's alias list
    should match a fleet entry of `airsucks.com`."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_1", name="airsucks",
                            alias=["www.airsucks.com"]),
        ])},
        {"status": 200, "body": _deployments_page([])},
    ])
    rows = walk_vercel("vc-token", fleet_domains={"airsucks.com"}, client=client)
    assert len(rows) == 1
    assert rows[0].domain == "airsucks.com"


def test_walk_vercel_unmatched_project_dropped():
    """Projects whose custom domains aren't in fleet_domains drop
    silently — they're not in the fleet."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_x", name="unowned",
                            alias=["someone-elses.com"]),
        ])},
    ])
    rows = walk_vercel("vc-token", fleet_domains={"airsucks.com"}, client=client)
    assert rows == []


def test_walk_vercel_project_without_production_target_skipped():
    """Preview-only projects with no `targets.production` emit no rows."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_preview", name="preview-only", alias=None),
        ])},
    ])
    rows = walk_vercel("vc-token", fleet_domains={"airsucks.com"}, client=client)
    assert rows == []


def test_walk_vercel_paginates_until_next_is_falsy():
    """When the first page's pagination.next is set, fetch a second
    page using `?until=<cursor>`. Stop when `next` is None."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_1", name="airsucks",
                            alias=["airsucks.com"]),
        ], next_cursor=1234567890000)},
        {"status": 200, "body": _deployments_page([
            _vercel_deploy(state="READY", created_ms=1700000000000),
        ])},
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_2", name="calcengine",
                            alias=["calcengine.site"]),
        ])},  # no next cursor — last page
        {"status": 200, "body": _deployments_page([
            _vercel_deploy(state="READY", created_ms=1700000010000),
        ])},
    ])
    rows = walk_vercel(
        "vc-token",
        fleet_domains={"airsucks.com", "calcengine.site"},
        client=client,
    )
    assert {r.domain for r in rows} == {"airsucks.com", "calcengine.site"}
    # The second projects-list call carried the cursor.
    page2 = client.calls[2]  # calls[0]=page1, [1]=deploys-1, [2]=page2
    assert page2["params"]["until"] == 1234567890000


def test_walk_vercel_only_domain_filter():
    """`only_domain` short-circuits emission to that one domain even
    when other projects' domains are in fleet_domains."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_1", name="airsucks",
                            alias=["airsucks.com"]),
            _vercel_project(project_id="prj_2", name="calcengine",
                            alias=["calcengine.site"]),
        ])},
        {"status": 200, "body": _deployments_page([])},
    ])
    rows = walk_vercel(
        "vc-token",
        fleet_domains={"airsucks.com", "calcengine.site"},
        only_domain="calcengine.site",
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "calcengine.site"


def test_walk_vercel_per_project_deploy_failure_records_error():
    """A 5xx on the per-project deployments call attaches `error` to
    the affected row but lets the walker keep going (resolution 11.H)."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([
            _vercel_project(project_id="prj_1", name="airsucks",
                            alias=["airsucks.com"]),
        ])},
        {"status": 503, "body": {}},  # deployments list 5xx
    ])
    rows = walk_vercel("vc-token", fleet_domains={"airsucks.com"}, client=client)
    assert len(rows) == 1
    assert rows[0].error and "503" in rows[0].error
    # Build-pipeline fields stay None since classification ran on []
    assert rows[0].latest_deploy_status is None


def test_walk_vercel_authorization_header_uses_bearer_token():
    """Sanity — the auth header is `Bearer <token>`, not Basic or raw."""
    client = _FakeClient([
        {"status": 200, "body": _projects_page([])},
    ])
    walk_vercel("vc-token-abc", fleet_domains=set(), client=client)
    assert client.calls[0]["headers"]["Authorization"] == "Bearer vc-token-abc"
