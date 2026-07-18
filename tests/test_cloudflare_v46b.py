"""Tests for v46.B — www→apex redirect provisioning in cloudflare.py (ADR-0027).

Covers:
  - www_redirect_rule (pure rule-dict shape: 301, expression, target, marker)
  - _rule_redirects_www_to_apex (marker match / behavioural match / non-match)
  - get_dynamic_redirect_rules (200 rules / 404 → [] / error / success=false)
  - put_dynamic_redirect_rules (PUT body + error mapping)
  - ensure_www_dns_record (creates proxied CNAME when absent; no-op when present)
  - ensure_www_redirect (GET-then-PUT merge appends; no-op when already present)
  - ensure_www_redirects_to_apex (combined; both-created / both-present)

All HTTP stubbed via `httpx.MockTransport`; a client is injected so no token
read happens.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import cloudflare
from portfolio.cloudflare import (
    API_BASE,
    CloudflareAPIError,
    WwwProvision,
    ensure_www_dns_record,
    ensure_www_redirect,
    ensure_www_redirects_to_apex,
    get_dynamic_redirect_rules,
    put_dynamic_redirect_rules,
    www_dns_present,
    www_redirect_present,
    www_redirect_rule,
    _rule_redirects_www_to_apex,
)

APEX = "voltloop.site"
ZID = "zone123"
_PREFIX = httpx.URL(API_BASE).path  # "/client/v4" — carried on req.url.path
_ENTRYPOINT = f"{_PREFIX}/zones/{ZID}/rulesets/phases/http_request_dynamic_redirect/entrypoint"
_DNS = f"{_PREFIX}/zones/{ZID}/dns_records"


def _client_for(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(
        base_url=API_BASE,
        transport=transport,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
    )


# ---- www_redirect_rule (pure) ----


def test_www_redirect_rule_shape():
    rule = www_redirect_rule(APEX)
    assert rule["action"] == "redirect"
    assert rule["expression"] == f'(http.host eq "www.{APEX}")'
    assert rule["enabled"] is True
    fv = rule["action_parameters"]["from_value"]
    assert fv["status_code"] == 301
    assert fv["preserve_query_string"] is True
    assert fv["target_url"]["expression"] == (
        f'concat("https://{APEX}", http.request.uri.path)'
    )
    assert rule["description"] == f"lamill:www-to-apex:{APEX}"


def test_www_redirect_rule_honors_status_code():
    assert www_redirect_rule(APEX, status_code=308)[
        "action_parameters"]["from_value"]["status_code"] == 308


# ---- _rule_redirects_www_to_apex (detection) ----


def test_detect_matches_own_marker():
    assert _rule_redirects_www_to_apex(www_redirect_rule(APEX), APEX) is True


def test_detect_matches_dashboard_rule_by_behaviour():
    """A rule made in the CF dashboard (no marker) still counts if it
    redirects www.<apex> to the apex."""
    dash = {
        "action": "redirect",
        "enabled": True,
        "expression": f'(http.host eq "www.{APEX}")',
        "action_parameters": {"from_value": {
            "target_url": {"expression": f'concat("https://{APEX}", http.request.uri.path)'},
        }},
    }
    assert _rule_redirects_www_to_apex(dash, APEX) is True


def test_detect_rejects_other_host_redirect():
    other = {
        "action": "redirect",
        "enabled": True,
        "expression": '(http.host eq "old.example.com")',
        "action_parameters": {"from_value": {"target_url": {"expression": '"https://new.example.com"'}}},
    }
    assert _rule_redirects_www_to_apex(other, APEX) is False


def test_detect_rejects_disabled_and_non_redirect():
    disabled = www_redirect_rule(APEX) | {"enabled": False}
    assert _rule_redirects_www_to_apex(disabled, APEX) is False
    blocky = {"action": "block", "enabled": True, "expression": f'(http.host eq "www.{APEX}")'}
    assert _rule_redirects_www_to_apex(blocky, APEX) is False


# ---- get_dynamic_redirect_rules ----


def test_get_rules_returns_rules_on_200():
    rules = [www_redirect_rule(APEX)]

    def handler(req):
        assert req.method == "GET" and req.url.path == _ENTRYPOINT
        return httpx.Response(200, json={"success": True, "result": {"rules": rules}})

    assert get_dynamic_redirect_rules(ZID, client=_client_for(handler)) == rules


def test_get_rules_treats_404_as_empty():
    """A zone with no dynamic-redirect ruleset yet answers 404 → []."""
    def handler(req):
        return httpx.Response(404, json={"success": False, "errors": [{"code": 1000}]})

    assert get_dynamic_redirect_rules(ZID, client=_client_for(handler)) == []


def test_get_rules_raises_on_403_scope_gap():
    """The token-scope gap (Dynamic Redirect edit missing) is a 403 → raises,
    it is not swallowed like the 404 no-ruleset case."""
    def handler(req):
        return httpx.Response(403, json={"success": False, "errors": [{"code": 10000, "message": "Authentication error"}]})

    with pytest.raises(CloudflareAPIError):
        get_dynamic_redirect_rules(ZID, client=_client_for(handler))


def test_get_rules_raises_on_success_false():
    def handler(req):
        return httpx.Response(200, json={"success": False, "errors": [{"code": 1}]})

    with pytest.raises(CloudflareAPIError):
        get_dynamic_redirect_rules(ZID, client=_client_for(handler))


# ---- put_dynamic_redirect_rules ----


def test_put_rules_sends_rules_body():
    captured = {}

    def handler(req):
        captured["method"] = req.method
        captured["path"] = req.url.path
        import json
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"success": True, "result": {"rules": []}})

    rules = [www_redirect_rule(APEX)]
    put_dynamic_redirect_rules(ZID, rules, client=_client_for(handler))
    assert captured["method"] == "PUT"
    assert captured["path"] == _ENTRYPOINT
    assert captured["body"] == {"rules": rules}


def test_put_rules_raises_on_error():
    def handler(req):
        return httpx.Response(400, json={"success": False, "errors": [{"code": 20000}]})

    with pytest.raises(CloudflareAPIError):
        put_dynamic_redirect_rules(ZID, [], client=_client_for(handler))


# ---- ensure_www_dns_record ----


def test_ensure_dns_creates_proxied_cname_when_absent():
    captured = {}

    def handler(req):
        if req.method == "GET" and req.url.path == _DNS:
            return httpx.Response(200, json={"success": True, "result": [
                {"id": "r1", "type": "A", "name": APEX, "content": "1.2.3.4", "proxied": True},
            ]})
        if req.method == "POST" and req.url.path == _DNS:
            import json
            captured["body"] = json.loads(req.content)
            return httpx.Response(200, json={"success": True, "result": {
                "id": "r2", "type": "CNAME", "name": f"www.{APEX}", "content": APEX, "proxied": True,
            }})
        raise AssertionError(f"unexpected {req.method} {req.url.path}")

    created = ensure_www_dns_record(ZID, APEX, client=_client_for(handler))
    assert created is True
    assert captured["body"] == {
        "type": "CNAME", "name": f"www.{APEX}", "content": APEX,
        "ttl": 1, "proxied": True,
    }


def test_ensure_dns_noop_when_www_present():
    posted = []

    def handler(req):
        if req.method == "GET" and req.url.path == _DNS:
            return httpx.Response(200, json={"success": True, "result": [
                {"id": "r2", "type": "CNAME", "name": f"www.{APEX}", "content": APEX, "proxied": True},
            ]})
        posted.append(req)  # a POST here would be a bug
        return httpx.Response(200, json={"success": True, "result": {}})

    assert ensure_www_dns_record(ZID, APEX, client=_client_for(handler)) is False
    assert posted == []


# ---- ensure_www_redirect ----


def test_ensure_redirect_appends_preserving_existing():
    """GET-then-PUT merge: keeps the operator's unrelated rule, appends ours."""
    existing = {
        "action": "redirect", "enabled": True,
        "expression": '(http.host eq "legacy.example.com")',
        "action_parameters": {"from_value": {"status_code": 301, "target_url": {"expression": '"https://example.com"'}}},
    }
    captured = {}

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"success": True, "result": {"rules": [existing]}})
        if req.method == "PUT":
            import json
            captured["body"] = json.loads(req.content)
            return httpx.Response(200, json={"success": True, "result": {"rules": []}})
        raise AssertionError

    created = ensure_www_redirect(ZID, APEX, client=_client_for(handler))
    assert created is True
    sent = captured["body"]["rules"]
    assert sent[0] == existing                       # existing preserved, first
    assert sent[1] == www_redirect_rule(APEX)        # ours appended


