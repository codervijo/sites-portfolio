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


def test_should_warn_strongly_at_95_percent(_stub_path):
    """The strong-warn threshold (95%) pairs with the soft-warn message
    to push the 'consider waiting' guidance. At this usage level a single
    research run can blow through the rest of the quota and silently
    force the synthesis-fallback path."""
    # Just shy of 95% (237/250 = 94.8%) — strong-warn off.
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 237, "limit": 250, "last_updated": ""})
    assert quota_mod.should_warn_strongly() is False
    # The soft-warn should still fire at this level — strong-warn is
    # additive, not a replacement.
    assert quota_mod.should_warn() is True

    # 238/250 = 95.2% — strong-warn fires.
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 238, "limit": 250, "last_updated": ""})
    assert quota_mod.should_warn_strongly() is True


def test_warn_thresholds_are_well_ordered():
    """Strong-warn must be at or above soft-warn — otherwise the strong
    message would fire BEFORE the soft one, which contradicts the
    'soft, then strong' tier."""
    assert quota_mod.WARN_STRONGLY_THRESHOLD >= quota_mod.WARN_THRESHOLD


# ---------- sync_with_serpapi ----------


class _FakeResp:
    """Minimal httpx-like response object — just enough for the sync
    helper's `.status_code`, `.text`, and `.json()` access patterns."""

    def __init__(self, status_code: int, body: dict | None = None,
                 text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text or (json.dumps(body) if body else "")

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class _FakeClient:
    """Capture the URL + params from one .get() call and return canned
    response. Mirrors httpx.Client's get() signature enough for the
    sync helper."""

    def __init__(self, resp: _FakeResp):
        self.resp = resp
        self.calls: list[dict] = []

    def get(self, url, params=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        return self.resp

    def close(self):
        pass


def test_sync_with_serpapi_overwrites_local_ledger(_stub_path):
    """A drifted local ledger gets overwritten with SerpAPI's records.
    This is the donready-style drift scenario: local says 250/250,
    SerpAPI says 16/250 — sync brings local back to ground truth."""
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 250, "limit": 250, "last_updated": ""})
    fake_client = _FakeClient(_FakeResp(200, {
        "this_month_usage": 16,
        "searches_per_month": 250,
        "plan_searches_left": 234,
    }))
    result = quota_mod.sync_with_serpapi("fake-key", client=fake_client)
    assert result["queries_used"] == 16
    assert result["limit"] == 250
    # And persisted.
    persisted = quota_mod.read_quota()
    assert persisted["queries_used"] == 16
    # Sync timestamp is recorded so `settings serpapi-quota show` can
    # surface "last synced with SerpAPI".
    assert "synced_with_serpapi_at" in result


def test_sync_with_serpapi_passes_api_key_as_query_param(_stub_path):
    fake_client = _FakeClient(_FakeResp(200, {
        "this_month_usage": 5, "searches_per_month": 250,
        "plan_searches_left": 245,
    }))
    quota_mod.sync_with_serpapi("k-7", client=fake_client)
    assert fake_client.calls[0]["params"] == {"api_key": "k-7"}
    assert fake_client.calls[0]["url"] == quota_mod.SERPAPI_ACCOUNT_URL


def test_sync_with_serpapi_raises_on_empty_key():
    with pytest.raises(quota_mod.QuotaSyncError):
        quota_mod.sync_with_serpapi("")


def test_sync_with_serpapi_raises_on_401(_stub_path):
    fake_client = _FakeClient(_FakeResp(401, text="unauthorized"))
    with pytest.raises(quota_mod.QuotaSyncError) as exc:
        quota_mod.sync_with_serpapi("bad-key", client=fake_client)
    # Operator-actionable hint, not just "401".
    assert "SERPAPI_KEY" in str(exc.value)


def test_sync_with_serpapi_raises_on_non_200(_stub_path):
    fake_client = _FakeClient(_FakeResp(500, text="server error"))
    with pytest.raises(quota_mod.QuotaSyncError) as exc:
        quota_mod.sync_with_serpapi("k", client=fake_client)
    assert "HTTP 500" in str(exc.value)


def test_sync_with_serpapi_raises_on_missing_fields(_stub_path):
    """A 200 response without the expected fields is a schema surprise.
    Better to surface it than silently zero out the counter."""
    fake_client = _FakeClient(_FakeResp(200, {
        "account_id": "abc",
        # missing this_month_usage / searches_per_month
    }))
    with pytest.raises(quota_mod.QuotaSyncError) as exc:
        quota_mod.sync_with_serpapi("k", client=fake_client)
    assert "missing" in str(exc.value).lower() or "malformed" in str(exc.value).lower()


def test_sync_uses_serpapi_plan_limit_not_local_default(_stub_path):
    """SerpAPI's `searches_per_month` overrides the local default.
    Operators on paid plans have higher limits than 250 — sync should
    pick those up rather than clamping to the local default."""
    quota_mod._save({"schema": quota_mod.SCHEMA, "month": _current_month(),
                     "queries_used": 0, "limit": 250, "last_updated": ""})
    fake_client = _FakeClient(_FakeResp(200, {
        "this_month_usage": 1200,
        "searches_per_month": 5000,    # paid plan
        "plan_searches_left": 3800,
    }))
    result = quota_mod.sync_with_serpapi("k", client=fake_client)
    assert result["limit"] == 5000
    assert result["queries_used"] == 1200


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
