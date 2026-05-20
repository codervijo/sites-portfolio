"""CHECK_146 — Last build for this project completed successfully (v15.E).

Reads the operator-side `fleet hosting` snapshot (which already polls
CF Pages + Vercel deployment-list endpoints) and checks the
`latest_deploy_status` for this project's domain.

Pass / warn / fail:
  - pass: latest deploy = READY (Vercel) / SUCCESS / ACTIVE
  - fail: latest deploy = ERROR / CANCELED (build failed at last attempt)
  - warn: BUILDING / INITIALIZING / QUEUED (in flight; not a failure)
          OR domain not in the latest hosting snapshot
          OR no hosting snapshot exists yet (operator hasn't run `fleet hosting`)
          OR provider doesn't have a build concept (CF Workers / HostGator)
            — these render `—` rather than fail-grading sites that
            don't have a build pipeline by design.

v15.E ships the signal; v15.A's audit deferred the question of
whether this should be a hard error vs warn. Defaulting to warn
keeps the new check from immediately fail-grading CFW/HG sites that
predate the version-stamp convention.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..result import CheckResult
from ... import hosting_cache
from ...hosting import PROVIDER_CF_PAGES, PROVIDER_VERCEL

CHECK_ID = "CHECK_146"
CHECK_NAME = "last-build-success"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Last build for this project completed successfully (reads `fleet hosting` snapshot)."
)

_SUCCESS_STATES = frozenset({"READY", "SUCCESS", "ACTIVE"})
_FAILURE_STATES = frozenset({"ERROR", "CANCELED", "FAILED"})
_IN_FLIGHT_STATES = frozenset(
    {"BUILDING", "INITIALIZING", "QUEUED", "PENDING"},
)
_BUILD_PROVIDERS = frozenset({PROVIDER_CF_PAGES, PROVIDER_VERCEL})


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path).resolve()
    domain = base.name

    snapshot_path = hosting_cache.latest_snapshot()
    if snapshot_path is None:
        return CheckResult(
            status="warn",
            message=(
                "no `fleet hosting` snapshot — run `lamill fleet hosting` "
                "to populate build state."
            ),
        )

    try:
        snap = hosting_cache.load_snapshot(snapshot_path)
    except Exception as e:
        return CheckResult(
            status="warn",
            message=f"hosting snapshot unreadable ({type(e).__name__}: {e})",
        )

    matched = _find_row(snap, domain)
    if matched is None:
        return CheckResult(
            status="warn",
            message=(
                f"{domain} not in latest hosting snapshot — run "
                f"`lamill fleet hosting --refresh` or check provider claim."
            ),
        )

    provider = _get(matched, "provider")
    if provider not in _BUILD_PROVIDERS:
        # CFW + HG don't have a build pipeline concept the walker exposes.
        return CheckResult(
            status="warn",
            message=f"provider `{provider}` has no build-pipeline signal — skipped",
        )

    status = _get(matched, "latest_deploy_status")
    when = _get(matched, "latest_deploy_at") or _get(matched, "last_successful_deploy_at")
    consecutive_failures = _get(matched, "consecutive_failures", 0) or 0

    if status is None:
        return CheckResult(
            status="warn",
            message=f"provider `{provider}` returned no deploy status — skipped",
        )

    upper = str(status).upper()

    if upper in _SUCCESS_STATES:
        when_str = f" · {when}" if when else ""
        return CheckResult(
            status="pass",
            message=f"last build {upper}{when_str}",
        )

    if upper in _FAILURE_STATES:
        cf_note = (
            f" · {consecutive_failures} consecutive failures"
            if consecutive_failures > 1
            else ""
        )
        return CheckResult(
            status="fail",
            message=(
                f"last build {upper} on {provider}{cf_note}. "
                f"Check the provider dashboard or re-run the build."
            ),
        )

    if upper in _IN_FLIGHT_STATES:
        return CheckResult(
            status="warn",
            message=f"build in flight ({upper}) — re-check after it resolves",
        )

    return CheckResult(
        status="warn",
        message=f"unrecognized deploy status: {status}",
    )


def _find_row(snap: Any, domain: str) -> Any:
    """Snapshot shape: `{"rows": [...]}` where each row is a dict with
    a `domain` field. Returns the first matching row (case-insensitive)
    or None."""
    rows = snap.get("rows", []) if isinstance(snap, dict) else []
    target = domain.lower()
    for row in rows:
        rd = row.get("domain") if isinstance(row, dict) else None
        if isinstance(rd, str) and rd.lower() == target:
            return row
    return None


def _get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