def test_ensure_redirect_noop_when_already_present():
    """A conformant rule already there → no PUT (idempotent for the 11)."""
    puts = []

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"success": True, "result": {"rules": [www_redirect_rule(APEX)]}})
        puts.append(req)
        return httpx.Response(200, json={"success": True, "result": {}})

    assert ensure_www_redirect(ZID, APEX, client=_client_for(handler)) is False
    assert puts == []


# ---- ensure_www_redirects_to_apex (combined) ----


def _combined_handler(*, www_dns_present: bool, redirect_present: bool, captured=None):
    def handler(req):
        p = req.url.path
        if p == _DNS and req.method == "GET":
            result = []
            if www_dns_present:
                result = [{"id": "r2", "type": "CNAME", "name": f"www.{APEX}", "content": APEX, "proxied": True}]
            return httpx.Response(200, json={"success": True, "result": result})
        if p == _DNS and req.method == "POST":
            if captured is not None:
                captured.append("POST dns")
            return httpx.Response(200, json={"success": True, "result": {
                "id": "r9", "type": "CNAME", "name": f"www.{APEX}", "content": APEX, "proxied": True}})
        if p == _ENTRYPOINT and req.method == "GET":
            rules = [www_redirect_rule(APEX)] if redirect_present else []
            return httpx.Response(200, json={"success": True, "result": {"rules": rules}})
        if p == _ENTRYPOINT and req.method == "PUT":
            if captured is not None:
                captured.append("PUT rule")
            return httpx.Response(200, json={"success": True, "result": {"rules": []}})
        raise AssertionError(f"unexpected {req.method} {p}")
    return handler


