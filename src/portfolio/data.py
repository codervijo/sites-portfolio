from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAINS_DIR = ROOT / "data" / "domains"
PORTFOLIO_JSON = ROOT / "data" / "portfolio.json"
PLAN_MD = ROOT / "plan.md"

REGISTRAR_GODADDY = "godaddy"
REGISTRAR_NAMECHEAP = "namecheap"
REGISTRAR_PORKBUN = "porkbun"

PORTFOLIO_SCHEMA_VERSION = 1


@dataclass
class Domain:
    name: str
    registrar: str
    tld: str
    expires: date | None
    auto_renew: str
    status: str
    category: str | None = None
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


def _load_from_registrars() -> list[Domain]:
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


def _load_legacy_plan_md(path: Path | None = None) -> dict[str, str]:
    """Parse plan.md categorized lists. Used only during cleanup bootstrap; deprecated post-v1.D."""
    path = path or PLAN_MD
    mapping: dict[str, str] = {}
    current: str | None = None
    if not path.exists():
        return mapping
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


def _apply_classification(domains: list[Domain], plan: dict[str, str]) -> tuple[list[Domain], list[str]]:
    """Apply classification rules and return (domains_with_category, uncategorized_names)."""
    uncategorized: list[str] = []
    for d in domains:
        if d.registrar in (REGISTRAR_NAMECHEAP, REGISTRAR_PORKBUN):
            d.category = "Under build"
        elif d.name in plan:
            d.category = plan[d.name]
        else:
            d.category = None
            uncategorized.append(d.name)
    return domains, uncategorized


def _domain_to_jsonable(d: Domain) -> dict:
    raw = asdict(d)
    for k in ("expires", "created"):
        if raw[k] is not None:
            raw[k] = raw[k].isoformat()
    return raw


def _domain_from_jsonable(r: dict) -> Domain:
    def _d(v: str | None) -> date | None:
        if not v:
            return None
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return Domain(
        name=r["name"],
        registrar=r["registrar"],
        tld=r.get("tld", ""),
        expires=_d(r.get("expires")),
        auto_renew=r.get("auto_renew", ""),
        status=r.get("status", ""),
        category=r.get("category"),
        created=_d(r.get("created")),
        renewal_price=r.get("renewal_price"),
        estimated_value=r.get("estimated_value"),
        listing_status=r.get("listing_status", ""),
        nameservers=r.get("nameservers", ""),
        forwarding_url=r.get("forwarding_url", ""),
        privacy=r.get("privacy"),
        transfer_locked=r.get("transfer_locked"),
    )


def cleanup() -> tuple[Path, list[Domain], list[str]]:
    """Run full pipeline: registrar CSVs + plan.md → data/portfolio.json. Returns (path, domains, uncategorized)."""
    domains = _load_from_registrars()
    plan = _load_legacy_plan_md()
    domains, uncategorized = _apply_classification(domains, plan)

    PORTFOLIO_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": PORTFOLIO_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "domains": [_domain_to_jsonable(d) for d in sorted(domains, key=lambda x: x.name)],
    }
    PORTFOLIO_JSON.write_text(json.dumps(payload, indent=2) + "\n")
    return PORTFOLIO_JSON, domains, uncategorized


def load_domains(path: Path | None = None) -> list[Domain]:
    """Load domains. Prefers data/portfolio.json (canonical post-v1.D); falls back to a
    bootstrap from raw registrar CSVs + plan.md when portfolio.json is absent.
    The legacy `path` arg is accepted but ignored — multi-registrar layout is fixed.
    """
    if PORTFOLIO_JSON.exists():
        try:
            payload = json.loads(PORTFOLIO_JSON.read_text())
            return [_domain_from_jsonable(r) for r in payload.get("domains", [])]
        except (json.JSONDecodeError, OSError):
            pass
    domains = _load_from_registrars()
    plan = _load_legacy_plan_md()
    domains, _ = _apply_classification(domains, plan)
    return domains


def domain_to_registrar() -> dict[str, str]:
    """Map of domain name -> registrar, for cross-feature dispatch (no API calls wasted)."""
    return {d.name: d.registrar for d in load_domains()}


def load_plan(path: Path | None = None) -> dict[str, str]:
    """Map of domain -> category. Sourced from `domain.category` (was plan.md)."""
    return {d.name: d.category for d in load_domains() if d.category}
