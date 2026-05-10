"""v5.F.1 — `data/seo/<date>.json` snapshot persistence for `check seo`.

Mirrors the shape of `data/checks/<date>.json` and `data/gsc/<date>.json`:
one snapshot per run, named by UTC date, kept indefinitely so trend
analysis (v7.B) can read history.

The cache is what makes `portfolio focus` cheap — focus pulls from this
file rather than re-running HTTP+GSC+CrUX probes every invocation.
`check seo` reads the latest snapshot by default and renders from it;
`check seo --refresh` forces a fresh probe and overwrites the snapshot.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT
from .seo_runtime import SEORow

SEO_DIR = ROOT / "data" / "seo"


def list_snapshots() -> list[Path]:
    """All cached SEO snapshot files, newest first."""
    if not SEO_DIR.exists():
        return []
    return sorted(SEO_DIR.glob("*.json"), reverse=True)


def latest_snapshot() -> Path | None:
    files = list_snapshots()
    return files[0] if files else None


def save_snapshot(rows: list[SEORow], *, days: int) -> Path:
    """Write `rows` to `data/seo/<UTC-today>.json`. Returns the path.

    Overwrites the same-day file (one snapshot per day).
    """
    SEO_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = SEO_DIR / f"{today}.json"
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "rows": [asdict(r) for r in rows],
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return out_path


def load_snapshot(path: Path) -> dict:
    """Parse a cached SEO snapshot. Caller deserializes `rows[]` via
    `rows_from_snapshot` since SEORow has typed fields."""
    return json.loads(path.read_text())


def rows_from_snapshot(snapshot: dict) -> list[SEORow]:
    """Reconstruct SEORow objects from the cached JSON shape."""
    out: list[SEORow] = []
    for r in snapshot.get("rows", []):
        # Drop any unknown keys (forward-compat with future SEORow fields).
        valid_keys = set(SEORow.__dataclass_fields__.keys())
        clean = {k: v for k, v in r.items() if k in valid_keys}
        out.append(SEORow(**clean))
    return out


def is_stale(path: Path, max_age_hours: int = 24) -> bool:
    """A snapshot older than `max_age_hours` is stale enough to warrant
    a re-probe. Default 24h matches one daily run."""
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