def test_combined_creates_both_when_nothing_present():
    captured = []
    res = ensure_www_redirects_to_apex(
        ZID, APEX, client=_client_for(_combined_handler(
            www_dns_present=False, redirect_present=False, captured=captured)))
    assert isinstance(res, WwwProvision)
    assert res.dns_created and res.rule_created and res.changed
    assert captured == ["POST dns", "PUT rule"]


def test_combined_noop_when_both_present():
    captured = []
    res = ensure_www_redirects_to_apex(
        ZID, APEX, client=_client_for(_combined_handler(
            www_dns_present=True, redirect_present=True, captured=captured)))
    assert not res.dns_created and not res.rule_created and not res.changed
    assert captured == []  # no writes


def test_combined_partial_dns_only():
    """www DNS exists but no redirect rule → only the rule is created."""
    res = ensure_www_redirects_to_apex(
        ZID, APEX, client=_client_for(_combined_handler(
            www_dns_present=True, redirect_present=False)))
    assert res.dns_created is False
    assert res.rule_created is True
    assert res.changed is True


# ---- www_dns_present / www_redirect_present (read-only detection) ----


def test_www_dns_present_true_and_false():
    def with_www(req):
        return httpx.Response(200, json={"success": True, "result": [
            {"id": "r2", "type": "CNAME", "name": f"www.{APEX}", "content": APEX, "proxied": True}]})

    def without_www(req):
        return httpx.Response(200, json={"success": True, "result": [
            {"id": "r1", "type": "A", "name": APEX, "content": "1.2.3.4", "proxied": True}]})

    assert www_dns_present(ZID, APEX, client=_client_for(with_www)) is True
    assert www_dns_present(ZID, APEX, client=_client_for(without_www)) is False


def test_www_redirect_present_true_and_false():
    def with_rule(req):
        return httpx.Response(200, json={"success": True, "result": {"rules": [www_redirect_rule(APEX)]}})

    def without_rule(req):
        return httpx.Response(200, json={"success": True, "result": {"rules": []}})

    assert www_redirect_present(ZID, APEX, client=_client_for(with_rule)) is True
    assert www_redirect_present(ZID, APEX, client=_client_for(without_rule)) is False


def test_www_redirect_present_raises_on_403_scope_gap():
    """The scope gap propagates so the fixer can surface an actionable hint
    rather than silently reporting 'no redirect'."""
    def handler(req):
        return httpx.Response(403, json={"success": False, "errors": [{"code": 10000}]})

    with pytest.raises(CloudflareAPIError):
        www_redirect_present(ZID, APEX, client=_client_for(handler))
