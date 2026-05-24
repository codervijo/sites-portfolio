"""Cloudflare API client for cache-purge operations.

Used by `CHECK_057 — cf-edge-cache-fresh`'s tier-1 fixer to purge stale
files at the Cloudflare edge. Auth pattern mirrors `gsc.py`:

  ~/.config/portfolio/cloudflare/token   ← API token (Zone:Cache Purge)

The zone-id-by-domain lookup is cached in `data/cloudflare/zones.json`
so a fix call doesn't round-trip to the CF API just to resolve the zone
when we've seen the domain before.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .data import ROOT

CONFIG_DIR = Path.home() / ".config" / "portfolio" / "cloudflare"
TOKEN_PATH = CONFIG_DIR / "token"
ZONES_CACHE = ROOT / "data" / "cloudflare" / "zones.json"

API_BASE = "https://api.cloudflare.com/client/v4"
HTTP_TIMEOUT = 15.0


class MissingCredentialsError(RuntimeError):
    """API token file isn't present. Caller surfaces a "manual" fix status
    rather than a hard error — operator can configure the token and retry."""


class CloudflareAPIError(RuntimeError):
    """Non-success response from Cloudflare. Carries the API's `errors`
    array in the message so debugging doesn't require log-spelunking."""


def _read_token() -> str:
    """v15.O hotfix — env-first token lookup.

    Two CF token storage locations existed historically:
      1. `portfolio.env` `CF_API_TOKEN` — canonical for v15.I-N
         (set via `lamill settings apikeys set CF_API_TOKEN <pat>`).
      2. `~/.config/portfolio/cloudflare/token` — legacy file from
         pre-apikeys era, used by `purge_files` (CHECK_057's
         tier-1 fixer).

    These can diverge if the operator updates one without the
    other. Env wins to keep the apikeys-canonical model clean;
    file is fallback for backward compat.
    """
    from . import apikeys

    env_token = (apikeys.get_key("CF_API_TOKEN") or "").strip()
    if env_token:
        return env_token

    if not TOKEN_PATH.is_file():
        raise MissingCredentialsError(
            f"No CF API token in portfolio.env (CF_API_TOKEN) or "
            f"{TOKEN_PATH}.\n"
            "  Set via `lamill settings apikeys set CF_API_TOKEN <pat>` "
            "(preferred — canonical location since v15.I).\n"
            "  Manual path:\n"
            "  1. Open https://dash.cloudflare.com/profile/api-tokens\n"
            "  2. Click 'Create Custom Token' → set permissions\n"
            "  3. Continue to summary → Create Token, copy the value\n"
            "  4. `lamill settings apikeys set CF_API_TOKEN <value>`"
        )
    return TOKEN_PATH.read_text().strip()


def _client(token: str | None = None, *,
            client: httpx.Client | None = None) -> httpx.Client:
    """Build an httpx.Client bound to the CF API with the token attached.
    Caller-injected clients are returned unchanged — tests pass a mocked
    transport here without going through the token-read path."""
    if client is not None:
        return client
    if token is None:
        token = _read_token()
    return httpx.Client(
        base_url=API_BASE,
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )


def _load_zones_cache() -> dict[str, str]:
    """Return the persisted {domain → zone_id} map. Empty when no cache
    file exists yet — first lookup of any domain writes the file."""
    if not ZONES_CACHE.is_file():
        return {}
    try:
        data = json.loads(ZONES_CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def _save_zones_cache(mapping: dict[str, str]) -> None:
    ZONES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ZONES_CACHE.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")


def resolve_zone_id(domain: str, *,
                    client: httpx.Client | None = None) -> str:
    """Return the CF zone id for `domain`. Cache-first; falls back to
    `GET /zones?name=<domain>` on miss and persists the result.

    Raises `CloudflareAPIError` when the API responds but the zone isn't
    in the account, or when the API call itself fails.
    """
    cache = _load_zones_cache()
    if domain in cache:
        return cache[domain]

    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get("/zones", params={"name": domain})
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /zones?name={domain} → HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"GET /zones?name={domain} returned success=false: "
            f"{body.get('errors')}"
        )
    result = body.get("result") or []
    if not result:
        raise CloudflareAPIError(
            f"No CF zone found for domain {domain}. Token may not have "
            f"access to this zone, or the domain isn't on Cloudflare."
        )
    zone_id = result[0].get("id")
    if not zone_id:
        raise CloudflareAPIError(
            f"CF zone lookup for {domain} returned no id: {result[0]}"
        )
    cache[domain] = zone_id
    _save_zones_cache(cache)
    return zone_id


def save_token(token: str) -> None:
    """Persist `token` to `TOKEN_PATH` with mode 0600. Creates the parent
    directory at 0700 if it doesn't exist yet. Strips surrounding
    whitespace before writing — the dashboard's copy widget sometimes
    appends one. Raises ValueError on an empty token (avoids saving a
    placeholder that breaks the next call obscurely)."""
    cleaned = token.strip()
    if not cleaned:
        raise ValueError("refusing to save empty token")
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        TOKEN_PATH.parent.chmod(0o700)
    except OSError:
        pass  # On some filesystems chmod is a no-op; not worth failing on.
    TOKEN_PATH.write_text(cleaned)
    TOKEN_PATH.chmod(0o600)


