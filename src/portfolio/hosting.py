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
PROVIDER_CF_WORKERS = "cloudflare-workers"
PROVIDER_HOSTGATOR = "hostgator"
PROVIDERS: tuple[str, ...] = (
    PROVIDER_VERCEL,
    PROVIDER_CF_PAGES,
    PROVIDER_CF_WORKERS,
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


# ---- Cloudflare Pages walker (v11.C) -------------------------------

CF_API_BASE = "https://api.cloudflare.com/client/v4"
CF_HTTP_TIMEOUT = 10.0

# CF Pages classifies a deployment via `latest_stage.{name,status}`:
#   stage.name   in {queued, initialize, clone_repo, build, deploy}
#   stage.status in {idle, active, success, failure, skipped}
# A deploy is SUCCESS only when both the stage is `deploy` AND status
# is `success`. Anything with status=failure (at any stage) is a
# FAILURE. Everything else (active / queued / idle / skipped) is
# IN-FLIGHT — same skipped-but-not-counted semantics as Vercel's
# BUILDING/INITIALIZING/QUEUED (resolution 11.D).
_CF_SUCCESS_STAGE_NAME = "deploy"
_CF_SUCCESS_STAGE_STATUS = "success"
_CF_FAILURE_STAGE_STATUS = "failure"


class CFPagesAuthError(Exception):
    """401 from the Cloudflare API. Orchestrator skips the walker."""


class CFPagesWalkError(Exception):
    """Unrecoverable non-auth failure during CF Pages pagination."""


def _cf_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": "lamill/v11.A fleet-hosting",
    }


def _cf_project_custom_domains(project: dict) -> list[str]:
    """Pull custom-domain list from a CF Pages project payload. The
    `domains` field is a list of fully-qualified hostnames the
    project's production deployment is served from. Includes the
    auto-assigned `<slug>.pages.dev` host — left in; bare-host
    intersect with fleet_domains filters it out naturally."""
    domains = project.get("domains") or []
    if not isinstance(domains, list):
        return []
    return [d for d in domains if isinstance(d, str) and d]


def _cf_deploy_created_iso(deploy: dict) -> str | None:
    """CF returns `created_on` as ISO 8601 already — pass through, but
    normalize to UTC `Z` form for snapshot parity. Returns None for
    malformed entries rather than raising — keeps the walker robust."""
    raw = deploy.get("created_on")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        # CF's ISO timestamps end in `Z`; datetime.fromisoformat handles
        # `+00:00` but not `Z` until 3.11 — this codebase requires 3.11+.
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts.astimezone(timezone.utc).isoformat()


def _cf_deploy_state(deploy: dict) -> tuple[str, str]:
    """Return `(stage_name, stage_status)` from a CF Pages deployment.
    Defensive against missing keys — unknowns map to empty strings so
    the classifier counts them as in-flight (won't bump
    consecutive_failures, won't anchor last_successful_deploy_at)."""
    stage = deploy.get("latest_stage") or {}
    name = stage.get("name") if isinstance(stage, dict) else None
    status = stage.get("status") if isinstance(stage, dict) else None
    return (
        name if isinstance(name, str) else "",
        status if isinstance(status, str) else "",
    )


def _cf_deploy_summary_status(deploy: dict) -> str:
    """One-token summary for `HostingRow.latest_deploy_status` — uses
    the CF stage name + status to derive a string the renderer (v11.H)
    can map to an emoji. Output vocabulary: `SUCCESS` / `FAILURE` /
    `IN_PROGRESS` (parallels Vercel's READY / ERROR / BUILDING)."""
    stage_name, stage_status = _cf_deploy_state(deploy)
    if stage_status == _CF_FAILURE_STAGE_STATUS:
        return "FAILURE"
    if stage_name == _CF_SUCCESS_STAGE_NAME and stage_status == _CF_SUCCESS_STAGE_STATUS:
        return "SUCCESS"
    return "IN_PROGRESS"


def _classify_cf_deploys(deployments: list[dict]) -> tuple[str | None, str | None, str | None, int]:
    """CF Pages variant of `_classify_deploys`. Returns the same shape
    `(latest_status, latest_at_iso, last_successful_at_iso, consecutive_failures)`.

    A deploy is SUCCESS only when its `latest_stage` is
    `(deploy, success)`. Anything with `stage.status == failure` is
    a FAILURE. Everything else (active / queued / skipped / idle) is
    IN-FLIGHT — skipped but not counted.
    """
    if not deployments:
        return None, None, None, 0
    latest = deployments[0]
    latest_status = _cf_deploy_summary_status(latest)
    latest_at = _cf_deploy_created_iso(latest)

    last_success: str | None = None
    consecutive_failures = 0
    for d in deployments:
        stage_name, stage_status = _cf_deploy_state(d)
        if stage_name == _CF_SUCCESS_STAGE_NAME and stage_status == _CF_SUCCESS_STAGE_STATUS:
            last_success = _cf_deploy_created_iso(d)
            break
        if stage_status == _CF_FAILURE_STAGE_STATUS:
            consecutive_failures += 1
        # else: in-flight; don't bump, keep walking.

    return latest_status, latest_at, last_success, consecutive_failures


