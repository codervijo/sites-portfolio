"""Tests for src/portfolio/availability.py — Porkbun + RDAP backends and orchestration."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from portfolio import availability
from portfolio.availability import (
    AvailabilityChecker,
    AvailResult,
    porkbun_check,
    rdap_check,
)


# ---------- porkbun_check ----------


def test_porkbun_check_available_with_price():
    fake = MagicMock()
    fake.json.return_value = {
        "status": "SUCCESS",
        "response": {"avail": "yes", "price": "11.98"},
    }
    with patch("portfolio.availability.requests") as r:
        r.post.return_value = fake
        out = porkbun_check("flow.com", "k", "s")
    assert out.available is True
    assert out.price == 11.98
    assert out.backend == "porkbun"
    assert out.error is None


def test_porkbun_check_not_available():
    fake = MagicMock()
    fake.json.return_value = {"response": {"avail": "no"}}
    with patch("portfolio.availability.requests") as r:
        r.post.return_value = fake
        out = porkbun_check("taken.com", "k", "s")
    assert out.available is False
    assert out.price is None


def test_porkbun_check_error_response():
    fake = MagicMock()
    fake.json.return_value = {"status": "ERROR", "message": "rate limited"}
    with patch("portfolio.availability.requests") as r:
        r.post.return_value = fake
        out = porkbun_check("flow.com", "k", "s")
    assert out.available is None
    assert "rate limited" in out.error


def test_porkbun_check_handles_network_exception():
    with patch("portfolio.availability.requests") as r:
        r.post.side_effect = ConnectionError("nope")
        out = porkbun_check("flow.com", "k", "s")
    assert out.available is None
    assert "ConnectionError" in out.error


def test_porkbun_check_money_parsing_with_dollar_sign():
    fake = MagicMock()
    fake.json.return_value = {"response": {"avail": "yes", "price": "$11.98"}}
    with patch("portfolio.availability.requests") as r:
        r.post.return_value = fake
        out = porkbun_check("flow.com", "k", "s")
    assert out.price == 11.98


# ---------- rdap_check ----------


def test_rdap_check_404_means_available(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    fake_404 = MagicMock(status_code=404)
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]},
        )
        # second call: domain query → 404
        r.get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}),
            fake_404,
        ]
        out = rdap_check("flow.com")
    assert out.available is True
    assert out.price is None
    assert out.backend == "rdap"


def test_rdap_check_200_means_taken(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}),
            MagicMock(status_code=200),
        ]
        out = rdap_check("google.com")
    assert out.available is False


def test_rdap_check_unknown_tld(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]},
        )
        out = rdap_check("flow.zzz")
    assert out.available is None
    assert out.error is not None
    assert "no RDAP endpoint" in out.error


def test_rdap_uses_cached_endpoints(tmp_path, monkeypatch):
    cache_path = tmp_path / "rdap.json"
    cache_path.write_text(json.dumps({
        "cached_at": time.time(),
        "services": {"com": ["https://example.com/rdap/"]},
    }))
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", cache_path)
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(status_code=404)
        out = rdap_check("flow.com")
    # Only ONE network call (the domain query), no bootstrap fetch.
    assert r.get.call_count == 1
    assert out.available is True


# ---------- AvailabilityChecker orchestration ----------


def test_checker_picks_porkbun_when_keys_present():
    c = AvailabilityChecker(porkbun_api_key="k", porkbun_secret_key="s")
    assert c.backend == "porkbun"


def test_checker_picks_rdap_when_keys_missing():
    c = AvailabilityChecker(porkbun_api_key=None, porkbun_secret_key=None)
    assert c.backend == "rdap"


def test_checker_picks_rdap_when_only_one_key_present():
    c = AvailabilityChecker(porkbun_api_key="k", porkbun_secret_key=None)
    assert c.backend == "rdap"


def test_checker_check_routes_to_porkbun():
    c = AvailabilityChecker(porkbun_api_key="k", porkbun_secret_key="s", rate_delay_s=0)
    with patch("portfolio.availability.porkbun_check") as p, \
         patch("portfolio.availability.rdap_check") as rd:
        p.return_value = AvailResult(True, 9.99, "porkbun")
        result = c.check("flow.com")
    assert result.backend == "porkbun"
    assert p.call_count == 1
    assert rd.call_count == 0


def test_checker_check_routes_to_rdap_when_no_keys():
    c = AvailabilityChecker(rate_delay_s=0)
    with patch("portfolio.availability.porkbun_check") as p, \
         patch("portfolio.availability.rdap_check") as rd:
        rd.return_value = AvailResult(True, None, "rdap")
        c.check("flow.com")
    assert p.call_count == 0
    assert rd.call_count == 1


def test_checker_rate_limits_between_calls(monkeypatch):
    c = AvailabilityChecker(rate_delay_s=0.05)
    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)
    monkeypatch.setattr(availability.time, "sleep", fake_sleep)
    with patch("portfolio.availability.rdap_check") as rd:
        rd.return_value = AvailResult(True, None, "rdap")
        c.check("a.com")
        c.check("b.com")
    # Second call should have triggered a sleep close to 0.05s.
    assert any(s > 0 for s in sleeps)


def test_make_check_callable_returns_tuple():
    c = AvailabilityChecker(rate_delay_s=0)
    with patch("portfolio.availability.rdap_check") as rd:
        rd.return_value = AvailResult(available=True, price=None, backend="rdap")
        f = c.make_check_callable()
        avail, price = f("flow.com")
    assert avail is True
    assert price is None
