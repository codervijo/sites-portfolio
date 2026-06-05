"""v31.A — GoDaddy Management API client (httpx-direct).

GoDaddy's Management + DNS APIs are available to accounts with 1+ domains
(only the *Availability*/search API needs 50+), so the operator's GoDaddy
portfolio qualifies. We use list + per-domain detail only — buying-side stays
on Porkbun, so the 50-domain Availability gate never applies.

Auth is the `sso-key <KEY>:<SECRET>` header against `https://api.godaddy.com`.
Mirrors the httpx-direct + `MockTransport` pattern of `cloudflare.py` /
`gh_repo.py`. See ADR-0021.
"""
from __future__ import annotations

import httpx

API_BASE = "https://api.godaddy.com"
_TIMEOUT = 15.0
_PAGE_LIMIT = 100


class GoDaddyError(RuntimeError):
    """A GoDaddy API call failed (auth / rate-limit / unexpected status)."""


def _client(api_key: str, secret: str,
            client: httpx.Client | None) -> tuple[httpx.Client, bool]:
    """(client, owned) — reuse a caller-supplied client (tests) or build one."""
    if client is not None:
        return client, False
    return (
        httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"sso-key {api_key}:{secret}",
                     "Accept": "application/json"},
            timeout=_TIMEOUT,
        ),
        True,
    )


def _raise_for(resp: httpx.Response, what: str) -> None:
    if resp.status_code in (401, 403):
        raise GoDaddyError(
            f"{what}: {resp.status_code} — check GODADDY_API_KEY / "
            f"GODADDY_API_SECRET (production keys need 1+ domains; OTE/test "
            f"keys don't work against api.godaddy.com)"
        )
    if resp.status_code == 429:
        raise GoDaddyError(f"{what}: 429 rate-limited — retry later")
    if resp.status_code >= 400:
        raise GoDaddyError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}")


def list_domains(*, api_key: str, secret: str,
                 client: httpx.Client | None = None,
                 page_limit: int = _PAGE_LIMIT) -> list[dict]:
    """All owned domains (summary records) via GET /v1/domains, marker-
    paginated. Each record carries at least `domain`, `status`, `expires`,
    `renewAuto`."""
    c, own = _client(api_key, secret, client)
    try:
        out: list[dict] = []
        marker: str | None = None
        while True:
            params: dict = {"limit": page_limit}
            if marker:
                params["marker"] = marker
            r = c.get("/v1/domains", params=params)
            _raise_for(r, "list domains")
            page = r.json()
            if not isinstance(page, list) or not page:
                break
            out.extend(page)
            if len(page) < page_limit:
                break
            marker = page[-1].get("domain")
            if not marker:
                break
        return out
    finally:
        if own:
            c.close()


def get_domain(domain: str, *, api_key: str, secret: str,
               client: httpx.Client | None = None) -> dict:
    """Detail record for one domain via GET /v1/domains/{domain}
    (`expires`, `status`, `nameServers`, `renewAuto`, …)."""
    c, own = _client(api_key, secret, client)
    try:
        r = c.get(f"/v1/domains/{domain}")
        _raise_for(r, f"get domain {domain}")
        return r.json()
    finally:
        if own:
            c.close()
