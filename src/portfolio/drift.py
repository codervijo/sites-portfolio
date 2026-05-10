"""v6.A — Drift detection: cross-checks the four sources of truth
about domains and surfaces inconsistencies the catalog (per-project
checks) can't catch.

Sources covered:
  - data/portfolio.json                          (consolidated inventory)
  - data/domains/{godaddy,namecheap,porkbun}.csv (registrar exports)
  - sites/<domain>/                              (working repos)
  - data/checks/<latest>.json                    (live snapshot)
  - GSC properties                               (read-only, optional)

Six drift signals, all read-only. Pure data analysis — no CLI side
effects, no writes. The renderer is in cli.py (`info drift` subcommand).

Filtering: domains in the "To be deleted immediately" category are
excluded from `portfolio_no_dir` (no point flagging absence on
domains the user has retired).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .data import _load_from_registrars, load_domains


_DELETE_CATEGORY = "to be deleted immediately"


# ---------- per-signal record types ----------


@dataclass
class ExpiryDelta:
    domain: str
    registrar: str
    csv_expires: date | None
    json_expires: date | None


@dataclass
class DeployedFlagged:
    domain: str
    classification: str
    category: str   # the flag-for-deletion category (kept for context)


@dataclass
class DuplicateAcrossRegistrars:
    domain: str
    registrars: list[str]


@dataclass
class DriftReport:
    """One snapshot of drift across the four sources of truth."""
    portfolio_no_dir: list[str] = field(default_factory=list)
    csv_only: list[tuple[str, str]] = field(default_factory=list)
    expiry_mismatches: list[ExpiryDelta] = field(default_factory=list)
    gsc_orphans: list[str] = field(default_factory=list)
    deployed_but_flagged: list[DeployedFlagged] = field(default_factory=list)
    duplicate_in_registrars: list[DuplicateAcrossRegistrars] = field(default_factory=list)
    # Provenance / status of each source (so the CLI can flag what
    # was unavailable rather than report a falsely-clean signal).
    gsc_skipped: bool = False
    snapshot_skipped: bool = False

    def is_clean(self) -> bool:
        return not (
            self.portfolio_no_dir or self.csv_only or self.expiry_mismatches
            or self.gsc_orphans or self.deployed_but_flagged
            or self.duplicate_in_registrars
        )


# ---------- per-signal compute helpers ----------


def _list_site_dirs(sites_root: Path) -> set[str]:
    """Lowercase names of immediate-child dirs under sites/. Only the
    *exact-match* set — drift's job isn't to expand harmonia → harmonia.tools."""
    if not sites_root.is_dir():
        return set()
    out: set[str] = set()
    for p in sites_root.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if name.startswith(".") or name in ("node_modules", "__pycache__",
                                             "tarball", "portfolio"):
            continue
        out.add(name.lower())
    return out


def _compute_signal_1(portfolio_doms: list, sites: set[str]) -> list[str]:
    """portfolio_no_dir: in portfolio.json but no exact-name dir.
    Skip domains in the 'to be deleted immediately' category."""
    out: list[str] = []
    for d in portfolio_doms:
        if (d.category or "").lower() == _DELETE_CATEGORY:
            continue
        if d.name.lower() not in sites:
            out.append(d.name.lower())
    return sorted(out)


def _compute_signal_2(csv_doms: list, portfolio_names: set[str]) -> list[tuple[str, str]]:
    """csv_only: appears in registrar CSV but not in portfolio.json.
    Returns (domain, registrar) tuples, sorted by domain."""
    out: list[tuple[str, str]] = []
    for d in csv_doms:
        if d.name.lower() not in portfolio_names:
            out.append((d.name.lower(), d.registrar))
    out.sort(key=lambda x: x[0])
    return out


def _compute_signal_3(csv_doms: list, portfolio_doms: list) -> list[ExpiryDelta]:
    """expiry_mismatches: for domains in BOTH sources, compare expires."""
    portfolio_by_name = {d.name.lower(): d for d in portfolio_doms}
    out: list[ExpiryDelta] = []
    for csv_d in csv_doms:
        json_d = portfolio_by_name.get(csv_d.name.lower())
        if json_d is None:
            continue
        if csv_d.expires != json_d.expires:
            out.append(ExpiryDelta(
                domain=csv_d.name.lower(),
                registrar=csv_d.registrar,
                csv_expires=csv_d.expires,
                json_expires=json_d.expires,
            ))
    out.sort(key=lambda x: x.domain)
    return out


def _compute_signal_4(portfolio_names: set[str]) -> tuple[list[str], bool]:
    """gsc_orphans: GSC has properties for domains not in portfolio.json.
    Returns (orphans, skipped) — skipped=True if GSC isn't authenticated."""
    try:
        from .gsc import authenticate, list_properties, property_to_domain
        creds = authenticate()
        props = list_properties()
        gsc_domains = {property_to_domain(p["siteUrl"]) for p in props}
    except Exception:
        return [], True
    orphans = sorted(d for d in gsc_domains if d and d.lower() not in portfolio_names)
    return orphans, False


