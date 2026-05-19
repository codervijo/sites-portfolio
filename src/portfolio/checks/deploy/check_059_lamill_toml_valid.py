"""CHECK_059 — `lamill.toml` parses cleanly through the v10.A loader.

Second of the v10.E lamill.toml-conformance trio. CHECK_058 covers
presence; this one covers schema. The loader (`lamill_toml.load()`) is
strict-on-read — TOML syntax errors, missing `[deploy]`, unknown enum
values, wrong-type fields all raise `ParseError`. Catching that here
turns "broken declaration silently mistreated by downstream tools"
into a fleet-visible signal.

Pass / fail / warn:
  - pass: file parses to a `LamillToml`
  - fail: file exists but `ParseError`
  - warn: file missing (CHECK_058 owns the presence verdict — no need
          to double-fail) / archived site
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...lamill_toml import LAMILL_TOML_FILENAME, ParseError, load

CHECK_ID = "CHECK_059"
CHECK_NAME = "lamill-toml-valid"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = (
    "When `lamill.toml` exists, it parses cleanly through the v10.A "
    "loader (schema valid, required fields present, enum values "
    "recognized)."
)


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path).resolve()
    try:
        from ...fleet_repos import _archived_reason
        if _archived_reason(base) is not None:
            return CheckResult(status="warn", message="archived — skipped")
    except Exception:
        pass

    if not (base / LAMILL_TOML_FILENAME).is_file():
        return CheckResult(
            status="warn",
            message=f"no {LAMILL_TOML_FILENAME} — see CHECK_058",
        )

    try:
        payload = load(base)
    except ParseError as e:
        return CheckResult(
            status="fail",
            message=f"{LAMILL_TOML_FILENAME} invalid — {e}",
        )

    if payload is None:
        # Shouldn't reach this branch given the is_file() guard above,
        # but the loader's contract permits None — surface defensively.
        return CheckResult(
            status="warn",
            message=f"no {LAMILL_TOML_FILENAME} — see CHECK_058",
        )

    return CheckResult(
        status="pass",
        message=f"parses as {payload.schema} (platform={payload.deploy.platform})",
    )