def verify_token(*, client: httpx.Client | None = None) -> dict:
    """Probe the saved token with a low-cost `GET /user/tokens/verify`.
    Returns the parsed `result` dict (carries `id`, `status`, `expires_on`,
    `not_before`). Raises `MissingCredentialsError` if no token saved,
    `CloudflareAPIError` if Cloudflare rejects it.

    Cheaper than `GET /zones` for verification — `/user/tokens/verify`
    is the CF-documented endpoint for "does this token still work?"
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get("/user/tokens/verify")
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /user/tokens/verify → HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"token verify returned success=false: {body.get('errors')}"
        )
    return body.get("result") or {}


def token_status() -> dict:
    """Read-only snapshot of local CF config state. Used by
    `settings cloudflare status` so the operator can see what's set up
    without running a network call.

    Returns: {token_present, token_path, token_mode, parent_mode,
              zones_cached, zones_cache_path}
    """
    out: dict = {
        "token_present": TOKEN_PATH.is_file(),
        "token_path": str(TOKEN_PATH),
        "token_mode": None,
        "parent_mode": None,
        "zones_cached": 0,
        "zones_cache_path": str(ZONES_CACHE),
    }
    if TOKEN_PATH.is_file():
        try:
            out["token_mode"] = oct(TOKEN_PATH.stat().st_mode & 0o777)
        except OSError:
            pass
    if TOKEN_PATH.parent.is_dir():
        try:
            out["parent_mode"] = oct(TOKEN_PATH.parent.stat().st_mode & 0o777)
        except OSError:
            pass
    out["zones_cached"] = len(_load_zones_cache())
    return out


def purge_files(zone_id: str, urls: list[str], *,
                client: httpx.Client | None = None) -> None:
    """POST a list of full URLs to CF's purge_cache endpoint.

    Cloudflare accepts up to 30 URLs per call; we don't paginate here
    because the cache check only flags up to 5 critical paths and we'd
    rather fail loud than silently truncate.

    Raises `CloudflareAPIError` on a non-200 or `success=false` response.
    Returns None on success — the API doesn't echo anything actionable.
    """
    if not urls:
        return
    if len(urls) > 30:
        raise CloudflareAPIError(
            f"Refusing to purge {len(urls)} URLs in one call — CF caps "
            "at 30 per request. Split the list or rerun the check first."
        )
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.post(f"/zones/{zone_id}/purge_cache", json={"files": urls})
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"POST purge_cache → HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"purge_cache returned success=false: {body.get('errors')}"
        )


# ============================================================================
# v15.I — git-integrated Pages deploy pipeline (ADR-0012)
# ============================================================================
#
# Helpers used by `lamill new deploy <domain>` for the unified
# `_deploy_cf_unified()` orchestrator. All operations are idempotent
# (probe-then-mutate; never blind-create).
#
# Endpoints used:
#   POST   /zones                                                       — create zone
#   GET    /zones/{zone_id}                                             — fetch NS + status
#   GET    /accounts/{id}/pages/projects/{name}                         — get project (idempotency probe)
#   POST   /accounts/{id}/pages/projects                                — create with git source
#   POST   /accounts/{id}/pages/projects/{name}/domains                 — attach custom domain
#   GET    /accounts/{id}/pages/projects/{name}/deployments?per_page=1  — build poll
#
# CF auth: same `_client()` pattern as `resolve_zone_id` / `purge_files`
# (token from `~/.config/portfolio/cloudflare/token`). Account-id comes
# from `apikeys.get_key("CF_ACCOUNT_ID")` — operator sets it once via
# `lamill settings apikeys set`. v15.I helpers take it as an explicit
# parameter; the orchestrator in cli.py resolves it.


from dataclasses import dataclass, field


@dataclass(frozen=True)
class TokenScopeReport:
    """v15.N — result of a CF token scope probe.

    `missing` lists scopes whose Read-side probe returned 401/403.
    CF's permission hierarchy: Edit ⊇ Read, so a Read failure
    means Edit isn't granted either.

    `ok` is True iff every required scope passed its probe.
    """
    ok: bool
    pages_read_ok: bool
    zone_read_ok: bool
    account_settings_read_ok: bool
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def probe_token_scopes(
    account_id: str, *,
    client: httpx.Client | None = None,
) -> TokenScopeReport:
    """v15.N — pre-flight probe to catch under-scoped CF tokens
    BEFORE the deploy pipeline mutates GitHub / git state.

    Read-only probes (each via low-cost GET):
      - `GET /user/tokens/verify` — token alive
      - `GET /accounts/{id}/pages/projects?per_page=1` — Pages access
      - `GET /zones?per_page=1` — Zone access
      - `GET /accounts/{id}` — Account-level read

    Returns `TokenScopeReport` with each scope's status + a
    `missing` list of operator-actionable scope names + a `notes`
    list for context.

    The probe is READ-only — it can't directly verify Edit
    permissions. But Read failure implies Edit isn't granted
    (CF permission hierarchy). Write-step 403s still surface
    distinctly during the pipeline.
    """
    own_client = client is None
    c = _client(client=client)
    missing: list[str] = []
    notes: list[str] = []
    pages_ok = zone_ok = account_ok = False

    try:
        # Token alive.
        resp = c.get("/user/tokens/verify")
        if resp.status_code == 401:
            missing.append("token-invalid (401 from /user/tokens/verify)")
            notes.append(
                "CF_API_TOKEN is rejected by Cloudflare. Generate a "
                "fresh token at https://dash.cloudflare.com/profile/api-tokens."
            )
            return TokenScopeReport(
                ok=False, pages_read_ok=False, zone_read_ok=False,
                account_settings_read_ok=False,
                missing=missing, notes=notes,
            )

        # Pages read.
        pages_resp = c.get(
            f"/accounts/{account_id}/pages/projects",
            params={"per_page": 1},
        )
        if pages_resp.status_code == 200:
            pages_ok = True
        elif pages_resp.status_code in (401, 403):
            missing.append("Account → Cloudflare Pages:Edit")
            notes.append(
                f"Pages probe returned HTTP {pages_resp.status_code}. "
                "Token must include the 'Cloudflare Pages' permission "
                "(Edit level) on the Account scope to create + manage "
                "Pages projects."
            )

        # Zone read.
        zone_resp = c.get("/zones", params={"per_page": 1})
        if zone_resp.status_code == 200:
            zone_ok = True
        elif zone_resp.status_code in (401, 403):
            missing.append("Zone → Zone:Edit")
            notes.append(
                f"Zone probe returned HTTP {zone_resp.status_code}. "
                "Token must include 'Zone' permission (Edit level) on "
                "the Zone scope. Resources should be 'All zones from "
                "an account' to allow creating new zones."
            )

        # Account-level read.
        acct_resp = c.get(f"/accounts/{account_id}")
        if acct_resp.status_code == 200:
            account_ok = True
        elif acct_resp.status_code in (401, 403):
            notes.append(
                f"Account probe returned HTTP {acct_resp.status_code}. "
                "Token should include 'Account Settings:Read' on the "
                "Account scope."
            )
    finally:
        if own_client:
            c.close()

    return TokenScopeReport(
        ok=(not missing),
        pages_read_ok=pages_ok,
        zone_read_ok=zone_ok,
        account_settings_read_ok=account_ok,
        missing=missing,
        notes=notes,
    )


# --- v25.D — comprehensive token diagnostic --------------------------


@dataclass(frozen=True)
class AccountDiag:
    """v25.D — per-account permission probe results for the active CF token."""
    account_id: str
    name: str
    has_pages_edit: bool
    has_workers_edit: bool
    has_account_settings_read: bool


@dataclass(frozen=True)
class ZoneDiag:
    """v25.D — per-zone DNS:Edit probe result for the active CF token.
    Backed by `probe_zone_write_capability` (v25.B)."""
    zone_id: str
    name: str
    has_dns_edit: bool


@dataclass(frozen=True)
class TokenDiagnostic:
    """v25.D — full diagnostic for the active CF API token.

    Returned by `diagnose_token()`; rendered by the `settings cloudflare
    check-token` CLI verb. `missing_account_permissions` and
    `missing_zone_permissions` are operator-facing strings ready for
    direct rendering — no further interpretation needed.
    """
    valid: bool
    token_status: str          # "active" | "disabled" | "expired" | "unknown"
    accounts: list[AccountDiag] = field(default_factory=list)
    zones: list[ZoneDiag] = field(default_factory=list)
    missing_account_permissions: list[str] = field(default_factory=list)
    missing_zone_permissions: list[tuple[str, str]] = field(default_factory=list)


def diagnose_token(*, client: httpx.Client | None = None) -> TokenDiagnostic:
    """v25.D — comprehensive CF API token diagnostic.

    Probes:
      - `/user/tokens/verify` — token alive + status
      - `/accounts` — list accessible accounts
      - per-account: `/accounts/{id}/pages/projects`, `/accounts/{id}/workers/services`, `/accounts/{id}`
      - `/zones?per_page=100` — list accessible zones
      - per-zone: `probe_zone_write_capability` (v25.B) for DNS:Edit

    Returns a `TokenDiagnostic` with per-account + per-zone status plus
    flat `missing_account_permissions` / `missing_zone_permissions`
    lists for the CLI renderer.

    Raises `CloudflareAPIError` only on unexpected (5xx, malformed
    JSON) errors — auth failures land in the diagnostic itself
    (`valid=False`, token_status reflects the failure).
    """
    own_client = client is None
    c = _client(client=client)
    accounts: list[AccountDiag] = []
    zones: list[ZoneDiag] = []
    missing_account_perms: list[str] = []
    missing_zone_perms: list[tuple[str, str]] = []

    try:
        # Token alive?
        verify_resp = c.get("/user/tokens/verify")
        if verify_resp.status_code == 401:
            return TokenDiagnostic(
                valid=False, token_status="invalid",
                missing_account_permissions=[
                    "token rejected by CF (HTTP 401 on /user/tokens/verify)"
                ],
            )
        if verify_resp.status_code != 200:
            raise CloudflareAPIError(
                f"/user/tokens/verify → HTTP {verify_resp.status_code}: "
                f"{verify_resp.text[:200]}"
            )
        verify_body = verify_resp.json()
        token_status = (verify_body.get("result") or {}).get("status", "unknown")

        # List accounts.
        accounts_resp = c.get("/accounts", params={"per_page": 50})
        if accounts_resp.status_code == 200:
            for acct in (accounts_resp.json().get("result") or []):
                acct_id = acct.get("id", "")
                acct_name = acct.get("name", "")

                pages_resp = c.get(
                    f"/accounts/{acct_id}/pages/projects",
                    params={"per_page": 1},
                )
                workers_resp = c.get(
                    f"/accounts/{acct_id}/workers/services",
                    params={"per_page": 1},
                )
                settings_resp = c.get(f"/accounts/{acct_id}")

                has_pages = pages_resp.status_code == 200
                has_workers = workers_resp.status_code == 200
                has_settings = settings_resp.status_code == 200

                accounts.append(AccountDiag(
                    account_id=acct_id, name=acct_name,
                    has_pages_edit=has_pages,
                    has_workers_edit=has_workers,
                    has_account_settings_read=has_settings,
                ))
                if not has_pages:
                    missing_account_perms.append(
                        f"{acct_name or acct_id}: Cloudflare Pages:Edit"
                    )
                if not has_workers:
                    missing_account_perms.append(
                        f"{acct_name or acct_id}: Workers Scripts:Edit"
                    )
                if not has_settings:
                    missing_account_perms.append(
                        f"{acct_name or acct_id}: Account Settings:Read"
                    )
        else:
            missing_account_perms.append(
                f"/accounts list returned HTTP {accounts_resp.status_code} "
                f"(token can't enumerate accounts)"
            )

        # List zones.
        zones_resp = c.get("/zones", params={"per_page": 100})
        if zones_resp.status_code == 200:
            for z in (zones_resp.json().get("result") or []):
                zone_id = z.get("id", "")
                zone_name = z.get("name", "")
                probe = probe_zone_write_capability(zone_id, client=c)
                zones.append(ZoneDiag(
                    zone_id=zone_id, name=zone_name,
                    has_dns_edit=probe.can_write,
                ))
                if not probe.can_write:
                    missing_zone_perms.append((zone_name, "DNS:Edit"))
        else:
            missing_account_perms.append(
                f"/zones list returned HTTP {zones_resp.status_code} "
                f"(token can't enumerate zones)"
            )

        return TokenDiagnostic(
            valid=(token_status == "active"),
            token_status=token_status,
            accounts=accounts,
            zones=zones,
            missing_account_permissions=missing_account_perms,
            missing_zone_permissions=missing_zone_perms,
        )
    finally:
        if own_client:
            c.close()


# --- ZoneInfo + ensure_zone ------------------------------------------


@dataclass(frozen=True)
class ZoneInfo:
    """Resolved or newly-created CF zone. `created=True` only when
    this run made the POST /zones call."""
    zone_id: str
    name: str
    name_servers: list[str]
    status: str          # "active" | "pending" | "deactivated" | ...
    created: bool = False


def ensure_zone(domain: str, *,
                account_id: str | None = None,
                client: httpx.Client | None = None) -> ZoneInfo:
    """Resolve OR create the CF zone for `domain`. Returns ZoneInfo
    with `name_servers` populated (so the caller knows what NS to
    push to the registrar) and `status`.

    Detection: try existing `resolve_zone_id()` (cache → GET /zones).
    Creation: on cache+API miss, POST /zones with {name, account.id}
    if `account_id` provided; otherwise raise.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        try:
            zone_id = resolve_zone_id(domain, client=c)
            # Existing zone — fetch full record for NS + status.
            return _fetch_zone_record(zone_id, client=c, created=False)
        except CloudflareAPIError as e:
            # "No CF zone found" → fall through to create.
            if "no cf zone found" in str(e).lower():
                if not account_id:
                    raise CloudflareAPIError(
                        f"Zone for {domain} does not exist and no "
                        f"account_id supplied to create it. Pass "
                        f"account_id via CF_ACCOUNT_ID."
                    ) from e
                return _create_zone(domain, account_id, client=c)
            raise
    finally:
        if own_client:
            c.close()


