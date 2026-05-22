"""Tests for v19.B — `lamill new trends <topic>` + `gtrends.py`.

`pytrends.request.TrendReq` is mocked at the module boundary; tests
never hit real Google Trends. Cache layer is exercised against tmp
directories so suite isolation holds.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from portfolio import gtrends
from portfolio.gtrends import (
    DEFAULT_TIMEFRAME,
    GTrendsError,
    GTrendsRateLimitError,
    SCHEMA,
    TIMEFRAME_MAP,
    TrendsPayload,
    cache_path,
    fetch_trends,
    is_stale,
    load_any_cached,
    load_cached,
    payload_age_hours,
    save_cached,
)


def _isolate_cache_dir(monkeypatch, tmp_path: Path) -> Path:
    """Point GTRENDS_DIR at a tmp path so tests don't write into the
    operator's real data/gtrends/."""
    cache_dir = tmp_path / "gtrends"
    monkeypatch.setattr(gtrends, "GTRENDS_DIR", cache_dir)
    return cache_dir


def _sample_payload(topic: str = "solar panels") -> TrendsPayload:
    return TrendsPayload(
        topic=topic,
        timeframe="12m",
        region="",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        interest_over_time=[
            {"date": "2025-05-25", "value": 42},
            {"date": "2025-06-01", "value": 45},
            {"date": "2026-05-15", "value": 78},
        ],
        related_top=[
            {"query": "solar panel cost", "value": 100},
            {"query": "diy solar", "value": 67},
        ],
        related_rising=[
            {"query": "tesla solar roof", "value": 5400},
            {"query": "lithium storage", "value": None},  # "Breakout"
        ],
    )


# ---- cache layer ---------------------------------------------------


