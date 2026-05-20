"""CHECK_144 — Live site serves `/version.json` with the v15.C schema.

Convention (v15.C, 2026-05-20): every sites/* project's build writes
`dist/version.json` via the `vite-version-stamp` plugin at
`~/work/projects/builder/vite-version-stamp.ts` (or an inline copy).
After deploy, the live URL should serve it at `/version.json`.

This check fetches the live URL's `/version.json` and validates shape:
  - HTTP 200
  - Body parses as JSON
  - Required fields: `commit` (non-empty string), `built_at` (string)
  - Optional: `schema` (integer; v1 = current)

Pass / warn / fail:
  - pass: file fetches, parses, has the required fields
  - fail: 404 (the deploy didn't produce a version.json — the plugin
          isn't wired into this site's vite.config) OR malformed body
  - warn: not a web project / no live URL / network error
          (don't fail-grade on flaky transport, matching the v15.D
          deploy-fresh check posture)

Pair: v15.D `deploy-fresh` (CHECK_145) reads the same `commit` field
to compare against the operator's local HEAD. v15.E `last-build-success`
column on `fleet hosting` reads the same `built_at`.
"""
from __future__ import annotations

from ..result import CheckResult
from ..seo._live import resolve_live_url
from ..seo import _is_web_project
from ...version_stamp import (
    VersionStamp,
    VersionStampError,
    fetch_version_stamp,
)

CHECK_ID = "CHECK_144"
CHECK_NAME = "has-version-stamp"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Live site serves `/version.json` with the v15.C schema (commit + built_at)."
)


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")

    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    result = fetch_version_stamp(origin)

    if isinstance(result, VersionStampError):
        # Map error kinds to pass/warn/fail per CHECK_144's posture.
        kind = result.kind
        if kind == "unreachable":
            return CheckResult(
                status="warn",
                message=f"version.json unreachable ({result.detail})",
            )
        if kind == "not_found":
            return CheckResult(
                status="fail",
                message=(
                    f"{result.detail}. Site isn't serving version.json — wire the "
                    f"`vite-version-stamp` plugin into vite.config and redeploy. "
                    f"See ~/work/projects/builder/vite-version-stamp.ts."
                ),
            )
        if kind == "http_error":
            return CheckResult(
                status="fail",
                message=f"{result.detail} (expected 200)",
            )
        if kind == "not_json":
            return CheckResult(
                status="fail",
                message=f"{result.detail}",
            )
        if kind == "wrong_shape":
            return CheckResult(
                status="fail",
                message=(
                    f"{result.detail}. Expected schema-v1 shape "
                    f'{{"schema":1,"commit":"<sha>","built_at":"<iso>"}}.'
                ),
            )
        return CheckResult(
            status="fail",
            message=f"unexpected version-stamp error: {result.kind} / {result.detail}",
        )

    # Happy path — VersionStamp parsed correctly.
    stamp: VersionStamp = result
    short_commit = stamp.commit[:12] if stamp.commit != "unknown" else stamp.commit
    schema_note = f" (schema v{stamp.schema})" if stamp.schema is not None else ""
    return CheckResult(
        status="pass",
        message=(
            f"version.json served · commit {short_commit} · "
            f"built {stamp.built_at}{schema_note}"
        ),
    )
