"""v8.D — SerpAPI quota ledger + auto-fallback.

Tracks how many SerpAPI queries we've used this UTC month against the
free-tier cap (250/month default). Resets automatically on the first
day of each UTC month — no scheduled task needed; the reader checks
the recorded month against today's month and zeroes when they differ.

Persisted at `data/serp/_quota.json`. Schema:

  {
    "schema": "serpapi-quota-v1",
    "month": "2026-05",                            // UTC YYYY-MM
    "queries_used": 47,
    "limit": 250,
    "last_updated": "2026-05-14T19:00:00+00:00"
  }

Two opinions encoded:
  - Increment AFTER a successful fetch — failed calls don't burn the
    counter. SerpAPI does charge for some 4xx responses, so the
    counter is an under-estimate by design (better to surprise
    high-volume users with quota left than to refuse calls that
    would have worked).
  - Soft-warn at 80% via printed message; hard-refuse at 100% via
    a specific exception the orchestrator catches and maps to the
    synthesis-only fallback path with a loud banner.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT

QUOTA_PATH = ROOT / "data" / "serp" / "_quota.json"
SCHEMA = "serpapi-quota-v1"
DEFAULT_LIMIT = 250
WARN_THRESHOLD = 0.8


class QuotaExhausted(RuntimeError):
    """Raised by `consume_quota()` when no headroom remains. Caller
    catches and triggers the synthesis-only fallback path with the
    user-facing banner from §8.G.3."""


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def read_quota() -> dict:
    """Return current quota state. Auto-resets on UTC month change.

    First-read on a cold install creates a fresh record at 0/limit
    for the current month. Schema-mismatch or corrupt files also
    reset (no migration; the file is regenerable).
    """
    today = _current_month()
    if not QUOTA_PATH.exists():
        return _fresh(today)
    try:
        payload = json.loads(QUOTA_PATH.read_text())
    except (OSError, ValueError):
        return _fresh(today)
    if payload.get("schema") != SCHEMA:
        return _fresh(today)
    if payload.get("month") != today:
        # Month rolled over — reset the counter, keep the limit.
        return _fresh(today, limit=payload.get("limit", DEFAULT_LIMIT))
    return {
        "schema": SCHEMA,
        "month": today,
        "queries_used": int(payload.get("queries_used", 0)),
        "limit": int(payload.get("limit", DEFAULT_LIMIT)),
        "last_updated": payload.get("last_updated", ""),
    }


def _fresh(month: str, *, limit: int = DEFAULT_LIMIT) -> dict:
    return {
        "schema": SCHEMA,
        "month": month,
        "queries_used": 0,
        "limit": limit,
        "last_updated": "",
    }


def _save(payload: dict) -> None:
    """Atomic write (tmpfile + rename). Creates the data/serp/ dir
    if absent (cold start might not have it yet)."""
    QUOTA_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUOTA_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(QUOTA_PATH)


def consume_quota(*, n: int = 1) -> dict:
    """Reserve `n` queries against the quota. Raises QuotaExhausted
    if there isn't enough headroom. Returns the updated quota dict.

    Soft-warns to stderr-ish (via print to console) when crossing the
    80% threshold — caller's renderer can pick this up if it captures
    output, but the warning is intentionally side-channel so it
    doesn't interleave with JSON output.
    """
    quota = read_quota()
    new_count = quota["queries_used"] + n
    if new_count > quota["limit"]:
        raise QuotaExhausted(
            f"SerpAPI quota exhausted ({quota['queries_used']}/{quota['limit']} "
            f"this UTC month). Resets {_next_month_first(quota['month'])}."
        )
    quota["queries_used"] = new_count
    quota["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save(quota)
    return quota


def is_quota_available(*, n: int = 1) -> bool:
    """Pure check — does the quota have headroom for `n` more queries?
    Useful for pre-flight decisions in the orchestrator."""
    quota = read_quota()
    return quota["queries_used"] + n <= quota["limit"]


def quota_pct_used() -> float:
    """0.0 - 1.0+. Useful for the 80%-warning check."""
    quota = read_quota()
    if quota["limit"] == 0:
        return 0.0
    return quota["queries_used"] / quota["limit"]


def should_warn() -> bool:
    """True when usage crosses the soft-warn threshold (default 80%).
    Caller decides what to do with this (typically: print a banner)."""
    return quota_pct_used() >= WARN_THRESHOLD


def _next_month_first(month: str) -> str:
    """Given `YYYY-MM`, return `YYYY-MM-01` of the following month.
    Used in the user-facing exhaustion message."""
    y, m = month.split("-")
    yi, mi = int(y), int(m)
    if mi == 12:
        return f"{yi + 1}-01-01"
    return f"{yi}-{mi + 1:02d}-01"
