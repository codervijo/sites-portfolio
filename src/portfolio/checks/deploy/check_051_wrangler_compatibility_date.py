"""CHECK_051 — wrangler.jsonc has compatibility_date set."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _read_jsonc

CHECK_ID = "CHECK_051"
CHECK_NAME = "wrangler-compatibility-date"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = "wrangler.jsonc declares compatibility_date (CF Pages requires it)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "wrangler.jsonc"
    if not p.is_file():
        return CheckResult(status="warn", message="not a CF Pages project — skipped")
    cfg = _read_jsonc(p)
    if cfg is None:
        return CheckResult(status="warn", message="wrangler.jsonc unreadable — skipped")
    cd = cfg.get("compatibility_date")
    if cd:
        return CheckResult(status="pass", message=f"compatibility_date={cd}")
    return CheckResult(status="fail", message="compatibility_date missing")