def _compute_signal_5(portfolio_doms: list) -> tuple[list[DeployedFlagged], bool]:
    """deployed_but_flagged: live snapshot says live-site/forwarder but
    portfolio.json category is 'to be deleted immediately'."""
    try:
        from .check import latest_snapshot, load_snapshot
        snap_path = latest_snapshot()
        if snap_path is None:
            return [], True
        snap = load_snapshot(snap_path)
    except Exception:
        return [], True

    delete_marked = {
        d.name.lower() for d in portfolio_doms
        if (d.category or "").lower() == _DELETE_CATEGORY
    }
    if not delete_marked:
        return [], False

    # Dedupe by domain — pick best variant. live-site beats forwarder
    # beats anything else.
    classifications: dict[str, str] = {}
    for r in snap.get("results", []):
        d = (r.get("domain") or "").lower()
        cls = r.get("classification")
        if not d or cls not in ("live-site", "forwarder"):
            continue
        if d not in classifications or classifications[d] != "live-site":
            classifications[d] = cls

    out: list[DeployedFlagged] = []
    for d, cls in classifications.items():
        if d in delete_marked:
            out.append(DeployedFlagged(domain=d, classification=cls,
                                       category="To be deleted immediately"))
    out.sort(key=lambda x: x.domain)
    return out, False


def _compute_signal_6(csv_doms: list) -> list[DuplicateAcrossRegistrars]:
    """duplicate_in_registrars: same domain appears in 2+ registrar CSVs.
    Means a transfer didn't clean up the source registrar's row."""
    by_name: dict[str, set[str]] = {}
    for d in csv_doms:
        by_name.setdefault(d.name.lower(), set()).add(d.registrar)
    out: list[DuplicateAcrossRegistrars] = []
    for name, regs in sorted(by_name.items()):
        if len(regs) > 1:
            out.append(DuplicateAcrossRegistrars(
                domain=name, registrars=sorted(regs)
            ))
    return out


# ---------- top-level ----------


def compute_drift(sites_root: Path | None = None) -> DriftReport:
    """Produce a DriftReport. Caller can override `sites_root` for testing
    (defaults to config.repos_dir)."""
    from .checks.config import load_config
    cfg = load_config()
    if sites_root is None:
        sites_root = cfg.repos_dir

    portfolio_doms = load_domains()
    portfolio_names = {d.name.lower() for d in portfolio_doms}
    try:
        csv_doms = _load_from_registrars()
    except Exception:
        csv_doms = []
    sites = _list_site_dirs(sites_root)

    gsc_orphans, gsc_skipped = _compute_signal_4(portfolio_names)
    deployed_flagged, snapshot_skipped = _compute_signal_5(portfolio_doms)

    return DriftReport(
        portfolio_no_dir=_compute_signal_1(portfolio_doms, sites),
        csv_only=_compute_signal_2(csv_doms, portfolio_names),
        expiry_mismatches=_compute_signal_3(csv_doms, portfolio_doms),
        gsc_orphans=gsc_orphans,
        deployed_but_flagged=deployed_flagged,
        duplicate_in_registrars=_compute_signal_6(csv_doms),
        gsc_skipped=gsc_skipped,
        snapshot_skipped=snapshot_skipped,
    )
