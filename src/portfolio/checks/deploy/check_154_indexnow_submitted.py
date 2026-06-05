"""CHECK_154 — the site's live sitemap URLs have been submitted to IndexNow
(v30.C). The autopilot: its `fix_tier_1` pings the new ones and `fleet fix`
backfills the fleet.

Warns when the sitemap carries URLs not yet in the per-domain submission
ledger. `warn`-severity (not `error`) so a freshly-provisioned-but-not-yet-
deployed site doesn't nag. Gated on IndexNow being provisioned + enabled
(CHECK_153 provisions first). Best-effort network: an unreachable sitemap →
`pass` (nothing to assert).
"""
from __future__ import annotations

from pathlib import Path

import httpx

from portfolio import indexnow, lamill_toml
from portfolio.fix_helpers import FixerSpec, FixResult
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

from ..result import CheckResult

CHECK_ID = "CHECK_154"
CHECK_NAME = "indexnow-submitted"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Live sitemap URLs are submitted to IndexNow (ledger-gated; `project fix` "
    "pings the new ones — v30.C)."
)


def _enabled_key(base: Path) -> str | None:
    """The IndexNow key when the site is provisioned + enabled, else None."""
    if not ((base / "package.json").is_file() and (base / LAMILL_TOML_FILENAME).is_file()):
        return None
    doc = lamill_toml.load(base)
    if doc is None or doc.index is None or not doc.index.indexnow_enabled:
        return None
    return doc.index.indexnow_key or None


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    key = _enabled_key(base)
    if not key:
        return CheckResult(status="pass", message="IndexNow not provisioned/enabled — n/a (see indexnow-key-present)")
    domain = base.name
    current = indexnow.fetch_sitemap_urls(domain)
    if not current:
        return CheckResult(status="pass", message="no reachable sitemap URLs — nothing to submit")
    pending = indexnow.new_urls(domain, current)
    if pending:
        return CheckResult(status="warn",
                           message=f"{len(pending)} sitemap URL(s) not submitted to IndexNow — `project fix` to ping")
    return CheckResult(status="pass", message=f"all {len(current)} sitemap URL(s) submitted to IndexNow")


def _fix(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    base = Path(project_dir)
    key = _enabled_key(base)
    if not key:
        return FixResult("manual", "IndexNow not provisioned — run the indexnow-key-present fix first", [])
    domain = base.name
    current = indexnow.fetch_sitemap_urls(domain)
    pending = indexnow.new_urls(domain, current)
    if not pending:
        return FixResult("nothing-to-do", "ledger current — nothing new to submit", [])
    if dry_run:
        return FixResult("would-fix", f"submit {len(pending)} new URL(s) to IndexNow", [])
    if not indexnow.key_is_live(domain, key):
        # Expected before the key file deploys — defer, don't error.
        return FixResult("manual", f"key not live at https://{domain}/{key}.txt — deploy the site first", [])
    try:
        n = indexnow.submit_urls(domain, key, pending)
    except indexnow.IndexNowError as e:
        return FixResult("error", str(e), [])
    except httpx.HTTPError as e:
        return FixResult("error", f"transient IndexNow failure ({e}) — retry later", [])
    indexnow.append_ledger(domain, pending)
    return FixResult("fixed", f"submitted {n} URL(s) to IndexNow ({domain})", [])


fix_tier_1 = FixerSpec(
    check_id="",
    tier=1,
    summary="submit new sitemap URLs to IndexNow",
    apply=_fix,
)