def _fetch_zone_record(zone_id: str, *, client: httpx.Client,
                       created: bool) -> ZoneInfo:
    resp = client.get(f"/zones/{zone_id}")
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /zones/{zone_id} → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"GET /zones/{zone_id} returned success=false: "
            f"{body.get('errors')}"
        )
    result = body.get("result") or {}
    return ZoneInfo(
        zone_id=zone_id,
        name=result.get("name", ""),
        name_servers=list(result.get("name_servers") or []),
        status=result.get("status", "unknown"),
        created=created,
    )


def _create_zone(domain: str, account_id: str, *,
                 client: httpx.Client) -> ZoneInfo:
    resp = client.post(
        "/zones",
        json={"name": domain, "account": {"id": account_id}},
    )
    # 409 → zone might exist in a race; refetch defensively.
    if resp.status_code == 409:
        # Look up by name to recover.
        return ensure_zone(domain, account_id=None, client=client)
    if resp.status_code not in (200, 201):
        raise CloudflareAPIError(
            f"POST /zones (name={domain}) → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"POST /zones (name={domain}) success=false: "
            f"{body.get('errors')}"
        )
    result = body.get("result") or {}
    # Cache the new zone id.
    cache = _load_zones_cache()
    new_id = result.get("id")
    if new_id:
        cache[domain] = new_id
        _save_zones_cache(cache)
    return ZoneInfo(
        zone_id=new_id or "",
        name=result.get("name", domain),
        name_servers=list(result.get("name_servers") or []),
        status=result.get("status", "pending"),
        created=True,
    )


