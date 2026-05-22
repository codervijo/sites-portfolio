"""v19.B — Google Trends via `pytrends`.

Standalone `lamill new trends <topic>` data fetcher. Cache layout
matches `seo_cache.py` / `hosting_cache.py` conventions (24h TTL,
per-topic JSON file, atomic write). pytrends boundary stays at the
edge of this module so tests can mock `pytrends.request.TrendReq`
without touching real Google Trends.

Per v19.A scope lock 2026-05-22: no cluster-snapshot integration,
no shortlist binding, no SerpAPI fallback — pytrends is the only
path. Soft failure on library errors (caller decides to surface or
exit; module just raises `GTrendsError`).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import ROOT

GTRENDS_DIR = ROOT / "data" / "gtrends"
SCHEMA = "gtrends-v1"
DEFAULT_TTL_HOURS = 24

# Map v19.A's flag values to pytrends' string conventions. Reject
# anything else — operator-facing CLI validates first, but the wrapper
# also guards so direct callers don't pass garbage.
TIMEFRAME_MAP: dict[str, str] = {
    "7d":  "now 7-d",
    "30d": "today 1-m",
    "90d": "today 3-m",
    "12m": "today 12-m",
    "5y":  "today 5-y",
    "all": "all",
}
DEFAULT_TIMEFRAME = "12m"


class GTrendsError(RuntimeError):
    """Raised when `pytrends` fails to fetch trend data. Carries the
    underlying error in the message. Caller (CLI) prints + exits
    non-zero; no automatic retry since pytrends has no official SLA."""


@dataclass(frozen=True)
class TrendsPayload:
    """Normalized trends snapshot. Cache file is a serialized form
    of this; in-memory shape is the same for renderer + JSON output."""
    topic: str
    timeframe: str  # operator-facing string from TIMEFRAME_MAP keys
    region: str
    fetched_at: str
    interest_over_time: list[dict]  # [{"date": "YYYY-MM-DD", "value": int}, ...]
    related_top: list[dict]         # [{"query": "...", "value": int}, ...]
    related_rising: list[dict]


# ---- cache plumbing -------------------------------------------------


def _topic_hash(topic: str, *, timeframe: str, region: str) -> str:
    """12-char sha256 prefix of the (topic, timeframe, region) tuple.
    Same topic at different timeframes hits separate cache files —
    operator running `lamill new trends X --timeframe 7d` and then
    `lamill new trends X --timeframe 12m` shouldn't get stale results
    from the first call."""
    key = f"{topic.strip().lower()}|{timeframe}|{region}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def cache_path(topic: str, *, timeframe: str, region: str) -> Path:
    return GTRENDS_DIR / f"{_topic_hash(topic, timeframe=timeframe, region=region)}.json"


def is_stale(payload: dict, *, max_age_hours: int = DEFAULT_TTL_HOURS) -> bool:
    """Cache freshness check. Caller passes the loaded JSON; we look
    at `fetched_at` (UTC ISO 8601). Missing / malformed timestamps
    count as stale — defensive against schema drift."""
    fetched = payload.get("fetched_at")
    if not isinstance(fetched, str):
        return True
    try:
        ts = datetime.fromisoformat(fetched)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - ts
    return age > timedelta(hours=max_age_hours)


def load_cached(
    topic: str, *,
    timeframe: str, region: str,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> TrendsPayload | None:
    """Return cached TrendsPayload if a fresh entry exists; else None."""
    path = cache_path(topic, timeframe=timeframe, region=region)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema") != SCHEMA:
        return None
    if is_stale(raw, max_age_hours=max_age_hours):
        return None
    return TrendsPayload(
        topic=raw["topic"],
        timeframe=raw["timeframe"],
        region=raw["region"],
        fetched_at=raw["fetched_at"],
        interest_over_time=list(raw.get("interest_over_time") or []),
        related_top=list(raw.get("related_top") or []),
        related_rising=list(raw.get("related_rising") or []),
    )


def save_cached(payload: TrendsPayload) -> Path:
    """Atomic write of the payload to its cache file."""
    GTRENDS_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(
        payload.topic, timeframe=payload.timeframe, region=payload.region,
    )
    body = {
        "schema": SCHEMA,
        "topic": payload.topic,
        "timeframe": payload.timeframe,
        "region": payload.region,
        "fetched_at": payload.fetched_at,
        "interest_over_time": payload.interest_over_time,
        "related_top": payload.related_top,
        "related_rising": payload.related_rising,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


# ---- pytrends wrapper ----------------------------------------------


def _fetch_from_pytrends(
    topic: str, *,
    timeframe_pytrends: str, region: str,
) -> TrendsPayload:
    """Make the actual pytrends call. Boundary kept narrow so tests
    mock `pytrends.request.TrendReq` here without faking the broader
    fetch flow."""
    # Local import so test environments that don't need pytrends (e.g.
    # `uv run pytest -k "not v19"`) don't pay the lxml/numpy/pandas
    # import cost. Also lets cache-only callers skip the dep entirely.
    from pytrends.request import TrendReq

    try:
        client = TrendReq(hl="en-US", tz=0, timeout=(10, 30))
        client.build_payload([topic], timeframe=timeframe_pytrends, geo=region)
        iot_df = client.interest_over_time()
        related = client.related_queries()
    except Exception as e:
        raise GTrendsError(f"pytrends fetch failed for {topic!r}: {e}") from e

    # interest_over_time DataFrame → list of {date, value}. pytrends
    # adds an `isPartial` column for the current incomplete period;
    # we keep all rows (partial flagged via a separate field if we
    # add one later) but drop the `isPartial` column from the value.
    iot_rows: list[dict] = []
    if iot_df is not None and not iot_df.empty:
        topic_col = topic if topic in iot_df.columns else iot_df.columns[0]
        for ts, row in iot_df.iterrows():
            iot_rows.append({
                "date": ts.strftime("%Y-%m-%d"),
                "value": int(row[topic_col]),
            })

    # related_queries returns {topic: {top: DataFrame|None, rising: DataFrame|None}}.
    # Either side can be None when Google has insufficient data; treat
    # as empty list rather than blowing up.
    top_rows: list[dict] = []
    rising_rows: list[dict] = []
    block = (related or {}).get(topic) or {}
    top_df = block.get("top")
    rising_df = block.get("rising")
    if top_df is not None and not top_df.empty:
        for _idx, row in top_df.iterrows():
            top_rows.append({
                "query": str(row["query"]),
                "value": int(row["value"]),
            })
    if rising_df is not None and not rising_df.empty:
        for _idx, row in rising_df.iterrows():
            rising_rows.append({
                "query": str(row["query"]),
                # "Breakout" / huge spikes render as the string "Breakout"
                # in pytrends rather than a number. Normalize to None so
                # the renderer can show "↑" instead of trying to parse.
                "value": _parse_rising_value(row["value"]),
            })

    return TrendsPayload(
        topic=topic,
        timeframe=_pytrends_to_flag(timeframe_pytrends),
        region=region,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        interest_over_time=iot_rows,
        related_top=top_rows,
        related_rising=rising_rows,
    )


def _parse_rising_value(raw) -> int | None:
    """pytrends' rising-queries value is either an integer (% growth)
    or the literal string `"Breakout"`. Normalize to int|None so JSON
    serialization stays clean."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _pytrends_to_flag(pytrends_tf: str) -> str:
    """Inverse of TIMEFRAME_MAP — used after a pytrends fetch to
    record the operator-facing flag value in the cache (so the
    renderer can display "12m" instead of "today 12-m")."""
    for flag, pt in TIMEFRAME_MAP.items():
        if pt == pytrends_tf:
            return flag
    return pytrends_tf  # passthrough for anything unmapped


# ---- public surface ------------------------------------------------


def fetch_trends(
    topic: str, *,
    timeframe: str = DEFAULT_TIMEFRAME,
    region: str = "",
    refresh: bool = False,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> TrendsPayload:
    """Top-level entry point used by `lamill new trends`.

    Reads cache when fresh + `refresh=False`. Otherwise calls
    `pytrends`, writes the cache, returns the payload.

    Raises `GTrendsError` when pytrends fails (network, Google
    rate-limit, parse error). `ValueError` when `timeframe` isn't
    one of `TIMEFRAME_MAP`'s keys.
    """
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(
            f"timeframe={timeframe!r} not in {list(TIMEFRAME_MAP)}"
        )

    if not refresh:
        cached = load_cached(
            topic, timeframe=timeframe, region=region,
            max_age_hours=max_age_hours,
        )
        if cached is not None:
            return cached

    payload = _fetch_from_pytrends(
        topic,
        timeframe_pytrends=TIMEFRAME_MAP[timeframe],
        region=region,
    )
    save_cached(payload)
    return payload
