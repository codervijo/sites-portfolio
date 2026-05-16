"""v8.D — per-query SerpAPI cache.

Stores one normalized SerpAPI response per (query, date) tuple at
`data/serp/<YYYY-MM-DD>/<query-hash>.json`. Layout chosen so a day's
worth of probes cluster naturally and old dates can be archived /
dropped without touching current data.

Cache TTL is 30 days (research-module-v2.md §8.G.1) — set generously
to stretch the SerpAPI free-tier quota. SERPs change weekly but
gate-level verdicts don't move with them; weekly re-fetches would
burn quota without changing the call.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import ROOT

SERP_DIR = ROOT / "data" / "serp"
DEFAULT_TTL_DAYS = 30


def normalize_query(query: str) -> str:
    """Whitespace-collapse + lowercase. Same query with different
    casings or padding hits the same cache."""
    return " ".join(query.lower().split())


def query_hash(query: str) -> str:
    """12-char sha256 prefix of the normalized query. Stable across
    runs; same query always hashes to the same file path."""
    digest = hashlib.sha256(normalize_query(query).encode("utf-8")).hexdigest()
    return digest[:12]


def cache_path(query: str, date: str | None = None) -> Path:
    """File path for one (query, date) entry. Date defaults to today
    UTC. Caller typically uses today for writes; reads walk all dates
    to find the most-recent within-TTL match."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return SERP_DIR / date / f"{query_hash(query)}.json"


def load_cached_query(query: str, *,
                      ttl_days: int = DEFAULT_TTL_DAYS) -> dict | None:
    """Return the most-recent cached SerpAPI response for `query` that's
    still within TTL. None if none exists or all are expired.

    Walks `data/serp/<date>/` subdirs in reverse date order, returns
    the first match for this query-hash whose `fetched_at` is within
    the TTL window. Corrupt files are silently skipped.
    """
    if not SERP_DIR.exists():
        return None
    target_hash = query_hash(query)
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)

    # Walk date subdirs newest first.
    date_dirs = sorted(
        (p for p in SERP_DIR.iterdir()
         if p.is_dir() and _is_date_subdir(p.name)),
        reverse=True,
    )
    for d in date_dirs:
        cache_file = d / f"{target_hash}.json"
        if not cache_file.exists():
            continue
        try:
            payload = json.loads(cache_file.read_text())
        except (OSError, ValueError):
            continue
        fetched_at_iso = payload.get("fetched_at")
        if not fetched_at_iso:
            continue
        try:
            fetched_at = datetime.fromisoformat(fetched_at_iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        if fetched_at < cutoff:
            # Older entries (in older date dirs) will also be expired.
            return None
        return payload
    return None


def save_cached_query(query: str, payload: dict) -> Path:
    """Write payload to `data/serp/<today>/<query-hash>.json`. Atomic
    (tmpfile + rename). Returns the path written.

    Date subdir is created if absent. Caller is responsible for the
    payload shape — this is a pure cache writer, not a validator.
    """
    p = cache_path(query)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(p)
    return p


def _is_date_subdir(name: str) -> bool:
    """`YYYY-MM-DD` format. Filters out `_archive_v8b/` etc."""
    if len(name) != 10 or name[4] != "-" or name[7] != "-":
        return False
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False
