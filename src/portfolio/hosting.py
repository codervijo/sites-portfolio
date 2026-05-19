"""v11.A-K — `fleet hosting` unified multi-provider walker.

Public surface (one phase per shippable unit per the 2026-05-19
renumber):
  - `HostingRow` + constants (v11.A foundation — this file)
  - `walk_vercel()` (v11.B) — Vercel projects + deployments
  - `walk_cf_pages()` (v11.C) — Cloudflare Pages projects + deployments
  - `walk_hostgator()` (v11.D) — cPanel UAPI domain + WP enumeration
  - `run_hosting()` (v11.E) — orchestrator + match logic
  - Snapshot persistence in `hosting_cache.py` (v11.F)
  - CLI shell at `cli.py` `fleet hosting` (v11.G)

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
from datetime import datetime, timezone

import httpx


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


# ---- Vercel walker (slice 3) ---------------------------------------

VERCEL_API_BASE = "https://api.vercel.com"
VERCEL_HTTP_TIMEOUT = 10.0

# Deploy states Vercel returns. The walker categorizes them three ways
# for the consecutive-failures count (resolution 11.D):
#   SUCCESS  → READY only. Anchors `last_successful_deploy_at`.
#   FAILURE  → ERROR / CANCELED. Counted toward `consecutive_failures`.
#   IN-FLIGHT → BUILDING / INITIALIZING / QUEUED. Not failures; the
#               walker keeps walking but doesn't bump the count
#               (waiting for the build to resolve before judging).
_VERCEL_SUCCESS_STATE = "READY"
_VERCEL_FAILURE_STATES: frozenset[str] = frozenset({"ERROR", "CANCELED"})


class VercelAuthError(Exception):
    """401 from the Vercel API.

    Orchestrator (slice 6) catches this and skips the Vercel walker
    entirely per resolution 11.H — cleaner than rendering N empty
    rows. Raised by `walk_vercel` rather than recorded per-row
    because every Vercel row would carry the same useless error.
    """


class VercelWalkError(Exception):
    """Unrecoverable non-auth failure during Vercel pagination.

    Raised when the projects-list endpoint returns 5xx / non-JSON /
    network-error BEFORE any project has been processed. Per-project
    failures during deploy enumeration are non-fatal — they attach
    to the affected row's `error` field instead.
    """


def _vercel_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "lamill/v11.A fleet-hosting",
    }


def _bare_host(host: str) -> str:
    """Resolution 11.E — bare-host normalize: strip leading `www.`,
    lowercase. Matches user intent — apex and `www.` variants are
    the same site for fleet purposes."""
    h = host.strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _project_custom_domains(project: dict) -> list[str]:
    """Pull production-target custom domains from a Vercel project
    payload. `targets.production.alias` is the canonical source —
    a list of fully-qualified hostnames the production deployment
    is served from. Some projects (preview-only / staging) have no
    production target at all and return an empty list.
    """
    targets = project.get("targets") or {}
    prod = targets.get("production") or {}
    alias = prod.get("alias") or []
    if not isinstance(alias, list):
        return []
    return [a for a in alias if isinstance(a, str) and a]


def _deploy_created_iso(deploy: dict) -> str | None:
    """Vercel returns `created` as Unix-ms. Convert to ISO 8601 UTC
    for snapshot parity with the SEO / live-check snapshots."""
    ts = deploy.get("created")
    if not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat()


def _classify_deploys(deployments: list[dict]) -> tuple[str | None, str | None, str | None, int]:
    """Walk a deployment history (newest-first) and derive the four
    HostingRow build-pipeline fields.

    Returns `(latest_status, latest_at_iso, last_successful_at_iso,
    consecutive_failures)`. `consecutive_failures` counts FAILURE-state
    deploys before the first READY — IN-FLIGHT states (BUILDING etc.)
    are skipped (not bumped, not anchored). When the entire window is
    failures with no READY, the count equals `len(deployments)`,
    which the renderer at slice 9 surfaces via the runaway-failures
    glyph per resolution 11.D.
    """
    if not deployments:
        return None, None, None, 0

    latest = deployments[0]
    latest_status = latest.get("state") or latest.get("readyState")
    latest_at = _deploy_created_iso(latest)

    last_success: str | None = None
    consecutive_failures = 0
    for d in deployments:
        state = d.get("state") or d.get("readyState")
        if state == _VERCEL_SUCCESS_STATE:
            last_success = _deploy_created_iso(d)
            break
        if state in _VERCEL_FAILURE_STATES:
            consecutive_failures += 1
        # else: in-flight; don't increment, keep walking.

    return latest_status, latest_at, last_success, consecutive_failures


def _list_vercel_projects(
    client: httpx.Client, token: str, *, until: int | None = None
) -> dict:
    """One page of `/v9/projects`. Returns the parsed JSON dict.

    Raises `VercelAuthError` on 401, `VercelWalkError` on 5xx / non-
    JSON / network error — both are pagination-level failures, so
    the orchestrator gets a clean signal to abort the Vercel walker.
    """
    url = f"{VERCEL_API_BASE}/v9/projects"
    params: dict = {"limit": 20}
    if until is not None:
        params["until"] = until
    try:
        r = client.get(url, headers=_vercel_headers(token), params=params)
    except httpx.HTTPError as e:
        raise VercelWalkError(
            f"projects list network error: {type(e).__name__}: {e}"
        ) from e
    if r.status_code == 401:
        raise VercelAuthError("Vercel API returned 401 — token missing or invalid")
    if r.status_code != 200:
        raise VercelWalkError(f"projects list http {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise VercelWalkError("projects list response not JSON") from e


def _list_vercel_deployments(
    client: httpx.Client, token: str, project_id: str
) -> tuple[list[dict], str | None]:
    """Latest N production deploys (newest-first). Capped at
    `MAX_DEPLOY_LOOKBACK` per resolution 11.D.

    Returns `(deployments, error_message)`. On any per-project failure
    (5xx / non-JSON / network), returns `([], <reason>)` so the
    caller can attach `error=` to the affected HostingRow per
    resolution 11.H. Does NOT raise — Vercel 401 has already been
    caught by `_list_vercel_projects` upstream.
    """
    url = f"{VERCEL_API_BASE}/v6/deployments"
    params = {
        "projectId": project_id,
        "limit": MAX_DEPLOY_LOOKBACK,
        "target": "production",
    }
    try:
        r = client.get(url, headers=_vercel_headers(token), params=params)
    except httpx.HTTPError as e:
        return [], f"deployments list error: {type(e).__name__}"
    if r.status_code == 429:
        return [], "deployments list rate-limited (429)"
    if r.status_code >= 500:
        return [], f"deployments list http {r.status_code}"
    if r.status_code != 200:
        return [], f"deployments list http {r.status_code}"
    try:
        body = r.json()
    except ValueError:
        return [], "deployments list response not JSON"
    deployments = body.get("deployments") or []
    if not isinstance(deployments, list):
        return [], "deployments list malformed"
    return deployments, None


def _walk_vercel_project(
    project: dict,
    client: httpx.Client,
    token: str,
    fleet_domains: set[str],
    only_normalized: str | None,
    rows: list[HostingRow],
) -> None:
    """Process one Vercel project: match its production custom domains
    against the fleet, walk deploy history, emit rows."""
    project_id = project.get("id") or ""
    project_slug = project.get("name") or ""
    if not project_id:
        return

    matched: list[str] = []
    seen: set[str] = set()
    for d in _project_custom_domains(project):
        normalized = _bare_host(d)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if only_normalized and normalized != only_normalized:
            continue
        if normalized in fleet_domains:
            matched.append(normalized)

    if not matched:
        return

    deployments, deploy_err = _list_vercel_deployments(client, token, project_id)
    latest_status, latest_at, last_success, consec = _classify_deploys(deployments)

    for domain in matched:
        rows.append(
            HostingRow(
                domain=domain,
                provider=PROVIDER_VERCEL,
                project_slug=project_slug,
                project_id=project_id,
                latest_deploy_status=latest_status,
                latest_deploy_at=latest_at,
                last_successful_deploy_at=last_success,
                consecutive_failures=consec,
                error=deploy_err,
            )
        )


_VERCEL_MAX_PAGES = 50  # safety guard against pathological pagination loops


def walk_vercel(
    token: str,
    fleet_domains: set[str],
    *,
    only_domain: str | None = None,
    client: httpx.Client | None = None,
) -> list[HostingRow]:
    """Walk every Vercel project; emit one HostingRow per matched fleet
    domain (bare-host normalize per resolution 11.E).

    `only_domain` further restricts emission to that single domain —
    used by `fleet hosting --only DOMAIN`. The walker still pages
    through every project (Vercel has no domain-keyed lookup); it
    just drops rows whose normalized host doesn't match.

    Raises `VercelAuthError` if the token is missing or rejected by
    the API — orchestrator (slice 6) catches and skips the entire
    Vercel walker per resolution 11.H. `VercelWalkError` signals an
    unrecoverable pagination failure (5xx on the projects list call).
    Per-project deploy-history failures are non-fatal and attach to
    the affected row's `error` field.
    """
    if not token:
        raise VercelAuthError("VERCEL_TOKEN not set")

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=VERCEL_HTTP_TIMEOUT)

    rows: list[HostingRow] = []
    only_normalized = _bare_host(only_domain) if only_domain else None
    seen_projects: set[str] = set()

    try:
        until: int | None = None
        for _ in range(_VERCEL_MAX_PAGES):
            page = _list_vercel_projects(client, token, until=until)
            projects = page.get("projects") or []
            if not isinstance(projects, list):
                break
            for project in projects:
                if not isinstance(project, dict):
                    continue
                project_id = project.get("id")
                if project_id and project_id in seen_projects:
                    continue
                if project_id:
                    seen_projects.add(project_id)
                _walk_vercel_project(
                    project, client, token, fleet_domains,
                    only_normalized, rows,
                )
            pagination = page.get("pagination") or {}
            next_until = pagination.get("next")
            if not next_until or not projects:
                break
            until = next_until
    finally:
        if own_client:
            client.close()

    return rows
