"""Tests for v26.D `vercel.py` write-side API client.

Covers the four public helpers CHECK_150's vercel branch uses:
  - `find_project_by_domain` — paginated walk of /v9/projects matching
    on `targets.production.alias`
  - `get_project_domain` — read one domain's redirect config; 404 → None
  - `update_domain_redirect` — PATCH with `redirect` + `redirectStatusCode`
  - `add_domain_to_project` — POST to attach a new domain (optionally
    with a redirect already configured)

Plus `verify_token` (pre-flight) + error paths (missing token / 401 /
5xx / pagination overflow).

All HTTP stubbed via `httpx.MockTransport`.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import vercel


# ---------- helpers ----------


def _client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=vercel.API_BASE,
        transport=transport,
        headers={"Authorization": "Bearer test"},
    )


def _project(id_: str, name: str, aliases: list[str]) -> dict:
    """Build a minimal Vercel project payload with production aliases."""
    return {
        "id": id_,
        "name": name,
        "targets": {"production": {"alias": aliases}},
    }


# ---------- find_project_by_domain ----------


def test_find_project_single_page_hit():
    """One page of projects; target domain in production aliases."""
    def handler(req):
        assert req.url.path == "/v9/projects"
        return httpx.Response(200, json={
            "projects": [
                _project("p_one", "homeloom-web", ["homeloom.app", "www.homeloom.app"]),
            ],
            "pagination": {"next": None},
        })
    result = vercel.find_project_by_domain("homeloom.app", client=_client(handler))
    assert result.project_id == "p_one"
    assert result.name == "homeloom-web"


def test_find_project_paginated_walks_to_next_page():
    """First page misses; second page hits."""
    calls = {"count": 0}
    def handler(req):
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(200, json={
                "projects": [_project("p_other", "other", ["other.com"])],
                "pagination": {"next": 1234567890},
            })
        # Second page — `until` param echoed
        assert req.url.params.get("until") == "1234567890"
        return httpx.Response(200, json={
            "projects": [_project("p_target", "target", ["example.com"])],
            "pagination": {"next": None},
        })
    result = vercel.find_project_by_domain("example.com", client=_client(handler))
    assert result.project_id == "p_target"
    assert calls["count"] == 2


def test_find_project_no_match_raises():
    """Walk all pages without a match → VercelAPIError."""
    def handler(req):
        return httpx.Response(200, json={
            "projects": [_project("p_x", "x", ["other.com"])],
            "pagination": {"next": None},
        })
    with pytest.raises(vercel.VercelAPIError, match="no Vercel project attaches"):
        vercel.find_project_by_domain("missing.com", client=_client(handler))


def test_find_project_api_error_raises():
    def handler(req):
        return httpx.Response(500, text="internal")
    with pytest.raises(vercel.VercelAPIError, match="HTTP 500"):
        vercel.find_project_by_domain("any.com", client=_client(handler))


def test_find_project_match_is_case_insensitive():
    """Mixed-case alias entries should still match a lowercase target."""
    def handler(req):
        return httpx.Response(200, json={
            "projects": [_project("p", "p", ["Example.COM"])],
            "pagination": {"next": None},
        })
    result = vercel.find_project_by_domain("example.com", client=_client(handler))
    assert result.project_id == "p"


def test_find_project_pagination_overflow_raises():
    """If pagination's `next` keeps recurring past `max_pages`, abort
    instead of hanging."""
    def handler(req):
        return httpx.Response(200, json={
            "projects": [_project("p_x", "x", ["other.com"])],
            "pagination": {"next": 1},
        })
    with pytest.raises(vercel.VercelAPIError):
        vercel.find_project_by_domain(
            "missing.com", client=_client(handler), max_pages=3,
        )


# ---------- get_project_domain ----------


def test_get_project_domain_returns_config():
    def handler(req):
        assert req.url.path == "/v9/projects/p_one/domains/homeloom.app"
        return httpx.Response(200, json={
            "name": "homeloom.app",
            "redirect": None,
            "redirectStatusCode": None,
            "verified": True,
        })
    cfg = vercel.get_project_domain("p_one", "homeloom.app",
                                    client=_client(handler))
    assert cfg is not None
    assert cfg.name == "homeloom.app"
    assert cfg.redirect is None
    assert cfg.redirect_status_code is None
    assert cfg.verified is True


def test_get_project_domain_with_redirect():
    def handler(req):
        return httpx.Response(200, json={
            "name": "www.homeloom.app",
            "redirect": "homeloom.app",
            "redirectStatusCode": 308,
            "verified": True,
        })
    cfg = vercel.get_project_domain("p_one", "www.homeloom.app",
                                    client=_client(handler))
    assert cfg.redirect == "homeloom.app"
    assert cfg.redirect_status_code == 308


def test_get_project_domain_404_returns_none():
    """Domain isn't attached to this project → None, not exception."""
    def handler(req):
        return httpx.Response(404, json={"error": {"code": "not_found"}})
    cfg = vercel.get_project_domain("p_one", "www.homeloom.app",
                                    client=_client(handler))
    assert cfg is None


