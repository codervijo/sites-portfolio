from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAINS_CSV = ROOT / "domains.csv"
PLAN_MD = ROOT / "plan.md"


@dataclass
class Domain:
    name: str
    tld: str
    created: date | None
    expires: date | None
    status: str
    renewal_price: float | None
    estimated_value: float | None
    listing_status: str
    auto_renew: str
    nameservers: str
    forwarding_url: str

    @property
    def days_to_expire(self) -> int | None:
        if self.expires is None:
            return None
        return (self.expires - date.today()).days


def _money(s: str) -> float | None:
    s = (s or "").strip().replace("$", "").replace(",", "").strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _date(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def load_domains(path: Path | None = None) -> list[Domain]:
    path = path or DOMAINS_CSV
    out: list[Domain] = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            out.append(
                Domain(
                    name=r["Domain Name"].strip().lower(),
                    tld=r.get("TLD", "").strip(),
                    created=_date(r.get("Create Date", "")),
                    expires=_date(r.get("Expiration Date", "")),
                    status=r.get("Status", "").strip(),
                    renewal_price=_money(r.get("Renewal Price", "")),
                    estimated_value=_money(r.get("Estimated Value", "")),
                    listing_status=r.get("ListingStatus", "").strip(),
                    auto_renew=r.get("Auto-renew", "").strip(),
                    nameservers=r.get("Nameservers", "").strip(),
                    forwarding_url=r.get("Forwarding URL", "").strip(),
                )
            )
    return out


def load_plan(path: Path | None = None) -> dict[str, str]:
    """Map lowercase domain name -> plan category from plan.md."""
    path = path or PLAN_MD
    mapping: dict[str, str] = {}
    current: str | None = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line.startswith("### "):
            current = line[4:].strip()
            if "(" in current:
                current = current.split("(")[0].strip()
        elif line.startswith("#") or not line:
            continue
        elif current and "." in line and " " not in line:
            mapping[line.lower()] = current
    return mapping
