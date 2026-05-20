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

import httpx

PORKBUN_API = "https://api.porkbun.com/api/json/v3"
HTTP_TIMEOUT = 15.0


class PorkbunDnsError(RuntimeError):
    """Any failure interacting with Porkbun's NS endpoints — missing
    creds, transport error, non-200 HTTP, non-SUCCESS status, shape
    surprise."""


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
        raise PorkbunDnsError(
            f"updateNs/{domain} status != SUCCESS: {body}"
        )


def ns_matches(current: list[str], target: list[str]) -> bool:
    """Case-insensitive set-equality. Order doesn't matter for NS
    sets (they're queried as a pool by DNS resolvers)."""
    return {n.strip().lower() for n in current} == {
        n.strip().lower() for n in target
    }
