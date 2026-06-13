"""CHECK_160 — the GSC property + registered sitemaps use the apex host.

Host-consistency triad (v26.G), the Search-Console half. A *stale* non-apex
sitemap left registered in GSC — e.g. the pre-v32.G `/sitemap.xml` residue,
or a `www`-host sitemap — keeps feeding Google the non-canonical host even
after the live site, redirect (CHECK_150), markup (CHECK_158), and live
sitemap (CHECK_159) are all correct. Apex is the ONLY canonical host
fleet-wide (see `docs/CLAUDE.md § Locked target shapes`).

Reads the cached per-domain GSC detail (`data/gsc/<domain>/`, written by
`project seo` / `fleet seo`) — offline, no GSC auth in the check itself.
Asserts the GSC property host (for a URL-prefix property; `sc-domain:`
properties are host-agnostic) and every registered sitemap's host equal the
apex. warn-skips when no GSC detail is cached or the domain isn't registered.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ... import gsc_detail_cache
from ..result import CheckResult

CHECK_ID = "CHECK_160"
CHECK_NAME = "gsc-sitemap-host-is-apex"
CATEGORY = "seo"
SEVERITY = "error"
DESCRIPTION = (
    "The GSC property and every registered sitemap use the apex host (no www)."
)


def _host(u: str) -> str:
    return (urlparse(u).hostname or "").lower()


def run(repo_path: str) -> CheckResult:
    apex = Path(repo_path).name.lower()
    path = gsc_detail_cache.latest_snapshot(apex)
    if path is None:
        return CheckResult(
            status="warn",
            message="no cached GSC detail — run `project seo` first",
        )
    try:
        snap = gsc_detail_cache.load_snapshot(path)
    except (OSError, ValueError):
        return CheckResult(
            status="warn", message=f"GSC detail unreadable ({path.name})")
    if snap.get("not_registered"):
        return CheckResult(
            status="warn", message="domain not registered in GSC — skipped")

    findings: list[str] = []

    # URL-prefix property (https://…) carries a host; a domain property
    # (sc-domain:…) is host-agnostic, so there's nothing to check there.
    prop = (snap.get("property_url") or "").strip()
    if prop.startswith("http"):
        h = _host(prop)
        if h and h != apex:
            findings.append(f"property host {h!r} ≠ apex")

    sitemaps = snap.get("sitemaps") or []
    for s in sitemaps:
        url = (s.get("full_url") or s.get("path") or "").strip()
        h = _host(url)  # relative paths have no host → skip
        if h and h != apex:
            findings.append(f"sitemap {url} → host {h!r}")

    if not findings:
        return CheckResult(
            status="pass",
            message=(f"GSC property + {len(sitemaps)} registered "
                     f"sitemap(s) use apex {apex!r}"),
        )
    return CheckResult(
        status="fail",
        message=(f"{len(findings)} non-apex GSC host(s) — "
                 + "; ".join(findings[:3])),
    )