@dataclass(frozen=True)
class PagesProject:
    """CF Pages project (also serves Workers Static Assets). The unified
    `/accounts/{id}/pages/projects` API model.

    `created=True` only when this run's POST /pages/projects call
    created it (vs. detected via GET).
    """
    name: str
    domains: list[str]               # custom domains attached
    source_owner: str | None         # owner of the connected GH repo (if any)
    source_repo: str | None          # repo name
    production_branch: str
    latest_deployment_id: str | None
    created: bool = False


@dataclass(frozen=True)
class WorkersServiceInfo:
    """v15.P — CF Workers Service (from `/accounts/{id}/workers/services/{name}`).

    Represents a Worker created via the unified Workers & Pages UI
    (post-2025 CF model). Has the same git-integration behavior as
    Pages projects but lives on a different API surface.

    `has_assets=True` indicates Workers Static Assets (the
    Pages-equivalent shape for this Worker).
    """
    name: str
    has_assets: bool
    deployment_id: str | None
    compatibility_date: str | None
    modified_on: str | None


def get_workers_service(name: str, *,
                        account_id: str,
                        client: httpx.Client | None = None) -> WorkersServiceInfo | None:
    """v15.P idempotency probe for Workers Services.

    GET `/accounts/{id}/workers/services/{name}` returns 200 with
    the service envelope if the Worker exists, 404 otherwise.
    Workers Services are CF's unified Workers & Pages model
    (post-2025); git-integrated Worker projects created via the
    dashboard's "Connect to Git" flow live here.

    Note: Workers Builds (git-integration API) is dashboard-only
    as of Jan 2026. This helper only DETECTS existing Workers
    Services; cannot create new git-integrated ones from API.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get(f"/accounts/{account_id}/workers/services/{name}")
    finally:
        if own_client:
            c.close()
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /workers/services/{name} → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"GET /workers/services/{name} success=false: {body.get('errors')}"
        )
    result = body.get("result") or {}
    default_env = result.get("default_environment") or {}
    script = default_env.get("script") or {}
    return WorkersServiceInfo(
        name=result.get("id", name),
        has_assets=bool(script.get("has_assets")),
        deployment_id=script.get("deployment_id") or None,
        compatibility_date=script.get("compatibility_date"),
        modified_on=result.get("modified_on"),
    )


def attach_workers_custom_domain(
    service_name: str, hostname: str, *,
    account_id: str,
    zone_id: str,
    environment: str = "production",
    client: httpx.Client | None = None,
) -> bool:
    """v15.P / v15.Q — attach `hostname` as a custom domain to a
    Workers Service. **GET-then-PUT** for idempotency (v15.Q): list
    existing `/workers/domains` mappings and skip PUT if the
    (hostname, service) pair is already attached.

    Why GET-then-PUT: operator's real-world testing 2026-05-20
    showed PUT returning 403 even for tokens with `Workers
    Scripts:Edit`. The pre-existing mappings in the account were
    likely created via dashboard (no API write needed). v15.Q lets
    operators set up custom domains via dashboard, then re-run
    `lamill new deploy` — Step 6 detects the existing attachment
    via the read-only GET and skips the (potentially 403-bound)
    PUT entirely.

    Body for PUT (when reached): `{service, hostname, environment,
    zone_id}`.

    Returns True if PUT was issued + succeeded; False if the
    mapping was already present (GET-detected; PUT skipped).
    """
    own_client = client is None
    c = _client(client=client)
    try:
        # v15.Q — GET existing mappings; skip PUT if (hostname, service) present.
        list_resp = c.get(f"/accounts/{account_id}/workers/domains")
        if list_resp.status_code == 200:
            body = list_resp.json()
            for d in (body.get("result") or []):
                if (
                    d.get("hostname") == hostname
                    and d.get("service") == service_name
                ):
                    return False  # Already attached — skip PUT.
        # Either GET failed (don't block on it) or pair not found — PUT.
        resp = c.put(
            f"/accounts/{account_id}/workers/domains",
            json={
                "service": service_name,
                "hostname": hostname,
                "environment": environment,
                "zone_id": zone_id,
            },
        )
    finally:
        if own_client:
            c.close()
    if resp.status_code not in (200, 201):
        raise CloudflareAPIError(
            f"PUT /workers/domains (service={service_name}, "
            f"hostname={hostname}) → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"PUT /workers/domains success=false: {body.get('errors')}"
        )
    # CF's PUT here is idempotent; the response doesn't say whether
    # we created or no-op'd. Treat as success either way.
    return True


def get_pages_project(name: str, *,
                      account_id: str,
                      client: httpx.Client | None = None) -> PagesProject | None:
    """Idempotency probe. 404 → None; 200 → PagesProject; else raise."""
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get(f"/accounts/{account_id}/pages/projects/{name}")
    finally:
        if own_client:
            c.close()
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /pages/projects/{name} → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"GET /pages/projects/{name} success=false: {body.get('errors')}"
        )
    return _project_info_from_json(body.get("result") or {}, created=False)


def create_pages_project_with_git(
    name: str, *,
    account_id: str,
    gh_owner: str,
    gh_repo: str,
    production_branch: str = "main",
    build_command: str = "pnpm run build",
    destination_dir: str = "dist",
    client: httpx.Client | None = None,
) -> PagesProject:
    """POST /accounts/{id}/pages/projects with `source.type=github`.

    CF queues a build from the connected GH repo on create; subsequent
    pushes to `production_branch` auto-deploy. Requires the CF GitHub
    App to be installed in the operator's account (one-time dashboard
    step at https://dash.cloudflare.com/?to=/:account/workers-and-pages/
    create/connect-to-git).
    """
    own_client = client is None
    c = _client(client=client)
    body = {
        "name": name,
        "production_branch": production_branch,
        "source": {
            "type": "github",
            "config": {
                "owner": gh_owner,
                "repo_name": gh_repo,
                "production_branch": production_branch,
                "deployments_enabled": True,
                "production_deployments_enabled": True,
            },
        },
        "build_config": {
            "build_command": build_command,
            "destination_dir": destination_dir,
        },
    }
    try:
        resp = c.post(
            f"/accounts/{account_id}/pages/projects",
            json=body,
        )
    finally:
        if own_client:
            c.close()
    if resp.status_code not in (200, 201):
        # Surface GitHub-App-missing errors with operator-actionable text.
        text_lower = resp.text.lower()
        if "github" in text_lower and (
            "install" in text_lower or "not authorized" in text_lower
            or "not configured" in text_lower
        ):
            raise CloudflareAPIError(
                f"POST /pages/projects/{name} → HTTP {resp.status_code}: "
                f"GitHub App not connected to this CF account. Install once "
                f"at https://dash.cloudflare.com/?to=/:account/"
                f"workers-and-pages/create/connect-to-git, authorize the "
                f"repo {gh_owner}/{gh_repo}, then re-run `lamill new "
                f"deploy {gh_repo}`. Full response: {resp.text[:200]}"
            )
        raise CloudflareAPIError(
            f"POST /pages/projects/{name} → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    payload = resp.json()
    if not payload.get("success"):
        raise CloudflareAPIError(
            f"POST /pages/projects/{name} success=false: "
            f"{payload.get('errors')}"
        )
    return _project_info_from_json(payload.get("result") or {}, created=True)


def attach_pages_custom_domain(
    project_name: str, hostname: str, *,
    account_id: str,
    client: httpx.Client | None = None,
) -> bool:
    """Idempotent attach. Returns True if newly attached; False if
    already present.

    Pattern: GET project → inspect `domains` array → POST only when
    `hostname` isn't already in the list. Defensive against CF's
    undocumented idempotency behavior on duplicate POST.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        existing = get_pages_project(project_name, account_id=account_id, client=c)
        if existing is None:
            raise CloudflareAPIError(
                f"Pages project {project_name} doesn't exist; can't "
                f"attach domain {hostname}. Create the project first."
            )
        if hostname in existing.domains:
            return False
        resp = c.post(
            f"/accounts/{account_id}/pages/projects/{project_name}/domains",
            json={"name": hostname},
        )
    finally:
        if own_client:
            c.close()
    # 409 → already attached in a race window — treat as success.
    if resp.status_code == 409:
        return False
    if resp.status_code not in (200, 201):
        raise CloudflareAPIError(
            f"POST /pages/projects/{project_name}/domains → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"attach_pages_custom_domain success=false: {body.get('errors')}"
        )
    return True


