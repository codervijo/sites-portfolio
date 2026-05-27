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
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from ...fix_helpers import FixerSpec, FixResult
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

# v26.C bug fix 2026-05-26 — CF accepts `always_use_https=on` instantly
# via API but edges take 5-30s to start serving the redirect. A single
# immediate verification probe races propagation and falsely reports
# "still 200." Poll with a short backoff instead — first 308/301 wins;
# 5 × 3s = 15s budget covers the observed CF flip time with margin.
_FIX_VERIFY_ATTEMPTS = 5
_FIX_VERIFY_INTERVAL_S = 3.0


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


# ============================================================================
# v26.C — fix_tier_1 — apex-canonical-redirect fixer
# ============================================================================
#
# Mirror-image of the check. Dispatches on the project's
# `lamill.toml [deploy].platform` field and routes to a per-platform
# helper. v26.C ships the Cloudflare branch (cf-pages + cf-workers);
# Vercel ships in v26.D, Netlify/HostGator in v26.E.
#
# CF branch covers 7 of the 19 fleet offenders identified in the
# 2026-05-25 audit — every cf-pages/cf-workers site whose HTTP variant
# returns 200 instead of redirecting to HTTPS. The root cause for those
# sites is the per-zone "Always Use HTTPS" toggle being OFF. The fixer
# turns it ON.
#
# Dry-run by default; --apply commits. Mirrors CHECK_057's CF-API fixer
# posture: probe → decide → write (when --apply) → verify by re-probing.


def _load_platform(project_dir: Path) -> str | None:
    """Read `[deploy].platform` from `<project_dir>/lamill.toml`.
    Returns None when the file is absent or unparseable — caller maps
    to a `manual` FixResult with an actionable hint."""
    try:
        from ...lamill_toml import load as _lamill_load
        toml = _lamill_load(project_dir)
    except Exception:
        return None
    if toml is None:
        return None
    return toml.deploy.platform


def _http_status(domain: str) -> int | None:
    """One HEAD probe against http://<domain>/. Used post-apply to
    verify the toggle actually changed the upstream behavior."""
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as c:
            r = c.head(f"http://{domain}/", follow_redirects=False)
            return r.status_code
    except httpx.RequestError:
        return None


def _apply_cf_always_use_https(
    domain: str, *, dry_run: bool,
) -> FixResult:
    """Turn on the CF zone-level `always_use_https` toggle for `domain`.

    Probes the current value first; skips with `nothing-to-do` if
    already on. On --apply, PATCHes the setting and re-probes
    `http://<domain>/` to verify the upgrade now returns a 308/301.
    """
    from ... import cloudflare

    try:
        zone_id = cloudflare.resolve_zone_id(domain)
    except cloudflare.MissingCredentialsError as e:
        return FixResult(
            status="error",
            summary=f"CF token missing: {e}\n"
                    "  Set via `lamill settings apikeys set CF_API_TOKEN ...`.",
            files_touched=[],
        )
    except cloudflare.CloudflareAPIError as e:
        return FixResult(
            status="error",
            summary=f"resolve zone failed: {e}\n"
                    "  Diagnose: `lamill settings cloudflare check-token`.",
            files_touched=[],
        )

    try:
        current = cloudflare.get_zone_setting(zone_id, "always_use_https")
    except cloudflare.CloudflareAPIError as e:
        return FixResult(
            status="error",
            summary=f"read always_use_https failed: {e}",
            files_touched=[],
        )
    if current == "on":
        return FixResult(
            status="nothing-to-do",
            summary=f"always_use_https already on (zone {zone_id[:8]}…)",
            files_touched=[],
        )

    if dry_run:
        return FixResult(
            status="would-fix",
            summary=f"would set always_use_https → on (current: {current!r}, "
                    f"zone {zone_id[:8]}…)",
            files_touched=[],
        )

    try:
        cloudflare.set_zone_setting(zone_id, "always_use_https", "on")
    except cloudflare.CloudflareAPIError as e:
        return FixResult(
            status="error",
            summary=f"PATCH always_use_https failed: {e}\n"
                    "  Verify with `lamill settings cloudflare check-token` — "
                    "the token likely lacks Zone Settings:Edit for this zone.",
            files_touched=[],
        )

    # Verify with backoff — CF edges take 5-30s to start serving the
    # new redirect even though the API write persists instantly. Poll
    # `_FIX_VERIFY_ATTEMPTS × _FIX_VERIFY_INTERVAL_S` (~15s default);
    # first 308/301 wins, all-200 means genuine conflict, unreachable
    # falls through to "verify manually."
    last_status: int | None = None
    for attempt in range(_FIX_VERIFY_ATTEMPTS):
        last_status = _http_status(domain)
        if last_status in _PERMANENT_REDIRECTS:
            return FixResult(
                status="fixed",
                summary=f"set always_use_https → on; http://{domain}/ now "
                        f"returns {last_status}",
                files_touched=[],
            )
        # 200 or None (transient unreachable) — sleep and retry. Skip
        # the sleep on the last attempt; nothing to wait for after.
        if attempt < _FIX_VERIFY_ATTEMPTS - 1:
            time.sleep(_FIX_VERIFY_INTERVAL_S)

    if last_status is None:
        return FixResult(
            status="fixed",
            summary=f"set always_use_https → on (post-write probe "
                    f"unreachable after {_FIX_VERIFY_ATTEMPTS} attempts; "
                    f"verify manually with `curl -sI http://{domain}/`)",
            files_touched=[],
        )
    # Setting persisted on CF's side but http stayed 200 across the full
    # ~15s window — likely a conflicting Page Rule / Worker / stuck cache.
    return FixResult(
        status="error",
        summary=f"set always_use_https → on, but http://{domain}/ still "
                f"returns {last_status} after "
                f"{_FIX_VERIFY_ATTEMPTS}×{_FIX_VERIFY_INTERVAL_S:.0f}s "
                f"probes. Check for conflicting Page Rules or stuck cache.",
        files_touched=[],
    )


