"""CHECK_145 — Live site's deployed commit matches local HEAD (v15.D).

Pairs with CHECK_144 (has-version-stamp). CHECK_144 ensures the
build artifact convention is followed; CHECK_145 ensures the latest
local commit is actually what's on the wire.

Reads `<live_url>/version.json`'s `commit` field and compares against
the operator's local `git rev-parse HEAD`.

Pass / warn / fail:
  - pass: local HEAD == live commit
  - fail: known mismatch — operator has unshipped local commits
          (or the deploy is ahead of local HEAD, which is rare and
          indicates branch divergence)
  - warn: can't determine one side
          * not a web project / no live URL
          * version.json unreachable / 404 / malformed
            (CHECK_144 surfaces those — don't double-fail here)
          * local HEAD undetermined (not a git repo / git missing)
          * deploy ran without git context (commit literal "unknown")

The fail message includes both SHAs (short form) so the operator can
diff. Common cause: forgot to `git push` or deploy pipeline isn't
wired up yet.
"""
from __future__ import annotations

from ..result import CheckResult
from ..seo._live import resolve_live_url
from ..seo import _is_web_project
from ...version_stamp import (
    compare_versions,
    fetch_version_stamp,
    local_head_sha,
)

CHECK_ID = "CHECK_145"
CHECK_NAME = "deploy-fresh"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Live site's deployed commit matches local HEAD (HEAD-vs-deployed drift signal)."
)


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")

    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    stamp_or_error = fetch_version_stamp(origin)
    head = local_head_sha(repo_path)
    report = compare_versions(head, stamp_or_error)

    if report.verdict == "in_sync":
        short = report.live_sha[:12] if report.live_sha else "?"
        return CheckResult(
            status="pass",
            message=f"HEAD matches live · {short}",
        )

    if report.verdict == "drift":
        head_short = (report.head_sha or "?")[:12]
        live_short = (report.live_sha or "?")[:12]
        return CheckResult(
            status="fail",
            message=(
                f"deploy drift · HEAD {head_short} ≠ live {live_short}. "
                f"Push + redeploy, or check whether the deploy pipeline is wired up."
            ),
        )

    if report.verdict == "head_unknown":
        return CheckResult(
            status="warn",
            message=(
                "can't determine local HEAD — not a git repo or `git` unavailable. "
                "v15.D needs `git rev-parse HEAD` to compute drift."
            ),
        )

    if report.verdict == "live_unknown":
        return CheckResult(
            status="warn",
            message=(
                f"can't read live version.json ({report.error_detail}) — "
                f"CHECK_144 surfaces the underlying cause."
            ),
        )

    if report.verdict == "live_marker_unknown":
        return CheckResult(
            status="warn",
            message=(
                "live version.json has commit=\"unknown\" — deploy ran without "
                "git context. Set CF_PAGES_COMMIT_SHA / VERCEL_GIT_COMMIT_SHA / "
                "GITHUB_SHA in the build env."
            ),
        )

    # Unknown verdict — defensive fallthrough.
    return CheckResult(
        status="warn",
        message=f"unexpected freshness verdict: {report.verdict}",
    )
