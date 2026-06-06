"""v24.B / v25.C — GSC + Site Verification API write client.

Three Google APIs that compose into a single "register a new domain
with Search Console at deploy time" flow:

  - **Site Verification API** (siteverification scope) —
    `get_verification_token(method=...)` returns the verification value;
    `write_verification_file()` writes the HTML file (FILE method, v25.C);
    `wait_for_verification_file_live()` polls the URL until reachable;
    `verify_domain(method=...)` triggers Google's ownership check.
  - **Webmasters API → sites** (webmasters scope) —
    `add_site()` registers the verified `sc-domain:<domain>` property.
  - **Webmasters API → sitemaps** (webmasters scope) —
    `submit_sitemap()` points GSC at the site's sitemap.xml.

Boundary: HTTP via httpx-direct so tests stub via `httpx.MockTransport`
(matching ga4_admin.py / gh_repo.py pattern). OAuth flow stays in
`gsc.py` — `gsc_admin._access_token()` reuses `gsc.authenticate()`.

v25.C verification methods:
  - FILE (default per v25.A decision a): writes `<project_dir>/public/
    google<token>.html`; doesn't need DNS:Edit on the zone (avoids the
    dropaudit.co failure mode); requires project to expose `public/`.
  - DNS_TXT (fallback): preserved for sites without `public/` (HG
    static-only layouts, etc.) and projects that opt out of FILE.

Per v24.A decision (m): no lazy imports of optional deps in here —
httpx is a hard dep already in pyproject.toml. The lazy-import-
ImportError-wrapping pattern from the pytrends bug applies to
gtrends.py, not here.
"""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote

import httpx

# v25.C — verification method values accepted by the Site Verification API.
#
# v25.F (2026-05-23) — IMPORTANT: verification method must match property
# type (see ADR-0016):
#   - DNS_TXT method verifies Domain properties (`sc-domain:<domain>`).
#     This is what `add_site` / `submit_sitemap` operate on per ADR (v24.A
#     decision c), so DNS_TXT is the load-bearing path.
#   - FILE method verifies URL-prefix properties (`https://<domain>/`).
#     Doesn't grant ownership of the Domain property. Preserved as a
#     fallback / future-use path; not the primary GSC flow.
#
# Default flipped 2026-05-23 from FILE → DNS_TXT. v25.B Step 3.5 already
# gates the deploy pipeline on DNS:Edit being available, so the original
# v25.A rationale ("FILE-first because DNS:Edit might be missing") no
# longer applies — DNS_TXT is always reachable when Step 9 runs.
VERIFICATION_METHOD_FILE = "FILE"
VERIFICATION_METHOD_DNS_TXT = "DNS_TXT"
_VALID_METHODS = (VERIFICATION_METHOD_FILE, VERIFICATION_METHOD_DNS_TXT)

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


# v25.D — GSC 403 cause-classification constants. The Step 9 helpers
# pass error-response bodies through `classify_403()` to surface
# specific actionable hints instead of a generic "scope insufficient"
# (which misled the operator during dropaudit.co's SERVICE_DISABLED case).
GSC_403_INSUFFICIENT_SCOPE = "insufficient_scope"
GSC_403_SERVICE_DISABLED = "service_disabled"
GSC_403_INVALID_GRANT = "invalid_grant"
GSC_403_UNKNOWN = "unknown"


