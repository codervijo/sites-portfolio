"""v24.B — GSC + Site Verification API write client.

Three Google APIs that compose into a single "register a new domain
with Search Console at deploy time" flow:

  - **Site Verification API** (siteverification scope) —
    `get_verification_token()` returns the TXT value to write to DNS;
    `verify_domain()` triggers Google's ownership check (with a DNS-
    propagation poll loop because TXT records take seconds to
    propagate even on CF).
  - **Webmasters API → sites** (webmasters scope) —
    `add_site()` registers the verified `sc-domain:<domain>` property.
  - **Webmasters API → sitemaps** (webmasters scope) —
    `submit_sitemap()` points GSC at the site's sitemap.xml.

Boundary: HTTP via httpx-direct so tests stub via `httpx.MockTransport`
(matching ga4_admin.py / gh_repo.py pattern). OAuth flow stays in
`gsc.py` — `gsc_admin._access_token()` reuses `gsc.authenticate()`.

Per v24.A decision (m): no lazy imports of optional deps in here —
httpx is a hard dep already in pyproject.toml. The lazy-import-
ImportError-wrapping pattern from the pytrends bug applies to
gtrends.py, not here.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import httpx

_SITE_VERIFICATION_API = "https://www.googleapis.com/siteVerification/v1"
_WEBMASTERS_API = "https://www.googleapis.com/webmasters/v3"
_DEFAULT_TIMEOUT = 30.0

# DNS propagation poll knobs (v24.A decision k).
# Total budget ~60s with exponential backoff: 5s + 10s + 20s + 25s = 60s.
_PROPAGATION_INTERVALS_S: tuple[int, ...] = (5, 10, 20, 25)


class GSCAdminError(RuntimeError):
    """Non-2xx response from the Site Verification or Webmasters API.
    Carries the HTTP status + truncated body in the message. Mirrors
    `cloudflare.CloudflareAPIError` and `ga4_admin.GA4AdminError`."""


class VerificationFailedError(RuntimeError):
    """`verify_domain()` exhausted the DNS-propagation poll budget
    without Google's verification check succeeding. Caller (deploy
    pipeline) treats this as operator-action gate: print actionable
    "TXT record present at Cloudflare but Google hasn't picked it up
    yet — wait + re-run, or verify manually in GSC" hint."""


def _access_token() -> str:
    """Resolve a valid OAuth access token from gsc.py's cached
    credentials. The v24.B scope bump applies — if the cached token
    was issued for the old `webmasters.readonly` scope, the write
    calls below will return 403 with `insufficient_scope` and the
    operator gets re-consent prompts via the standard auth path."""
    from . import gsc
    creds = gsc.authenticate()
    return creds.token


def _client(client: httpx.Client | None = None) -> httpx.Client:
    """Return an httpx.Client with bearer auth. Tests inject
    `httpx.Client(transport=httpx.MockTransport(...))` via `client=`
    on the public helpers."""
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


# ---- Site Verification API -----------------------------------------