def test_cache_path_changes_with_timeframe_and_region(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    a = cache_path("solar", timeframe="12m", region="")
    b = cache_path("solar", timeframe="7d", region="")
    c = cache_path("solar", timeframe="12m", region="US")
    # Same topic, different timeframe / region → different files. The
    # operator running both `--timeframe 7d` and `--timeframe 12m`
    # shouldn't get stale 7d results on the 12m query.
    assert a != b
    assert a != c
    assert b != c


def test_cache_path_is_stable_across_runs(monkeypatch, tmp_path):
    """Same topic + timeframe + region → same path always. Whitespace +
    casing in the topic doesn't matter (normalized in the hash)."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    a = cache_path("Solar Panels", timeframe="12m", region="")
    b = cache_path("  solar panels  ", timeframe="12m", region="")
    assert a == b


def test_is_stale_uses_24h_default():
    fresh = {"fetched_at": datetime.now(timezone.utc).isoformat()}
    assert is_stale(fresh) is False

    just_inside = {
        "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat(),
    }
    assert is_stale(just_inside) is False

    too_old = {
        "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
    }
    assert is_stale(too_old) is True


def test_is_stale_treats_malformed_timestamps_as_stale():
    assert is_stale({}) is True
    assert is_stale({"fetched_at": None}) is True
    assert is_stale({"fetched_at": "not-an-iso-string"}) is True


def test_save_and_load_cached_round_trip(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    original = _sample_payload()
    save_cached(original)

    loaded = load_cached("solar panels", timeframe="12m", region="")
    assert loaded is not None
    assert loaded.topic == "solar panels"
    assert loaded.interest_over_time == original.interest_over_time
    assert loaded.related_top == original.related_top
    assert loaded.related_rising == original.related_rising


def test_load_cached_returns_none_when_file_absent(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    assert load_cached("nope", timeframe="12m", region="") is None


def test_load_cached_returns_none_when_stale(monkeypatch, tmp_path):
    """Stale entry → load_cached returns None so the caller re-fetches."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    stale = _sample_payload()
    stale = TrendsPayload(
        topic=stale.topic, timeframe=stale.timeframe, region=stale.region,
        fetched_at=(datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
        interest_over_time=stale.interest_over_time,
        related_top=stale.related_top,
        related_rising=stale.related_rising,
    )
    save_cached(stale)
    assert load_cached("solar panels", timeframe="12m", region="") is None


def test_load_cached_returns_none_when_schema_mismatch(monkeypatch, tmp_path):
    cache_dir = _isolate_cache_dir(monkeypatch, tmp_path)
    cache_dir.mkdir(parents=True)
    path = cache_path("solar", timeframe="12m", region="")
    path.write_text(json.dumps({
        "schema": "old-schema-v0",
        "topic": "solar",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }))
    assert load_cached("solar", timeframe="12m", region="") is None


# ---- fetch_trends entry point --------------------------------------


def _patch_pytrends_with(monkeypatch, *, iot_data=None, related_data=None):
    """Stub the `pytrends.request.TrendReq` class so `_fetch_from_pytrends`
    returns a deterministic payload. Returns the spy-mock so tests can
    assert call shape."""
    fake_client = MagicMock()

    # interest_over_time DataFrame stub — pytrends returns a pandas
    # DataFrame; we mimic the .iterrows() + column-access surface only.
    import pandas as pd
    iot_df = pd.DataFrame(iot_data or {
        "solar": [42, 45, 78],
        "isPartial": [False, False, True],
    }, index=pd.to_datetime(["2025-05-25", "2025-06-01", "2026-05-15"]))
    fake_client.interest_over_time.return_value = iot_df

    if related_data is None:
        top_df = pd.DataFrame({
            "query": ["solar panel cost", "diy solar"],
            "value": [100, 67],
        })
        rising_df = pd.DataFrame({
            "query": ["tesla solar roof"],
            "value": [5400],
        })
        related_data = {"solar": {"top": top_df, "rising": rising_df}}
    fake_client.related_queries.return_value = related_data

    fake_trend_req_class = MagicMock(return_value=fake_client)
    monkeypatch.setattr(
        "pytrends.request.TrendReq", fake_trend_req_class,
    )
    return fake_client, fake_trend_req_class


def test_fetch_trends_happy_path(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    fake_client, _ = _patch_pytrends_with(monkeypatch)

    payload = fetch_trends("solar", timeframe="12m")

    assert payload.topic == "solar"
    assert payload.timeframe == "12m"
    assert len(payload.interest_over_time) == 3
    assert payload.interest_over_time[0] == {"date": "2025-05-25", "value": 42}
    assert payload.interest_over_time[-1] == {"date": "2026-05-15", "value": 78}
    assert payload.related_top[0]["query"] == "solar panel cost"
    assert payload.related_rising[0]["query"] == "tesla solar roof"

    # build_payload should have been called with the mapped pytrends timeframe.
    fake_client.build_payload.assert_called_once_with(
        ["solar"], timeframe="today 12-m", geo="",
    )


def test_fetch_trends_uses_cache_on_second_call(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    _, fake_trend_req_class = _patch_pytrends_with(monkeypatch)

    fetch_trends("solar", timeframe="12m")
    fetch_trends("solar", timeframe="12m")  # cache hit

    # TrendReq was instantiated only once (cache served the second call).
    assert fake_trend_req_class.call_count == 1


def test_fetch_trends_refresh_bypasses_cache(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    _, fake_trend_req_class = _patch_pytrends_with(monkeypatch)

    fetch_trends("solar", timeframe="12m")
    fetch_trends("solar", timeframe="12m", refresh=True)

    # Two pytrends instantiations — cache was bypassed.
    assert fake_trend_req_class.call_count == 2


def test_fetch_trends_rejects_invalid_timeframe(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="timeframe="):
        fetch_trends("solar", timeframe="bogus")


def test_fetch_trends_raises_gtrends_error_on_pytrends_failure(
    monkeypatch, tmp_path,
):
    """Network / rate-limit / parse errors from pytrends bubble up as
    GTrendsError so the CLI can surface them cleanly."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    bad_class = MagicMock(side_effect=Exception("connection refused"))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    with pytest.raises(GTrendsError, match="connection refused"):
        fetch_trends("solar", timeframe="12m")


def test_fetch_trends_handles_empty_related_blocks(monkeypatch, tmp_path):
    """Google may return None for top OR rising when it doesn't have
    enough data. Wrapper must coerce to empty lists, not blow up."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    _patch_pytrends_with(
        monkeypatch,
        related_data={"solar": {"top": None, "rising": None}},
    )

    payload = fetch_trends("solar", timeframe="12m")
    assert payload.related_top == []
    assert payload.related_rising == []


def test_breakout_rising_value_normalizes_to_none(monkeypatch, tmp_path):
    """pytrends emits the literal string `"Breakout"` for huge spikes.
    We coerce to None so JSON serialization stays clean."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    import pandas as pd
    breakout_df = pd.DataFrame({
        "query": ["tesla roof"],
        "value": ["Breakout"],
    })
    _patch_pytrends_with(
        monkeypatch,
        related_data={"solar": {
            "top": pd.DataFrame({"query": [], "value": []}),
            "rising": breakout_df,
        }},
    )

    payload = fetch_trends("solar", timeframe="12m")
    assert payload.related_rising == [
        {"query": "tesla roof", "value": None},
    ]


# ---- CLI integration -----------------------------------------------


runner = CliRunner()


def test_cli_new_trends_renders_table(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    _patch_pytrends_with(monkeypatch)

    from portfolio.cli import app
    result = runner.invoke(app, ["new", "trends", "solar"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Google Trends" in out
    assert "solar" in out
    assert "Interest over time" in out
    assert "Related queries" in out


def test_cli_new_trends_json_emits_valid_json(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    _patch_pytrends_with(monkeypatch)

    from portfolio.cli import app
    result = runner.invoke(app, ["new", "trends", "solar", "--json"])
    assert result.exit_code == 0
    # Output is the JSON payload (no rendering noise before it).
    data = json.loads(result.output)
    assert data["topic"] == "solar"
    assert data["timeframe"] == "12m"
    assert isinstance(data["interest_over_time"], list)


def test_cli_new_trends_exits_2_on_invalid_timeframe(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    from portfolio.cli import app
    result = runner.invoke(app, ["new", "trends", "solar", "-t", "garbage"])
    assert result.exit_code == 2
    assert "Invalid --timeframe" in result.output


def test_cli_new_trends_exits_3_on_fetch_failure(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    bad_class = MagicMock(side_effect=Exception("rate limit"))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    from portfolio.cli import app
    result = runner.invoke(app, ["new", "trends", "solar"])
    assert result.exit_code == 3
    assert "fetch failed" in result.output.lower()


def test_cli_new_trends_refresh_flag_bypasses_cache(monkeypatch, tmp_path):
    _isolate_cache_dir(monkeypatch, tmp_path)
    _, fake_trend_req_class = _patch_pytrends_with(monkeypatch)

    from portfolio.cli import app
    runner.invoke(app, ["new", "trends", "solar"])
    runner.invoke(app, ["new", "trends", "solar", "--refresh"])

    assert fake_trend_req_class.call_count == 2


# ---- 2026-05-22 mitigations: ImportError + 429 + UA + L1 fallback --


def test_typed_error_on_pytrends_not_installed(monkeypatch, tmp_path):
    """ImportError from `from pytrends.request import TrendReq` should
    raise typed GTrendsError with actionable `uv sync` hint.
    Closes the docs/bugs.md 2026-05-22 ModuleNotFoundError entry."""
    _isolate_cache_dir(monkeypatch, tmp_path)

    # Make the pytrends.request import fail.
    import sys
    monkeypatch.setitem(sys.modules, "pytrends", None)
    monkeypatch.setitem(sys.modules, "pytrends.request", None)

    with pytest.raises(GTrendsError) as exc_info:
        fetch_trends("solar", timeframe="12m")
    msg = str(exc_info.value)
    assert "pytrends library not installed" in msg
    assert "uv sync" in msg


def test_429_raises_specific_subclass(monkeypatch, tmp_path):
    """When pytrends raises a 429-shaped error (string contains '429'),
    fetch_trends raises GTrendsRateLimitError (subclass), not generic
    GTrendsError. Closes the docs/bugs.md 2026-05-22 cryptic-429 entry."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    bad_class = MagicMock(side_effect=Exception(
        "The request failed: Google returned a response with code 429"
    ))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    with pytest.raises(GTrendsRateLimitError) as exc_info:
        fetch_trends("solar", timeframe="12m")
    msg = str(exc_info.value)
    assert "rate-limited" in msg.lower()
    assert "10-30 minutes" in msg
    assert "IP-based" in msg


def test_429_subclass_is_caught_by_generic_gtrends_error(monkeypatch, tmp_path):
    """`GTrendsRateLimitError` must be a subclass of `GTrendsError` so
    existing `except GTrendsError` callers continue to work without
    special-casing."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    bad_class = MagicMock(side_effect=Exception(
        "The request failed: Google returned a response with code 429"
    ))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    with pytest.raises(GTrendsError):
        fetch_trends("solar", timeframe="12m")


def test_l1_stale_cache_fallback_on_rate_limit(monkeypatch, tmp_path):
    """L1 fallback: when pytrends rate-limits AND a stale cache entry
    exists for the same (topic, timeframe, region), fetch_trends
    returns the stale payload rather than raising."""
    _isolate_cache_dir(monkeypatch, tmp_path)

    # Pre-seed a stale cache entry (49h old → past 24h TTL).
    stale_payload = TrendsPayload(
        topic="solar",
        timeframe="12m",
        region="",
        fetched_at=(datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(),
        interest_over_time=[{"date": "2025-04-01", "value": 50}],
        related_top=[{"query": "solar panels", "value": 100}],
        related_rising=[],
    )
    save_cached(stale_payload)

    # Make pytrends 429 on the fresh fetch attempt.
    bad_class = MagicMock(side_effect=Exception(
        "Google returned a response with code 429"
    ))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    # fetch_trends with refresh=True forces fresh path, hits 429,
    # falls back to stale cache.
    result = fetch_trends("solar", timeframe="12m", refresh=True)

    assert result.topic == "solar"
    assert result.interest_over_time == stale_payload.interest_over_time
    assert payload_age_hours(result) > 24  # confirms it's the stale entry


def test_l1_fallback_raises_when_no_cache(monkeypatch, tmp_path):
    """L1 fallback can't recover if no cache entry exists at all.
    fetch_trends re-raises the GTrendsRateLimitError so the CLI can
    surface the wait-and-retry hint."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    bad_class = MagicMock(side_effect=Exception(
        "Google returned a response with code 429"
    ))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    with pytest.raises(GTrendsRateLimitError):
        fetch_trends("solar", timeframe="12m")