def classify_403(error_body: str) -> tuple[str, str]:
    """v25.D — parse a Google API 403 response body and classify into
    one of:

      - GSC_403_INSUFFICIENT_SCOPE — OAuth token missing scopes
        (`ACCESS_TOKEN_SCOPE_INSUFFICIENT`). Fix: re-consent.
      - GSC_403_SERVICE_DISABLED — Site Verification API not enabled
        in the GCP project the OAuth credentials belong to (the
        dropaudit.co Step 9 failure mode). Fix: enable API in GCP
        console; URL surfaced with the consumer project pre-populated
        if available.
      - GSC_403_INVALID_GRANT — refresh token expired / revoked.
        Fix: re-consent.
      - GSC_403_UNKNOWN — couldn't disambiguate. Surface raw message.

    Returns `(cause_code, operator_action_hint)`. The hint is ready
    for direct rendering — no further interpretation needed by callers.
    """
    import json

    try:
        body = json.loads(error_body)
    except (ValueError, TypeError):
        body = {}

    err = body.get("error", {}) if isinstance(body, dict) else {}
    msg = (err.get("message") or "") if isinstance(err, dict) else ""
    details = (err.get("details") or []) if isinstance(err, dict) else []

    for d in details:
        if not isinstance(d, dict):
            continue
        reason = d.get("reason", "")
        if reason == "ACCESS_TOKEN_SCOPE_INSUFFICIENT":
            return (
                GSC_403_INSUFFICIENT_SCOPE,
                "OAuth token missing scopes (webmasters write + "
                "siteverification). Re-consent with: "
                "`lamill settings gsc auth --force`.",
            )
        if reason == "SERVICE_DISABLED":
            meta = d.get("metadata") if isinstance(d.get("metadata"), dict) else {}
            consumer = meta.get("consumer", "")
            project_id = (
                consumer.split("/")[-1] if "/" in consumer else ""
            )
            api_url = (
                "https://console.developers.google.com/apis/api/"
                "siteverification.googleapis.com/overview"
            )
            if project_id:
                api_url = f"{api_url}?project={project_id}"
            project_hint = f" (GCP project: {project_id})" if project_id else ""
            return (
                GSC_403_SERVICE_DISABLED,
                f"Site Verification API not enabled{project_hint}. "
                f"Enable at: {api_url} — wait ~1-2 min for propagation, "
                f"then re-run deploy.",
            )
        if reason == "REFRESH_TOKEN_REVOKED" or reason == "INVALID_GRANT":
            return (
                GSC_403_INVALID_GRANT,
                "OAuth refresh token revoked or expired. Re-authenticate "
                "with: `lamill settings gsc auth --force`.",
            )

    # Fall back to keyword scan on the parsed message text first, then
    # on the raw input string (covers thin error messages from internal
    # code that don't carry the full Google API JSON body).
    for scan_text in (msg, error_body):
        scan_lower = (scan_text or "").lower()
        if "insufficient" in scan_lower or "access_token_scope" in scan_lower:
            return (
                GSC_403_INSUFFICIENT_SCOPE,
                "OAuth scope appears insufficient. Re-consent with: "
                "`lamill settings gsc auth --force`.",
            )
        if "service_disabled" in scan_lower or "has not been used" in scan_lower:
            return (
                GSC_403_SERVICE_DISABLED,
                "Site Verification API not enabled in your GCP project. "
                "Enable at: https://console.developers.google.com/apis/api/"
                "siteverification.googleapis.com/overview — wait ~1-2 min, "
                "re-run deploy.",
            )
        if "invalid_grant" in scan_lower or "refresh_token" in scan_lower:
            return (
                GSC_403_INVALID_GRANT,
                "OAuth refresh token revoked or expired. Re-authenticate "
                "with: `lamill settings gsc auth --force`.",
            )

    return (
        GSC_403_UNKNOWN,
        f"Unrecognized 403 response — raw message: {msg or '<empty>'}",
    )


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


def _site_payload_for_method(domain: str, method: str) -> dict:
    """Build the `site` payload for the Site Verification API based
    on the verification method.

    - FILE method uses `SITE` type + full URL identifier (Google's spec
      for HTML-file-based verification of a specific origin).
    - DNS_TXT method uses `INET_DOMAIN` type + bare domain (covers the
      whole zone via TXT at apex).
    """
    if method == VERIFICATION_METHOD_FILE:
        return {"type": "SITE", "identifier": f"https://{domain}/"}
    if method == VERIFICATION_METHOD_DNS_TXT:
        return {"type": "INET_DOMAIN", "identifier": domain}
    raise GSCAdminError(
        f"Unknown verification method {method!r}. "
        f"Expected one of {_VALID_METHODS}."
    )


