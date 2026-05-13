"""CHECK_042 — live HTTP probe's final URL resolves to this domain.

Fourth check in the naming-consistency cluster (040 = git remote, 041
= portfolio.json entry, 042 = live final URL). Catches "deployed code
points elsewhere" failure modes:

  - Apex / www variant redirects to a totally different brand
  - Domain forwarded to a parked / holding URL (airsucks → thakinaam)
  - Misconfigured deploy that ended up serving the wrong domain's
    custom-domain setup

Reads the latest `data/checks/<date>.json` snapshot (populated by
`lamill fleet live`). If no snapshot covers this domain, the check
is skipped — running it without live data would be a false fail.

The `final_url` is allowed to be either the bare apex (`<domain>`)
or the `www.<domain>` variant — both are normal target shapes for a
correctly-deployed site. Anything else is a fail.

Pass / fail / warn:
  - pass: live HTTP probe's final URL hostname matches this domain
  - fail: final URL hostname is a *different* domain
  - warn: no live snapshot covers this domain (skip — surfaces no
          conclusion rather than risking a false fail)
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..result import CheckResult

CHECK_ID = "CHECK_042"
CHECK_NAME = "live-final-url-matches-domain"
CATEGORY = "git"
SEVERITY = "warn"
DESCRIPTION = (
    "Live HTTP probe's final URL hostname matches the project's "
    "domain (catches forwarders / wrong-deploy mismatches)."
)


def _hostname_of(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    return host or None


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    domain = p.name.lower()
    # Skip archived sites — they may legitimately redirect to a holding
    # forwarder during wind-down, no need to flag.
    try:
        from ...fleet_repos import _archived_reason
        if _archived_reason(p) is not None:
            return CheckResult(status="warn", message="archived — skipped")
    except Exception:
        pass
    try:
        from ...check import best_per_domain, latest_snapshot, load_snapshot
        snap_path = latest_snapshot()
        if snap_path is None:
            return CheckResult(status="warn",
                               message="no live snapshot — skipped")
        snapshot = load_snapshot(snap_path)
    except Exception as e:
        return CheckResult(status="warn",
                           message=f"could not load live snapshot: {type(e).__name__}")

    rows_by_domain = best_per_domain(snapshot)
    row = rows_by_domain.get(domain)
    if row is None:
        return CheckResult(status="warn",
                           message=f"no row for {domain} in {snap_path.name} — skipped")

    final_url = row.get("final_url")
    if not final_url:
        # Domain was probed but didn't reach a final URL (dead / error /
        # ssl-broken). Surface as warn — other checks cover liveness.
        cls = row.get("classification") or "?"
        return CheckResult(status="warn",
                           message=f"no final URL — classification={cls}")
    host = _hostname_of(final_url)
    if host is None:
        return CheckResult(status="warn",
                           message=f"could not parse final URL: {final_url!r}")

    if host == domain or host == f"www.{domain}":
        return CheckResult(status="pass",
                           message=f"final URL resolves to {host}")
    return CheckResult(
        status="fail",
        message=(f"final URL resolves to {host}, not {domain} — "
                 f"site forwards / redirects elsewhere"),
    )
