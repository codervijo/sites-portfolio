"""Tests for v15.F — Porkbun listAll → CSV converter.

Stubs `httpx.post` via monkeypatch. The watch-loop in cli.py is not
exercised here (it's a polling loop; manual / integration test).
"""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from portfolio.porkbun_list import (
    PorkbunListError,
    fetch_porkbun_domains,
    refresh_porkbun_csv,
    write_porkbun_csv,
)


def _stub_post(monkeypatch, response_or_exc):
    """Patch httpx.post (imported at module level in porkbun_list)."""
    def _post(*args, **kwargs):
        if isinstance(response_or_exc, Exception):
            raise response_or_exc
        return response_or_exc
    monkeypatch.setattr("portfolio.porkbun_list.httpx.post", _post)


def _ok_response(domains):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"status": "SUCCESS", "domains": domains}
    return resp


# ---- error paths ---------------------------------------------------


def test_missing_credentials_raises():
    with pytest.raises(PorkbunListError, match="missing"):
        fetch_porkbun_domains("", "")
    with pytest.raises(PorkbunListError, match="missing"):
        fetch_porkbun_domains("key", "")
    with pytest.raises(PorkbunListError, match="missing"):
        fetch_porkbun_domains("", "secret")


def test_network_error_wrapped(monkeypatch):
    _stub_post(monkeypatch, httpx.ConnectError("refused"))
    with pytest.raises(PorkbunListError, match="network error"):
        fetch_porkbun_domains("key", "secret")


def test_non_200_response(monkeypatch):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 500
    _stub_post(monkeypatch, resp)
    with pytest.raises(PorkbunListError, match="HTTP 500"):
        fetch_porkbun_domains("key", "secret")


def test_non_json_body(monkeypatch):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.side_effect = ValueError("not json")
    _stub_post(monkeypatch, resp)
    with pytest.raises(PorkbunListError, match="non-JSON"):
        fetch_porkbun_domains("key", "secret")


def test_non_success_status(monkeypatch):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"status": "ERROR", "message": "auth failed"}
    _stub_post(monkeypatch, resp)
    with pytest.raises(PorkbunListError, match="status != SUCCESS"):
        fetch_porkbun_domains("key", "secret")


def test_domains_not_a_list(monkeypatch):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"status": "SUCCESS", "domains": "wat"}
    _stub_post(monkeypatch, resp)
    with pytest.raises(PorkbunListError, match="not a list"):
        fetch_porkbun_domains("key", "secret")


# ---- happy paths ---------------------------------------------------


def test_fetch_posts_to_listall_endpoint(monkeypatch):
    # Guard the endpoint — the rest of the suite's stub ignores the URL, so a
    # wrong path would ship green (the GoDaddy-class blind spot).
    seen = {}

    def _post(url, *a, **kw):
        seen["url"] = url
        return _ok_response([])

    monkeypatch.setattr("portfolio.porkbun_list.httpx.post", _post)
    fetch_porkbun_domains("key", "secret")
    assert seen["url"].endswith("/domain/listAll")


def test_fetch_normalizes_fields(monkeypatch):
    _stub_post(monkeypatch, _ok_response([{
        "domain": "Example.COM",
        "tld": "com",
        "status": "ACTIVE",
        "createDate": "2026-01-15 10:00:00",
        "expireDate": "2027-01-15 10:00:00",
        "autoRenew": "1",
        "ns": ["NS1.PORKBUN.COM", "ns2.porkbun.com"],
        "securityLock": "1",
        "whoisPrivacy": "0",
    }]))
    rows = fetch_porkbun_domains("key", "secret")
    assert len(rows) == 1
    r = rows[0]
    assert r.domain == "example.com"           # lowercased
    assert r.tld == "com"
    assert r.status == "ACTIVE"
    assert r.auto_renew is True
    assert r.security_lock is True
    assert r.whois_privacy is False
    # Nameservers normalized: lowercased + sorted.
    assert r.nameservers == ["ns1.porkbun.com", "ns2.porkbun.com"]


def test_fetch_skips_empty_domain_field(monkeypatch):
    _stub_post(monkeypatch, _ok_response([
        {"domain": "ok.com", "tld": "com"},
        {"domain": "", "tld": "com"},     # skipped — no name
        {"tld": "com"},                    # skipped — no domain key
    ]))
    rows = fetch_porkbun_domains("key", "secret")
    assert [r.domain for r in rows] == ["ok.com"]


def test_fetch_handles_comma_string_nameservers(monkeypatch):
    """Porkbun has historically returned `ns` as both a list and a
    comma string — handle both."""
    _stub_post(monkeypatch, _ok_response([{
        "domain": "x.com",
        "ns": "NS1.example.net, ns2.example.net , ns3.example.net",
    }]))
    rows = fetch_porkbun_domains("key", "secret")
    assert rows[0].nameservers == [
        "ns1.example.net", "ns2.example.net", "ns3.example.net",
    ]


# ---- CSV write ----------------------------------------------------


def test_write_csv_has_expected_headers_and_round_trips(monkeypatch, tmp_path):
    _stub_post(monkeypatch, _ok_response([{
        "domain": "ok.com",
        "tld": "com",
        "status": "ACTIVE",
        "createDate": "2026-01-15 10:00:00",
        "expireDate": "2027-01-15 10:00:00",
        "autoRenew": "1",
        "ns": ["a.example.net"],
        "securityLock": "0",
        "whoisPrivacy": "1",
    }]))
    out = tmp_path / "porkbun.csv"
    count = refresh_porkbun_csv("key", "secret", out)
    assert count == 1

    with out.open() as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    row = rows[0]
    assert row["DOMAIN"] == "ok.com"
    assert row["TLD"] == "com"
    assert row["STATUSES"] == "ACTIVE"
    assert row["CREATE DATE"] == "2026-01-15 10:00:00"
    assert row["AUTO RENEW"] == "ON"
    assert row["PRIVACY"] == "Yes"
    assert row["LOCKED"] == "No"


def test_write_csv_atomic_uses_tmpfile(tmp_path):
    """write_porkbun_csv writes to `<path>.tmp` then renames — verify
    no leftover .tmp file when the write succeeds."""
    out = tmp_path / "porkbun.csv"
    write_porkbun_csv([], out)
    assert out.exists()
    assert not (tmp_path / "porkbun.csv.tmp").exists()