def get_verification_token(
    domain: str, *,
    method: str = VERIFICATION_METHOD_DNS_TXT,
    client: httpx.Client | None = None,
) -> str:
    """Get the verification value Google wants to see for `domain`.

    `method` per v25.F (2026-05-23): DNS_TXT is the default because the
    rest of the GSC pipeline (`add_site` / `submit_sitemap`) operates on
    Domain properties (`sc-domain:<domain>`) per v24.A decision (c), and
    only DNS_TXT verifies Domain properties (FILE verifies URL-prefix
    properties only — see ADR-0016). v25.B Step 3.5 already gates the
    deploy pipeline on DNS:Edit being available, so DNS_TXT is always
    reachable when Step 9 runs.

    FILE method preserved as a fallback / future-use path (verifies the
    `https://<domain>/` URL-prefix property; doesn't grant Domain
    ownership).

    Returns:
      - For method=FILE: the filename string (e.g., `"google<hash>.html"`).
        Caller writes this filename under `<project_dir>/public/` with the
        body `google-site-verification: <token>` (see `write_verification_file`).
      - For method=DNS_TXT: the TXT record content
        (e.g., `"google-site-verification=hX..."`). Caller writes this
        as a TXT record at the domain's apex.

    Raises `GSCAdminError` on non-200 response, unknown method, or empty
    token in the response.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.post(
            f"{_SITE_VERIFICATION_API}/token",
            json={
                "verificationMethod": method,
                "site": _site_payload_for_method(domain, method),
            },
        )
    finally:
        # Don't close test-injected clients — caller owns those.
        pass

    if resp.status_code != 200:
        raise GSCAdminError(
            f"POST siteVerification/v1/token (domain={domain}, "
            f"method={method}) → HTTP {resp.status_code}: "
            f"{resp.text[:300]}"
        )
    body = resp.json()
    token = body.get("token", "")
    if not token:
        raise GSCAdminError(
            f"siteVerification.getToken returned empty token "
            f"for {domain} (method={method}): {body!r}"
        )
    if own_client:
        c.close()
    return token


def write_verification_file(project_dir: Path, token: str) -> Path:
    """v25.C — Write Google's HTML verification file to `project_dir/public/<token>`.

    The `token` returned by `get_verification_token(method="FILE")` is
    the filename Google expects (e.g., `"google1234abc.html"`). Per
    Google's spec the file's body is a single line:

        google-site-verification: <token>

    Idempotent — same input always produces same output content.

    Returns the path to the written file.

    Raises `GSCAdminError` if `<project_dir>/public/` doesn't exist —
    the FILE method can't apply, caller should fall back to DNS_TXT.
    """
    public_dir = Path(project_dir) / "public"
    if not public_dir.is_dir():
        raise GSCAdminError(
            f"FILE verification method requires {public_dir} to exist "
            f"(Astro/Vite convention). Project doesn't expose a "
            f"public/ dir — fall back to DNS_TXT verification."
        )
    file_path = public_dir / token
    file_path.write_text(f"google-site-verification: {token}\n")
    return file_path


# v25.C — HEAD-poll budget for wait_for_verification_file_live.
# Total = sum(intervals) ≈ 180s. Tries immediately + once per interval.
_FILE_LIVE_INTERVALS_S: tuple[float, ...] = (5.0, 10.0, 20.0, 30.0, 45.0, 70.0)


def wait_for_verification_file_live(
    domain: str, token: str, *,
    intervals: tuple[float, ...] = _FILE_LIVE_INTERVALS_S,
    sleep: callable = time.sleep,
    client: httpx.Client | None = None,
) -> bool:
    """v25.C — HEAD-probe `https://<domain>/<token>` until it returns 200.

    CF Workers / Pages auto-deploys typically complete in 30-60s after
    a git push; this poll loop absorbs that window. Total budget
    defaults to ~180s (`sum(intervals)`).

    Returns:
      - True if the file became reachable (200 OK) within budget.
      - False if the poll budget exhausted without success — caller
        should soft-fail Step 9 (deploy isn't ready yet; operator
        re-runs after the build completes).

    `sleep` and `client` are injectable for tests (so the poll loop
    runs instantly without hitting real wall-clock time or live
    network).
    """
    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=10.0, follow_redirects=True)
    url = f"https://{domain}/{token}"
    attempts = len(intervals) + 1
    try:
        for attempt_idx in range(attempts):
            try:
                resp = client.head(url)
                if resp.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            if attempt_idx == attempts - 1:
                return False
            sleep(intervals[attempt_idx])
        return False
    finally:
        if own_client:
            client.close()


def verify_domain(
    domain: str, *,
    method: str = VERIFICATION_METHOD_DNS_TXT,
    intervals: tuple[int, ...] = _PROPAGATION_INTERVALS_S,
    client: httpx.Client | None = None,
    sleep: callable = time.sleep,
) -> None:
    """Trigger Google's ownership-verification check for `domain`.

    `method` per v25.F (2026-05-23): DNS_TXT is the default — verifies
    the Domain property (`sc-domain:<domain>`) that the rest of the
    GSC pipeline operates on. Caller must have already written the TXT
    record via `cloudflare.create_dns_record()` before calling. v25.B
    Step 3.5 guarantees DNS:Edit is available.

    FILE method preserved for the URL-prefix property path (see
    ADR-0016 on the verification-method ↔ property-type coupling).
    Assumes caller has already written the verification file via
    `write_verification_file()` AND confirmed reachable via
    `wait_for_verification_file_live()`.

    Polls Google's verification endpoint with exponential backoff to
    absorb propagation/cache delay.

    Returns None on success.

    Raises `VerificationFailedError` if the poll budget runs out (file
    or TXT not yet visible to Google — operator should wait a few more
    minutes and re-run, or complete verification manually).

    Raises `GSCAdminError` for other 4xx/5xx errors that aren't "not
    yet propagated" — typically scope issues (insufficient_scope →
    re-consent) or auth failures.

    `sleep` and `client` are injectable for tests so the poll loop
    runs instantly.
    """
    if method not in _VALID_METHODS:
        raise GSCAdminError(
            f"Unknown verification method {method!r}. "
            f"Expected one of {_VALID_METHODS}."
        )

    own_client = client is None
    c = _client(client=client)
    last_error: GSCAdminError | None = None

    site_payload = _site_payload_for_method(domain, method)

    # We try once immediately + then after each interval. So total
    # attempts = len(intervals) + 1, total sleep = sum(intervals).
    attempts = len(intervals) + 1
    for attempt_idx in range(attempts):
        try:
            resp = c.post(
                f"{_SITE_VERIFICATION_API}/webResource"
                f"?verificationMethod={method}",
                json={"site": site_payload},
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

    if method == VERIFICATION_METHOD_FILE:
        propagation_hint = (
            "Verification file may not be reachable to Google's fetcher "
            "yet (CF/DNS edge cache, recently-pushed deploy, etc.)"
        )
    else:
        propagation_hint = (
            "TXT record may not have propagated to Google's resolver yet"
        )
    raise VerificationFailedError(
        f"{method} verification for {domain} didn't complete after "
        f"{sum(intervals)}s of polling. {propagation_hint}. Wait a few "
        f"minutes and re-run `lamill new deploy {domain}`, or verify "
        f"manually at https://search.google.com/search-console/welcome. "
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


def resolve_sitemap_url(
    domain: str, *, client: httpx.Client | None = None,
) -> str:
    """v32.G — the site's *actual* sitemap URL, read from the live
    `robots.txt` `Sitemap:` directive.

    `@astrojs/sitemap` (used across the Astro fleet) emits
    `/sitemap-index.xml`, never `/sitemap.xml`, and auto-writes that URL into
    `robots.txt`. Submitting the assumed `/sitemap.xml` made the SPA catch-all
    serve `index.html` for it → GSC "couldn't read" parse errors fleet-wide
    (bugs.md 2026-06-05). We read the real URL from `robots.txt` and fall back
    to `https://<domain>/sitemap.xml` only when robots.txt is unreachable or
    carries no `Sitemap:` line. Returns the first `Sitemap:` entry."""
    fallback = f"https://{domain}/sitemap.xml"
    url = f"https://{domain}/robots.txt"
    try:
        r = (client.get(url) if client is not None
             else httpx.get(url, timeout=5.0, follow_redirects=True))
    except httpx.HTTPError:
        return fallback
    if r.status_code != 200:
        return fallback
    for line in (r.text or "").splitlines():
        s = line.strip()
        if s.lower().startswith("sitemap:"):
            val = s.split(":", 1)[1].strip()
            if val:
                return val
    return fallback


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


def delete_sitemap(
    domain: str, sitemap_url: str, *,
    client: httpx.Client | None = None,
) -> bool:
    """v32.G — remove a stale sitemap entry from `sc-domain:<domain>` (e.g.
    the bad `/sitemap.xml` that the SPA catch-all served as HTML). Returns
    True if deleted, False if it wasn't listed (idempotent skip via
    `list_sitemaps()` pre-check). Mirrors `submit_sitemap`, DELETE instead
    of PUT."""
    own_client = client is None
    c = _client(client=client)

    try:
        existing = list_sitemaps(domain, client=c)
    except GSCAdminError:
        existing = []
    if not any(s.get("path") == sitemap_url for s in existing):
        if own_client:
            c.close()
        return False

    site_uri = _sc_domain_uri(domain)
    encoded_site = quote(site_uri, safe="")
    encoded_feed = quote(sitemap_url, safe="")
    resp = c.delete(
        f"{_WEBMASTERS_API}/sites/{encoded_site}/sitemaps/{encoded_feed}"
    )
    if resp.status_code not in (200, 204):
        raise GSCAdminError(
            f"DELETE webmasters/v3/sites/{site_uri}/sitemaps/{sitemap_url} → "
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
    if own_client:
        c.close()
    return True