def _list_cf_projects(
    client: httpx.Client, token: str, account_id: str
) -> dict:
    """Fetch `/accounts/{account_id}/pages/projects`. Returns the parsed
    CF envelope dict (`{success, errors, messages, result, result_info}`).

    CF Pages's projects-list endpoint returns ALL projects in a single
    response — the `?page=N&per_page=N` params that work on the
    Search Analytics / Zone listings are rejected here with API error
    `8000024 "Invalid list options provided"`. Personal-portfolio-scale
    fleets fit in one response; v11.C accepts that for now. If a future
    operator hits the implicit list cap, we'll add cursor pagination
    then.

    Raises CFPagesAuthError on 401; CFPagesWalkError on 5xx / non-JSON
    / envelope success=false.
    """
    url = f"{CF_API_BASE}/accounts/{account_id}/pages/projects"
    try:
        r = client.get(url, headers=_cf_headers(token))
    except httpx.HTTPError as e:
        raise CFPagesWalkError(
            f"projects list network error: {type(e).__name__}: {e}"
        ) from e
    if r.status_code == 401:
        raise CFPagesAuthError("Cloudflare API returned 401 — CF_API_TOKEN missing or invalid")
    if r.status_code != 200:
        raise CFPagesWalkError(f"projects list http {r.status_code}")
    try:
        body = r.json()
    except ValueError as e:
        raise CFPagesWalkError("projects list response not JSON") from e
    if not isinstance(body, dict) or not body.get("success"):
        errs = body.get("errors") if isinstance(body, dict) else None
        raise CFPagesWalkError(f"CF API success=false (errors={errs})")
    return body


def _list_cf_deployments(
    client: httpx.Client, token: str, account_id: str, project_name: str
) -> tuple[list[dict], str | None]:
    """Latest N production deploys for one project. Capped at
    `MAX_DEPLOY_LOOKBACK` per resolution 11.D. Per-project failures
    return `([], <reason>)` so the caller attaches `error=` to the
    row instead of raising upward."""
    url = (
        f"{CF_API_BASE}/accounts/{account_id}/pages/projects/"
        f"{project_name}/deployments"
    )
    params = {"env": "production", "per_page": MAX_DEPLOY_LOOKBACK}
    try:
        r = client.get(url, headers=_cf_headers(token), params=params)
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
    if not isinstance(body, dict) or not body.get("success"):
        return [], "CF API success=false on deployments list"
    result = body.get("result") or []
    if not isinstance(result, list):
        return [], "deployments list malformed"
    return result, None


def _walk_cf_project(
    project: dict,
    client: httpx.Client,
    token: str,
    account_id: str,
    fleet_domains: set[str],
    only_normalized: str | None,
    rows: list[HostingRow],
) -> None:
    project_id = project.get("id") or ""
    project_slug = project.get("name") or ""
    if not project_slug:
        return

    matched: list[str] = []
    seen: set[str] = set()
    for d in _cf_project_custom_domains(project):
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

    deployments, deploy_err = _list_cf_deployments(
        client, token, account_id, project_slug
    )
    latest_status, latest_at, last_success, consec = _classify_cf_deploys(deployments)

    for domain in matched:
        rows.append(
            HostingRow(
                domain=domain,
                provider=PROVIDER_CF_PAGES,
                project_slug=project_slug,
                project_id=project_id,
                latest_deploy_status=latest_status,
                latest_deploy_at=latest_at,
                last_successful_deploy_at=last_success,
                consecutive_failures=consec,
                error=deploy_err,
            )
        )


def walk_cf_pages(
    token: str,
    account_id: str,
    fleet_domains: set[str],
    *,
    only_domain: str | None = None,
    client: httpx.Client | None = None,
) -> list[HostingRow]:
    """Walk every CF Pages project in `account_id`; emit one HostingRow
    per matched fleet domain.

    Same contract as `walk_vercel`. Raises `CFPagesAuthError` on 401 /
    empty inputs (orchestrator skips); `CFPagesWalkError` on 5xx /
    envelope-success-false. Per-project deploy failures record on the
    row's `error` field.

    Single-shot — CF Pages's projects-list endpoint returns all
    projects in one response. If a future operator hits an implicit
    list cap (unlikely for personal-portfolio scale), revisit and
    add cursor pagination.
    """
    if not token:
        raise CFPagesAuthError("CF_API_TOKEN not set")
    if not account_id:
        raise CFPagesAuthError("CF_ACCOUNT_ID not set")

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=CF_HTTP_TIMEOUT)

    rows: list[HostingRow] = []
    only_normalized = _bare_host(only_domain) if only_domain else None
    seen_projects: set[str] = set()

    try:
        body = _list_cf_projects(client, token, account_id)
        projects = body.get("result") or []
        if not isinstance(projects, list):
            return rows
        for project in projects:
            if not isinstance(project, dict):
                continue
            slug = project.get("name") or ""
            if slug in seen_projects:
                continue
            if slug:
                seen_projects.add(slug)
            _walk_cf_project(
                project, client, token, account_id,
                fleet_domains, only_normalized, rows,
            )
    finally:
        if own_client:
            client.close()

    return rows


