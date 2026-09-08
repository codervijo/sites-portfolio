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
# v45.D — client-owned domains carry no operator registrar credential,
# so registrar truth is unavailable for them.
REGISTRAR_OTHER = "other"

# v45.B — `owner` sentinel for the operator's own sites. Any other
# value names an agency client. Absent/blank normalizes to this, so no
# migration is needed and no consumer can trip over a missing field.
OWNER_SELF = "lamill"

# v45.D — the fourth sync source. Operator-authored roster of
# client-owned domains (`domain,owner,category`); hand-edited, or
# appended by `new bootstrap --owner`. Client domains appear in no
# registrar CSV, and `cleanup()` deletes anything absent from a
# source — so they are made a source rather than a preserve-exception.
CLIENTS_CSV = DOMAINS_DIR / "clients.csv"

# v45.B — bumped for the `owner` field. Nothing reads this value today
# (it is written for the record); the field itself is backward-
# compatible in both directions, so the bump is documentary.
PORTFOLIO_SCHEMA_VERSION = 2


def normalize_owner(value: str | None) -> str:
    """v45.B — coerce any owner value to a usable string.

    Blank, whitespace-only, `None`, or a non-string all normalize to
    `OWNER_SELF`. **Never raises** — a missing or malformed `owner`
    must never fail or crash a CLI, so every read path funnels through
    here rather than touching the raw value.
    """
    if not isinstance(value, str):
        return OWNER_SELF
    return value.strip() or OWNER_SELF


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
    # v45.B — who owns the *domain*. `OWNER_SELF` ("lamill") = one of
    # the operator's own sites; any other string names an agency client
    # whose site the operator builds/deploys/hosts but whose domain
    # they don't hold. Defaults to self, so every pre-v45 row and every
    # registrar-CSV row is correctly self-owned without a migration.
    owner: str = OWNER_SELF

    @property
    def days_to_expire(self) -> int | None:
        if self.expires is None:
            return None
        return (self.expires - date.today()).days

    @property
    def is_client(self) -> bool:
        """v45.B — True when this domain belongs to an agency client
        rather than to the operator. Tolerates a blank/missing owner
        (reads as self-owned)."""
        return normalize_owner(self.owner) != OWNER_SELF

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


def _load_clients(path: Path | None = None) -> list[Domain]:
    """v45.D — load the client-domain roster (`data/domains/clients.csv`).

    The fourth sync source. Unlike the three registrar CSVs this one is
    operator-authored, not an API/dashboard export: the operator *is*
    the source of truth for who their clients are. Columns:

        domain,owner,category

    `domain` (alias: `name`) is the only required column. A blank or
    missing `owner` normalizes to `OWNER_SELF` rather than erroring —
    a malformed roster must never crash a CLI. `category` is optional.

    Everything else stays *derived*, never stored here: `registrar` is
    `REGISTRAR_OTHER` (the operator holds no registrar credential for a
    client's account), `expires`/`domain_created` come from RDAP, and
    `launched` from first-commit inference. Keeping derived truth out
    of the roster is what keeps the file readable at a glance.

    Returns `[]` for an absent, unreadable, or malformed file — this is
    a best-effort read by design.
    """
    path = path or CLIENTS_CSV
    if not path.exists():
        return []
    out: list[Domain] = []
    try:
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            for r in reader:
                if not r:
                    continue
                raw = r.get("domain") or r.get("name") or ""
                name = raw.strip().lower()
                if not name or name.startswith("#"):
                    continue
                category = (r.get("category") or "").strip() or None
                tld = "." + name.rsplit(".", 1)[-1] if "." in name else ""
                out.append(
                    Domain(
                        name=name,
                        registrar=REGISTRAR_OTHER,
                        tld=tld,
                        expires=None,
                        auto_renew="",
                        status="Active",
                        category=category,
                        owner=normalize_owner(r.get("owner")),
                    )
                )
    except (OSError, csv.Error, UnicodeDecodeError):
        return []
    return out


def _merge_clients(domains: list[Domain], clients: list[Domain]) -> list[Domain]:
    """v45.D — fold the client roster into the registrar-derived rows.

    A roster entry for a domain that is *also* in an operator registrar
    CSV isn't an error: it's the operator having registered a domain on
    a client's behalf. In that case the registrar row wins on every
    registrar-truth field (it has API truth) and the roster contributes
    only `owner` — plus `category` when the registrar row has none.
    Otherwise the roster row is appended as a new domain.
    """
    by_name = {d.name: d for d in domains}
    for c in clients:
        existing = by_name.get(c.name)
        if existing is None:
            domains.append(c)
            by_name[c.name] = c
            continue
        existing.owner = c.owner
        if c.category and not existing.category:
            existing.category = c.category
    return domains


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
    # v45.D — fourth source. Merged last so an operator-registered
    # client domain keeps its registrar truth and gains only `owner`.
    return _merge_clients(out, _load_clients())


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
        # v45.D — a category supplied by a source (clients.csv) is
        # already authoritative; don't re-derive or blank it.
        if d.category:
            continue
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
        # v45.B — absent/blank → OWNER_SELF. Every pre-v45
        # portfolio.json parses unchanged; no migration.
        owner=normalize_owner(r.get("owner")),
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


def append_client_row(
    *,
    name: str,
    owner: str,
    category: str | None = None,
    path: Path | None = None,
) -> str:
    """v45.D — append a row to `data/domains/clients.csv`, the client
    roster. Idempotent; creates the file (with header) when absent.

    This is the write half of the fourth sync source, and the reason
    `new bootstrap --owner` does NOT reuse `append_domain_row`: that
    one writes straight into `portfolio.json`, and `cleanup()` deletes
    any row not backed by a source on the next `fleet sync`. Writing
    the roster instead makes the row durable by construction.

    Only the operator-authored facts are written — `domain`, `owner`,
    `category`. Derived truth (registrar / expiry / RDAP dates /
    launch date) is never written back here.

    Returns:
      "added"   — new row appended
      "exists"  — a row for `name` is already present; no change
      "skipped" — `owner` normalizes to OWNER_SELF (not a client), or
                  `name` is blank; nothing written
    """
    path = path or CLIENTS_CSV
    name = (name or "").strip().lower()
    owner = normalize_owner(owner)
    if not name or owner == OWNER_SELF:
        return "skipped"

    header = ["domain", "owner", "category"]
    rows: list[dict] = []
    if path.exists():
        try:
            with path.open(newline="") as f:
                rows = [r for r in csv.DictReader(f) if r]
        except (OSError, csv.Error, UnicodeDecodeError):
            rows = []
        for r in rows:
            existing = (r.get("domain") or r.get("name") or "").strip().lower()
            if existing == name:
                return "exists"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "domain": (r.get("domain") or r.get("name") or "").strip().lower(),
                "owner": normalize_owner(r.get("owner")),
                "category": (r.get("category") or "").strip(),
            })
        writer.writerow({
            "domain": name, "owner": owner, "category": (category or "").strip(),
        })
    tmp.replace(path)
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
