"""v15.F — Porkbun `domain/listAll` API → CSV converter.

Lets `lamill fleet sync --refresh` pull the operator's owned-domain
inventory directly from Porkbun's API and write it to
`data/domains/porkbun.csv` (replacing the manually-exported file).
The existing CSV-merging pipeline (`run_cleanup`) then consumes the
fresh CSV exactly like the manual export.

GoDaddy + Namecheap are deferred (their account-side APIs require
additional setup the operator hasn't done yet). Calls there land
when those CSVs need account-driven refresh.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import httpx

PORKBUN_LIST_ALL_URL = "https://api.porkbun.com/api/json/v3/domain/listAll"
PORKBUN_HTTP_TIMEOUT = 15.0  # listAll is heavier than ping; allow more time

# CSV column order used by `data._load_porkbun()`. Keep this stable
# unless that loader changes — the merged `data/portfolio.json` field
# shape depends on these column names.
_CSV_HEADERS = [
    "DOMAIN",
    "TLD",
    "STATUSES",
    "CREATE DATE",
    "EXPIRE DATE",
    "AUTO RENEW",
    "EST. RENEWAL PRICE",
    "NAMESERVERS",
    "URL FORWARDS",
    "PRIVACY",
    "LOCKED",
]


class PorkbunListError(RuntimeError):
    """Wraps every failure mode of the `domain/listAll` call —
    network error, non-200 HTTP, non-SUCCESS status, missing fields."""


@dataclass(frozen=True)
class _PorkbunDomain:
    """Subset of the listAll response fields we serialize to CSV."""
    domain: str
    tld: str
    status: str
    create_date: str
    expire_date: str
    auto_renew: bool
    nameservers: list[str]
    security_lock: bool
    whois_privacy: bool


def fetch_porkbun_domains(api_key: str, secret: str) -> list[_PorkbunDomain]:
    """Call `domain/listAll` and return a typed list. Raises
    `PorkbunListError` on any failure. No retries; the caller drives
    retry policy if needed."""
    if not api_key or not secret:
        raise PorkbunListError("missing PORKBUN_API_KEY or PORKBUN_SECRET_API_KEY")

    try:
        response = httpx.post(
            PORKBUN_LIST_ALL_URL,
            json={"apikey": api_key, "secretapikey": secret},
            timeout=PORKBUN_HTTP_TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise PorkbunListError(
            f"network error calling Porkbun listAll: {type(e).__name__}: {e}"
        ) from e

    if response.status_code != 200:
        raise PorkbunListError(
            f"Porkbun listAll returned HTTP {response.status_code}"
        )

    try:
        body = response.json()
    except ValueError as e:
        raise PorkbunListError(
            f"Porkbun listAll returned non-JSON body: {e}"
        ) from e

    if not isinstance(body, dict) or body.get("status") != "SUCCESS":
        raise PorkbunListError(
            f"Porkbun listAll status != SUCCESS: {body}"
        )

    domains_raw = body.get("domains")
    if not isinstance(domains_raw, list):
        raise PorkbunListError(
            f"Porkbun listAll body.domains is not a list: {type(domains_raw).__name__}"
        )

    out: list[_PorkbunDomain] = []
    for entry in domains_raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("domain", "")).strip().lower()
        if not name:
            continue
        out.append(
            _PorkbunDomain(
                domain=name,
                tld=str(entry.get("tld", "")).strip(),
                status=str(entry.get("status", "")).strip(),
                create_date=str(entry.get("createDate", "")).strip(),
                expire_date=str(entry.get("expireDate", "")).strip(),
                auto_renew=str(entry.get("autoRenew", "")).strip() == "1",
                nameservers=_split_nameservers(entry.get("ns", "")),
                security_lock=str(entry.get("securityLock", "")).strip() == "1",
                whois_privacy=str(entry.get("whoisPrivacy", "")).strip() == "1",
            )
        )
    return out


def write_porkbun_csv(rows: list[_PorkbunDomain], out_path: Path) -> None:
    """Serialize fetched rows to the column shape `data._load_porkbun`
    expects. Overwrites `out_path` atomically (tmpfile + rename)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_CSV_HEADERS)
        for r in rows:
            writer.writerow([
                r.domain,
                r.tld,
                r.status,
                r.create_date,
                r.expire_date,
                "ON" if r.auto_renew else "OFF",
                "",  # EST. RENEWAL PRICE — listAll doesn't return pricing
                " | ".join(r.nameservers),
                "",  # URL FORWARDS — separate API endpoint; not in scope here
                "Yes" if r.whois_privacy else "No",
                "Yes" if r.security_lock else "No",
            ])
    tmp.replace(out_path)


def refresh_porkbun_csv(api_key: str, secret: str, out_path: Path) -> int:
    """Convenience — fetch + write, return the row count.

    Raises `PorkbunListError` on any failure."""
    rows = fetch_porkbun_domains(api_key, secret)
    write_porkbun_csv(rows, out_path)
    return len(rows)


def _split_nameservers(raw) -> list[str]:
    """Porkbun's `ns` field may be a list or a comma-string. Normalize
    both to a list of lowercased nameservers (sorted)."""
    if isinstance(raw, list):
        items = [str(x).strip().lower() for x in raw if x]
    elif isinstance(raw, str):
        items = [s.strip().lower() for s in raw.split(",") if s.strip()]
    else:
        items = []
    return sorted(items)