# ---- Cloudflare Workers walker (v11.H) -----------------------------
#
# Inserted 2026-05-19 after a real-fleet hand test surfaced that the
# operator's CF-deployed sites are Workers (with `has_assets: true`),
# not legacy CF Pages projects — `/accounts/{id}/pages/projects`
# returned `result: []`. Modern wrangler deploys land here, not in
# Pages. This walker queries the Workers surface and emits rows with
# `provider="cloudflare-workers"`.
#
# Two endpoints, single-shot each (same lesson as v11.C — these CF
# endpoints don't accept `?page=N&per_page=N`):
#   /workers/scripts  → script metadata: id (slug), modified_on, etc.
#   /workers/domains  → custom-domain → service mapping. THIS is the
#                       matching layer — each entry pairs a hostname
#                       with the script (`service` field) that handles
#                       it. We intersect hostnames against fleet_domains.
#
# Workers don't have a build pipeline the way Pages does. Each
# `wrangler deploy` either lands a new version atomically or fails
# at the publish-API call (caught locally by wrangler). So
# `consecutive_failures` stays 0 and `last_successful_deploy_at`
# equals `script.modified_on`.


class CFWorkersAuthError(Exception):
    """401 from the Workers API or empty token/account_id."""


class CFWorkersWalkError(Exception):
    """Unrecoverable failure during the /workers/domains call.

    Raised when the domains endpoint returns 5xx / envelope
    success=false / non-JSON. Script-list failures are non-fatal
    (rows still emit with `latest_deploy_at=None`).
    """


def _list_cf_workers_scripts(
    client: httpx.Client, token: str, account_id: str
) -> tuple[dict[str, dict], str | None]:
    """Fetch `/accounts/{id}/workers/scripts`. Returns a
    `{script_id: script_dict}` map keyed by the script's slug.

    Non-critical for the walker — a failure here means we still emit
    rows for matched domains but with `latest_deploy_at=None`. Returns
    `({}, <error_message>)` on any failure so the caller can log without
    aborting.
    """
    url = f"{CF_API_BASE}/accounts/{account_id}/workers/scripts"
    try:
        r = client.get(url, headers=_cf_headers(token))
    except httpx.HTTPError as e:
        return {}, f"scripts list network error: {type(e).__name__}"
    if r.status_code == 401:
        raise CFWorkersAuthError(
            "Cloudflare Workers API returned 401 — CF_API_TOKEN missing or invalid"
        )
    if r.status_code != 200:
        return {}, f"scripts list http {r.status_code}"
    try:
        body = r.json()
    except ValueError:
        return {}, "scripts list response not JSON"
    if not isinstance(body, dict) or not body.get("success"):
        return {}, "scripts list envelope success=false"
    result = body.get("result") or []
    if not isinstance(result, list):
        return {}, "scripts list result malformed"
    out: dict[str, dict] = {}
    for script in result:
        if not isinstance(script, dict):
            continue
        slug = script.get("id")
        if isinstance(slug, str) and slug:
            out[slug] = script
    return out, None


def _list_cf_workers_domains(
    client: httpx.Client, token: str, account_id: str
) -> list[dict]:
    """Fetch `/accounts/{id}/workers/domains`. Each result entry maps
    a hostname to a worker `service` (script slug).

    Raises `CFWorkersAuthError` on 401; `CFWorkersWalkError` on any
    other failure since this is the *matching* layer — without it
    we can't emit any rows.
    """
    url = f"{CF_API_BASE}/accounts/{account_id}/workers/domains"
    try:
        r = client.get(url, headers=_cf_headers(token))
    except httpx.HTTPError as e:
        raise CFWorkersWalkError(
            f"domains list network error: {type(e).__name__}: {e}"
        ) from e
    if r.status_code == 401:
        raise CFWorkersAuthError(
            "Cloudflare Workers API returned 401 — CF_API_TOKEN missing or invalid"
        )
    if r.status_code != 200:
        raise CFWorkersWalkError(f"domains list http {r.status_code}")
    try:
        body = r.json()
    except ValueError as e:
        raise CFWorkersWalkError("domains list response not JSON") from e
    if not isinstance(body, dict) or not body.get("success"):
        errs = body.get("errors") if isinstance(body, dict) else None
        raise CFWorkersWalkError(f"CF Workers API success=false (errors={errs})")
    result = body.get("result") or []
    if not isinstance(result, list):
        return []
    return [d for d in result if isinstance(d, dict)]


