"""Tests for v11.D — `walk_hostgator()` cPanel UAPI walker.

HG is structurally different from Vercel/CF: no build pipeline,
no deploy history. The walker enumerates domains via
`DomainInfo/list_domains`, reads account-level disk usage via
`Quota/get_quota_info`, optionally pulls WP version/path via
`WordPressManager/list_installations`, and emits one `HostingRow`
per matched fleet domain with `provider=hostgator`.
"""
from __future__ import annotations

from typing import Any

import pytest

from portfolio.hosting import (
    PROVIDER_HOSTGATOR,
    HostGatorAuthError,
    HostGatorWalkError,
    _hg_url,
    walk_hostgator,
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
    """For HG the call order is non-trivial (list_domains → quota →
    wp_installs), and individual calls can succeed or fail. Pre-load
    a dict keyed by `Module/Function` so tests can wire each endpoint
    independently."""

    def __init__(self, endpoint_responses: dict[str, dict]):
        # Each value: {"status": int, "body": dict | Exception}.
        self.responses = dict(endpoint_responses)
        self.calls: list[dict] = []

    def get(self, url: str, **kw) -> _FakeResponse:
        self.calls.append({
            "url": url, "params": kw.get("params"),
            "headers": kw.get("headers"),
        })
        # Find the matching Module/Function by URL suffix.
        for key, spec in self.responses.items():
            if key in url:
                return _FakeResponse(spec["status"], spec.get("body", {}))
        raise AssertionError(f"No fake response for URL: {url}")

    def close(self) -> None:
        pass


def _uapi_ok(data: Any) -> dict:
    """UAPI success envelope — `status: 1` + data."""
    return {"status": 1, "errors": [], "messages": [], "data": data}


def _uapi_err(errors: list[str]) -> dict:
    return {"status": 0, "errors": errors, "messages": [], "data": None}


# ---- helper unit tests --------------------------------------------


def test_hg_url_uses_account_id_as_subdomain():
    """Resolution 11.L — cPanel host derives from account_id, not
    config. `_hg_url('gator3164', 'X', 'Y')` →
    `https://gator3164.hostgator.com:2083/execute/X/Y`."""
    url = _hg_url("gator3164", "DomainInfo", "list_domains")
    assert url == "https://gator3164.hostgator.com:2083/execute/DomainInfo/list_domains"


# ---- walk_hostgator error paths -----------------------------------


def test_walk_hostgator_empty_token_raises_auth_error():
    with pytest.raises(HostGatorAuthError):
        walk_hostgator("", "gator3164", fleet_domains=set())


def test_walk_hostgator_empty_account_id_raises_auth_error():
    with pytest.raises(HostGatorAuthError):
        walk_hostgator("hg-token", "", fleet_domains=set())


def test_walk_hostgator_401_on_list_domains_raises_auth_error():
    client = _FakeClient({"DomainInfo/list_domains": {"status": 401, "body": {}}})
    with pytest.raises(HostGatorAuthError):
        walk_hostgator(
            "hg-bad", "gator3164",
            fleet_domains={"any.com"}, client=client,
        )


def test_walk_hostgator_500_on_list_domains_raises_walk_error():
    client = _FakeClient({"DomainInfo/list_domains": {"status": 502, "body": {}}})
    with pytest.raises(HostGatorWalkError):
        walk_hostgator(
            "hg-good", "gator3164",
            fleet_domains={"any.com"}, client=client,
        )


def test_walk_hostgator_uapi_status_0_raises_walk_error():
    """HTTP 200 + envelope status=0 is the UAPI-level failure mode."""
    client = _FakeClient({
        "DomainInfo/list_domains": {
            "status": 200, "body": _uapi_err(["Internal cPanel error"]),
        },
    })
    with pytest.raises(HostGatorWalkError):
        walk_hostgator(
            "hg-good", "gator3164",
            fleet_domains={"any.com"}, client=client,
        )


# ---- walk_hostgator happy paths -----------------------------------


def test_walk_hostgator_emits_row_for_matched_main_domain():
    """`main_domain` alone gets a row when it's in fleet_domains."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": [],
            "parked_domains": [],
            "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({
            "disk_used": "1430", "disk_limit": "20480",
        })},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com"}, client=client,
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.domain == "hybridautopart.com"
    assert row.provider == PROVIDER_HOSTGATOR
    assert row.hg_account_id == "gator3164"
    assert row.disk_used_mb == 1430
    # No matching WP install yet — fields stay None.
    assert row.wp_version is None
    assert row.install_path is None
    # Build-pipeline fields stay None — HG has no build pipeline.
    assert row.latest_deploy_status is None
    assert row.consecutive_failures == 0


def test_walk_hostgator_emits_addon_domains_with_doc_root():
    """Addon-domain entries are typically dicts with `domain` +
    `documentroot`. The doc_root becomes the row's `install_path`."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": [
                {"domain": "streamsgalaxy.com",
                 "documentroot": "/home1/user/public_html/streamsgalaxy.com"},
            ],
            "parked_domains": [],
            "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 800})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"streamsgalaxy.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "streamsgalaxy.com"
    assert rows[0].install_path == "/home1/user/public_html/streamsgalaxy.com"


