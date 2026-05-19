"""CHECK_143 — declared `lamill.toml` platform matches live-snapshot reality.

Third of the v10.E lamill.toml-conformance trio. Compares the platform
declared in `<repo>/lamill.toml` against a best-effort classification
derived from the most recent `data/checks/<date>.json` snapshot
(populated by `lamill fleet live`).

Canonical drift case (2026-05-18): `iotnews.today` declares
`platform = "vercel"` but currently serves a WordPress install
(server-side HTML carries a `<meta name="generator" content="WordPress">`
tag). Operator memory `project-hostgator-wp-sites` flags every WP
site in the fleet as HostGator-hosted, so the classifier maps
WordPress-generator HTML → `hostgator`. A `vercel` declaration plus
that classification is the drift signal.

Classification signals (in priority order):
  1. WordPress generator meta in body excerpt → `hostgator`.
  2. final URL or any redirect-chain host ends in `*.vercel.app`,
     `*.pages.dev`, or `*.netlify.app` → that provider.
  Anything else → unknown (warn-skip — drift can't be concluded
  honestly without a stronger signal).

Pass / fail / warn:
  - pass: declared platform matches classified actual
  - fail: declared platform != classified actual (drift)
  - warn: no `lamill.toml` (CHECK_058 covers presence) / `platform="none"`
          (intentional no-deploy) / no live snapshot / no row for this
          domain / classifier returned unknown / archived
"""
from __future__ import annotations

import re
from pathlib import Path

import httpx

from ..result import CheckResult
from ...lamill_toml import LAMILL_TOML_FILENAME, ParseError, load

CHECK_ID = "CHECK_143"
CHECK_NAME = "deploy-drift"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "`lamill.toml` declared platform matches what the live HTTP probe "
    "actually shows (catches stale declarations after a host migration)."
)


# WordPress fingerprints — any one is sufficient. Each pattern is
# strict enough that an HTML body containing it is almost certainly
# WP-rendered (vs a plain HTML page that happens to mention WordPress).
#
#   - `<meta generator content="WordPress ...">` — the standard core tag
#     (absent on half-installed sites that haven't completed setup, so
#     it's necessary but not sufficient).
#   - `<title>WordPress ...` — the WP installer / error pages set their
#     own title before any generator meta is rendered (catches the
#     iotnews.today 2026-05-18 mid-migration case: declared=vercel but
#     served the WP install error page from HostGator).
#   - `/wp-includes/`, `/wp-content/`, `/wp-admin/` — server-side
#     URL paths. WP emits these in `<link>` / `<script>` references on
#     every rendered page. A plain HTML page would have to be literally
#     about WordPress filesystem layout to false-positive.
_WP_FINGERPRINTS: tuple[re.Pattern, ...] = (
    re.compile(
        r"""<meta\s+[^>]*name=["']generator["'][^>]*content=["']WordPress\b""",
        re.IGNORECASE,
    ),
    re.compile(r"<title>\s*WordPress\b", re.IGNORECASE),
    re.compile(r"/wp-(?:includes|content|admin)/", re.IGNORECASE),
)

# Provider-suffix → platform enum (matches lamill_toml.PLATFORM_VALUES).
# Order matters only for the message; classification is unique-per-host.
_PROVIDER_SUFFIXES: tuple[tuple[str, str], ...] = (
    (".vercel.app", "vercel"),
    (".pages.dev", "cf-pages"),
    (".netlify.app", "netlify"),
    (".workers.dev", "cf-workers"),
)


def _classify_actual_platform(row: dict) -> tuple[str | None, str | None]:
    """Map a `data/checks/<date>.json` row to a platform enum value.

    Returns `(platform, signal_description)` when a strong signal is
    found; otherwise `(None, None)`. The signal-description string is
    user-facing — it gets echoed back through the drift message so the
    operator can see *why* the check classified the site this way.
    """
    body = row.get("body_excerpt") or ""
    for pat in _WP_FINGERPRINTS:
        if pat.search(body):
            return ("hostgator", f"WordPress fingerprint in HTML body ({pat.pattern[:60]})")

    final_url = row.get("final_url") or ""
    redirect_chain = list(row.get("redirect_chain") or [])
    candidate_urls = [final_url, *redirect_chain] if final_url else redirect_chain
    for url in candidate_urls:
        if not url:
            continue
        try:
            host = httpx.URL(url).host.lower()
        except Exception:
            continue
        for suffix, platform in _PROVIDER_SUFFIXES:
            if host.endswith(suffix):
                return (platform, f"{host} ends with {suffix}")

    return (None, None)


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path).resolve()
    domain = base.name.lower()

    try:
        from ...fleet_repos import _archived_reason
        if _archived_reason(base) is not None:
            return CheckResult(status="warn", message="archived — skipped")
    except Exception:
        pass

    toml_path = base / LAMILL_TOML_FILENAME
    if not toml_path.is_file():
        return CheckResult(
            status="warn",
            message=f"no {LAMILL_TOML_FILENAME} — drift not checkable",
        )

    try:
        payload = load(base)
    except ParseError as e:
        return CheckResult(
            status="warn",
            message=f"{LAMILL_TOML_FILENAME} invalid — see CHECK_059 ({e})",
        )
    if payload is None:
        return CheckResult(
            status="warn",
            message=f"no {LAMILL_TOML_FILENAME} — drift not checkable",
        )

    declared = payload.deploy.platform
    if declared == "none":
        return CheckResult(
            status="warn",
            message='declared platform="none" — drift not applicable',
        )

    try:
        from ...check import best_per_domain, latest_snapshot, load_snapshot
        snap_path = latest_snapshot()
        if snap_path is None:
            return CheckResult(status="warn",
                               message="no live snapshot — drift not checkable")
        snapshot = load_snapshot(snap_path)
    except Exception as e:
        return CheckResult(
            status="warn",
            message=f"could not load live snapshot: {type(e).__name__}",
        )

    rows_by_domain = best_per_domain(snapshot)
    row = rows_by_domain.get(domain)
    if row is None:
        return CheckResult(
            status="warn",
            message=f"no row for {domain} in {snap_path.name} — skipped",
        )

    actual, signal = _classify_actual_platform(row)
    if actual is None:
        return CheckResult(
            status="warn",
            message=f"declared={declared} · actual unknown (no strong signal)",
        )

    if actual == declared:
        return CheckResult(
            status="pass",
            message=f"declared={declared} matches actual ({signal})",
        )
    return CheckResult(
        status="fail",
        message=(
            f"DRIFT — declared={declared} but actual={actual} ({signal}). "
            f"Either update `lamill.toml` via "
            f"`lamill settings project set-deploy {domain} {actual}` or "
            f"migrate the live site back to {declared}."
        ),
    )