def _cf_worker_script_modified_iso(script: dict) -> str | None:
    """CF returns `modified_on` as ISO 8601 (Z suffix). Reuse the
    Pages timestamp normalizer for consistency."""
    return _cf_deploy_created_iso({"created_on": script.get("modified_on")})


def walk_cf_workers(
    token: str,
    account_id: str,
    fleet_domains: set[str],
    *,
    only_domain: str | None = None,
    client: httpx.Client | None = None,
) -> list[HostingRow]:
    """Walk CF Workers (Static Assets) deployments in `account_id`;
    emit one HostingRow per matched fleet domain.

    Same contract as `walk_cf_pages`. Raises `CFWorkersAuthError` on
    401 / empty inputs; `CFWorkersWalkError` on a non-recoverable
    `/workers/domains` failure (that's the matching-layer call —
    without it, nothing matches). Script-metadata failures degrade
    gracefully — rows still emit with `latest_deploy_at=None` and
    the per-row `error` field carrying the script-fetch reason.

    Workers deploys are atomic — no `consecutive_failures` walk
    needed. `latest_deploy_status="DEPLOYED"` and
    `last_successful_deploy_at == latest_deploy_at == script.modified_on`
    for every emitted row.
    """
    if not token:
        raise CFWorkersAuthError("CF_API_TOKEN not set")
    if not account_id:
        raise CFWorkersAuthError("CF_ACCOUNT_ID not set")

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=CF_HTTP_TIMEOUT)

    rows: list[HostingRow] = []
    only_normalized = _bare_host(only_domain) if only_domain else None

    try:
        # Domain mapping first — if this fails, no point fetching scripts.
        domains = _list_cf_workers_domains(client, token, account_id)
        scripts_by_slug, scripts_err = _list_cf_workers_scripts(
            client, token, account_id,
        )

        # Dedup by (normalized_host, script). Multiple /workers/domains
        # entries can reference the same hostname under different
        # environments (production / preview); we only want production
        # for the headline row.
        seen: set[tuple[str, str]] = set()
        for entry in domains:
            hostname = entry.get("hostname")
            service = entry.get("service")
            environment = entry.get("environment") or "production"
            if not isinstance(hostname, str) or not hostname:
                continue
            if not isinstance(service, str) or not service:
                continue
            if environment != "production":
                continue
            normalized = _bare_host(hostname)
            if not normalized:
                continue
            if only_normalized and normalized != only_normalized:
                continue
            if normalized not in fleet_domains:
                continue
            if (normalized, service) in seen:
                continue
            seen.add((normalized, service))

            script = scripts_by_slug.get(service) or {}
            modified_at = _cf_worker_script_modified_iso(script)
            # Workers don't have a public per-deploy identifier we'd
            # surface as project_id — the script tag is internal. Leave
            # project_id as None and use the slug for project_slug.
            rows.append(
                HostingRow(
                    domain=normalized,
                    provider=PROVIDER_CF_WORKERS,
                    project_slug=service,
                    project_id=None,
                    latest_deploy_status="DEPLOYED" if modified_at else None,
                    latest_deploy_at=modified_at,
                    last_successful_deploy_at=modified_at,
                    consecutive_failures=0,
                    error=scripts_err,
                )
            )
    finally:
        if own_client:
            client.close()

    return rows


# ---- HostGator walker (v11.D) --------------------------------------

HG_HTTP_TIMEOUT = 12.0  # cPanel UAPI is slower than CF/Vercel
HG_PORT = 2083


class HostGatorAuthError(Exception):
    """401 from cPanel UAPI, or empty token/account_id."""


class HostGatorWalkError(Exception):
    """Unrecoverable failure during HG walker (5xx on list_domains)."""


def _hg_url(account_id: str, module: str, function: str) -> str:
    """cPanel UAPI endpoint URL — host auto-derived from account_id per
    resolution 11.L (no separate HOSTGATOR_HOST_<account> env var)."""
    return f"https://{account_id}.hostgator.com:{HG_PORT}/execute/{module}/{function}"


def _hg_headers(token: str, cpanel_user: str) -> dict[str, str]:
    """cPanel API tokens use a custom auth scheme — `cpanel <user>:<token>`
    NOT HTTP Basic. `cpanel_user` is the cPanel username on the
    server, NOT necessarily the same as the server's hostname slug.
    Resolution 11.L was patched 2026-05-19 to decouple the two after
    the operator's 403 hand test showed `Current User: foundervijo`
    on a `gator3164.hostgator.com` server."""
    return {
        "Authorization": f"cpanel {cpanel_user}:{token}",
        "User-Agent": "lamill/v11.A fleet-hosting",
    }


