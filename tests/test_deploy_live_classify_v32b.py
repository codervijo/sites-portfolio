"""v32.B — `_probe_apex_live`: a deploy is "live" only when the apex serves
THIS site. A 3xx that lands on a parking/forwarder host (Porkbun URL
Forwarding → l.ink, or any off-domain host) is NOT live, even though the
redirect chain ends in a 200. Same-site redirects (apex→www, http→https)
stay live. See ADR-0022 rule (a) + the mdburst.com false-green bug.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio.cli import _probe_apex_live


class _Resp:
    def __init__(self, status_code, url, text=""):
        self.status_code = status_code
        self.url = url
        self.text = text


def _patch(monkeypatch, resp=None, exc=None):
    def _fake(url, **kw):
        if exc is not None:
            raise exc
        return resp
    monkeypatch.setattr("httpx.get", _fake)
    monkeypatch.setattr("httpx.head", _fake)


# ---- not live: redirect lands off-domain / on a parking host ----


def test_redirect_to_link_is_not_live(monkeypatch):
    # mdburst.com → 302 → https://l.ink/... (final 200). l.ink is in
    # PARKED_HOST_SUFFIXES → classified parked → NOT live.
    _patch(monkeypatch, _Resp(200, "https://l.ink/abc123", "parked"))
    is_live, token, detail = _probe_apex_live("mdburst.com")
    assert is_live is False
    assert token == "parked"
    assert detail == "l.ink"


def test_redirect_to_other_registrable_domain_is_not_live(monkeypatch):
    _patch(monkeypatch, _Resp(200, "https://someoneelse.com/", "hi"))
    is_live, token, detail = _probe_apex_live("mysite.com")
    assert is_live is False
    assert token == "forwarder"
    assert detail == "someoneelse.com"


# ---- live: same-site redirects ----


def test_apex_to_www_stays_live(monkeypatch):
    _patch(monkeypatch, _Resp(200, "https://www.example.com/", "<html>ok"))
    is_live, token, detail = _probe_apex_live("example.com")
    assert is_live is True
    assert token == "200"
    assert detail is None


def test_http_to_https_stays_live(monkeypatch):
    # final URL is the https apex itself (same registrable domain).
    _patch(monkeypatch, _Resp(200, "https://example.com/", "<html>ok"))
    is_live, token, _ = _probe_apex_live("example.com")
    assert is_live is True
    assert token == "200"


def test_direct_200_is_live(monkeypatch):
    _patch(monkeypatch, _Resp(200, "https://example.com/", "<html>ok"))
    assert _probe_apex_live("example.com", head=True)[0] is True


# ---- not live: non-2xx + transport errors ----


def test_same_domain_404_is_not_live(monkeypatch):
    _patch(monkeypatch, _Resp(404, "https://example.com/404", ""))
    is_live, token, _ = _probe_apex_live("example.com")
    assert is_live is False
    assert token == "404"


def test_connect_error_is_dns_token(monkeypatch):
    _patch(monkeypatch, exc=httpx.ConnectError("no dns"))
    is_live, token, _ = _probe_apex_live("example.com")
    assert is_live is False
    assert token == "DNS"


def test_generic_http_error_is_err_token(monkeypatch):
    _patch(monkeypatch, exc=httpx.ReadTimeout("slow"))
    is_live, token, detail = _probe_apex_live("example.com")
    assert is_live is False
    assert token == "err"
    assert detail == "ReadTimeout"