def latest_deployment_status(
    project_name: str, *,
    account_id: str,
    client: httpx.Client | None = None,
) -> tuple[str, str | None, str | None]:
    """GET /accounts/{id}/pages/projects/{name}/deployments?per_page=1
    → returns `(stage_name, stage_status, deployment_id)`.

    `stage_status` ∈ {"success", "idle", "active", "failure", "canceled"};
    `stage_name` is one of {"queued", "initialize", "clone_repo", "build",
    "deploy"}. Returns `("", None, None)` if no deployments exist yet
    (e.g., create just queued one but it hasn't started).
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get(
            f"/accounts/{account_id}/pages/projects/{project_name}/deployments",
            params={"page": 1, "per_page": 1},
        )
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /pages/projects/{project_name}/deployments → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"deployment list success=false: {body.get('errors')}"
        )
    result = body.get("result") or []
    if not result:
        return ("", None, None)
    dep = result[0]
    latest = dep.get("latest_stage") or {}
    return (
        latest.get("name") or "",
        latest.get("status"),
        dep.get("id"),
    )


def poll_build(
    project_name: str, *,
    account_id: str,
    timeout_s: int = 300,
    interval_s: int = 5,
    on_status: callable = None,
    client: httpx.Client | None = None,
) -> tuple[str, str | None]:
    """Block until the latest deployment reaches a terminal state, OR
    `timeout_s` elapses.

    Returns `(stage_status, deployment_id)`. Terminal status values
    are `success` / `failure` / `canceled`. On timeout, returns the
    last-observed `(status, deployment_id)` even if non-terminal.

    `on_status(stage, status)` is an optional callback invoked once
    per poll iteration (use for live progress logging).
    """
    import time
    terminal = {"success", "failure", "canceled"}
    deadline = time.monotonic() + timeout_s
    stage_name, stage_status, dep_id = "", None, None
    while time.monotonic() < deadline:
        stage_name, stage_status, dep_id = latest_deployment_status(
            project_name, account_id=account_id, client=client,
        )
        if on_status is not None:
            try:
                on_status(stage_name, stage_status)
            except Exception:
                pass
        if stage_status in terminal:
            return stage_status, dep_id
        time.sleep(interval_s)
    return stage_status or "timeout", dep_id


def _project_info_from_json(payload: dict, *, created: bool) -> PagesProject:
    source = payload.get("source") or {}
    source_config = source.get("config") or {}
    latest = payload.get("latest_deployment") or {}
    domains = payload.get("domains") or []
    if not isinstance(domains, list):
        domains = []
    return PagesProject(
        name=payload.get("name", ""),
        domains=[str(d) for d in domains],
        source_owner=source_config.get("owner"),
        source_repo=source_config.get("repo_name"),
        production_branch=payload.get("production_branch") or "main",
        latest_deployment_id=(
            latest.get("id") if isinstance(latest, dict) else None
        ),
        created=created,
    )


# ============================================================================
# v15.R — DNS records read + delete (auto-cleanup of conflicting records)
# ============================================================================


@dataclass(frozen=True)
class DnsRecord:
    """v15.R — one row from `/zones/{id}/dns_records`."""
    record_id: str
    type: str          # "A" | "AAAA" | "CNAME" | "MX" | "TXT" | "NS" | ...
    name: str          # FQDN (e.g. "agesdk.dev" or "www.agesdk.dev")
    content: str       # IP / target hostname / etc.
    proxied: bool


def list_dns_records(
    zone_id: str, *,
    client: httpx.Client | None = None,
) -> list[DnsRecord]:
    """List DNS records in a zone. CF caps per_page at 50000 but our
    use case rarely exceeds 20 records per zone."""
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get(
            f"/zones/{zone_id}/dns_records",
            params={"per_page": 100},
        )
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"GET /zones/{zone_id}/dns_records → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"dns_records list success=false: {body.get('errors')}"
        )
    out: list[DnsRecord] = []
    for r in (body.get("result") or []):
        out.append(DnsRecord(
            record_id=r.get("id", ""),
            type=r.get("type", ""),
            name=r.get("name", ""),
            content=r.get("content", ""),
            proxied=bool(r.get("proxied")),
        ))
    return out


def create_dns_record(
    zone_id: str, *,
    type: str,
    name: str,
    content: str,
    proxied: bool = False,
    ttl: int = 1,  # 1 = "automatic" per CF API
    client: httpx.Client | None = None,
) -> DnsRecord:
    """v24.C — Create a DNS record in a zone. Used by the deploy
    pipeline's Step 9 GSC block to write the verification TXT.

    `ttl=1` means "automatic" in CF's API (~5 min); explicit values
    must be in the range 60-86400.

    Raises `CloudflareAPIError` on non-200. Returns the created record
    so callers can capture the assigned `record_id` (useful if they
    later need to clean up via `delete_dns_record`).
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.post(
            f"/zones/{zone_id}/dns_records",
            json={
                "type": type,
                "name": name,
                "content": content,
                "ttl": ttl,
                "proxied": proxied,
            },
        )
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"POST /zones/{zone_id}/dns_records ({type} {name}) → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"create_dns_record success=false: {body.get('errors')}"
        )
    r = body.get("result") or {}
    return DnsRecord(
        record_id=r.get("id", ""),
        type=r.get("type", ""),
        name=r.get("name", ""),
        content=r.get("content", ""),
        proxied=bool(r.get("proxied")),
    )


