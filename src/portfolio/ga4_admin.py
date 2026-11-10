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
from dataclasses import dataclass
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


# ---- v49.B — read + idempotent ensure --------------------------------

RETENTION = "FOURTEEN_MONTHS"


def _raise_for(resp: httpx.Response, what: str) -> None:
    if resp.status_code == 200:
        return
    cls = (
        GA4TransientError
        if _httpapi.status_is_transient(resp.status_code)
        else GA4AdminError
    )
    raise cls(f"{what} → HTTP {resp.status_code}: {resp.text[:300]}")


def _paged(c: httpx.Client, url: str, key: str) -> list[dict]:
    """GET every page of a list endpoint; returns the concatenated `key` items."""
    items: list[dict] = []
    token = ""
    while True:
        params = {"pageSize": 200}
        if token:
            params["pageToken"] = token
        resp = c.get(url, params=params)
        _raise_for(resp, f"GET {url}")
        body = resp.json()
        items.extend(body.get(key) or [])
        token = body.get("nextPageToken") or ""
        if not token:
            return items


def normalize_host(uri_or_host: str) -> str:
    """`https://www.Foo.com/` → `foo.com` (scheme, path and `www.` dropped)."""
    from urllib.parse import urlparse

    s = (uri_or_host or "").strip()
    host = (urlparse(s).hostname if "://" in s else s.split("/", 1)[0]) or ""
    host = host.lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host



@dataclass(frozen=True)
class StreamHit:
    """One GA4 property (and its web stream, if any) visible to the token."""
    account_id: str
    account_name: str
    property_id: str
    property_name: str
    measurement_id: str | None
    host: str | None


def stream_index(*, client: httpx.Client | None = None) -> list[StreamHit]:
    """Every property in every account the token can see, one row per web
    stream (a property with no web stream still gets one row, ids None)."""
    hits: list[StreamHit] = []
    with _httpapi.managed_client(client, _client) as c:
        for acct in _paged(c, f"{_ADMIN_API_BASE}/accountSummaries", "accountSummaries"):
            account_id = acct.get("account", "").split("/")[-1]
            account_name = (acct.get("displayName") or "").strip()
            for prop in acct.get("propertySummaries") or []:
                property_id = prop.get("property", "").split("/")[-1]
                property_name = (prop.get("displayName") or "").strip()
                streams = _paged(
                    c, f"{_ADMIN_API_BASE}/properties/{property_id}/dataStreams",
                    "dataStreams",
                )
                web = [s for s in streams if s.get("type") == "WEB_DATA_STREAM"]
                if not web:
                    hits.append(StreamHit(account_id, account_name, property_id,
                                          property_name, None, None))
                for s in web:
                    wsd = s.get("webStreamData") or {}
                    uri = wsd.get("defaultUri") or ""
                    hits.append(StreamHit(
                        account_id, account_name, property_id, property_name,
                        wsd.get("measurementId") or None,
                        normalize_host(uri) if uri else None,
                    ))
    return hits


def find_for_domain(domain: str, index: list[StreamHit]) -> list[StreamHit]:
    """Rows belonging to `domain`: web-stream host match first; failing that,
    a property whose display name is the domain (covers a half-finished
    create where the stream never landed)."""
    d = normalize_host(domain)
    by_host = [h for h in index if h.host == d and h.measurement_id]
    if by_host:
        return by_host
    return [h for h in index if normalize_host(h.property_name) == d]


def set_data_retention(property_id: str, *, client: httpx.Client | None = None) -> bool:
    """Ensure event + user data retention are 14 months. Returns True when it
    changed anything (probe before act — ADR-0015 idempotency)."""
    url = f"{_ADMIN_API_BASE}/properties/{property_id}/dataRetentionSettings"
    with _httpapi.managed_client(client, _client) as c:
        resp = c.get(url)
        _raise_for(resp, f"GET {url}")
        cur = resp.json()
        if (cur.get("eventDataRetention") == RETENTION
                and cur.get("userDataRetention") == RETENTION):
            return False
        resp = c.patch(
            url,
            params={"updateMask": "eventDataRetention,userDataRetention"},
            json={"eventDataRetention": RETENTION, "userDataRetention": RETENTION},
        )
        _raise_for(resp, f"PATCH {url}")
        return True


@dataclass(frozen=True)
class EnsureOutcome:
    """Result of `ensure_property`.

    status:
      - "found"        — a property for the domain already exists in the fleet account
      - "created"      — a new property (and/or web stream) was created
      - "would-create" — dry run; nothing exists yet
      - "elsewhere"    — the domain's property lives in another account (move it first)
      - "ambiguous"    — more than one fleet-account property matches
    """
    status: str
    measurement_id: str | None = None
    property_id: str | None = None
    account_name: str | None = None
    detail: str = ""


def ensure_property(
    domain: str,
    account_id: str,
    *,
    index: list[StreamHit] | None = None,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> EnsureOutcome:
    """Find-or-create the GA4 property + web stream for `domain` in the fleet
    account `account_id`. Never creates a duplicate: a match in any visible
    account wins. New properties get display name = domain, a web stream at
    `https://<domain>`, and 14-month retention (v49.A (i))."""
    with _httpapi.managed_client(client, _client) as c:
        idx = index if index is not None else stream_index(client=c)
        hits = find_for_domain(domain, idx)
        mine = [h for h in hits if h.account_id == str(account_id)]
        other = [h for h in hits if h.account_id != str(account_id)]
        mine_ids = {h.measurement_id for h in mine if h.measurement_id}
        if len(mine_ids) > 1:
            return EnsureOutcome("ambiguous", detail=", ".join(sorted(mine_ids)))
        if mine_ids:
            h = next(h for h in mine if h.measurement_id)
            if not dry_run:
                set_data_retention(h.property_id, client=c)
            return EnsureOutcome("found", h.measurement_id, h.property_id, h.account_name)
        if other and not mine:
            h = other[0]
            return EnsureOutcome(
                "elsewhere", h.measurement_id, h.property_id, h.account_name,
                detail=f"account {h.account_name} ({h.account_id})",
            )
        if dry_run:
            return EnsureOutcome("would-create")
        # A fleet-account property with no web stream → add the stream only.
        property_id = mine[0].property_id if mine else create_property(
            str(account_id), domain, client=c,
        )
        _sid, measurement_id = create_web_stream(
            property_id, f"https://{domain}", display_name=domain, client=c,
        )
        set_data_retention(property_id, client=c)
        if index is not None:
            index.append(StreamHit(str(account_id), "", property_id, domain,
                                   measurement_id, normalize_host(domain)))
        return EnsureOutcome("created", measurement_id, property_id)
