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
    # When *this* site went live (manual set or auto-inferred from
    # first commit in sites/<domain>/). Distinct from `created`
    # (registrar-account date) and `domain_created` (global RDAP).
    launched: date | None = None
    # Global RDAP creation_date — when the domain was first registered
    # by *anyone*. Populated by `fleet sync --refresh-rdap`.
    domain_created: date | None = None

    @property
    def days_to_expire(self) -> int | None:
        if self.expires is None:
            return None
        return (self.expires - date.today()).days

    @property
    def site_age_days(self) -> int | None:
        if self.launched is None:
            return None
        return (date.today() - self.launched).days

    @property
    def domain_age_days(self) -> int | None:
        if self.domain_created is None:
            return None
        return (date.today() - self.domain_created).days


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
    for k in ("expires", "created", "launched", "domain_created"):
        if raw.get(k) is not None:
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
        launched=_d(r.get("launched")),
        domain_created=_d(r.get("domain_created")),
    )


def cleanup() -> tuple[Path, list[Domain], list[str]]:
    """Run full pipeline: registrar CSVs + plan.md → data/portfolio.json. Returns (path, domains, uncategorized).

    Preserves user-set metadata (`launched`, `domain_created`) across
    re-runs: CSV inputs don't carry these fields, so re-deriving from
    CSV alone would erase manual edits and RDAP refreshes. Read the
    existing portfolio.json first and copy them forward by domain
    name when present.
    """
    domains = _load_from_registrars()
    plan = _load_legacy_plan_md()
    domains, uncategorized = _apply_classification(domains, plan)

    preserved: dict[str, dict] = {}
    if PORTFOLIO_JSON.exists():
        try:
            old = json.loads(PORTFOLIO_JSON.read_text())
            for row in old.get("domains", []):
                name = row.get("name")
                if not name:
                    continue
                preserved[name] = {
                    "launched": row.get("launched"),
                    "domain_created": row.get("domain_created"),
                }
        except (json.JSONDecodeError, OSError):
            pass

    for d in domains:
        carry = preserved.get(d.name)
        if not carry:
            continue
        if carry.get("launched") and d.launched is None:
            try:
                d.launched = date.fromisoformat(carry["launched"])
            except ValueError:
                pass
        if carry.get("domain_created") and d.domain_created is None:
            try:
                d.domain_created = date.fromisoformat(carry["domain_created"])
            except ValueError:
                pass

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


def load_plan(path: Path | None = None) -> dict[str, str]:
    """Map of domain -> category. Sourced from `domain.category` (was plan.md)."""
    return {d.name: d.category for d in load_domains() if d.category}


def append_domain_row(
    *,
    name: str,
    registrar: str,
    registered: bool = True,
    today: date | None = None,
) -> str:
    """v9.C — append a domain row to `data/portfolio.json` for a freshly-
    bought / freshly-scaffolded domain. Atomic write, idempotent.

    Returns:
      "added"     — new row appended
      "exists"    — row for `name` already present; no change
      "no-file"   — portfolio.json doesn't exist (cold start; caller
                    runs `fleet sync` first)

    Conservative placeholders fill fields a future Porkbun-CSV refresh
    (or the `--sync-porkbun` API path TBD) will overwrite with
    authoritative numbers:

      created / domain_created → today UTC
      expires                  → today + 1 year (Porkbun's default
                                 registration term)
      auto_renew               → "On" (Porkbun's default)
      privacy                  → True (Porkbun's default for new regs)
      transfer_locked          → True (registrar's standard 60-day lock)
      renewal_price            → None (registrar-specific; CSV fills in)
      nameservers              → "" (cleanup pulls live)
      estimated_value          → None (operator decides later)

    `status` is "Active" when `registered=True`, else "Pending" — the
    Pending row reminds the operator the domain isn't bought yet, so
    `project check <name>` resolves but won't surface in live-domain
    rollups.
    """
    if not PORTFOLIO_JSON.exists():
        return "no-file"
    payload = json.loads(PORTFOLIO_JSON.read_text())
    existing = {row.get("name", "").lower() for row in payload.get("domains", [])}
    if name.lower() in existing:
        return "exists"

    today = today or date.today()
    expires = today.replace(year=today.year + 1)
    # Extract TLD from the domain — last dot-segment, prefixed with `.`
    # so it matches the existing portfolio.json convention (".xyz",
    # ".dev"). Handles ccTLDs by surfacing the eTLD-1 (e.g. ".uk" for
    # "newsite.co.uk") — accurate enough for the inventory; the
    # cleanup CSV refresh corrects in edge cases.
    tld = "." + name.rsplit(".", 1)[-1]

    row = {
        "name": name,
        "registrar": registrar,
        "tld": tld,
        "expires": expires.isoformat(),
        "auto_renew": "On",
        "status": "Active" if registered else "Pending",
        "category": "Under build",
        "created": today.isoformat(),
        "renewal_price": None,
        "estimated_value": None,
        "listing_status": "",
        "nameservers": "",
        "forwarding_url": "",
        "privacy": True,
        "transfer_locked": True,
        "launched": None,
        "domain_created": today.isoformat() if registered else None,
    }
    payload.setdefault("domains", []).append(row)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    if "total" in payload:
        payload["total"] = len(payload["domains"])

    tmp = PORTFOLIO_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(PORTFOLIO_JSON)
    return "added"


def update_domain_field(name: str, field_name: str, value) -> bool:
    """Set a single field on one domain's portfolio.json entry. Atomic.

    Used by `settings deploy set-launched` and the RDAP refresh path to mutate
    a single record without rebuilding from CSV. Returns True if the
    domain was found and updated. `value` should be a JSON-serializable
    primitive (date objects auto-ISO-format).
    """
    if not PORTFOLIO_JSON.exists():
        return False
    try:
        payload = json.loads(PORTFOLIO_JSON.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    if isinstance(value, date):
        value = value.isoformat()
    found = False
    for row in payload.get("domains", []):
        if row.get("name") == name:
            row[field_name] = value
            found = True
            break
    if not found:
        return False
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = PORTFOLIO_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(PORTFOLIO_JSON)
    return True