def _call_hg_uapi(
    client: httpx.Client,
    token: str,
    account_id: str,
    cpanel_user: str,
    module: str,
    function: str,
    *,
    params: dict | None = None,
) -> tuple[dict | None, str | None, bool]:
    """One UAPI call. Returns `(body_dict, error_message, is_auth_error)`.

    `body_dict` is the parsed top-level JSON (status / data / errors)
    when status=1 and HTTP is 200. Otherwise None + error string.
    `is_auth_error` is True on 401 only — caller can elevate to
    `HostGatorAuthError`.

    `cpanel_user` is the cPanel username; `account_id` is the server
    hostname slug. They're often equal on unmanaged HG shared hosting
    but can differ on accounts with a custom username (patched
    2026-05-19 after the 403 hand test).
    """
    url = _hg_url(account_id, module, function)
    try:
        r = client.get(
            url, headers=_hg_headers(token, cpanel_user), params=params,
        )
    except httpx.HTTPError as e:
        return None, f"{module}/{function} network error: {type(e).__name__}", False
    if r.status_code == 401:
        return None, f"{module}/{function} http 401", True
    if r.status_code == 404:
        return None, f"{module}/{function} not available (404)", False
    if r.status_code >= 500:
        return None, f"{module}/{function} http {r.status_code}", False
    if r.status_code != 200:
        return None, f"{module}/{function} http {r.status_code}", False
    try:
        body = r.json()
    except ValueError:
        return None, f"{module}/{function} non-JSON response", False
    if not isinstance(body, dict):
        return None, f"{module}/{function} malformed envelope", False
    if body.get("status") != 1:
        errors = body.get("errors") or []
        first = errors[0] if errors else "status=0"
        return None, f"{module}/{function} UAPI {first}", False
    return body, None, False


def _hg_list_domains(
    client: httpx.Client, token: str, account_id: str, cpanel_user: str,
) -> tuple[list[tuple[str, str | None]], str | None]:
    """Returns `[(domain, document_root)]` for every domain on the
    account (main + addon + parked + sub), plus an error string.

    The UAPI `DomainInfo/list_domains` shape:
      data = {
        "main_domain": "...",
        "addon_domains": [{"domain": "...", "documentroot": "..."}, ...]
                          OR a list of strings on older cPanel versions,
        "parked_domains": [...],
        "sub_domains": [...],
      }
    Tolerant of both shapes — older cPanel versions return strings,
    newer return dicts with documentroot.
    """
    body, err, is_auth = _call_hg_uapi(
        client, token, account_id, cpanel_user, "DomainInfo", "list_domains",
    )
    if is_auth:
        raise HostGatorAuthError(f"DomainInfo/list_domains 401 for {account_id}")
    if err is not None or body is None:
        return [], err
    data = body.get("data") or {}
    out: list[tuple[str, str | None]] = []

    main = data.get("main_domain")
    if isinstance(main, str) and main:
        out.append((main, None))

    for key in ("addon_domains", "parked_domains", "sub_domains"):
        entries = data.get(key) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                out.append((entry, None))
            elif isinstance(entry, dict):
                d = entry.get("domain")
                dr = entry.get("documentroot")
                if isinstance(d, str) and d:
                    out.append((d, dr if isinstance(dr, str) else None))
    return out, None