def get_verification_token(
    domain: str, *, client: httpx.Client | None = None,
) -> str:
    """Get the TXT record value Google wants to see at the domain to
    verify ownership.

    Returns the bare token string (e.g.,
    `"google-site-verification=hX..."`). Caller writes this as the
    `content` of a TXT record at the domain's apex.

    Raises `GSCAdminError` on non-200 response.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.post(
            f"{_SITE_VERIFICATION_API}/token",
            json={
                "verificationMethod": "DNS_TXT",
                "site": {
                    "type": "INET_DOMAIN",
                    "identifier": domain,
                },
            },
        )
    finally:
        # Don't close test-injected clients — caller owns those.
        pass

    if resp.status_code != 200:
        raise GSCAdminError(
            f"POST siteVerification/v1/token (domain={domain}) → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json()
    token = body.get("token", "")
    if not token:
        raise GSCAdminError(
            f"siteVerification.getToken returned empty token "
            f"for {domain}: {body!r}"
        )
    if own_client:
        c.close()
    return token


def verify_domain(
    domain: str, *,
    intervals: tuple[int, ...] = _PROPAGATION_INTERVALS_S,
    client: httpx.Client | None = None,
    sleep: callable = time.sleep,
) -> None:
    """Trigger Google's ownership-verification check for `domain`.

    Assumes the verification TXT record is already in DNS (caller is
    responsible for writing it via cloudflare.create_dns_record before
    calling this). Polls Google's verification endpoint with
    exponential backoff to absorb DNS propagation delay.

    Returns None on success.

    Raises `VerificationFailedError` if the poll budget runs out (TXT
    not visible to Google's resolver yet — operator should wait a few
    more minutes and re-run, or complete verification manually).

    Raises `GSCAdminError` for other 4xx/5xx errors that aren't
    "verification not yet propagated" — those are typically scope
    issues (insufficient_scope → re-consent) or auth failures.

    `sleep` is injectable for tests so the poll loop runs instantly
    without hitting real wall-clock time.
    """
    own_client = client is None
    c = _client(client=client)
    last_error: GSCAdminError | None = None

    # We try once immediately + then after each interval. So total
    # attempts = len(intervals) + 1, total sleep = sum(intervals).
    attempts = len(intervals) + 1
    for attempt_idx in range(attempts):
        try:
            resp = c.post(
                f"{_SITE_VERIFICATION_API}/webResource"
                "?verificationMethod=DNS_TXT",
                json={
                    "site": {
                        "type": "INET_DOMAIN",
                        "identifier": domain,
                    },
                },
            )
        except httpx.RequestError as e:
            # Transient network blip — treat as a propagation-style
            # retry candidate; let the poll loop continue.
            last_error = GSCAdminError(
                f"siteVerification.insert network error: {e}"
            )
        else:
            if resp.status_code == 200:
                if own_client:
                    c.close()
                return
            # 400 = "Failed to verify the site" → DNS hasn't propagated
            # yet (or the TXT record isn't there). Retry.
            # 403 with `insufficient_scope` = OAuth scope missing →
            # don't retry; raise immediately.
            if resp.status_code == 403 and "insufficient" in resp.text.lower():
                if own_client:
                    c.close()
                raise GSCAdminError(
                    f"siteVerification.insert (domain={domain}) → "
                    f"HTTP 403 insufficient_scope. Run "
                    f"`lamill settings gsc auth --force` to re-consent "
                    f"with the v24.B scope bump."
                )
            last_error = GSCAdminError(
                f"siteVerification.insert (domain={domain}) → "
                f"HTTP {resp.status_code}: {resp.text[:300]}"
            )

        # Last attempt — don't sleep, fall through to raise.
        if attempt_idx == attempts - 1:
            break
        sleep(intervals[attempt_idx])

    if own_client:
        c.close()

    raise VerificationFailedError(
        f"DNS verification for {domain} didn't complete after "
        f"{sum(intervals)}s of polling. TXT record may not have "
        f"propagated to Google's resolver yet. Wait a few minutes "
        f"and re-run `lamill new deploy {domain}`, or verify manually "
        f"at https://search.google.com/search-console/welcome. "
        f"Last API error: {last_error}"
    )


# ---- Webmasters API → sites ---------------------------------------


def _sc_domain_uri(domain: str) -> str:
    """Convert a bare domain to the GSC property URI form
    (`sc-domain:example.com`). Locked in v24.A decision (c) as the
    canonical property type for v24."""
    return f"sc-domain:{domain}"


def list_sites(*, client: httpx.Client | None = None) -> list[dict]:
    """List GSC properties the authenticated user owns. Used by
    `add_site()` for the idempotency probe.

    Returns the raw `siteEntry` array from the API response (each
    entry: `{siteUrl: str, permissionLevel: str}`).
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get(f"{_WEBMASTERS_API}/sites")
    finally:
        pass
    if resp.status_code != 200:
        raise GSCAdminError(
            f"GET webmasters/v3/sites → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json() or {}
    if own_client:
        c.close()
    return list(body.get("siteEntry") or [])


def add_site(
    domain: str, *, client: httpx.Client | None = None,
) -> bool:
    """Add `sc-domain:<domain>` as a property to GSC. Returns True
    if the property was newly added; False if it already existed
    (idempotent skip via `list_sites()` pre-check).

    Raises `GSCAdminError` on non-2xx response. Domain verification
    via `verify_domain()` must complete BEFORE this call — Google
    rejects sites.add() for unverified domains.
    """
    own_client = client is None
    c = _client(client=client)

    # Idempotency probe: skip if the property already exists.
    site_uri = _sc_domain_uri(domain)
    try:
        existing = list_sites(client=c)
    except GSCAdminError:
        # If the list call fails, fall through to the PUT — the API
        # gives us the same outcome with one less call.
        existing = []
    if any(e.get("siteUrl") == site_uri for e in existing):
        if own_client:
            c.close()
        return False

    # URL-encode the property URI for the path. `sc-domain:example.com`
    # → `sc-domain%3Aexample.com`.
    encoded = quote(site_uri, safe="")
    try:
        resp = c.put(f"{_WEBMASTERS_API}/sites/{encoded}")
    finally:
        pass

    if resp.status_code not in (200, 204):
        raise GSCAdminError(
            f"PUT webmasters/v3/sites/{site_uri} → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    if own_client:
        c.close()
    return True


# ---- Webmasters API → sitemaps ------------------------------------


def list_sitemaps(
    domain: str, *, client: httpx.Client | None = None,
) -> list[dict]:
    """List sitemaps currently submitted for `sc-domain:<domain>`.
    Used by `submit_sitemap()` for the idempotency probe."""
    own_client = client is None
    c = _client(client=client)
    site_uri = _sc_domain_uri(domain)
    encoded = quote(site_uri, safe="")
    try:
        resp = c.get(f"{_WEBMASTERS_API}/sites/{encoded}/sitemaps")
    finally:
        pass
    if resp.status_code != 200:
        raise GSCAdminError(
            f"GET webmasters/v3/sites/{site_uri}/sitemaps → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    body = resp.json() or {}
    if own_client:
        c.close()
    return list(body.get("sitemap") or [])


def submit_sitemap(
    domain: str, sitemap_url: str, *,
    client: httpx.Client | None = None,
) -> bool:
    """Submit a sitemap URL to the `sc-domain:<domain>` property.
    Returns True if newly submitted; False if already in the
    property's sitemap list (idempotent skip via `list_sitemaps()`
    pre-check).

    `sitemap_url` is the full URL (e.g., `https://example.com/sitemap.xml`)
    not a path. GSC stores it as the `path` field in the response.
    """
    own_client = client is None
    c = _client(client=client)

    # Idempotency probe.
    try:
        existing = list_sitemaps(domain, client=c)
    except GSCAdminError:
        existing = []
    if any(s.get("path") == sitemap_url for s in existing):
        if own_client:
            c.close()
        return False

    site_uri = _sc_domain_uri(domain)
    encoded_site = quote(site_uri, safe="")
    encoded_feed = quote(sitemap_url, safe="")
    try:
        resp = c.put(
            f"{_WEBMASTERS_API}/sites/{encoded_site}"
            f"/sitemaps/{encoded_feed}",
        )
    finally:
        pass
    if resp.status_code not in (200, 204):
        raise GSCAdminError(
            f"PUT webmasters/v3/sites/{site_uri}/sitemaps/{sitemap_url} → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    if own_client:
        c.close()
    return True