def delete_dns_record(
    zone_id: str, record_id: str, *,
    client: httpx.Client | None = None,
) -> None:
    """Delete a single DNS record by id."""
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.delete(f"/zones/{zone_id}/dns_records/{record_id}")
    finally:
        if own_client:
            c.close()
    if resp.status_code != 200:
        raise CloudflareAPIError(
            f"DELETE /zones/{zone_id}/dns_records/{record_id} → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    if not body.get("success"):
        raise CloudflareAPIError(
            f"delete_dns_record success=false: {body.get('errors')}"
        )


@dataclass(frozen=True)
class ZoneWriteProbe:
    """v25.B — result of a zone-level DNS:Edit probe.

    `can_write` is True iff the active token can write DNS records on
    this specific zone. `missing_scope` carries an operator-actionable
    hint when `can_write=False`; otherwise None.

    See `probe_zone_write_capability` for the probing approach.
    """
    can_write: bool
    missing_scope: str | None = None


def probe_zone_write_capability(
    zone_id: str, *,
    client: httpx.Client | None = None,
) -> ZoneWriteProbe:
    """v25.B — probe whether the active CF token can write DNS records
    on this specific zone, without modifying state.

    Why a write-probe vs a read of `/user/tokens/verify` policies: the
    verify endpoint's policies array uses permission-group labels
    ("DNS Write") that don't map cleanly to per-zone authorization in
    a machine-readable way (especially when the token is "Specific
    zones" rather than "All zones"). A real POST to
    `/zones/{id}/dns_records` is the cleanest signal of whether THIS
    zone is writable by THIS token.

    Approach: POST with a deliberately-invalid TTL (CF requires `1`
    or `60-86400`; `2` is rejected at validation). Validation runs
    AFTER authorization, so:

      - HTTP 403 → token lacks DNS:Edit on this zone. `can_write=False`,
        missing_scope describes the gap.
      - HTTP 400 → auth passed; the bogus TTL was rejected. `can_write=True`.
      - HTTP 401 → token globally invalid. `can_write=False`,
        missing_scope flags that.
      - HTTP 200/201 → unexpected (a record was created despite the
        invalid TTL). Treat as `can_write=True` and attempt cleanup.
      - HTTP 404 → zone not found. Raises CloudflareAPIError.
      - Other → raises CloudflareAPIError.

    Used by `_deploy_cf_unified` Step 3.5 — catches the dropaudit.co
    failure mode (token has zone-scope DNS:Edit on "All zones" account-
    wide, but the specific zone isn't covered) at the cheapest moment,
    before Steps 5.5 / 9 attempt DNS writes mid-pipeline.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.post(
            f"/zones/{zone_id}/dns_records",
            json={
                "type": "TXT",
                "name": "_lamill-write-probe",
                "content": "lamill v25.B write-probe (TTL=2 ensures rejection)",
                "ttl": 2,
                "proxied": False,
            },
        )
        if resp.status_code == 403:
            return ZoneWriteProbe(
                can_write=False,
                missing_scope="Zone → DNS:Edit on this zone",
            )
        if resp.status_code == 401:
            return ZoneWriteProbe(
                can_write=False,
                missing_scope="CF_API_TOKEN rejected (401 from POST /dns_records)",
            )
        if resp.status_code == 404:
            raise CloudflareAPIError(
                f"POST /zones/{zone_id}/dns_records → HTTP 404 (zone not "
                f"found). The zone_id may be stale; re-run after zone "
                f"resolution."
            )
        if resp.status_code in (200, 201):
            body = resp.json()
            rec = (body.get("result") or {}) if isinstance(body, dict) else {}
            stray_id = rec.get("id") if isinstance(rec, dict) else None
            if stray_id:
                try:
                    delete_dns_record(zone_id, stray_id, client=c)
                except CloudflareAPIError:
                    pass
            return ZoneWriteProbe(can_write=True, missing_scope=None)
        if resp.status_code == 400:
            return ZoneWriteProbe(can_write=True, missing_scope=None)
        raise CloudflareAPIError(
            f"POST /zones/{zone_id}/dns_records (write-probe) → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    finally:
        if own_client:
            c.close()


def purge_conflicting_root_records(
    zone_id: str, domain: str, *,
    client: httpx.Client | None = None,
) -> list[DnsRecord]:
    """v15.R — delete DNS records that would conflict with a Workers
    Custom Domain attach on the root domain.

    Targets A / AAAA / CNAME records where `name` matches:
      - `<domain>` (the root itself)
      - `*.<domain>` (wildcard subdomain)
      - `www.<domain>` (operator's parking page often has this)

    Returns the list of records that were deleted (for caller-side
    reporting / audit).

    Used before Step 6 (Workers Custom Domain attach) to avoid the
    "Hostname already has externally managed DNS records" error.
    Token must have DNS:Edit on the zone (operator's "lamillio
    build token" has Zone-scope DNS:Edit on All Zones).
    """
    own_client = client is None
    c = _client(client=client)
    deleted: list[DnsRecord] = []
    try:
        records = list_dns_records(zone_id, client=c)
        targets = {domain, f"*.{domain}", f"www.{domain}"}
        conflicting_types = {"A", "AAAA", "CNAME"}
        for r in records:
            if r.type not in conflicting_types:
                continue
            if r.name not in targets:
                continue
            delete_dns_record(zone_id, r.record_id, client=c)
            deleted.append(r)
    finally:
        if own_client:
            c.close()
    return deleted
