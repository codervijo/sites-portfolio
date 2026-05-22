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
    SCHEMA,
    TIMEFRAME_MAP,
    TrendsPayload,
    cache_path,
    fetch_trends,
    is_stale,
    load_cached,
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
