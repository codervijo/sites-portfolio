"""v15.I — Porkbun nameserver get/update helpers.

Used by `lamill new deploy` to push CF nameservers to Porkbun when
the operator's domain isn't yet pointing at Cloudflare. Per
ADR-0012 the deploy pipeline does GET-then-update-if-mismatch
(idempotency-safe; Porkbun's `updateNs` endpoint doesn't document
idempotency behavior, so we don't rely on it).

Endpoints:
  - `POST /api/json/v3/domain/getNs/<domain>`     → list current NS
  - `POST /api/json/v3/domain/updateNs/<domain>` → set new NS list

Both use the same {apikey, secretapikey} body shape that v15.F's
`porkbun_list.py` established.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

PORKBUN_API = "https://api.porkbun.com/api/json/v3"
HTTP_TIMEOUT = 15.0


class PorkbunDnsError(RuntimeError):
    """Any failure interacting with Porkbun's NS endpoints — missing
    creds, transport error, non-200 HTTP, non-SUCCESS status, shape
    surprise."""


class PorkbunApiAccessError(PorkbunDnsError):
    """Raised when Porkbun rejects an NS call because the domain's
    per-domain "API ACCESS" toggle is OFF.

    This is operator-action-needed, not transient: Porkbun exposes no
    API to flip the toggle, so the fix is a one-time dashboard click per
    domain. Callers should surface the enable-it instructions rather
    than a raw error. Distinct subclass so the deploy pipeline can catch
    it specifically (and `except PorkbunDnsError` still works as a
    catch-all)."""


def _api_access_off(body: dict) -> bool:
    """True when a non-SUCCESS Porkbun body signals the per-domain API
    access toggle is OFF (e.g. status=ERROR, message "Domain is not
    opted in to API access."). Matches defensively on the known
    phrasings so a wording tweak doesn't silently regress detection."""
    msg = str(body.get("message", "")).lower()
    return (
        "not opted in" in msg
        or "api access" in msg
        or "api_access_disabled" in msg
    )


def get_porkbun_ns(domain: str, *, api_key: str, secret: str) -> list[str]:
    """Fetch current nameservers for `domain`. Returns a sorted list
    of lowercased nameserver hostnames; empty if the domain has no NS
    set (rare; usually Porkbun's defaults sit in place).

    Raises `PorkbunDnsError` on any failure.
    """
    if not api_key or not secret:
        raise PorkbunDnsError(
            "missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY"
        )

    try:
        r = httpx.post(
            f"{PORKBUN_API}/domain/getNs/{domain}",
            json={"apikey": api_key, "secretapikey": secret},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise PorkbunDnsError(
            f"network error calling getNs/{domain}: {type(e).__name__}: {e}"
        ) from e

    if r.status_code != 200:
        raise PorkbunDnsError(
            f"getNs/{domain} → HTTP {r.status_code}: {r.text[:200]}"
        )

    try:
        body = r.json()
    except ValueError as e:
        raise PorkbunDnsError(
            f"getNs/{domain} returned non-JSON: {e}"
        ) from e

    if not isinstance(body, dict) or body.get("status") != "SUCCESS":
        if isinstance(body, dict) and _api_access_off(body):
            raise PorkbunApiAccessError(
                f"per-domain API access is OFF for {domain}"
            )
        raise PorkbunDnsError(
            f"getNs/{domain} status != SUCCESS: {body}"
        )

    ns_raw = body.get("ns") or []
    if not isinstance(ns_raw, list):
        raise PorkbunDnsError(
            f"getNs/{domain} body.ns is not a list: {type(ns_raw).__name__}"
        )

    return sorted({str(n).strip().lower() for n in ns_raw if n})


def update_porkbun_ns(
    domain: str, *, api_key: str, secret: str, ns_list: list[str],
) -> None:
    """Set nameservers for `domain`. Raises `PorkbunDnsError` on
    failure. Does NOT pre-check — callers do GET-then-compare to skip
    no-op updates."""
    if not api_key or not secret:
        raise PorkbunDnsError(
            "missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY"
        )
    if not ns_list:
        raise PorkbunDnsError(
            f"refusing to update NS to empty list for {domain}"
        )

    try:
        r = httpx.post(
            f"{PORKBUN_API}/domain/updateNs/{domain}",
            json={
                "apikey": api_key,
                "secretapikey": secret,
                "ns": list(ns_list),
            },
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise PorkbunDnsError(
            f"network error calling updateNs/{domain}: {type(e).__name__}: {e}"
        ) from e

    if r.status_code != 200:
        raise PorkbunDnsError(
            f"updateNs/{domain} → HTTP {r.status_code}: {r.text[:200]}"
        )

    try:
        body = r.json()
    except ValueError as e:
        raise PorkbunDnsError(
            f"updateNs/{domain} returned non-JSON: {e}"
        ) from e

    if not isinstance(body, dict) or body.get("status") != "SUCCESS":
        if isinstance(body, dict) and _api_access_off(body):
            raise PorkbunApiAccessError(
                f"per-domain API access is OFF for {domain}"
            )
        raise PorkbunDnsError(
            f"updateNs/{domain} status != SUCCESS: {body}"
        )


def ns_matches(current: list[str], target: list[str]) -> bool:
    """Case-insensitive set-equality. Order doesn't matter for NS
    sets (they're queried as a pool by DNS resolvers)."""
    return {n.strip().lower() for n in current} == {
        n.strip().lower() for n in target
    }


# ---- URL Forwarding read / clear (v32.D) -----------------------------------
#
# Porkbun's URL Forwarding pins a domain to Porkbun nameservers regardless of
# the stored NS value, so an apex with forwarding active silently no-ops an
# NS cutover (the mdburst.com false-green root cause). lamill reads it as the
# real cutover blocker and clears it only on explicit `--clear-forwarding`.
#
# Endpoints:
#   - POST /domain/getUrlForwarding/<domain>           → list active forwards
#   - POST /domain/deleteUrlForward/<domain>/<record_id> → remove one forward


@dataclass
class UrlForward:
    """One Porkbun URL-forwarding record. `subdomain` is "" for the apex."""
    id: str
    subdomain: str
    location: str
    type: str  # "temporary" | "permanent"

    @property
    def is_apex(self) -> bool:
        return self.subdomain.strip() == ""


def _post_porkbun(path: str, *, api_key: str, secret: str, what: str) -> dict:
    """Shared POST + envelope-validation for the URL-forwarding endpoints.
    Mirrors `get_porkbun_ns`'s error handling (HTTP, JSON, SUCCESS, the
    per-domain API-access toggle). Returns the parsed body dict."""
    if not api_key or not secret:
        raise PorkbunDnsError(
            "missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY"
        )
    try:
        r = httpx.post(
            f"{PORKBUN_API}/{path}",
            json={"apikey": api_key, "secretapikey": secret},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise PorkbunDnsError(
            f"network error calling {what}: {type(e).__name__}: {e}"
        ) from e
    if r.status_code != 200:
        raise PorkbunDnsError(f"{what} → HTTP {r.status_code}: {r.text[:200]}")
    try:
        body = r.json()
    except ValueError as e:
        raise PorkbunDnsError(f"{what} returned non-JSON: {e}") from e
    if not isinstance(body, dict) or body.get("status") != "SUCCESS":
        if isinstance(body, dict) and _api_access_off(body):
            raise PorkbunApiAccessError(
                f"per-domain API access is OFF for {what}"
            )
        raise PorkbunDnsError(f"{what} status != SUCCESS: {body}")
    return body


def get_porkbun_url_forwarding(
    domain: str, *, api_key: str, secret: str,
) -> list[UrlForward]:
    """List active URL forwards for `domain`. Empty list = none configured.
    Raises `PorkbunDnsError` (or `PorkbunApiAccessError`) on failure."""
    body = _post_porkbun(
        f"domain/getUrlForwarding/{domain}",
        api_key=api_key, secret=secret, what=f"getUrlForwarding/{domain}",
    )
    raw = body.get("forwards") or []
    if not isinstance(raw, list):
        raise PorkbunDnsError(
            f"getUrlForwarding/{domain} body.forwards is not a list: "
            f"{type(raw).__name__}"
        )
    out: list[UrlForward] = []
    for f in raw:
        if not isinstance(f, dict):
            continue
        out.append(UrlForward(
            id=str(f.get("id", "")),
            subdomain=str(f.get("subdomain", "") or ""),
            location=str(f.get("location", "") or ""),
            type=str(f.get("type", "") or ""),
        ))
    return out


def delete_porkbun_url_forward(
    domain: str, record_id: str, *, api_key: str, secret: str,
) -> None:
    """Delete one URL-forwarding record by id. Raises `PorkbunDnsError`
    (or `PorkbunApiAccessError`) on failure."""
    if not record_id:
        raise PorkbunDnsError(
            f"refusing to delete URL forward with empty id for {domain}"
        )
    _post_porkbun(
        f"domain/deleteUrlForward/{domain}/{record_id}",
        api_key=api_key, secret=secret,
        what=f"deleteUrlForward/{domain}/{record_id}",
    )