def _hg_get_disk_used_mb(
    client: httpx.Client, token: str, account_id: str, cpanel_user: str,
) -> int | None:
    """Account-level disk usage from `Quota/get_quota_info`. Returns MB
    rounded down. None on any failure — the walker still emits rows;
    `disk_used_mb` stays None on the affected rows."""
    body, _err, is_auth = _call_hg_uapi(
        client, token, account_id, cpanel_user, "Quota", "get_quota_info",
    )
    if is_auth:
        raise HostGatorAuthError(f"Quota/get_quota_info 401 for {account_id}")
    if body is None:
        return None
    data = body.get("data") or {}
    # cPanel reports disk_used in MB. Some versions ship the field as
    # a string; coerce to int.
    raw = data.get("disk_used")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _hg_list_wp_installs(
    client: httpx.Client, token: str, account_id: str, cpanel_user: str,
) -> dict[str, str]:
    """Map of `document_root → wp_version` from `WordPressManager/
    list_installations`. Returns `{}` on any failure (the module
    isn't always available — older cPanel versions, accounts without
    the WPM plugin). Walker rows just get `wp_version=None` in that
    case; no crash."""
    body, _err, is_auth = _call_hg_uapi(
        client, token, account_id, cpanel_user,
        "WordPressManager", "list_installations",
    )
    if is_auth:
        raise HostGatorAuthError(
            f"WordPressManager/list_installations 401 for {account_id}"
        )
    if body is None:
        return {}
    data = body.get("data")
    # Shape: data is usually a list of install dicts with `installation_path`
    # + `version` fields, but versions vary. Be defensive.
    installs: list[dict] = []
    if isinstance(data, list):
        installs = [e for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        # Some plugin builds nest under `installations`.
        nested = data.get("installations")
        if isinstance(nested, list):
            installs = [e for e in nested if isinstance(e, dict)]
    out: dict[str, str] = {}
    for inst in installs:
        path = inst.get("installation_path") or inst.get("install_path") or inst.get("path")
        version = inst.get("version") or inst.get("wp_version")
        if isinstance(path, str) and isinstance(version, str) and path and version:
            out[path] = version
    return out


def walk_hostgator(
    token: str,
    account_id: str,
    fleet_domains: set[str],
    *,
    cpanel_user: str | None = None,
    only_domain: str | None = None,
    client: httpx.Client | None = None,
) -> list[HostingRow]:
    """Enumerate domains hosted under cPanel account `account_id`;
    emit one HostingRow per matched fleet domain. HG has no build
    pipeline so build-pipeline fields stay None; HG-specific fields
    (`hg_account_id`, `disk_used_mb`, `wp_version`, `install_path`)
    carry the operator-relevant signal.

    `cpanel_user` is the cPanel username on the server. Falls back to
    `account_id` when None — works for unmanaged HG shared hosting
    where username equals the server hostname. For accounts with a
    custom username (set `HOSTGATOR_USER_<account_id>` in
    `portfolio.env`), pass it through. Decoupled from `account_id`
    on 2026-05-19 after the 403 hand test exposed the original
    11.L assumption was wrong for the operator's account
    (`gator3164.hostgator.com` server / `foundervijo` cPanel user).

    Raises `HostGatorAuthError` if the token/account_id is missing or
    rejected by UAPI on any required call (orchestrator skips this
    account per resolution 11.H). `HostGatorWalkError` on
    unrecoverable failures during domain enumeration.

    Note that HG's UAPI is rigid about which modules each cPanel build
    exposes — `WordPressManager` may be missing on some accounts.
    That's treated as "WP info unavailable" (rows still emit with
    `wp_version=None` / `install_path` from `DomainInfo` if present).
    """
    if not token:
        raise HostGatorAuthError("HG token not set")
    if not account_id:
        raise HostGatorAuthError("HG account_id not set")
    effective_user = cpanel_user or account_id

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=HG_HTTP_TIMEOUT)

    rows: list[HostingRow] = []
    only_normalized = _bare_host(only_domain) if only_domain else None

    try:
        domains, list_err = _hg_list_domains(
            client, token, account_id, effective_user,
        )
        if list_err is not None and not domains:
            raise HostGatorWalkError(
                f"list_domains failed for {account_id}: {list_err}"
            )

        disk_used = _hg_get_disk_used_mb(
            client, token, account_id, effective_user,
        )
        wp_map = _hg_list_wp_installs(
            client, token, account_id, effective_user,
        )

        # Dedup by bare-host normalize, preferring the entry that
        # actually carries a `documentroot` — main_domain sometimes
        # appears twice in cPanel responses (once at top level without
        # a doc_root, once as an addon entry with one), and we want
        # the doc_root version so WP detection can match.
        best_doc_root: dict[str, str | None] = {}
        for domain, doc_root in domains:
            normalized = _bare_host(domain)
            if not normalized:
                continue
            if normalized in best_doc_root:
                if best_doc_root[normalized] is None and doc_root is not None:
                    best_doc_root[normalized] = doc_root
            else:
                best_doc_root[normalized] = doc_root

        for normalized, doc_root in best_doc_root.items():
            if only_normalized and normalized != only_normalized:
                continue
            if normalized not in fleet_domains:
                continue
            wp_version = wp_map.get(doc_root) if doc_root else None
            rows.append(
                HostingRow(
                    domain=normalized,
                    provider=PROVIDER_HOSTGATOR,
                    hg_account_id=account_id,
                    disk_used_mb=disk_used,
                    wp_version=wp_version,
                    install_path=doc_root,
                )
            )
    finally:
        if own_client:
            client.close()

    return rows


# ---- Orchestrator (v11.E) ------------------------------------------

from concurrent.futures import ThreadPoolExecutor, as_completed


@dataclass
class HostingResult:
    """Output of `run_hosting()`. Carries the row list plus per-provider
    skip annotations so the renderer can footer "<provider> skipped:
    <reason>" (resolution 11.H — cleaner than rendering N empty rows
    from an auth-failed walker)."""

    rows: list[HostingRow] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def _flag_provider_conflicts(rows: list[HostingRow]) -> None:
    """Per resolution 11.F: when the same fleet domain shows up under
    multiple providers (e.g. apex on CF Pages + an addon-domain entry
    on HostGator), flag every affected row with
    `provider_conflict=True`. Mutates `rows` in place — caller has
    already collected the cross-walker result list.

    Conflict semantics: rows ARE emitted per-provider (two-row drift
    surface, not collapsed). The flag just lets the renderer highlight
    the conflict without changing the row count.
    """
    providers_by_domain: dict[str, set[str]] = {}
    for r in rows:
        if r.provider is None:
            continue
        providers_by_domain.setdefault(r.domain, set()).add(r.provider)
    conflicting = {d for d, ps in providers_by_domain.items() if len(ps) > 1}
    if not conflicting:
        return
    for r in rows:
        if r.domain in conflicting:
            r.provider_conflict = True