# Manual-fix hints per platform — surfaced when the fixer dispatcher
# can't run an automated fix for this platform (v26.E lands HostGator).
_MANUAL_HINTS: dict[str, str] = {
    "hostgator": (
        "HostGator fixer ships in v26.E. Manual path: edit `.htaccess` "
        "in public_html to force HTTPS + 301 www→apex."
    ),
    "github-pages": (
        "GitHub Pages: enforce HTTPS in repo Settings → Pages; configure "
        "the custom-domain CNAME accordingly."
    ),
    "custom": "Platform=`custom`: fixer can't automate — fix in your hosting config.",
    "none": "Platform=`none`: no fix applicable.",
}


def _apply_vercel_canonical_redirect(domain: str, *, dry_run: bool) -> FixResult:
    """Set apex as primary + www→apex 308 on the Vercel project that
    owns the domain.

    Strategy:
      1. Locate the project that has `<apex>` attached.
      2. Read current configs for apex and www.<apex>.
      3. Decide what needs to change:
           - apex must have redirect=None (i.e., serve directly).
           - www.<apex> must have redirect=<apex> + statusCode=308.
           - www missing from project → POST to add it as a redirect.
      4. On --apply: issue the PATCH/POST calls.
      5. Verify by re-probing https://<apex>/ and https://www.<apex>/.

    Returns FixResult with status: `fixed`, `nothing-to-do`,
    `would-fix`, `error`, or `manual`.
    """
    from ... import vercel

    apex = domain
    www_name = f"www.{domain}"

    try:
        project = vercel.find_project_by_domain(apex)
    except vercel.MissingCredentialsError as e:
        return FixResult(
            status="error",
            summary=f"Vercel token missing: {e}",
            files_touched=[],
        )
    except vercel.VercelAPIError as e:
        # "no Vercel project attaches X" lands here too — surface as
        # `manual` so operator can check project ownership vs the
        # `lamill.toml [deploy].platform` declaration.
        return FixResult(
            status="manual",
            summary=f"Vercel project for {apex} not found: {e}",
            files_touched=[],
        )

    try:
        apex_cfg = vercel.get_project_domain(project.project_id, apex)
        www_cfg = vercel.get_project_domain(project.project_id, www_name)
    except vercel.VercelAPIError as e:
        return FixResult(
            status="error",
            summary=f"read domain configs failed: {e}",
            files_touched=[],
        )

    # Decide the changes.
    apex_needs_clear = apex_cfg is not None and apex_cfg.redirect is not None
    www_needs_update = (
        www_cfg is None
        or www_cfg.redirect != apex
        or www_cfg.redirect_status_code != 308
    )
    www_needs_add = www_cfg is None

    if apex_cfg is None:
        # Apex not attached to this project — odd shape; route manual.
        return FixResult(
            status="manual",
            summary=f"apex {apex} isn't attached to project "
                    f"{project.name!r} — check Vercel dashboard.",
            files_touched=[],
        )

    if not apex_needs_clear and not www_needs_update:
        return FixResult(
            status="nothing-to-do",
            summary=f"apex serves directly; www→apex already 308 "
                    f"(project {project.name!r})",
            files_touched=[],
        )

    plan_bits: list[str] = []
    if apex_needs_clear:
        plan_bits.append(f"clear redirect on {apex}")
    if www_needs_add:
        plan_bits.append(f"add {www_name} → 308 → {apex}")
    elif www_needs_update:
        plan_bits.append(f"set {www_name} redirect → 308 → {apex}")
    plan_text = "; ".join(plan_bits)

    if dry_run:
        return FixResult(
            status="would-fix",
            summary=f"would {plan_text} (project {project.name!r})",
            files_touched=[],
        )

    try:
        if apex_needs_clear:
            vercel.update_domain_redirect(
                project.project_id, apex,
                redirect_to=None,
            )
        if www_needs_add:
            vercel.add_domain_to_project(
                project.project_id, www_name,
                redirect_to=apex, status_code=308,
            )
        elif www_needs_update:
            vercel.update_domain_redirect(
                project.project_id, www_name,
                redirect_to=apex, status_code=308,
            )
    except vercel.VercelAPIError as e:
        return FixResult(
            status="error",
            summary=f"Vercel API write failed mid-fix: {e}\n"
                    "  Project state may be partially updated; re-run with "
                    "--apply (idempotent) once the issue is resolved.",
            files_touched=[],
        )

    # Verify with same backoff posture as the CF branch — Vercel edges
    # also need a moment to start serving the new redirect after the
    # API write.
    apex_ok = False
    www_ok = False
    last_apex: int | None = None
    last_www: int | None = None
    for attempt in range(_FIX_VERIFY_ATTEMPTS):
        last_apex = _probe_status(f"https://{apex}/")
        last_www = _probe_status(f"https://{www_name}/")
        apex_ok = last_apex == 200
        # www_ok if it permanent-redirects to apex (or returns NXDOMAIN
        # which would mean www was never DNS-attached — unusual after
        # an add, so don't accept that here)
        www_ok = (
            last_www in _PERMANENT_REDIRECTS
        )
        if apex_ok and www_ok:
            return FixResult(
                status="fixed",
                summary=f"{plan_text}; verified apex=200, www={last_www}",
                files_touched=[],
            )
        if attempt < _FIX_VERIFY_ATTEMPTS - 1:
            time.sleep(_FIX_VERIFY_INTERVAL_S)

    # Writes succeeded but verification didn't settle — Vercel can take
    # longer than CF for edge propagation. Mark fixed-with-caveat.
    return FixResult(
        status="fixed",
        summary=f"{plan_text}; post-write probe shows apex={last_apex}, "
                f"www={last_www} after "
                f"{_FIX_VERIFY_ATTEMPTS}×{_FIX_VERIFY_INTERVAL_S:.0f}s. "
                f"Re-probe in ~1 min: `curl -sI https://{apex}/` + "
                f"`curl -sI https://{www_name}/`.",
        files_touched=[],
    )


