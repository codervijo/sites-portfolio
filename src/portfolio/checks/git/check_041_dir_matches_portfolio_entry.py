"""CHECK_041 — directory name appears in data/portfolio.json.

Third check in the naming-consistency cluster (040 = git remote name,
041 = portfolio.json entry, 042 = live HTTP final URL). Catches the
"misnamed sub-directory" failure mode: you intended to create
`sites/homeloom.app/` but typed `sites/homloom.app/` and now nothing
in the canonical inventory anchors that directory.

`fleet drift` reports the same gap at the data layer ("dir_only"),
but that's a separate surface. This check brings the same signal into
the per-project `project check <name>` flow, so it shows up alongside
the other project-level conformance failures rather than only when
the user thinks to run drift.

Pass / fail / warn:
  - pass: directory's basename matches a `name` field in portfolio.json
  - fail: directory exists but no portfolio.json entry has that name
  - warn: portfolio.json couldn't be loaded (rare — surfaces config issue)
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_041"
CHECK_NAME = "dir-matches-portfolio-entry"
CATEGORY = "git"
SEVERITY = "error"
DESCRIPTION = (
    "Project directory name appears as a `name` field in "
    "data/portfolio.json (canonical inventory)."
)


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path).resolve()
    domain = p.name
    # Skip archived sites — their inventory presence is irrelevant if
    # they're being retired.
    try:
        from ...fleet_repos import _archived_reason
        if _archived_reason(p) is not None:
            return CheckResult(status="warn", message="archived — skipped")
    except Exception:
        pass
    try:
        from ...data import load_domains
        domains = load_domains()
    except Exception as e:
        return CheckResult(
            status="warn",
            message=f"could not load portfolio.json: {type(e).__name__}",
        )
    if not domains:
        return CheckResult(
            status="warn",
            message="portfolio.json is empty or missing",
        )
    names = {d.name.lower() for d in domains}
    if domain.lower() in names:
        return CheckResult(status="pass", message=f"matches portfolio entry")
    return CheckResult(
        status="fail",
        message=(f"no portfolio.json row matches {domain!r} — possible "
                 f"typo or missing inventory entry (run `lamill fleet "
                 f"info cleanup` to rebuild from registrar CSVs)"),
    )
