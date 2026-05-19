"""v11.F — `data/hosting/<date>.json` snapshot persistence.

Mirrors `seo_cache.py` exactly — same directory shape, same list /
latest / save / load / rows_from_snapshot / is_stale surface. Reuses
the orchestrator's `HostingResult` so callers can persist the
walker's skip-annotations alongside the rows.

The cache makes `fleet hosting` (v11.G) cheap on repeat invocations:
the renderer reads the latest snapshot by default and only re-walks
when `--refresh` is passed or `is_stale()` returns True. Snapshots
are git-tracked and kept forever (resolution 11.I) — disk isn't a
constraint at fleet scale.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT
from .hosting import HostingResult, HostingRow

HOSTING_DIR = ROOT / "data" / "hosting"


def list_snapshots() -> list[Path]:
    """All cached hosting snapshot files, newest first."""
    if not HOSTING_DIR.exists():
        return []
    return sorted(HOSTING_DIR.glob("*.json"), reverse=True)


def latest_snapshot() -> Path | None:
    files = list_snapshots()
    return files[0] if files else None


def save_snapshot(result: HostingResult) -> Path:
    """Write the orchestrator result to `data/hosting/<UTC-today>.json`.
    Same-day file is overwritten (one snapshot per day, matches the
    seo_cache.py convention).
    """
    HOSTING_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = HOSTING_DIR / f"{today}.json"
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": [asdict(r) for r in result.rows],
        "skipped": dict(result.skipped),
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


def load_snapshot(path: Path) -> dict:
    """Parse a cached hosting snapshot. Caller uses `result_from_snapshot`
    to reconstruct the typed shape."""
    return json.loads(path.read_text())


def result_from_snapshot(snapshot: dict) -> HostingResult:
    """Reconstruct a `HostingResult` from the cached JSON shape. Drops
    any unknown keys on each row so a forward-compat HostingRow field
    addition doesn't break older snapshots."""
    valid_keys = set(HostingRow.__dataclass_fields__.keys())
    rows: list[HostingRow] = []
    for r in snapshot.get("rows", []):
        clean = {k: v for k, v in r.items() if k in valid_keys}
        rows.append(HostingRow(**clean))
    skipped = snapshot.get("skipped") or {}
    if not isinstance(skipped, dict):
        skipped = {}
    return HostingResult(rows=rows, skipped=dict(skipped))


def is_stale(path: Path, max_age_hours: int = 24) -> bool:
    """A snapshot older than `max_age_hours` is stale. Default 24h
    matches the seo_cache.py convention — one daily run."""
    try:
        snapshot = load_snapshot(path)
    except (OSError, ValueError):
        return True
    fetched = snapshot.get("fetched_at")
    if not fetched:
        return True
    try:
        ts = datetime.fromisoformat(fetched)
    except ValueError:
        return True
    age = datetime.now(timezone.utc) - ts
    return age.total_seconds() > max_age_hours * 3600
