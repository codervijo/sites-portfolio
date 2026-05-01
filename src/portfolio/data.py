from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAINS_DIR = ROOT / "data" / "domains"
PLAN_MD = ROOT / "plan.md"

REGISTRAR_GODADDY = "godaddy"
REGISTRAR_NAMECHEAP = "namecheap"
REGISTRAR_PORKBUN = "porkbun"


@dataclass
class Domain:
    name: str
    registrar: str
    tld: str
    expires: date | None
    auto_renew: str
    status: str
    created: date | None = None
    renewal_price: float | None = None
    estimated_value: float | None = None
    listing_status: str = ""
    nameservers: str = ""
    forwarding_url: str = ""
    privacy: bool | None = None
    transfer_locked: bool | None = None

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


def _date_iso(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _date_namecheap(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%b %d %Y").date()
    except ValueError:
        return None


def _date_porkbun(s: str) -> date | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").date()
    except ValueError:
        return None


def _bool_yesno(s: str) -> bool | None:
    s = (s or "").strip().lower()
    if s in ("yes", "on", "true", "1"):
        return True
    if s in ("no", "off", "false", "0"):
        return False
    return None


def _norm_onoff(s: str) -> str:
    """Normalize auto-renew/privacy strings to canonical "On"/"Off" (back-compat with existing cli.py)."""
    b = _bool_yesno(s)
    if b is True:
        return "On"
    if b is False:
        return "Off"
    return ""


def _load_godaddy(path: Path) -> list[Domain]:
    out: list[Domain] = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            out.append(
                Domain(
                    name=r["Domain Name"].strip().lower(),
                    registrar=REGISTRAR_GODADDY,
                    tld=r.get("TLD", "").strip(),
                    created=_date_iso(r.get("Create Date", "")),
                    expires=_date_iso(r.get("Expiration Date", "")),
                    status=r.get("Status", "").strip(),
                    renewal_price=_money(r.get("Renewal Price", "")),
                    estimated_value=_money(r.get("Estimated Value", "")),
                    listing_status=r.get("ListingStatus", "").strip(),
                    auto_renew=_norm_onoff(r.get("Auto-renew", "")),
                    nameservers=r.get("Nameservers", "").strip(),
                    forwarding_url=r.get("Forwarding URL", "").strip(),
                    privacy=_bool_yesno(r.get("Privacy", "")),
                    transfer_locked=(r.get("Lock", "").strip().lower() == "locked") if r.get("Lock") else None,
                )
            )
    return out


def _load_namecheap(path: Path) -> list[Domain]:
    out: list[Domain] = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            name = (r.get("Domain Name") or "").strip().lower()
            if not name:
                continue
            tld = "." + name.rsplit(".", 1)[-1] if "." in name else ""
            out.append(
                Domain(
                    name=name,
                    registrar=REGISTRAR_NAMECHEAP,
                    tld=tld,
                    expires=_date_namecheap(r.get("Domain expiration date", "")),
                    auto_renew=_norm_onoff(r.get("Domain auto-renew status", "")),
                    status=(r.get("Domain status at NC") or "").strip(),
                    privacy=_bool_yesno(r.get("Domain privacy protection status", "")),
                )
            )
    return out


def _load_porkbun(path: Path) -> list[Domain]:
    out: list[Domain] = []
    with path.open(newline="") as f:
        first = f.readline()
        if first.startswith("Please note") or "renewal prices" in first.lower():
            pass
        else:
            f.seek(0)
        reader = csv.DictReader(f)
        for r in reader:
            name = (r.get("DOMAIN") or "").strip().lower()
            if not name:
                continue
            tld_raw = (r.get("TLD") or "").strip().lstrip(".")
            tld = "." + tld_raw if tld_raw else ""
            statuses_raw = (r.get("STATUSES") or "").strip()
            status = "Active" if statuses_raw else ""
            out.append(
                Domain(
                    name=name,
                    registrar=REGISTRAR_PORKBUN,
                    tld=tld,
                    created=_date_porkbun(r.get("CREATE DATE", "")),
                    expires=_date_porkbun(r.get("EXPIRE DATE", "")),
                    auto_renew=_norm_onoff(r.get("AUTO RENEW", "")),
                    status=status,
                    renewal_price=_money(r.get("EST. RENEWAL PRICE", "")),
                    nameservers=(r.get("NAMESERVERS") or "").replace("|", " ").strip(),
                    forwarding_url=(r.get("URL FORWARDS") or "").strip(),
                    privacy=_bool_yesno(r.get("PRIVACY", "")),
                    transfer_locked=_bool_yesno(r.get("LOCKED", "")),
                )
            )
    return out


def load_domains(path: Path | None = None) -> list[Domain]:
    """Load and merge domains from all per-registrar CSVs in data/domains/.

    The legacy `path` arg is accepted for back-compat but ignored — multi-registrar
    layout always reads from DOMAINS_DIR.
    """
    out: list[Domain] = []
    godaddy = DOMAINS_DIR / "godaddy.csv"
    namecheap = DOMAINS_DIR / "namecheap.csv"
    porkbun = DOMAINS_DIR / "porkbun.csv"
    if godaddy.exists():
        out.extend(_load_godaddy(godaddy))
    if namecheap.exists():
        out.extend(_load_namecheap(namecheap))
    if porkbun.exists():
        out.extend(_load_porkbun(porkbun))
    return out


def domain_to_registrar() -> dict[str, str]:
    """Map of domain name -> registrar, for cross-feature dispatch (no API calls wasted)."""
    return {d.name: d.registrar for d in load_domains()}


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
