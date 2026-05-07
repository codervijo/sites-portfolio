"""Tests for src/portfolio/availability.py — RDAP availability + Porkbun pricing.

All network calls mocked. The Porkbun /domain/checkAvailability endpoint
was removed by Porkbun in 2026 — this module no longer uses it; tests
reflect the current RDAP+pricing architecture.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from portfolio import availability
from portfolio.availability import (
    AvailabilityChecker,
    AvailResult,
    _fetch_porkbun_pricing,
    load_porkbun_pricing,
    lookup_price,
    rdap_check,
)


# ---------- Porkbun pricing fetch ----------


def test_fetch_pricing_parses_success():
    fake = MagicMock(status_code=200)
    fake.json.return_value = {
        "status": "SUCCESS",
        "pricing": {
            "com": {"registration": "11.08", "renewal": "13.50", "transfer": "11.08"},
            "ai": {"registration": "82.70", "renewal": "82.70", "transfer": "82.70"},
        },
    }
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = fake
        out = _fetch_porkbun_pricing()
    assert out is not None
    assert out["com"]["registration"] == "11.08"
    assert out["ai"]["registration"] == "82.70"


def test_fetch_pricing_returns_none_on_non_200():
    fake = MagicMock(status_code=404)
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = fake
        out = _fetch_porkbun_pricing()
    assert out is None


def test_fetch_pricing_returns_none_on_status_error():
    fake = MagicMock(status_code=200)
    fake.json.return_value = {"status": "ERROR", "message": "rate limited"}
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = fake
        out = _fetch_porkbun_pricing()
    assert out is None


def test_fetch_pricing_retries_on_5xx(monkeypatch):
    """5xx triggers retry; if final attempt succeeds, return pricing."""
    monkeypatch.setattr(availability, "PORKBUN_PRICING_RETRY_BACKOFF_S", 0)
    fake_503 = MagicMock(status_code=503)
    fake_ok = MagicMock(status_code=200)
    fake_ok.json.return_value = {"status": "SUCCESS", "pricing": {"com": {"registration": "11.08"}}}
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = [fake_503, fake_ok]
        out = _fetch_porkbun_pricing()
    assert out is not None
    assert out["com"]["registration"] == "11.08"


def test_fetch_pricing_retries_on_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr(availability, "PORKBUN_PRICING_RETRY_BACKOFF_S", 0)
    import requests as r_mod
    fake_ok = MagicMock(status_code=200)
    fake_ok.json.return_value = {"status": "SUCCESS", "pricing": {"com": {"registration": "11.08"}}}
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = [r_mod.exceptions.ReadTimeout("timeout"), fake_ok]
        out = _fetch_porkbun_pricing()
    assert out is not None


# ---------- pricing cache ----------


def test_load_pricing_uses_fresh_cache(tmp_path, monkeypatch):
    cache = tmp_path / "porkbun_pricing.json"
    cache.write_text(json.dumps({
        "cached_at": time.time(),
        "pricing": {"com": {"registration": "11.08"}},
    }))
    monkeypatch.setattr(availability, "PORKBUN_PRICING_CACHE_PATH", cache)
    with patch("portfolio.availability.requests") as r:
        out = load_porkbun_pricing()
    # Should not have hit the network
    r.get.assert_not_called()
    assert out["com"]["registration"] == "11.08"


def test_load_pricing_refetches_when_stale(tmp_path, monkeypatch):
    cache = tmp_path / "porkbun_pricing.json"
    monkeypatch.setattr(availability, "PORKBUN_PRICING_CACHE_PATH", cache)
    monkeypatch.setattr(availability, "PORKBUN_PRICING_TTL_SECONDS", 0)
    cache.write_text(json.dumps({"cached_at": time.time() - 1, "pricing": {"com": {"registration": "OLD"}}}))
    fake_ok = MagicMock(status_code=200)
    fake_ok.json.return_value = {"status": "SUCCESS", "pricing": {"com": {"registration": "11.08"}}}
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = fake_ok
        out = load_porkbun_pricing()
    assert out["com"]["registration"] == "11.08"


def test_load_pricing_returns_empty_dict_on_persistent_failure(tmp_path, monkeypatch):
    """Better to return {} than raise so callers can degrade to no-price."""
    cache = tmp_path / "porkbun_pricing.json"
    monkeypatch.setattr(availability, "PORKBUN_PRICING_CACHE_PATH", cache)
    monkeypatch.setattr(availability, "PORKBUN_PRICING_RETRY_BACKOFF_S", 0)
    fake_500 = MagicMock(status_code=500)
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = fake_500
        out = load_porkbun_pricing()
    assert out == {}


# ---------- lookup_price ----------


def test_lookup_price_basic():
    pricing = {"com": {"registration": "11.08"}, "ai": {"registration": "82.70"}}
    assert lookup_price("flow.com", pricing) == 11.08
    assert lookup_price("flow.ai", pricing) == 82.70


def test_lookup_price_missing_tld_returns_none():
    pricing = {"com": {"registration": "11.08"}}
    assert lookup_price("flow.zzz", pricing) is None


def test_lookup_price_handles_dollar_sign_strings():
    pricing = {"com": {"registration": "$11.08"}}
    assert lookup_price("flow.com", pricing) == 11.08


def test_lookup_price_returns_none_when_pricing_empty():
    assert lookup_price("flow.com", {}) is None


def test_lookup_price_handles_multipart_tld():
    pricing = {
        "com": {"registration": "11.08"},
        "co.in": {"registration": "9.99"},
    }
    # The multi-part TLD should match before the leaf .in
    assert lookup_price("flow.co.in", pricing) == 9.99


# ---------- RDAP availability ----------


def test_rdap_404_means_available(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    with patch("portfolio.availability.requests") as r:
        # Bootstrap call returns endpoints
        r.get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}),
            MagicMock(status_code=404),
        ]
        out = rdap_check("flow.com")
    assert out.available is True
    assert out.error is None


def test_rdap_200_means_taken(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = [
            MagicMock(status_code=200, json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]}),
            MagicMock(status_code=200),
        ]
        out = rdap_check("google.com")
    assert out.available is False


def test_rdap_unknown_tld_no_error(tmp_path, monkeypatch):
    """A TLD with no RDAP endpoint should return None+no-error (genuine gap)."""
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"services": [[["com"], ["https://rdap.verisign.com/com/v1/"]]]},
        )
        out = rdap_check("flow.zzz")
    assert out.available is None
    assert out.error is None  # not an error — just no endpoint


def test_rdap_retries_on_timeout_then_succeeds(tmp_path, monkeypatch):
    """Transient timeout should trigger retry; eventual success returns proper avail."""
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    monkeypatch.setattr(availability, "DEFAULT_RETRY_BACKOFF_S", 0)
    cache = tmp_path / "rdap.json"
    cache.write_text(json.dumps({"cached_at": time.time(), "services": {"com": ["https://example/"]}}))

    import requests as r_mod
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = [
            r_mod.exceptions.ReadTimeout("timeout"),
            MagicMock(status_code=404),
        ]
        out = rdap_check("flow.com", retries=1, backoff_s=0)
    assert out.available is True
    assert out.error is None


def test_rdap_retries_then_gives_up_with_error(tmp_path, monkeypatch):
    """Persistent failure surfaces error after exhausting retries."""
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    cache = tmp_path / "rdap.json"
    cache.write_text(json.dumps({"cached_at": time.time(), "services": {"com": ["https://example/"]}}))

    import requests as r_mod
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = r_mod.exceptions.ConnectionError("dns fail")
        out = rdap_check("flow.com", retries=1, backoff_s=0)
    assert out.available is None
    assert out.error is not None
    assert "ConnectionError" in out.error or "dns fail" in out.error


def test_rdap_5xx_retries_then_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    cache = tmp_path / "rdap.json"
    cache.write_text(json.dumps({"cached_at": time.time(), "services": {"com": ["https://example/"]}}))
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(status_code=503)
        out = rdap_check("flow.com", retries=1, backoff_s=0)
    assert out.available is None
    assert out.error is not None
    assert "503" in out.error


# ---------- AvailabilityChecker ----------


def test_checker_combines_rdap_and_pricing(tmp_path, monkeypatch):
    """check() returns avail from RDAP and price from pricing dict."""
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    monkeypatch.setattr(availability, "PORKBUN_PRICING_CACHE_PATH", tmp_path / "pricing.json")
    (tmp_path / "rdap.json").write_text(json.dumps({"cached_at": time.time(),
                                                     "services": {"com": ["https://example/"]}}))
    (tmp_path / "pricing.json").write_text(json.dumps({
        "cached_at": time.time(),
        "pricing": {"com": {"registration": "11.08"}},
    }))
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(status_code=404)  # → available
        chk = AvailabilityChecker(rate_delay_s=0)
        out = chk.check("flow.com")
    assert out.available is True
    assert out.price == 11.08
    assert out.error is None


def test_checker_propagates_rdap_error(tmp_path, monkeypatch):
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    monkeypatch.setattr(availability, "PORKBUN_PRICING_CACHE_PATH", tmp_path / "pricing.json")
    monkeypatch.setattr(availability, "DEFAULT_RETRY_BACKOFF_S", 0)
    (tmp_path / "rdap.json").write_text(json.dumps({"cached_at": time.time(),
                                                     "services": {"com": ["https://example/"]}}))
    (tmp_path / "pricing.json").write_text(json.dumps({
        "cached_at": time.time(),
        "pricing": {"com": {"registration": "11.08"}},
    }))
    import requests as r_mod
    with patch("portfolio.availability.requests") as r:
        r.get.side_effect = r_mod.exceptions.ConnectionError("fail")
        chk = AvailabilityChecker(rate_delay_s=0)
        out = chk.check("flow.com")
    assert out.available is None
    assert out.error is not None


def test_checker_make_check_callable_returns_3_tuple():
    """The callable yields (available, price, error) for render_options."""
    chk = AvailabilityChecker(rate_delay_s=0)
    with patch("portfolio.availability.rdap_check") as rd, \
         patch("portfolio.availability.lookup_price") as lp:
        rd.return_value = AvailResult(available=True, price=None, backend="rdap")
        lp.return_value = 11.08
        chk._pricing = {}  # ensure lookup_price uses our mock
        fn = chk.make_check_callable()
        a, p, err = fn("flow.com")
    assert a is True
    assert p == 11.08
    assert err is None


def test_checker_logs_each_check_when_log_fn_provided():
    """The callable logs one line per check via log_fn."""
    log: list[str] = []
    chk = AvailabilityChecker(rate_delay_s=0, log_fn=lambda m: log.append(m))
    with patch("portfolio.availability.rdap_check") as rd, \
         patch("portfolio.availability.lookup_price") as lp:
        rd.side_effect = [
            AvailResult(available=True, price=None, backend="rdap"),
            AvailResult(available=False, price=None, backend="rdap"),
            AvailResult(available=None, price=None, backend="rdap", error=None),
            AvailResult(available=None, price=None, backend="rdap", error="timeout"),
        ]
        lp.return_value = None
        chk._pricing = {}
        fn = chk.make_check_callable()
        fn("a.com"); fn("b.com"); fn("c.io"); fn("d.com")

    assert any("✓" in l and "a.com" in l for l in log)
    assert any("✗" in l and "b.com" in l for l in log)
    assert any("?" in l and "c.io" in l for l in log)
    assert any("✕" in l and "d.com" in l and "timeout" in l for l in log)


def test_checker_rate_limits_between_calls(monkeypatch):
    chk = AvailabilityChecker(rate_delay_s=0.05)
    sleeps: list[float] = []
    monkeypatch.setattr(availability.time, "sleep", lambda s: sleeps.append(s))
    with patch("portfolio.availability.rdap_check") as rd, \
         patch("portfolio.availability.lookup_price"):
        rd.return_value = AvailResult(available=True, price=None, backend="rdap")
        chk._pricing = {}
        chk.check("a.com")
        chk.check("b.com")
    # Second call should have triggered a sleep
    assert any(s > 0 for s in sleeps)


# ---------- back-compat shim ----------


def test_porkbun_check_shim_routes_to_rdap_plus_pricing(tmp_path, monkeypatch):
    """The deprecated porkbun_check function still returns sane data via the new path."""
    monkeypatch.setattr(availability, "RDAP_CACHE_PATH", tmp_path / "rdap.json")
    monkeypatch.setattr(availability, "PORKBUN_PRICING_CACHE_PATH", tmp_path / "pricing.json")
    (tmp_path / "rdap.json").write_text(json.dumps({"cached_at": time.time(),
                                                     "services": {"com": ["https://example/"]}}))
    (tmp_path / "pricing.json").write_text(json.dumps({
        "cached_at": time.time(),
        "pricing": {"com": {"registration": "11.08"}},
    }))
    from portfolio.availability import porkbun_check
    with patch("portfolio.availability.requests") as r:
        r.get.return_value = MagicMock(status_code=404)
        out = porkbun_check("flow.com")
    assert out.available is True
    assert out.price == 11.08
