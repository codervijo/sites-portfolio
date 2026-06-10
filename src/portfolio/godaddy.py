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

import csv
from pathlib import Path

import httpx

from . import _httpapi

API_BASE = "https://api.godaddy.com"
_TIMEOUT = 15.0
_PAGE_LIMIT = 100


class GoDaddyError(_httpapi.HttpApiError):
    """A GoDaddy API call failed (auth / bad-request / unexpected status).
    Permanent by default; a 429 rate-limit raises `GoDaddyTransientError`."""


class GoDaddyTransientError(GoDaddyError, _httpapi.TransientHTTPError):
    """A retryable GoDaddy failure (429 rate-limit). Subclasses `GoDaddyError`
    so existing `except GoDaddyError` handlers still catch it; the taxonomy
    lets callers report `↷` + re-run (ADR-0015)."""


def _build_client(api_key: str, secret: str) -> httpx.Client:
    """Build an httpx.Client bound to the GoDaddy API. Lifecycle (close iff
    owned) is handled by `_httpapi.managed_client` at the call site."""
    return httpx.Client(
        base_url=API_BASE,
        headers={"Authorization": f"sso-key {api_key}:{secret}",
                 "Accept": "application/json"},
        timeout=_TIMEOUT,
    )


def _raise_for(resp: httpx.Response, what: str) -> None:
    """Typed non-2xx → permanent `GoDaddyError`, except 429 → transient."""
    if resp.status_code in (401, 403):
        raise GoDaddyError(
            f"{what}: {resp.status_code} — check GODADDY_API_KEY / "
            f"GODADDY_API_SECRET (production keys need 1+ domains; OTE/test "
            f"keys don't work against api.godaddy.com)"
        )
    if resp.status_code == 429:
        raise GoDaddyTransientError(f"{what}: 429 rate-limited — retry later")
    if resp.status_code >= 400:
        raise GoDaddyError(f"{what}: HTTP {resp.status_code} {resp.text[:200]}")


def list_domains(*, api_key: str, secret: str,
                 client: httpx.Client | None = None,
                 page_limit: int = _PAGE_LIMIT) -> list[dict]:
    """All owned domains (summary records) via GET /v1/domains, marker-
    paginated. Each record carries at least `domain`, `status`, `expires`,
    `renewAuto`."""
    with _httpapi.managed_client(
        client, lambda: _build_client(api_key, secret)
    ) as c:
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


def get_domain(domain: str, *, api_key: str, secret: str,
               client: httpx.Client | None = None) -> dict:
    """Detail record for one domain via GET /v1/domains/{domain}
    (`expires`, `status`, `nameServers`, `renewAuto`, …)."""
    with _httpapi.managed_client(
        client, lambda: _build_client(api_key, secret)
    ) as c:
        r = c.get(f"/v1/domains/{domain}")
        _raise_for(r, f"get domain {domain}")
        return r.json()


# ---- nameservers: get / set (v31.C — `new deploy` Step 4) ------------


def get_nameservers(domain: str, *, api_key: str, secret: str,
                    client: httpx.Client | None = None) -> list[str]:
    """Current nameservers for `domain` (sorted, lowercased; empty if none).
    Reuses `get_domain`. Raises `GoDaddyError` on failure."""
    ns = get_domain(domain, api_key=api_key, secret=secret,
                    client=client).get("nameServers") or []
    if not isinstance(ns, list):
        raise GoDaddyError(
            f"get nameservers {domain}: nameServers is not a list "
            f"({type(ns).__name__})"
        )
    return sorted({str(n).strip().lower() for n in ns if n})


def set_nameservers(domain: str, *, api_key: str, secret: str,
                    ns_list: list[str],
                    client: httpx.Client | None = None) -> None:
    """Set nameservers for `domain` via PATCH /v1/domains/{domain}. Does NOT
    pre-check — callers GET-then-compare to skip no-op updates (the ADR-0015
    idempotency invariant). Refuses an empty list. Raises `GoDaddyError` on
    failure. GoDaddy returns 200 with an empty body on success.

    GoDaddy's domain resource exposes **PATCH** (not PUT) for updates — the
    `nameServers` field rides in the DomainUpdate body. An earlier PUT 404'd
    ("resource not found") because GoDaddy never registers PUT on this path,
    even though GET on the same path succeeds — so the read worked while the
    write silently failed on every GoDaddy domain.
    """
    if not ns_list:
        raise GoDaddyError(f"refusing to set NS to empty list for {domain}")
    with _httpapi.managed_client(
        client, lambda: _build_client(api_key, secret)
    ) as c:
        r = c.patch(f"/v1/domains/{domain}", json={"nameServers": list(ns_list)})
        _raise_for(r, f"set nameservers {domain}")


