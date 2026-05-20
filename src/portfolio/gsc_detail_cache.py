"""v13.B — per-domain GSC detail snapshot persistence.

Writes one snapshot file per `(domain, UTC-date)` pair under
`data/gsc/<domain>/<UTC-today>.json`. Subdir shape (rather than the
flat `data/gsc/<date>.json` used by `gsc.sync()`) so each domain
gets its own day-by-day history without an inner `domain` key
indirection — easier to grep, easier for `ls` to scan a single
domain's history.

Distinct from `data/gsc/<date>.json` (`gsc.sync()` output — fleet-
wide GSC totals snapshot) and `data/seo/<date>.json` (`fleet seo`
output — runtime SEO probe). v13.B is the per-project diagnostics
detail (sitemap-level errors + per-URL coverage from URL
Inspection); merits its own surface so the 24h TTL and the
URL Inspection daily-quota budget can be reasoned about
per-domain.

Also reused by v15.A's planned per-project GSC analytics cache
(same shape, same TTL convention). v15.A may extend the snapshot
schema with additional sections (queries / pages / devices / trend
data); the loader's forward-compat clean drops unknown keys so
older snapshots stay readable.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT

GSC_DETAIL_DIR = ROOT / "data" / "gsc"


def _domain_dir(domain: str) -> Path:
    """Cache subdirectory for a domain. Lowercased + stripped to
    match the rest of the codebase's domain-key normalization."""
    return GSC_DETAIL_DIR / domain.strip().lower()


def list_snapshots(domain: str) -> list[Path]:
    """All cached GSC-detail snapshot files for `domain`, newest first."""
    d = _domain_dir(domain)
    if not d.exists():
        return []
    return sorted(d.glob("*.json"), reverse=True)


def latest_snapshot(domain: str) -> Path | None:
    files = list_snapshots(domain)
    return files[0] if files else None


def save_snapshot(domain: str, payload: dict) -> Path:
    """Write the diagnostics payload to
    `data/gsc/<domain>/<UTC-today>.json`. Same-day file is
    overwritten — one snapshot per day per domain (matches
    `hosting_cache` / `seo_cache` convention)."""
    d = _domain_dir(domain)
    d.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = d / f"{today}.json"
    payload_with_meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "domain": domain.strip().lower(),
        **payload,
    }
    out_path.write_text(json.dumps(payload_with_meta, indent=2) + "\n")
    return out_path


def load_snapshot(path: Path) -> dict:
    """Parse a cached GSC-detail snapshot. Returns the raw dict;
    forward-compat reconstruction (e.g., into a dataclass) is the
    caller's responsibility — this layer doesn't know about
    `ProjectSeoDiagnostics` to avoid an import cycle."""
    return json.loads(path.read_text())


def is_stale(path: Path, max_age_hours: int = 24) -> bool:
    """A snapshot older than `max_age_hours` is stale. Default 24h
    matches `hosting_cache` / `seo_cache`. GSC search data has a
    2-3 day publishing lag anyway; refreshing more than daily
    burns URL Inspection quota for stale signal."""
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