def test_walk_hostgator_attaches_wp_version_when_install_matches_doc_root():
    """When WordPressManager reports an install at the same doc_root
    as a matched domain, `wp_version` populates."""
    doc_root = "/home1/user/public_html/hybridautopart.com"
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": [
                {"domain": "hybridautopart.com", "documentroot": doc_root},
            ],
            "parked_domains": [],
            "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 1430})},
        "WordPressManager/list_installations": {"status": 200, "body": _uapi_ok([
            {"installation_path": doc_root, "version": "6.7.1"},
        ])},
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com"}, client=client,
    )
    # main_domain + addon entry both match → deduped to one row.
    assert len(rows) == 1
    assert rows[0].wp_version == "6.7.1"
    assert rows[0].install_path == doc_root


def test_walk_hostgator_handles_string_addon_entries_legacy_shape():
    """Older cPanel versions return addon_domains as a list of bare
    strings. Walker accepts that shape too — install_path stays None."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": ["streamsgalaxy.com"],   # string, not dict
            "parked_domains": [],
            "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 500})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"streamsgalaxy.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].install_path is None


def test_walk_hostgator_wordpressmanager_404_silently_yields_no_wp_version():
    """`WordPressManager` module isn't on every cPanel — 404 doesn't
    crash; rows just get `wp_version=None`."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": [],
            "parked_domains": [],
            "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 200})},
        "WordPressManager/list_installations": {"status": 404, "body": {}},
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].wp_version is None


def test_walk_hostgator_quota_failure_leaves_disk_used_none():
    """Quota module failure doesn't fail the walk — rows emit with
    `disk_used_mb=None`."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": [], "parked_domains": [], "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 503, "body": {}},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com"}, client=client,
    )
    assert len(rows) == 1
    assert rows[0].disk_used_mb is None


def test_walk_hostgator_unmatched_domains_dropped():
    """Domains on the account but not in `fleet_domains` drop silently —
    they're someone else's site or out of scope."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "not-in-fleet.com",
            "addon_domains": [
                {"domain": "also-not-in-fleet.com", "documentroot": "/x"},
            ],
            "parked_domains": [], "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 100})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com"},  # not on this account
        client=client,
    )
    assert rows == []


def test_walk_hostgator_only_domain_filter():
    """`only_domain` restricts to that one even when multiple matches
    exist on the account."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "hybridautopart.com",
            "addon_domains": [
                {"domain": "streamsgalaxy.com", "documentroot": "/x/sg"},
            ],
            "parked_domains": [], "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 1000})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com", "streamsgalaxy.com"},
        only_domain="streamsgalaxy.com",
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "streamsgalaxy.com"


def test_walk_hostgator_bare_host_normalize_on_main_domain():
    """`www.<apex>` in the API response matches a fleet entry of `<apex>`."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "www.hybridautopart.com",
            "addon_domains": [], "parked_domains": [], "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 100})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    rows = walk_hostgator(
        "hg-token", "gator3164",
        fleet_domains={"hybridautopart.com"},
        client=client,
    )
    assert len(rows) == 1
    assert rows[0].domain == "hybridautopart.com"


def test_walk_hostgator_uses_cpanel_auth_header():
    """cPanel custom auth scheme — NOT HTTP Basic. Default cpanel_user
    falls back to `account_id` when the kwarg isn't passed (back-compat
    with shared-hosting where the username equals the server name)."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "x.com",
            "addon_domains": [], "parked_domains": [], "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 50})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    walk_hostgator(
        "hg-token-abc", "gator3164",
        fleet_domains=set(),
        client=client,
    )
    assert client.calls[0]["headers"]["Authorization"] == "cpanel gator3164:hg-token-abc"


def test_walk_hostgator_cpanel_user_override_changes_auth_header():
    """v11.A patch 2026-05-19 — operator's cPanel username can differ
    from the server hostname slug. When `cpanel_user=` is passed, the
    Authorization header uses that, not `account_id`. URL stays
    keyed on `account_id` (the server hostname)."""
    client = _FakeClient({
        "DomainInfo/list_domains": {"status": 200, "body": _uapi_ok({
            "main_domain": "x.com",
            "addon_domains": [], "parked_domains": [], "sub_domains": [],
        })},
        "Quota/get_quota_info": {"status": 200, "body": _uapi_ok({"disk_used": 50})},
        "WordPressManager/list_installations": {
            "status": 200, "body": _uapi_ok([]),
        },
    })
    walk_hostgator(
        "hg-token-abc", "gator3164",
        fleet_domains=set(),
        cpanel_user="foundervijo",
        client=client,
    )
    # Server-hostname URL unchanged.
    assert "gator3164.hostgator.com:2083" in client.calls[0]["url"]
    # Auth header uses the override username.
    assert client.calls[0]["headers"]["Authorization"] == "cpanel foundervijo:hg-token-abc"
