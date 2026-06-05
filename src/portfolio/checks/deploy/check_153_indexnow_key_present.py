"""CHECK_153 — the IndexNow key is provisioned (public/<key>.txt + [index])
so the site can notify Bing/Yandex/... on publish (v30.A).

Warns on a web project whose `lamill.toml` has no provisioned IndexNow key,
so `fleet fix` backfills the fleet. A site opts out with
`[index] indexnow_enabled = false` (→ pass). Delivered as check + fix per
the prefer-check/fix rule.
"""
from __future__ import annotations

from pathlib import Path

from portfolio import indexnow, lamill_toml
from portfolio.fix_helpers import FixerSpec, FixResult
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

from ..result import CheckResult

CHECK_ID = "CHECK_153"
CHECK_NAME = "indexnow-key-present"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "IndexNow key is provisioned (public/<key>.txt + [index]) so the site "
    "can notify Bing/Yandex/... on publish (v30.A)."
)


def _applicable(base: Path) -> bool:
    """A web project with a lamill.toml — IndexNow serves a static key file
    from `public/`, so it needs a buildable site and a place to record the
    key."""
    return (base / "package.json").is_file() and (base / LAMILL_TOML_FILENAME).is_file()


def _opted_out(base: Path) -> bool:
    doc = lamill_toml.load(base)
    return doc is not None and doc.index is not None and not doc.index.indexnow_enabled


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    if not _applicable(base):
        return CheckResult(status="pass", message="not a web project with lamill.toml — not applicable")
    if _opted_out(base):
        return CheckResult(status="pass", message="IndexNow disabled ([index].indexnow_enabled = false)")
    if indexnow.is_provisioned(base):
        return CheckResult(status="pass", message="IndexNow key provisioned")
    return CheckResult(
        status="warn",
        message="no IndexNow key — `project fix` to provision (public/<key>.txt + [index])",
    )


def _fix(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    base = Path(project_dir)
    if not _applicable(base):
        return FixResult("manual", "not a web project with lamill.toml — can't provision IndexNow", [])
    if _opted_out(base):
        return FixResult("nothing-to-do", "IndexNow disabled for this site", [])
    if indexnow.is_provisioned(base):
        return FixResult("nothing-to-do", "IndexNow key already provisioned", [])
    if dry_run:
        return FixResult("would-fix", "generate IndexNow key + write public/<key>.txt + [index]", [])
    key, written = indexnow.provision(base)
    return FixResult(
        "fixed",
        f"provisioned IndexNow key {key[:8]}… (public/{key}.txt + [index])",
        written,
    )


fix_tier_1 = FixerSpec(
    check_id="",
    tier=1,
    summary="provision IndexNow key (public/<key>.txt + [index])",
    apply=_fix,
)