def test_load_any_cached_returns_stale_payload(monkeypatch, tmp_path):
    """load_any_cached must return entries past the 24h TTL — that's
    the whole point. Differs from load_cached which would return None."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    very_stale = TrendsPayload(
        topic="solar", timeframe="12m", region="",
        fetched_at=(datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        interest_over_time=[{"date": "2025-01-01", "value": 1}],
        related_top=[], related_rising=[],
    )
    save_cached(very_stale)

    # load_cached returns None (past TTL):
    assert load_cached("solar", timeframe="12m", region="") is None
    # load_any_cached returns the entry regardless:
    result = load_any_cached("solar", timeframe="12m", region="")
    assert result is not None
    assert result.fetched_at == very_stale.fetched_at


def test_ua_rotation_passes_header_to_pytrends(monkeypatch, tmp_path):
    """L3 — pytrends client is constructed with a User-Agent header in
    requests_args. Spot-check that one of the rotation UAs gets passed
    through (the exact UA varies per call due to random.choice)."""
    _isolate_cache_dir(monkeypatch, tmp_path)
    fake_client, fake_trend_req_class = _patch_pytrends_with(monkeypatch)

    fetch_trends("solar", timeframe="12m")

    # TrendReq was called with requests_args carrying a User-Agent.
    _, kwargs = fake_trend_req_class.call_args
    requests_args = kwargs.get("requests_args") or {}
    headers = requests_args.get("headers") or {}
    ua = headers.get("User-Agent", "")
    assert "Mozilla/5.0" in ua  # all 5 rotation UAs start with this
    # Accept-Language also set:
    assert headers.get("Accept-Language") == "en-US,en;q=0.9"


def test_payload_age_hours_computes_correctly():
    """payload_age_hours computes the delta from fetched_at to now."""
    five_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    p = TrendsPayload(
        topic="x", timeframe="12m", region="",
        fetched_at=five_hours_ago,
        interest_over_time=[], related_top=[], related_rising=[],
    )
    age = payload_age_hours(p)
    assert age is not None
    assert 4.9 < age < 5.1  # ~5 hours, accounting for test execution time


def test_payload_age_hours_returns_none_on_bad_timestamp():
    p = TrendsPayload(
        topic="x", timeframe="12m", region="",
        fetched_at="not-a-real-iso-string",
        interest_over_time=[], related_top=[], related_rising=[],
    )
    assert payload_age_hours(p) is None


def test_cli_renders_stale_warning_on_l1_fallback(monkeypatch, tmp_path):
    """End-to-end: when L1 fallback fires, the CLI renderer prints the
    yellow stale-cache warning header so the operator knows the data
    isn't fresh."""
    _isolate_cache_dir(monkeypatch, tmp_path)

    # Pre-seed stale.
    save_cached(TrendsPayload(
        topic="solar", timeframe="12m", region="",
        fetched_at=(datetime.now(timezone.utc) - timedelta(hours=49)).isoformat(),
        interest_over_time=[{"date": "2025-04-01", "value": 50}],
        related_top=[], related_rising=[],
    ))
    bad_class = MagicMock(side_effect=Exception(
        "Google returned a response with code 429"
    ))
    monkeypatch.setattr("pytrends.request.TrendReq", bad_class)

    from portfolio.cli import app
    result = runner.invoke(app, ["new", "trends", "solar", "--refresh"])
    assert result.exit_code == 0, result.output
    assert "Stale cache fallback" in result.output
    assert "--refresh" in result.output  # the hint to retry


