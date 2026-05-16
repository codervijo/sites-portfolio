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
    if not TOKEN_PATH.is_file():
        raise MissingCredentialsError(
            f"No Cloudflare API token at {TOKEN_PATH}.\n"
            "  Easiest: run `portfolio settings cloudflare token` "
            "— prompts for the token, saves it at mode 0600, and verifies "
            "it works against Cloudflare in one step.\n"
            "  Manual path:\n"
            "  1. Open https://dash.cloudflare.com/profile/api-tokens\n"
            "  2. Click 'Create Custom Token' → Get started\n"
            "  3. Permissions: Zone → Cache Purge → Purge\n"
            "  4. Zone Resources: Include → All zones from an account → "
            "<your account>\n"
            "  5. Continue to summary → Create Token, copy the value\n"
            f"  6. mkdir -p {TOKEN_PATH.parent} && "
            f"printf '%s' '<token>' > {TOKEN_PATH} && chmod 600 {TOKEN_PATH}"
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