# ---- inventory refresh → data/domains/godaddy.csv (v31.B) ------------

# Header used only when no godaddy.csv exists yet (a fresh write). A merge
# preserves the manual export's full header + its non-API columns.
_MIN_HEADER = [
    "Domain Name", "TLD", "Create Date", "Expiration Date", "Status",
    "Renewal Price", "Estimated Value", "ListingStatus", "Auto-renew",
    "Nameservers", "Forwarding URL", "Privacy", "Lock",
]


# GoDaddy returns the account's *whole* history — including domains
# cancelled/expired years ago. Only currently-owned-and-live domains belong
# in the inventory; the rest would bloat godaddy.csv with dead rows.
_OWNED_STATUSES = frozenset({"ACTIVE"})


def fetch_inventory(api_key: str, secret: str, *,
                    client: httpx.Client | None = None,
                    active_only: bool = True) -> list[dict]:
    """Live GoDaddy inventory: per domain
    `{domain, status, expires, renewAuto, nameServers}`. Uses `list_domains`
    for the summary, falling back to `get_domain` for nameServers when the
    summary omits them. `active_only` (default) drops cancelled/expired
    domains — the account carries years of dead ones."""
    with _httpapi.managed_client(
        client, lambda: _build_client(api_key, secret)
    ) as c:
        out: list[dict] = []
        for s in list_domains(api_key=api_key, secret=secret, client=c):
            dom = (s.get("domain") or "").strip()
            if not dom:
                continue
            status = (s.get("status") or "").upper()
            if active_only and status not in _OWNED_STATUSES:
                continue
            ns = s.get("nameServers")
            if not ns:
                try:
                    ns = get_domain(dom, api_key=api_key, secret=secret,
                                    client=c).get("nameServers")
                except GoDaddyError:
                    ns = None
            out.append({
                "domain": dom,
                "status": s.get("status", ""),
                "expires": s.get("expires", ""),
                "renewAuto": s.get("renewAuto"),
                "nameServers": ns or [],
            })
        return out


def _apply_api_fields(row: dict, d: dict) -> None:
    """Overwrite a CSV row's staleness-prone columns from an API record;
    everything else (renewal price, estimated value, …) is left untouched."""
    exp = (d.get("expires") or "")[:10]
    if exp:
        row["Expiration Date"] = exp
    if d.get("status"):
        row["Status"] = str(d["status"]).title()
    row["Auto-renew"] = "On" if d.get("renewAuto") else "Off"
    ns = d.get("nameServers") or []
    if ns:
        row["Nameservers"] = " ".join(ns)


def refresh_godaddy_csv(api_key: str, secret: str, out_path: Path, *,
                        client: httpx.Client | None = None) -> int:
    """Merge-refresh `out_path` from the live API: update each domain's
    Expiration Date / Status / Auto-renew / Nameservers, **preserving** the
    manual export's other columns; add domains new at GoDaddy; drop ones
    removed there. Returns the row count written."""
    inv = fetch_inventory(api_key, secret, client=client)
    by_domain = {d["domain"].lower(): d for d in inv if d.get("domain")}

    fieldnames = list(_MIN_HEADER)
    existing: dict[str, dict] = {}
    if out_path.is_file():
        with out_path.open(newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                fieldnames = reader.fieldnames
            for r in reader:
                dom = (r.get("Domain Name") or "").strip().lower()
                if dom:
                    existing[dom] = r

    rows_out: list[dict] = []
    # Existing domains still present at GoDaddy — update in place (CSV order).
    for dom, row in existing.items():
        if dom in by_domain:
            _apply_api_fields(row, by_domain[dom])
            rows_out.append(row)
        # else: removed at GoDaddy → dropped
    # Domains new at GoDaddy → fresh rows.
    for dom, d in by_domain.items():
        if dom not in existing:
            row = {fn: "" for fn in fieldnames}
            row["Domain Name"] = d["domain"]
            if "." in d["domain"]:
                row["TLD"] = "." + d["domain"].split(".", 1)[1]
            _apply_api_fields(row, d)
            rows_out.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows_out)
    return len(rows_out)
