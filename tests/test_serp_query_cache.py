"""Tests for v8.D — per-query SerpAPI cache (`portfolio.serp_query_cache`)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from portfolio import serp_query_cache as cache


@pytest.fixture
def _stub_dir(tmp_path, monkeypatch):
    """Redirect cache to tmp_path."""
    monkeypatch.setattr(cache, "SERP_DIR", tmp_path / "serp")
    return tmp_path / "serp"


def _payload(query: str, age_days: float = 0.0) -> dict:
    """A minimal valid SerpAPI payload."""
    fetched_at = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    return {
        "schema": "serp-query-v1",
        "query": query,
        "fetched_at": fetched_at,
        "source": "serpapi",
        "organic_results": [],
        "features": {},
    }


# ---------- normalize + hash ----------


def test_normalize_query_collapses_whitespace_and_lowercases():
    assert cache.normalize_query("  EV  Charger Cost  ") == "ev charger cost"


def test_query_hash_is_deterministic():
    a = cache.query_hash("ev charger cost")
    b = cache.query_hash("ev charger cost")
    assert a == b
    assert len(a) == 12


def test_query_hash_normalizes_before_hashing():
    assert cache.query_hash("EV Charger Cost") == cache.query_hash("ev charger cost")
    assert cache.query_hash("  ev   charger   cost  ") == cache.query_hash("ev charger cost")


def test_cache_path_uses_today_when_date_omitted(_stub_dir):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = cache.cache_path("test")
    assert p.parent.name == today
    assert p.name.endswith(".json")


def test_cache_path_honors_explicit_date(_stub_dir):
    p = cache.cache_path("test", date="2026-01-15")
    assert p.parent.name == "2026-01-15"


# ---------- save + load roundtrip ----------


def test_save_then_load_roundtrip(_stub_dir):
    payload = _payload("ev charger cost")
    cache.save_cached_query("ev charger cost", payload)
    loaded = cache.load_cached_query("ev charger cost")
    assert loaded is not None
    assert loaded["query"] == "ev charger cost"


def test_load_returns_none_when_missing(_stub_dir):
    assert cache.load_cached_query("never cached") is None


def test_load_returns_none_when_cache_dir_missing(_stub_dir):
    """Don't crash on cold-start (no SERP_DIR yet)."""
    assert cache.load_cached_query("anything") is None


def test_save_creates_date_subdir(_stub_dir):
    cache.save_cached_query("test", _payload("test"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert (_stub_dir / today).is_dir()


def test_save_atomic_no_tmp_leftover(_stub_dir):
    cache.save_cached_query("test", _payload("test"))
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    files = list((_stub_dir / today).iterdir())
    # Exactly one file, no .tmp leftover
    assert len(files) == 1
    assert all(not f.name.endswith(".tmp") for f in files)


# ---------- TTL handling ----------


def test_expired_entry_treated_as_miss(_stub_dir):
    """A payload older than TTL → cache miss."""
    p = cache.cache_path("stale", date="2026-04-01")  # 40+ days back
    p.parent.mkdir(parents=True)
    payload = _payload("stale", age_days=40)
    payload["fetched_at"] = "2026-04-01T00:00:00+00:00"
    p.write_text(json.dumps(payload))
    assert cache.load_cached_query("stale", ttl_days=30) is None


def test_within_ttl_returns_hit(_stub_dir):
    """A payload within TTL → cache hit."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache.save_cached_query("fresh", _payload("fresh"))
    loaded = cache.load_cached_query("fresh", ttl_days=30)
    assert loaded is not None


def test_corrupt_cache_treated_as_miss(_stub_dir):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = _stub_dir / today / f"{cache.query_hash('corrupt')}.json"
    p.parent.mkdir(parents=True)
    p.write_text("{not valid json")
    assert cache.load_cached_query("corrupt") is None


def test_payload_missing_fetched_at_treated_as_miss(_stub_dir):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = _stub_dir / today / f"{cache.query_hash('bad')}.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"query": "bad"}))   # no fetched_at
    assert cache.load_cached_query("bad") is None


# ---------- date-walk behavior ----------


def test_load_walks_dates_newest_first(_stub_dir):
    """If the same query was probed on multiple dates, return the most
    recent within-TTL entry."""
    today = datetime.now(timezone.utc)
    yesterday = today - timedelta(days=1)
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    # Yesterday's entry
    p_old = _stub_dir / yesterday_str / f"{cache.query_hash('q')}.json"
    p_old.parent.mkdir(parents=True)
    old_payload = _payload("q")
    old_payload["fetched_at"] = yesterday.isoformat()
    old_payload["marker"] = "old"
    p_old.write_text(json.dumps(old_payload))

    # Today's entry (newer)
    new_payload = _payload("q")
    new_payload["marker"] = "new"
    cache.save_cached_query("q", new_payload)

    loaded = cache.load_cached_query("q")
    assert loaded is not None
    assert loaded["marker"] == "new"


def test_archive_dir_skipped(_stub_dir):
    """`_archive_v8b/` shouldn't be confused with a date subdir."""
    (_stub_dir / "_archive_v8b").mkdir(parents=True)
    p = _stub_dir / "_archive_v8b" / f"{cache.query_hash('q')}.json"
    p.write_text(json.dumps(_payload("q")))
    # Should not match — _archive_v8b isn't a YYYY-MM-DD subdir
    assert cache.load_cached_query("q") is None


def test_is_date_subdir_pattern():
    assert cache._is_date_subdir("2026-05-14")
    assert not cache._is_date_subdir("_archive_v8b")
    assert not cache._is_date_subdir("2026-5-14")     # missing pad
    assert not cache._is_date_subdir("2026/05/14")    # wrong sep
    assert not cache._is_date_subdir("2026-13-01")    # invalid month