def _hg_account_ids_from_apikeys() -> list[str]:
    """Enumerate every `HOSTGATOR_TOKEN_<ACCOUNT_ID>` env var that's
    actually set, return the lowercased account IDs. Drives the
    orchestrator's per-account HG walker fan-out — picks up
    automatically when the operator adds a third HG account via
    `lamill settings apikeys set HOSTGATOR_TOKEN_GATOR<NNNN> <token>`.
    """
    # Local import — orchestrator is the first hosting-module caller
    # that needs apikeys lookup, and pulling it at module top would
    # circular-import on the apikeys side (which depends on .suggest).
    from . import apikeys

    out: list[str] = []
    for keyname in apikeys.KNOWN_KEYS:
        if not keyname.startswith(apikeys.HOSTGATOR_TOKEN_PREFIX):
            continue
        if not apikeys.get_key(keyname):
            continue
        account_id = apikeys._hg_account_from_keyname(keyname)
        if account_id:
            out.append(account_id)
    return out


def run_hosting(
    fleet_domains: set[str],
    *,
    only_domain: str | None = None,
) -> HostingResult:
    """Walk every configured hosting provider in parallel; collect
    rows for matched fleet domains.

    Reads tokens from `apikeys.get_key` (the `portfolio.env` file):
      - `VERCEL_TOKEN` → Vercel walker
      - `CF_API_TOKEN` + `CF_ACCOUNT_ID` → Cloudflare Pages walker
      - `HOSTGATOR_TOKEN_GATOR<NNNN>` → one HG walker task per
        configured account

    Auth failures (missing token, 401) are RECORDED — not raised —
    so a misconfigured single provider doesn't crash the whole
    `fleet hosting` invocation. The other walkers still run; their
    rows still come back; the renderer footers the skipped ones.

    Provider-conflict flagging (resolution 11.F) runs after all
    walkers complete: any domain matched by multiple providers
    gets `provider_conflict=True` on every row that bears it.

    `only_domain` short-circuits emission to one fleet domain;
    walkers still walk all projects per-provider since none of them
    have domain-keyed lookups.
    """
    from . import apikeys

    result = HostingResult()

    vercel_token = apikeys.get_key("VERCEL_TOKEN") or ""
    cf_token = apikeys.get_key("CF_API_TOKEN") or ""
    cf_account = apikeys.get_key("CF_ACCOUNT_ID") or ""
    hg_accounts = _hg_account_ids_from_apikeys()

    # Build the task plan — one future per provider walker, plus one
    # per HG account. Skip-on-missing pre-checked so the
    # `WalkError` exit path stays for unrecoverable mid-walk failures.
    tasks: list[tuple[str, callable]] = []
    if vercel_token:
        tasks.append((
            "vercel",
            lambda: walk_vercel(vercel_token, fleet_domains, only_domain=only_domain),
        ))
    else:
        result.skipped["vercel"] = "VERCEL_TOKEN not set"

    if cf_token and cf_account:
        # CF account drives two tasks — legacy Pages + modern Workers
        # (Static Assets). Both share auth; results merge in
        # `result.rows`. Workers walker was inserted 2026-05-19 (v11.H)
        # after the hand test against operator's CF account returned
        # zero Pages projects — modern wrangler deploys land in
        # Workers, not Pages.
        tasks.append((
            "cloudflare-pages",
            lambda: walk_cf_pages(
                cf_token, cf_account, fleet_domains, only_domain=only_domain,
            ),
        ))
        tasks.append((
            "cloudflare-workers",
            lambda: walk_cf_workers(
                cf_token, cf_account, fleet_domains, only_domain=only_domain,
            ),
        ))
    else:
        missing: list[str] = []
        if not cf_token:
            missing.append("CF_API_TOKEN")
        if not cf_account:
            missing.append("CF_ACCOUNT_ID")
        # Same missing-credential message covers both CF walkers — they
        # share auth, so they share the skip slot too.
        result.skipped["cloudflare-pages"] = f"{' + '.join(missing)} not set"
        result.skipped["cloudflare-workers"] = f"{' + '.join(missing)} not set"

    if hg_accounts:
        for account_id in hg_accounts:
            # `account_id=account_id` in lambda binds the loop var by
            # value — otherwise every task would capture the last one.
            hg_token = apikeys.get_key(
                f"{apikeys.HOSTGATOR_TOKEN_PREFIX}{account_id.upper()}"
            ) or ""
            # cPanel username is decoupled from server hostname per the
            # 2026-05-19 patch; falls back to account_id when
            # HOSTGATOR_USER_<...> isn't set.
            cpanel_user = apikeys.hg_user_for_account(account_id)
            tasks.append((
                f"hostgator:{account_id}",
                lambda token=hg_token, acct=account_id, user=cpanel_user:
                    walk_hostgator(
                        token, acct, fleet_domains,
                        cpanel_user=user, only_domain=only_domain,
                    ),
            ))
    else:
        result.skipped["hostgator"] = "no HOSTGATOR_TOKEN_<account> set"

    if not tasks:
        return result

    max_workers = max(1, len(tasks))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_label = {ex.submit(fn): label for label, fn in tasks}
        for future in as_completed(future_to_label):
            label = future_to_label[future]
            try:
                rows = future.result()
            except (
                VercelAuthError, CFPagesAuthError, CFWorkersAuthError,
                HostGatorAuthError,
            ) as e:
                result.skipped[label] = f"auth — {e}"
                continue
            except (
                VercelWalkError, CFPagesWalkError, CFWorkersWalkError,
                HostGatorWalkError,
            ) as e:
                result.skipped[label] = f"walker — {e}"
                continue
            result.rows.extend(rows)

    _flag_provider_conflicts(result.rows)
    return result


