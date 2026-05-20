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

Pair: v15.D `deploy-fresh` (CHECK_NNN) reads the same `commit` field
to compare against the operator's local HEAD. v15.E `last-build-success`
column on `fleet hosting` reads the same `built_at`.
"""
from __future__ import annotations

import json
from typing import Any

from ..result import CheckResult
from ..seo._live import (
    LiveFetchError,
    _build_client,
    resolve_live_url,
)
from ..seo import _is_web_project

CHECK_ID = "CHECK_144"
CHECK_NAME = "has-version-stamp"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Live site serves `/version.json` with the v15.C schema (commit + built_at)."
)

VERSION_JSON_PATH = "/version.json"


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")

    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    url = origin.rstrip("/") + VERSION_JSON_PATH

    try:
        with _build_client() as client:
            response = client.get(url, timeout=10.0)
    except Exception as e:
        # Network-level failure → warn, not fail. Matches CHECK_090 posture.
        return CheckResult(
            status="warn",
            message=f"version.json unreachable ({type(e).__name__}: {e})",
        )

    if response.status_code == 404:
        return CheckResult(
            status="fail",
            message=(
                f"{url} → 404. Site isn't serving version.json — wire the "
                f"`vite-version-stamp` plugin into vite.config and redeploy. "
                f"See ~/work/projects/builder/vite-version-stamp.ts."
            ),
        )

    if not (200 <= response.status_code < 300):
        return CheckResult(
            status="fail",
            message=f"{url} → HTTP {response.status_code} (expected 200)",
        )

    try:
        payload: Any = response.json()
    except (json.JSONDecodeError, ValueError) as e:
        return CheckResult(
            status="fail",
            message=f"{url} → body did not parse as JSON: {e}",
        )

    if not isinstance(payload, dict):
        return CheckResult(
            status="fail",
            message=f"{url} → expected object, got {type(payload).__name__}",
        )

    commit = payload.get("commit")
    built_at = payload.get("built_at")
    schema = payload.get("schema")

    missing = []
    if not isinstance(commit, str) or not commit.strip():
        missing.append("commit")
    if not isinstance(built_at, str) or not built_at.strip():
        missing.append("built_at")

    if missing:
        return CheckResult(
            status="fail",
            message=(
                f"{url} → missing or invalid: {', '.join(missing)}. "
                f"Expected schema-v1 shape "
                f'{{"schema":1,"commit":"<sha>","built_at":"<iso>"}}.'
            ),
        )

    short_commit = commit[:12] if commit != "unknown" else commit
    schema_note = f" (schema v{schema})" if isinstance(schema, int) else ""
    return CheckResult(
        status="pass",
        message=f"version.json served · commit {short_commit} · built {built_at}{schema_note}",
    )
