"""v32.D — Porkbun URL Forwarding read + opt-in clear. URL Forwarding pins a
domain to Porkbun nameservers regardless of the stored NS value, so an active
apex forward silently no-ops the CF cutover (the mdburst.com false-green root
cause). lamill reads it as the real blocker and clears it only on explicit
`--clear-forwarding`.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio.porkbun_dns import (
    PorkbunDnsError,
    UrlForward,
    delete_porkbun_url_forward,
    get_porkbun_url_forwarding,
)


def _post(monkeypatch, handler):
    monkeypatch.setattr(
        httpx, "post",
        lambda url, **kw: handler(httpx.Request(
            "POST", url, **{k: v for k, v in kw.items() if k != "timeout"})),
    )


# ---- get_porkbun_url_forwarding ----


def test_get_forwarding_parses_records(monkeypatch):
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return httpx.Response(200, json={
            "status": "SUCCESS",
            "forwards": [
                {"id": "42", "subdomain": "", "location": "https://x.l.ink/",
                 "type": "temporary"},
                {"id": "43", "subdomain": "blog",
                 "location": "https://elsewhere.com", "type": "permanent"},
            ],
        })

    _post(monkeypatch, handler)
    out = get_porkbun_url_forwarding("mdburst.com", api_key="k", secret="s")
    assert "getUrlForwarding/mdburst.com" in captured["url"]
    assert [f.id for f in out] == ["42", "43"]
    apex = [f for f in out if f.is_apex]
    assert len(apex) == 1 and apex[0].id == "42"
    assert out[1].is_apex is False  # subdomain="blog"


def test_get_forwarding_empty(monkeypatch):
    _post(monkeypatch, lambda req: httpx.Response(
        200, json={"status": "SUCCESS", "forwards": []}))
    assert get_porkbun_url_forwarding("ex.com", api_key="k", secret="s") == []


def test_get_forwarding_non_success_raises(monkeypatch):
    _post(monkeypatch, lambda req: httpx.Response(
        200, json={"status": "ERROR", "message": "domain not found"}))
    with pytest.raises(PorkbunDnsError, match="status != SUCCESS"):
        get_porkbun_url_forwarding("ex.com", api_key="k", secret="s")


def test_get_forwarding_missing_creds(monkeypatch):
    with pytest.raises(PorkbunDnsError, match="missing PORKBUN"):
        get_porkbun_url_forwarding("ex.com", api_key="", secret="s")


# ---- delete_porkbun_url_forward ----


def test_delete_forward_hits_expected_url(monkeypatch):
    captured = {}

    def handler(req):
        captured["url"] = str(req.url)
        return httpx.Response(200, json={"status": "SUCCESS"})

    _post(monkeypatch, handler)
    delete_porkbun_url_forward("mdburst.com", "42", api_key="k", secret="s")
    assert "deleteUrlForward/mdburst.com/42" in captured["url"]


def test_delete_forward_refuses_empty_id(monkeypatch):
    def handler(req):  # pragma: no cover - must not be called
        raise AssertionError("should not POST with an empty record id")
    _post(monkeypatch, handler)
    with pytest.raises(PorkbunDnsError, match="empty id"):
        delete_porkbun_url_forward("ex.com", "", api_key="k", secret="s")


def test_delete_forward_failure_status_raises(monkeypatch):
    _post(monkeypatch, lambda req: httpx.Response(
        200, json={"status": "ERROR", "message": "nope"}))
    with pytest.raises(PorkbunDnsError, match="status != SUCCESS"):
        delete_porkbun_url_forward("ex.com", "9", api_key="k", secret="s")


def test_url_forward_is_apex_flag():
    assert UrlForward("1", "", "https://x", "temporary").is_apex is True
    assert UrlForward("2", "www", "https://x", "temporary").is_apex is False


# ---- _porkbun_forwarding_preflight (CLI integration) ----


def test_preflight_warns_when_active_and_not_clearing(monkeypatch, capsys):
    from portfolio import cli
    monkeypatch.setattr(
        "portfolio.porkbun_dns.get_porkbun_url_forwarding",
        lambda domain, **kw: [UrlForward("42", "", "https://x.l.ink/", "temporary")])
    cli._porkbun_forwarding_preflight(
        "mdburst.com", api_key="k", secret="s", clear=False, yes=True)
    out = capsys.readouterr().out
    assert "URL Forwarding active" in out
    assert "--clear-forwarding" in out


def test_preflight_clears_when_flag_set(monkeypatch, capsys):
    from portfolio import cli
    deleted = []
    monkeypatch.setattr(
        "portfolio.porkbun_dns.get_porkbun_url_forwarding",
        lambda domain, **kw: [UrlForward("42", "", "https://x.l.ink/", "temporary")])
    monkeypatch.setattr(
        "portfolio.porkbun_dns.delete_porkbun_url_forward",
        lambda domain, rid, **kw: deleted.append(rid))
    cli._porkbun_forwarding_preflight(
        "mdburst.com", api_key="k", secret="s", clear=True, yes=True)
    out = capsys.readouterr().out
    assert deleted == ["42"]
    assert "cleared 1 apex URL forward" in out


def test_preflight_silent_when_no_apex_forward(monkeypatch, capsys):
    from portfolio import cli
    monkeypatch.setattr(
        "portfolio.porkbun_dns.get_porkbun_url_forwarding",
        lambda domain, **kw: [UrlForward("43", "blog", "https://e.com", "permanent")])
    cli._porkbun_forwarding_preflight(
        "ex.com", api_key="k", secret="s", clear=True, yes=True)
    assert capsys.readouterr().out == ""