# ---- Status emoji + footer helpers (v11.I) -------------------------


# Priority order — first match wins. Documented here so v11.I tests
# and the renderer agree without re-implementing the cascade.
#
#   provider=None                              → "—"  (unowned)
#   provider_conflict=True                     → "🤐" (cross-provider drift)
#   consecutive_failures ≥ MAX_DEPLOY_LOOKBACK → "✗"  (runaway failures)
#   last_successful_deploy_at:
#       <RECENT_DAYS  (default 30) → "✓"  (recent)
#       <STALE_DAYS   (default 90) → "⚠"  (stale)
#       ≥STALE_DAYS                → "💤" (dormant)
#       None                       → "—"  (unknown — HG case; no build
#                                          pipeline so no deploy timestamp)


_STATUS_UNOWNED = "—"
_STATUS_CONFLICT = "🤐"
_STATUS_RUNAWAY = "✗"
_STATUS_RECENT = "✓"
_STATUS_STALE = "⚠"
_STATUS_DORMANT = "💤"


def hosting_status_emoji(
    row: HostingRow, *, now: datetime | None = None,
) -> str:
    """Resolution 11.C — map a `HostingRow` to a single status glyph.

    `now` is injectable for deterministic tests. Production callers
    leave it default (`datetime.now(timezone.utc)`).
    """
    if row.provider is None:
        return _STATUS_UNOWNED
    if row.provider_conflict:
        return _STATUS_CONFLICT
    if row.consecutive_failures >= MAX_DEPLOY_LOOKBACK:
        return _STATUS_RUNAWAY
    last_ok = row.last_successful_deploy_at
    if not last_ok:
        return _STATUS_UNOWNED
    try:
        ts = datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
    except ValueError:
        return _STATUS_UNOWNED
    if now is None:
        now = datetime.now(timezone.utc)
    age_days = (now - ts).total_seconds() / 86400
    if age_days < RECENT_DAYS:
        return _STATUS_RECENT
    if age_days < STALE_DAYS:
        return _STATUS_STALE
    return _STATUS_DORMANT


def hosting_provider_counts(rows: list[HostingRow]) -> dict[str, int]:
    """Count rows by `provider`. Includes every entry in `PROVIDERS`
    (zero counts surface in the footer so the operator can see at a
    glance that a configured provider walked but matched nothing —
    useful diagnostic for the "missing fleet" bug class). `None`
    providers (unowned rows) bucket under the literal key `"—"`."""
    counts = {p: 0 for p in PROVIDERS}
    for r in rows:
        if r.provider is None:
            counts[_STATUS_UNOWNED] = counts.get(_STATUS_UNOWNED, 0) + 1
        elif r.provider in counts:
            counts[r.provider] += 1
        else:
            # Unknown provider string (shouldn't happen — walkers all
            # emit canonical names — but defensive).
            counts[r.provider] = counts.get(r.provider, 0) + 1
    return counts


def hosting_footer_summary(
    rows: list[HostingRow],
    skipped: dict[str, str],
) -> str:
    """One-line footer summary for `fleet hosting`. Format:

        N rows · M cloudflare-workers · L vercel · K cloudflare-pages
        · J hostgator (X skipped, Y conflicts)

    Zero counts surface — they're load-bearing for diagnostics.
    Skipped + conflict tallies only appear when non-zero.
    """
    counts = hosting_provider_counts(rows)
    total = sum(counts.values())
    parts: list[str] = [f"{total} row{'s' if total != 1 else ''}"]
    for provider in PROVIDERS:
        parts.append(f"{counts.get(provider, 0)} {provider}")
    suffix_bits: list[str] = []
    if skipped:
        suffix_bits.append(f"{len(skipped)} skipped")
    n_conflicts = sum(1 for r in rows if r.provider_conflict)
    if n_conflicts:
        suffix_bits.append(f"{n_conflicts} conflicts")
    suffix = f" ({', '.join(suffix_bits)})" if suffix_bits else ""
    return " · ".join(parts) + suffix

