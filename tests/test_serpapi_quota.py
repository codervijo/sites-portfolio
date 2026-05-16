"""Tests for v8.D — SerpAPI quota ledger (`portfolio.serpapi_quota`)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from portfolio import serpapi_quota as quota_mod


@pytest.fixture
def _stub_path(tmp_path, monkeypatch):
    """Redirect the quota file at tmp_path."""
    p = tmp_path / "_quota.json"
    monkeypatch.setattr(quota_mod, "QUOTA_PATH", p)
    return p


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


# ---------- cold start ----------


def test_cold_start_returns_zero_used(_stub_path):
    q = quota_mod.read_quota()
    assert q["queries_used"] == 0
    assert q["limit"] == quota_mod.DEFAULT_LIMIT
    assert q["month"] == _current_month()


def test_cold_start_does_not_create_file(_stub_path):
    """read_quota() doesn't touch disk on cold start (no-op read)."""
    quota_mod.read_quota()
    assert not _stub_path.exists()


# ---------- increment + persist ----------


def test_consume_quota_increments_and_persists(_stub_path):
    q = quota_mod.consume_quota()
    assert q["queries_used"] == 1
    # File should exist now
    assert _stub_path.exists()
    persisted = json.loads(_stub_path.read_text())
    assert persisted["queries_used"] == 1


def test_consume_quota_multiple_calls_accumulate(_stub_path):
    for _ in range(5):
        quota_mod.consume_quota()
    q = quota_mod.read_quota()
    assert q["queries_used"] == 5


def test_consume_quota_at_limit_raises(_stub_path):
    """At 250/250, the next call raises QuotaExhausted."""
    # Seed the file at 250/250
    quota_mod._save({
        "schema": quota_mod.SCHEMA,
        "month": _current_month(),
        "queries_used": 250,
        "limit": 250,
        "last_updated": "",
    })
    with pytest.raises(quota_mod.QuotaExhausted, match="exhausted"):
        quota_mod.consume_quota()


def test_consume_quota_just_under_limit_succeeds(_stub_path):
    quota_mod._save({
        "schema": quota_mod.SCHEMA,
        "month": _current_month(),
        "queries_used": 249,
        "limit": 250,
        "last_updated": "",
    })
    q = quota_mod.consume_quota()
    assert q["queries_used"] == 250


# ---------- month rollover ----------


def test_month_rollover_resets_counter(_stub_path):
    """A ledger from last month → fresh ledger for the current month."""
    last_month = datetime.now(timezone.utc).replace(day=1)
    # back up one calendar month — handle Jan rollover
    if last_month.month == 1:
        last_month = last_month.replace(year=last_month.year - 1, month=12)
    else:
        last_month = last_month.replace(month=last_month.month - 1)
    last_month_str = last_month.strftime("%Y-%m")

    quota_mod._save({
        "schema": quota_mod.SCHEMA,
        "month": last_month_str,
        "queries_used": 150,
        "limit": 250,
        "last_updated": "",
    })
    q = quota_mod.read_quota()
    assert q["month"] == _current_month()
    assert q["queries_used"] == 0   # reset
    assert q["limit"] == 250         # carries forward


def test_corrupt_file_resets(_stub_path):
    _stub_path.write_text("{not json")
    q = quota_mod.read_quota()
    assert q["queries_used"] == 0


def test_schema_mismatch_resets(_stub_path):
    _stub_path.write_text(json.dumps({"schema": "old", "queries_used": 100}))
    q = quota_mod.read_quota()
    assert q["queries_used"] == 0


# ---------- helpers ----------


def test_is_quota_available_true_under_limit(_stub_path):
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 50, "limit": 250, "last_updated": ""})
    assert quota_mod.is_quota_available()
    assert quota_mod.is_quota_available(n=200)
    assert not quota_mod.is_quota_available(n=201)


def test_quota_pct_used(_stub_path):
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 200, "limit": 250, "last_updated": ""})
    pct = quota_mod.quota_pct_used()
    assert 0.79 < pct < 0.81


def test_should_warn_at_80_percent(_stub_path):
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 200, "limit": 250, "last_updated": ""})
    assert quota_mod.should_warn() is True

    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 199, "limit": 250, "last_updated": ""})
    assert quota_mod.should_warn() is False


def test_next_month_first_handles_december():
    assert quota_mod._next_month_first("2026-12") == "2027-01-01"


def test_next_month_first_pads_month():
    assert quota_mod._next_month_first("2026-08") == "2026-09-01"


# ---------- integration: fetch_serp + quota ----------


def test_fetch_serp_consumes_quota_on_success(_stub_path, monkeypatch):
    """When a SerpAPI fetch succeeds, the quota counter increments."""
    from portfolio import serp_fetch
    # Mock the HTTP call
    class _Resp:
        status_code = 200
        text = "{}"
        def json(self):
            return {"organic_results": []}
    monkeypatch.setattr(serp_fetch.httpx, "get", lambda *a, **kw: _Resp())

    before = quota_mod.read_quota()["queries_used"]
    serp_fetch.fetch_serp("test", api_key="fake")
    after = quota_mod.read_quota()["queries_used"]
    assert after - before == 1


def test_fetch_serp_no_quota_consumption_on_failure(_stub_path, monkeypatch):
    """A 401 doesn't burn quota — counter unchanged."""
    from portfolio import serp_fetch
    class _Resp:
        status_code = 401
        text = "unauthorized"
    monkeypatch.setattr(serp_fetch.httpx, "get", lambda *a, **kw: _Resp())

    before = quota_mod.read_quota()["queries_used"]
    with pytest.raises(serp_fetch.SerpFetchError):
        serp_fetch.fetch_serp("test", api_key="bad")
    after = quota_mod.read_quota()["queries_used"]
    assert after == before


def test_fetch_serp_refuses_when_quota_exhausted(_stub_path, monkeypatch):
    """When quota is at limit, fetch_serp raises QuotaExhausted without
    making any HTTP call."""
    from portfolio import serp_fetch
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 250, "limit": 250, "last_updated": ""})
    def _explode(*a, **kw):
        pytest.fail("HTTP should not be called when quota is exhausted")
    monkeypatch.setattr(serp_fetch.httpx, "get", _explode)

    with pytest.raises(quota_mod.QuotaExhausted):
        serp_fetch.fetch_serp("test", api_key="fake")
