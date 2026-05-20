"""v15.C/D/E shared `/version.json` fetch + parse + compare helpers.

`version.json` is the v15.C build artifact convention: every sites/*
Vite build emits `dist/version.json` with `{schema, commit, built_at}`.
After deploy, the file is served at `https://<domain>/version.json`.

This module owns the read side. Used by:
  - CHECK_144 has-version-stamp (v15.C) — shape validation
  - CHECK_145 deploy-fresh (v15.D) — HEAD vs deployed comparison
  - CHECK_146 last-build-success (v15.E) — `built_at` freshness
  - `project hosting <domain>` renderer's 📋 Freshness and 🔧 Build
    sections (v15.B → enriched by v15.D + v15.E)

Why split out: three checks + one renderer all want the same fetch
+ parse logic. Keeping it here means the v15.C CHECK_144 stays the
shape-validation authority while v15.D/E layer comparisons on top.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .checks.seo._live import _build_client

VERSION_JSON_PATH = "/version.json"


@dataclass(frozen=True)
class VersionStamp:
    """Parsed shape of `version.json`. v1 schema."""
    schema: Optional[int]
    commit: str
    built_at: str


@dataclass(frozen=True)
class VersionStampError:
    """Why we couldn't read a usable VersionStamp.

    `kind` is one of:
      - "unreachable" — transport error before HTTP layer (DNS, refused)
      - "not_found"   — HTTP 404 (the most common deploy-side issue:
                        plugin not wired into vite.config)
      - "http_error"  — HTTP 4xx/5xx other than 404
      - "not_json"    — response body did not parse as JSON
      - "wrong_shape" — JSON parsed but missing required fields

    Callers (CHECK_144 et al.) map these to pass/warn/fail per their
    own posture.
    """
    kind: str
    detail: str


def fetch_version_stamp(origin: str) -> VersionStamp | VersionStampError:
    """Fetch `<origin>/version.json` and return a VersionStamp or
    VersionStampError. Origin may or may not have a trailing slash."""
    url = origin.rstrip("/") + VERSION_JSON_PATH
    try:
        with _build_client() as client:
            response = client.get(url, timeout=10.0)
    except Exception as e:
        return VersionStampError(
            kind="unreachable",
            detail=f"{type(e).__name__}: {e}",
        )

    if response.status_code == 404:
        return VersionStampError(kind="not_found", detail=f"{url} → 404")

    if not (200 <= response.status_code < 300):
        return VersionStampError(
            kind="http_error",
            detail=f"{url} → HTTP {response.status_code}",
        )

    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError) as e:
        return VersionStampError(
            kind="not_json",
            detail=f"{url} → body did not parse as JSON: {e}",
        )

    if not isinstance(payload, dict):
        return VersionStampError(
            kind="wrong_shape",
            detail=f"{url} → expected object, got {type(payload).__name__}",
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
        return VersionStampError(
            kind="wrong_shape",
            detail=f"{url} → missing or invalid: {', '.join(missing)}",
        )

    return VersionStamp(
        schema=schema if isinstance(schema, int) else None,
        commit=commit.strip(),
        built_at=built_at.strip(),
    )


def local_head_sha(repo_path: str) -> Optional[str]:
    """`git rev-parse HEAD` against `repo_path`. Returns None when:
      - `repo_path` doesn't exist
      - `repo_path` isn't a git repo
      - `git` isn't on PATH

    Operator-side check — does NOT touch the network."""
    base = Path(repo_path)
    if not base.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(base),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


@dataclass(frozen=True)
class FreshnessReport:
    """Output of comparing local HEAD against a live VersionStamp.

    `verdict` is one of:
      - "in_sync"    — HEAD SHA == live commit
      - "drift"      — both known, different SHAs
      - "head_unknown" — couldn't determine local HEAD
      - "live_unknown" — couldn't fetch / parse live stamp
      - "live_marker_unknown" — live commit is the literal "unknown"
                                fallback (deploy ran without git or
                                a cloud-env SHA env var)
    """
    head_sha: Optional[str]
    live_sha: Optional[str]
    verdict: str
    error_detail: Optional[str]


def compare_versions(
    head_sha: Optional[str],
    stamp_or_error: VersionStamp | VersionStampError,
) -> FreshnessReport:
    """Pure comparison — no I/O. Callers pass the results of
    `local_head_sha()` + `fetch_version_stamp()`."""
    if isinstance(stamp_or_error, VersionStampError):
        return FreshnessReport(
            head_sha=head_sha,
            live_sha=None,
            verdict="live_unknown",
            error_detail=stamp_or_error.detail,
        )
    live_sha = stamp_or_error.commit
    if live_sha == "unknown":
        return FreshnessReport(
            head_sha=head_sha,
            live_sha=live_sha,
            verdict="live_marker_unknown",
            error_detail=None,
        )
    if head_sha is None:
        return FreshnessReport(
            head_sha=None,
            live_sha=live_sha,
            verdict="head_unknown",
            error_detail=None,
        )
    if head_sha == live_sha:
        return FreshnessReport(
            head_sha=head_sha,
            live_sha=live_sha,
            verdict="in_sync",
            error_detail=None,
        )
    return FreshnessReport(
        head_sha=head_sha,
        live_sha=live_sha,
        verdict="drift",
        error_detail=None,
    )