def _probe_status(url: str) -> int | None:
    """Variant of `_http_status` that takes a full URL (not just a
    domain). Used by the Vercel verification step which probes both
    apex (https) and www (https), not just http upgrade."""
    try:
        with httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _UA}) as c:
            r = c.head(url, follow_redirects=False)
            return r.status_code
    except httpx.RequestError:
        return None


def _apply_canonical_redirect_fix(
    project_dir: Path, dry_run: bool, assume_yes: bool,
) -> FixResult:
    """Dispatch the canonical-redirect fix by `[deploy].platform`.

    v26.C ships the CF branch (cf-pages + cf-workers). Other platforms
    return `manual` with a per-platform hint pointing at the future
    phase that will automate them."""
    domain = project_dir.resolve().name.lower()
    if not _DOMAIN_RE.match(domain):
        return FixResult(
            status="nothing-to-do",
            summary=f"{project_dir.name!r} is not a domain-shaped dir — skipping",
            files_touched=[],
        )

    platform = _load_platform(project_dir)
    if platform is None:
        return FixResult(
            status="manual",
            summary="lamill.toml missing or unparseable — can't dispatch "
                    "to a platform fixer. Run `lamill settings deploy show "
                    f"{domain}` to verify the declared platform.",
            files_touched=[],
        )

    if platform in ("cf-pages", "cf-workers"):
        return _apply_cf_always_use_https(domain, dry_run=dry_run)

    if platform == "vercel":
        return _apply_vercel_canonical_redirect(domain, dry_run=dry_run)

    hint = _MANUAL_HINTS.get(
        platform,
        f"unknown platform {platform!r} — no automated fix available.",
    )
    return FixResult(
        status="manual",
        summary=hint,
        files_touched=[],
    )


fix_tier_1 = FixerSpec(
    check_id="",   # registry rewrites at discovery time
    tier=1,
    summary="enable https + permanent redirects per the project's platform",
    apply=_apply_canonical_redirect_fix,
)
