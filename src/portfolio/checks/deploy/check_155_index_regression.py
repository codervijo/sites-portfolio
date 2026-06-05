"""CHECK_155 — index-regression: a previously-indexed URL has fallen out of
Google's index (v30.E).

Diffs the two most recent GSC URL-Inspection snapshots
(`data/gsc/<domain>/<date>.json`, the `v16c_inspections` cached by
CHECK_147). Monitoring only — deindexing isn't operator-auto-fixable, so
there is **no fixer**; the regression surfaces in `project`/`fleet check`.
`warn`, not `fail`: a drop can be transient/external, so it's a signal to
investigate, not a hard conformance break.
"""
from __future__ import annotations

from pathlib import Path

from ... import gsc_detail_cache

from ..result import CheckResult

CHECK_ID = "CHECK_155"
CHECK_NAME = "index-regression"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "No previously-indexed URL has dropped out of Google's index "
    "(URL-Inspection snapshot diff; v30.E)."
)

# Same canonical "indexed" coverage states CHECK_147 keys on.
_INDEXED_STATES = frozenset({
    "Submitted and indexed",
    "Indexed, not submitted in sitemap",
})


def _coverage_by_url(path) -> dict[str, str]:
    """`{url: coverage_state}` from a GSC snapshot ({} when unreadable)."""
    try:
        snap = gsc_detail_cache.load_snapshot(path)
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for insp in snap.get("v16c_inspections", []):
        url = insp.get("url")
        if url:
            out[url] = insp.get("coverage_state") or ""
    return out


def _short(url: str, n: int = 48) -> str:
    return url if len(url) <= n else url[: n - 1] + "…"


def run(repo_path: str) -> CheckResult:
    domain = Path(repo_path).resolve().name
    snaps = gsc_detail_cache.list_snapshots(domain)
    if len(snaps) < 2:
        return CheckResult(status="pass",
                           message="not enough index history to compare (need 2 snapshots)")
    newer = _coverage_by_url(snaps[0])
    older = _coverage_by_url(snaps[1])
    regressed = [
        url for url, prev in older.items()
        if prev in _INDEXED_STATES and url in newer and newer[url] not in _INDEXED_STATES
    ]
    if regressed:
        preview = ", ".join(_short(u) for u in regressed[:3])
        more = f" (+{len(regressed) - 3} more)" if len(regressed) > 3 else ""
        return CheckResult(
            status="warn",
            message=f"{len(regressed)} URL(s) dropped from the index: {preview}{more}",
        )
    return CheckResult(status="pass", message=f"no index regressions ({len(newer)} URLs checked)")