def test_get_project_domain_500_raises():
    def handler(req):
        return httpx.Response(500, text="server error")
    with pytest.raises(vercel.VercelAPIError, match="HTTP 500"):
        vercel.get_project_domain("p_one", "x.com", client=_client(handler))


# ---------- update_domain_redirect ----------


def test_update_domain_redirect_sets_308():
    captured = {}
    def handler(req):
        assert req.method == "PATCH"
        assert req.url.path == "/v9/projects/p_one/domains/www.homeloom.app"
        body = httpx.Request(method=req.method, url=req.url,
                             content=req.content).content
        import json as _json
        captured["body"] = _json.loads(body)
        return httpx.Response(200, json={"name": "www.homeloom.app",
                                          "redirect": "homeloom.app",
                                          "redirectStatusCode": 308})
    vercel.update_domain_redirect(
        "p_one", "www.homeloom.app",
        redirect_to="homeloom.app", status_code=308,
        client=_client(handler),
    )
    assert captured["body"] == {"redirect": "homeloom.app",
                                "redirectStatusCode": 308}


def test_update_domain_redirect_clears_with_null():
    captured = {}
    def handler(req):
        import json as _json
        captured["body"] = _json.loads(req.content)
        return httpx.Response(200, json={})
    vercel.update_domain_redirect(
        "p_one", "homeloom.app",
        redirect_to=None,
        client=_client(handler),
    )
    assert captured["body"] == {"redirect": None, "redirectStatusCode": None}


def test_update_domain_redirect_403_raises():
    def handler(req):
        return httpx.Response(403, text="forbidden")
    with pytest.raises(vercel.VercelAPIError, match="HTTP 403"):
        vercel.update_domain_redirect(
            "p_one", "x.com", redirect_to=None,
            client=_client(handler),
        )


# ---------- add_domain_to_project ----------


def test_add_domain_minimal():
    captured = {}
    def handler(req):
        assert req.method == "POST"
        assert req.url.path == "/v10/projects/p_one/domains"
        import json as _json
        captured["body"] = _json.loads(req.content)
        return httpx.Response(200, json={"name": "www.homeloom.app"})
    vercel.add_domain_to_project("p_one", "www.homeloom.app",
                                  client=_client(handler))
    assert captured["body"] == {"name": "www.homeloom.app"}


def test_add_domain_with_redirect():
    captured = {}
    def handler(req):
        import json as _json
        captured["body"] = _json.loads(req.content)
        return httpx.Response(200, json={})
    vercel.add_domain_to_project(
        "p_one", "www.homeloom.app",
        redirect_to="homeloom.app", status_code=308,
        client=_client(handler),
    )
    assert captured["body"] == {
        "name": "www.homeloom.app",
        "redirect": "homeloom.app",
        "redirectStatusCode": 308,
    }


def test_add_domain_409_already_in_other_project_raises():
    def handler(req):
        return httpx.Response(409, json={"error": {"code": "domain_taken"}})
    with pytest.raises(vercel.VercelAPIError, match="HTTP 409"):
        vercel.add_domain_to_project("p_one", "x.com",
                                      client=_client(handler))


# ---------- verify_token + error/credential paths ----------


def test_verify_token_200():
    def handler(req):
        assert req.url.path == "/v2/user"
        return httpx.Response(200, json={"user": {"username": "vijo"}})
    result = vercel.verify_token(client=_client(handler))
    assert result["user"]["username"] == "vijo"


def test_verify_token_401_raises():
    def handler(req):
        return httpx.Response(401, text="invalid token")
    with pytest.raises(vercel.VercelAPIError, match="HTTP 401"):
        vercel.verify_token(client=_client(handler))


def test_read_token_missing_raises(monkeypatch):
    """When VERCEL_TOKEN is unset in portfolio.env, _read_token surfaces
    a MissingCredentialsError with an actionable hint."""
    from portfolio import apikeys
    monkeypatch.setattr(apikeys, "get_key", lambda k: "")
    with pytest.raises(vercel.MissingCredentialsError,
                       match="VERCEL_TOKEN not set"):
        vercel._read_token()


def test_read_token_present_returns_stripped(monkeypatch):
    from portfolio import apikeys
    monkeypatch.setattr(apikeys, "get_key", lambda k: "  abc123  ")
    assert vercel._read_token() == "abc123"
