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
    client: httpx.Client, token: str, account_id: str, *, page: int = 1
) -> dict:
    """One page of `/accounts/{account_id}/pages/projects`. Returns the
    `result` array unwrapped from the CF envelope, plus pagination
    metadata via the caller checking `len(result) < per_page`.

    CF's response envelope is `{success, errors, messages, result, result_info}`.
    We raise on the same conditions as the Vercel equivalent — 401
    becomes auth-error; 5xx / non-JSON / envelope-success=false becomes
    walk-error.
    """
    url = f"{CF_API_BASE}/accounts/{account_id}/pages/projects"
    params = {"page": page, "per_page": 25}
    try:
        r = client.get(url, headers=_cf_headers(token), params=params)
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


_CF_MAX_PAGES = 50


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
    empty inputs (orchestrator skips); `CFPagesWalkError` on
    unrecoverable pagination failures. Per-project deploy failures
    record on the row's `error` field.
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
        for page in range(1, _CF_MAX_PAGES + 1):
            body = _list_cf_projects(client, token, account_id, page=page)
            projects = body.get("result") or []
            if not isinstance(projects, list):
                break
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
            # Pagination: trust `result_info.total_pages` when present.
            # Fall back to short-page heuristic only if CF doesn't ship
            # that metadata (defensive — older API versions did omit it).
            result_info = body.get("result_info") or {}
            total_pages = result_info.get("total_pages") if isinstance(result_info, dict) else None
            if isinstance(total_pages, int):
                if page >= total_pages:
                    break
            elif len(projects) < 25:
                break
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


def _hg_headers(token: str, account_id: str) -> dict[str, str]:
    """cPanel API tokens use a custom auth scheme — `cpanel <user>:<token>`
    NOT HTTP Basic. Same as `_probe_hostgator` in apikeys.py."""
    return {
        "Authorization": f"cpanel {account_id}:{token}",
        "User-Agent": "lamill/v11.A fleet-hosting",
    }


def _call_hg_uapi(
    client: httpx.Client,
    token: str,
    account_id: str,
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
    """
    url = _hg_url(account_id, module, function)
    try:
        r = client.get(
            url, headers=_hg_headers(token, account_id), params=params,
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
    client: httpx.Client, token: str, account_id: str
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
        client, token, account_id, "DomainInfo", "list_domains",
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
    client: httpx.Client, token: str, account_id: str
) -> int | None:
    """Account-level disk usage from `Quota/get_quota_info`. Returns MB
    rounded down. None on any failure — the walker still emits rows;
    `disk_used_mb` stays None on the affected rows."""
    body, _err, is_auth = _call_hg_uapi(
        client, token, account_id, "Quota", "get_quota_info",
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
    client: httpx.Client, token: str, account_id: str
) -> dict[str, str]:
    """Map of `document_root → wp_version` from `WordPressManager/
    list_installations`. Returns `{}` on any failure (the module
    isn't always available — older cPanel versions, accounts without
    the WPM plugin). Walker rows just get `wp_version=None` in that
    case; no crash."""
    body, _err, is_auth = _call_hg_uapi(
        client, token, account_id, "WordPressManager", "list_installations",
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
    only_domain: str | None = None,
    client: httpx.Client | None = None,
) -> list[HostingRow]:
    """Enumerate domains hosted under cPanel account `account_id`;
    emit one HostingRow per matched fleet domain. HG has no build
    pipeline so build-pipeline fields stay None; HG-specific fields
    (`hg_account_id`, `disk_used_mb`, `wp_version`, `install_path`)
    carry the operator-relevant signal.

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

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=HG_HTTP_TIMEOUT)

    rows: list[HostingRow] = []
    only_normalized = _bare_host(only_domain) if only_domain else None

    try:
        domains, list_err = _hg_list_domains(client, token, account_id)
        if list_err is not None and not domains:
            raise HostGatorWalkError(
                f"list_domains failed for {account_id}: {list_err}"
            )

        disk_used = _hg_get_disk_used_mb(client, token, account_id)
        wp_map = _hg_list_wp_installs(client, token, account_id)

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
