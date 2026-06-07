"""v18.C — GA4 Admin API client + OAuth flow.

Creates GA4 properties + web data streams via the Google Analytics
Admin API so `lamill new bootstrap` (v18.D) can auto-provision a
property for each new domain. The returned measurement ID lands in
the new site's `lamill.toml [analytics] ga4_id` field (per
2026-05-21 v18.A Option A — portfolio owns lifecycle, SEO pipeline
owns markup injection).

Two API calls:

  - `POST /v1beta/accounts/{account}/properties`
      Creates a new GA4 property. Returns the property resource.
  - `POST /v1beta/properties/{property}/dataStreams`
      Creates a Web data stream under the property. Response carries
      `webStreamData.measurementId` (the `G-XXXXXX` value).

OAuth scope: `analytics.edit` (the property + stream creation
require write access). One-time interactive flow on first use;
refresh token cached for subsequent calls.

**Credential storage location.** `~/lamill/ga4/` per
`feedback_no_hidden_config` — NOT `~/.config/portfolio/ga4/`. The
existing GSC location at `~/.config/portfolio/gsc/` predates that
rule and is itself due for migration; v18 deliberately picks the
new location for GA4 to avoid compounding the drift.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from . import _httpapi

# Per feedback_no_hidden_config — use `~/lamill/`, NOT `~/.config/portfolio/`.
CONFIG_DIR = Path.home() / "lamill" / "ga4"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"

# analytics.edit lets us create + modify properties and data streams.
# Narrower than analytics.manage.users which is a different concern.
SCOPES = ["https://www.googleapis.com/auth/analytics.edit"]

_ADMIN_API_BASE = "https://analyticsadmin.googleapis.com/v1beta"
_DEFAULT_TIMEOUT = 30.0


class MissingCredentialsError(RuntimeError):
    """OAuth client config not present at `CREDENTIALS_PATH`. The
    operator must download `credentials.json` from the GCP Console
    (APIs & Services → Credentials → OAuth 2.0 Client IDs → Desktop
    app) and place it at the expected path. Surfaced by `authenticate()`
    and re-raised by `lamill settings ga4 auth` with an actionable hint."""


class GA4AdminError(_httpapi.HttpApiError):
    """Non-success response from the GA4 Admin API. Carries the
    response body in the message so debugging doesn't require
    log-spelunking. Mirrors `cloudflare.CloudflareAPIError`. Permanent by
    default; a 429 / 5xx raises `GA4TransientError`."""


class GA4TransientError(GA4AdminError, _httpapi.TransientHTTPError):
    """A retryable GA4 Admin failure (429 / transient 5xx). Subclasses
    `GA4AdminError` so existing handlers still catch it."""


# ---- OAuth flow + token management ---------------------------------


def _interactive_flow() -> Credentials:
    """Open a local-server OAuth dance against Google's consent page.
    Returns valid `Credentials` on success; raises `RuntimeError` if
    the operator denies or the redirect fails."""
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDENTIALS_PATH), SCOPES,
    )
    return flow.run_local_server(port=0, open_browser=True)


def _save_token(creds: Credentials) -> None:
    """Persist the refresh token to `TOKEN_PATH` with chmod 600 (mirrors
    `gsc._save_token`). Creates the parent dir if missing."""
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)


def authenticate(force: bool = False) -> Credentials:
    """Return valid `Credentials`. Runs interactive flow on first use
    or when the cached refresh token has expired beyond recovery.

    `force=True` always runs the interactive flow (e.g. on
    `lamill settings ga4 auth --force` to re-authorize after the
    operator changes the GA4 account they want lamill to manage).
    """
    if not CREDENTIALS_PATH.exists():
        raise MissingCredentialsError(
            f"Missing OAuth client config at {CREDENTIALS_PATH}.\n"
            f"  1. Open https://console.cloud.google.com/apis/credentials\n"
            f"  2. Create OAuth 2.0 Client ID (Application type: Desktop app)\n"
            f"  3. Download the JSON\n"
            f"  4. Save it as {CREDENTIALS_PATH}\n"
            f"  5. Re-run `lamill settings ga4 auth`"
        )

    creds: Credentials | None = None
    if not force and TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token and not force:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except RefreshError:
            pass  # Fall through to interactive flow

    creds = _interactive_flow()
    _save_token(creds)
    return creds


def has_token() -> bool:
    """True iff a cached token exists at `TOKEN_PATH`. Used by
    `lamill settings apikeys list` to render a tick beside GA4 OAuth
    status (parallel to how the existing apikeys connectivity probes
    work). Does NOT validate the token — that's `authenticate()`'s
    job. This is a cheap "is OAuth configured at all" probe."""
    return TOKEN_PATH.exists()


# ---- HTTP client -----------------------------------------------------


def _access_token() -> str:
    """Resolve a valid access token string for HTTP `Authorization`
    headers. Triggers the auth flow / refresh as needed."""
    creds = authenticate()
    return creds.token


def _client(client: httpx.Client | None = None) -> httpx.Client:
    """Return an httpx.Client with the GA4 bearer token attached. Used
    as `client or _client()` in API helpers so tests can inject a
    `httpx.Client(transport=httpx.MockTransport(...))` for offline
    stubbing (matches cloudflare.py / gh_repo.py pattern)."""
    if client is not None:
        return client
    token = _access_token()
    return httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=_DEFAULT_TIMEOUT,
    )


# ---- API helpers -----------------------------------------------------


def create_property(
    account_id: str,
    display_name: str,
    *,
    time_zone: str = "America/Los_Angeles",
    currency_code: str = "USD",
    client: httpx.Client | None = None,
) -> str:
    """Create a GA4 property under `account_id`. Returns the property's
    numeric ID (e.g. `"123456789"`) extracted from the response's
    `name` field (shape: `properties/<id>`).

    Required fields per Admin API docs: parent (`accounts/<id>`),
    displayName, timeZone. currencyCode optional but recommended.

    Raises `GA4AdminError` on non-201 response.
    """
    with _httpapi.managed_client(client, _client) as c:
        resp = c.post(
            f"{_ADMIN_API_BASE}/properties",
            json={
                "parent": f"accounts/{account_id}",
                "displayName": display_name,
                "timeZone": time_zone,
                "currencyCode": currency_code,
            },
        )
        if resp.status_code != 200:
            cls = (
                GA4TransientError
                if _httpapi.status_is_transient(resp.status_code)
                else GA4AdminError
            )
            raise cls(
                f"POST /properties (display_name={display_name}) "
                f"→ HTTP {resp.status_code}: {resp.text[:300]}"
            )
        body = resp.json()
        # Response shape: { "name": "properties/123456789", ... }
        name = body.get("name", "")
        if not name.startswith("properties/"):
            raise GA4AdminError(
                f"unexpected create_property response shape: {body!r}"
            )
        return name[len("properties/"):]


def create_web_stream(
    property_id: str,
    default_uri: str,
    *,
    display_name: str | None = None,
    client: httpx.Client | None = None,
) -> tuple[str, str]:
    """Create a Web data stream under `property_id`. Returns
    `(stream_id, measurement_id)`. The measurement ID is the
    `G-XXXXXX` value the operator embeds in the site's gtag block.

    `default_uri` is the production URL (`https://<domain>/`).
    `display_name` defaults to the domain inferred from default_uri
    if not supplied.

    Raises `GA4AdminError` on non-201 response.
    """
    if display_name is None:
        # "https://washcalc.app/" → "washcalc.app web stream"
        from urllib.parse import urlparse
        host = urlparse(default_uri).hostname or default_uri
        display_name = f"{host} web stream"

    with _httpapi.managed_client(client, _client) as c:
        resp = c.post(
            f"{_ADMIN_API_BASE}/properties/{property_id}/dataStreams",
            json={
                "type": "WEB_DATA_STREAM",
                "displayName": display_name,
                "webStreamData": {
                    "defaultUri": default_uri,
                },
            },
        )
        if resp.status_code != 200:
            cls = (
                GA4TransientError
                if _httpapi.status_is_transient(resp.status_code)
                else GA4AdminError
            )
            raise cls(
                f"POST /properties/{property_id}/dataStreams "
                f"(uri={default_uri}) → HTTP {resp.status_code}: "
                f"{resp.text[:300]}"
            )
        body = resp.json()
        # Response shape: {
        #   "name": "properties/123/dataStreams/456",
        #   "webStreamData": { "measurementId": "G-XXXXXX", ... }, ...
        # }
        name = body.get("name", "")
        if "/dataStreams/" not in name:
            raise GA4AdminError(
                f"unexpected create_web_stream response shape: {body!r}"
            )
        stream_id = name.split("/dataStreams/", 1)[1]
        web_data = body.get("webStreamData") or {}
        measurement_id = web_data.get("measurementId", "")
        if not measurement_id.startswith("G-"):
            raise GA4AdminError(
                f"create_web_stream returned no measurementId in response: "
                f"{body!r}"
            )
        return stream_id, measurement_id
