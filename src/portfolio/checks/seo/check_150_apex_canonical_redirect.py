"""CHECK_150 — apex is canonical; www and http permanently redirect to it.

v26.B — fleetwide canonical-redirect conformance. Shipped at `warn`
severity for the v26.C soak cycle; promotes to `fail` once Bucket A
sites are fixed (see `docs/bugs.md` 2026-05-25 audit entry).

Probes three endpoints per repo (domain = dir name):
  1. `HEAD https://<apex>/` → must be 200 (apex is the canonical).
  2. `HEAD https://www.<apex>/` → must 308/301 → https://<apex>/,
     OR be unreachable (NXDOMAIN / connrefused = "no www" = pass).
  3. `HEAD http://<apex>/` → must 308/301 → https://<apex>/.

Any 307 / 302 (temporary redirect) fails — Google holds signal-transfer
indefinitely on temporary redirects, so `<lastmod>` and ranking signals
never consolidate onto the canonical URL. This is what blocked
homeloom.app indexation 2026-05-25 and motivated v26.

Network errors on the apex probe downgrade to `warn` (skipped) so
flaky CI doesn't fail-grade a check on a transient outage. Network
errors on the www probe are interpreted as "no www" → pass (the
common case for CF Pages sites without a www DNS record).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..result import CheckResult

CHECK_ID = "CHECK_150"
CHECK_NAME = "apex-canonical-redirect"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "Apex is the canonical endpoint (200); www and http variants "
    "permanently redirect (308/301) to it. Catches Vercel-style "
    "307 temporary redirects that block Google indexation."
)

# Same shape as `bootstrap.DOMAIN_RE` — guards against running the
# check on non-domain dirs (e.g., `sites/portfolio/`, `sites/rankmill/`).
_DOMAIN_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)
_PERMANENT_REDIRECTS = frozenset({301, 308})
_TEMPORARY_REDIRECTS = frozenset({302, 307})
_TIMEOUT = 8.0
_UA = "lamill-CHECK_150/0.1"


@dataclass
class _Probe:
    """One HEAD probe result. `status=None` means the connection
    failed before any HTTP exchange (DNS / connrefused / TLS handshake)."""
    status: int | None
    location: str  # lowercased Location header; "" if absent or unreachable


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()

    # Skip archived sites — same posture as CHECK_042.
    try:
        from ...fleet_repos import _archived_reason
        if _archived_reason(p) is not None:
            return CheckResult(status="warn", message="archived — skipped")
    except Exception:
        pass

    domain = p.name.lower()
    if not _DOMAIN_RE.match(domain):
        return CheckResult(
            status="warn",
            message=f"{p.name!r} is not a domain-shaped dir — skipped",
        )

    with httpx.Client(
        timeout=_TIMEOUT,
        headers={"User-Agent": _UA},
    ) as client:
        return _classify(domain, client)


def _classify(domain: str, client: httpx.Client) -> CheckResult:
    """Run the three probes and classify. Split out for testability —
    tests pass an `httpx.Client` wired to a `MockTransport`."""
    apex = _probe(client, f"https://{domain}/")
    if apex.status is None:
        return CheckResult(
            status="warn",
            message=f"apex unreachable (https://{domain}/) — skipped",
        )

    www = _probe(client, f"https://www.{domain}/")
    http = _probe(client, f"http://{domain}/")

    issues: list[str] = []

    # Rule 1: apex must serve 200.
    if apex.status == 200:
        pass
    elif apex.status in _PERMANENT_REDIRECTS:
        target = apex.location
        if f"https://www.{domain}/" in target:
            issues.append(
                f"apex {apex.status}→www (apex isn't the canonical)"
            )
        elif f"https://{domain}/" not in target:
            issues.append(f"apex {apex.status}→{_short(target)}")
    elif apex.status in _TEMPORARY_REDIRECTS:
        issues.append(
            f"apex {apex.status} (TEMP) → {_short(apex.location)} — "
            f"Google holds signal-transfer on temp redirects"
        )
    else:
        issues.append(f"apex returned {apex.status} (expected 200)")

    # Rule 2: www must 308/301 → apex (or be unreachable = no www = pass).
    if www.status is None:
        pass  # NXDOMAIN / connrefused / TLS unreachable — no www = no split
    elif www.status in _PERMANENT_REDIRECTS:
        if f"https://{domain}/" not in www.location:
            issues.append(
                f"www {www.status}→{_short(www.location)} (not apex)"
            )
    elif www.status in _TEMPORARY_REDIRECTS:
        issues.append(
            f"www {www.status} (TEMP) — 308 needed for SEO signal transfer"
        )
    elif www.status == 200:
        issues.append("www returns 200 (second canonical — splits SEO signals)")
    else:
        issues.append(f"www returned {www.status} (expected 308/301→apex)")

    # Rule 3: http://apex must 308/301 → https://apex.
    if http.status is None:
        # If HTTP is unreachable entirely (port 80 closed), that's
        # functionally fine — no http exposure to upgrade.
        pass
    elif http.status in _PERMANENT_REDIRECTS:
        if not http.location.startswith("https://"):
            issues.append(
                f"http {http.status}→{_short(http.location)} (not HTTPS)"
            )
    elif http.status in _TEMPORARY_REDIRECTS:
        issues.append(f"http {http.status} (TEMP) — 308 needed")
    elif http.status == 200:
        issues.append("http=200 (no HTTPS upgrade)")
    else:
        issues.append(f"http returned {http.status}")

    if not issues:
        return CheckResult(
            status="pass",
            message=(
                f"{domain}: apex 200, "
                f"www {'NXDOMAIN' if www.status is None else www.status}→apex, "
                f"http {'closed' if http.status is None else http.status}"
            ),
        )
    return CheckResult(
        status="fail",
        message="canonical chain non-conforming: " + "; ".join(issues),
    )


def _probe(client: httpx.Client, url: str) -> _Probe:
    """HEAD probe; capture status + Location. Connection failures
    return `_Probe(None, "")` rather than raising."""
    try:
        r = client.head(url, follow_redirects=False)
    except httpx.RequestError:
        return _Probe(status=None, location="")
    return _Probe(
        status=r.status_code,
        location=(r.headers.get("Location") or "").lower(),
    )


def _short(s: str, limit: int = 60) -> str:
    """Truncate a URL for the message line."""
    return s if len(s) <= limit else s[: limit - 1] + "…"
