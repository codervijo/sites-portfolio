"""v11.A — `fleet hosting` unified multi-provider walker.

Public surface (in v11.A slice order):
  - `HostingRow` (slice 2 — this file) — one domain's deploy state
  - `walk_vercel()` (slice 3) — Vercel projects + deployments
  - `walk_cf_pages()` (slice 4) — Cloudflare Pages projects + deployments
  - `walk_hostgator()` (slice 5) — cPanel UAPI domain + WP enumeration
  - `run_hosting()` (slice 6) — orchestrator + match logic
  - Snapshot persistence in `hosting_cache.py` (slice 7)

Companion to v10's `lamill.toml` declaration mechanism. v10 closed the
"what platform did the operator declare for this site?" gap; v11.A
closes the "what does each provider's API actually say is running
there?" gap. Two together let CHECK_143 (deploy-drift) graduate from
heuristic HTML-body classification (v10.E) to authoritative
provider-state comparison.

Tier-level design notes in `docs/prd.md § 6 → v11 → Design notes`.
Implementation plan in `docs/architecture.md § 9 v11.A`.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---- constants ------------------------------------------------------

# Provider enum values. Match the strings emitted by each walker
# (`HostingRow.provider`); the table renderer's status logic +
# `--provider <X>` flag normalize against these.
PROVIDER_VERCEL = "vercel"
PROVIDER_CF_PAGES = "cloudflare-pages"
PROVIDER_HOSTGATOR = "hostgator"
PROVIDERS: tuple[str, ...] = (
    PROVIDER_VERCEL,
    PROVIDER_CF_PAGES,
    PROVIDER_HOSTGATOR,
)

# Age thresholds for deploy-status classification (resolution 11.C —
# hardcoded; revisit only if real fleet data shows the thresholds are
# wrong). The renderer at slice 9 uses these to map
# `last_successful_deploy_at` → emoji:
#   ≤ RECENT_DAYS  → ✓ recent
#   ≤ STALE_DAYS   → ⚠ stale
#   > STALE_DAYS   → 💤 dormant
RECENT_DAYS = 30
STALE_DAYS = 90

# Deploy-history pagination cap (resolution 11.D — two-tier: stop at N,
# mark `consecutive_failures >= N` when the walker hits the cap without
# finding a `READY`/`SUCCESS` state). Honest about the cap; surfaces
# runaway-failure cases without unbounded paging.
MAX_DEPLOY_LOOKBACK = 10


# ---- dataclass ------------------------------------------------------


@dataclass
class HostingRow:
    """One domain's deploy state across Vercel + CF Pages + HostGator.

    Field shape decisions:
      - `provider` matches `PROVIDERS` strings (or None when no provider
        claims the domain).
      - Build-pipeline fields (`project_slug` / `project_id` /
        `latest_deploy_*` / `last_successful_deploy_at` /
        `consecutive_failures`) stay `None` / `0` for HostGator rows —
        HG has no build pipeline.
      - HG-specific fields (`hg_account_id` / `disk_used_mb` /
        `wp_version` / `install_path`) stay `None` for non-HG rows.
        Typed explicitly rather than nested in an `extra: dict` blob
        per resolution 11.M — matches every other dataclass in the
        codebase.
      - `provider_conflict=True` flags drift: the same domain matched
        by multiple providers' walkers (resolution 11.F). Each
        conflicting provider emits its own row; rollup counts treat
        the set as a single conflict.
      - `error` carries per-row 5xx / rate-limit surfaces from the
        walker (resolution 11.H). 401 failures skip the affected
        walker entirely and don't show up here.
    """

    domain: str
    provider: str | None = None

    # Build-pipeline fields (Vercel / CF Pages — None for HG).
    project_slug: str | None = None
    project_id: str | None = None
    latest_deploy_status: str | None = None    # READY | ERROR | BUILDING | CANCELED
    latest_deploy_at: str | None = None        # ISO 8601 UTC
    last_successful_deploy_at: str | None = None
    consecutive_failures: int = 0

    # Cross-provider drift signal (resolution 11.F).
    provider_conflict: bool = False

    # Per-row error surface (resolution 11.H).
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    # HostGator-specific fields (None for non-HG rows). Per resolution
    # 11.M — typed optional, no `extra: dict` blob.
    hg_account_id: str | None = None      # "gator3164" / "gator4216"
    disk_used_mb: int | None = None       # account-level, attached to all rows from that account
    wp_version: str | None = None         # None if not a WordPress install
    install_path: str | None = None       # absolute path on the cPanel host
