"""CHECK_053 — No public/_redirects SPA fallback file (CF Pages bug)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_053"
CHECK_NAME = "wrangler-no-redirects-fallback"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = "No public/_redirects SPA fallback file (CF Pages handles SPA via wrangler.jsonc not_found_handling)."


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    if not (base / "wrangler.jsonc").is_file():
        return CheckResult(status="warn", message="not a CF Pages project — skipped")
    redirects = base / "public" / "_redirects"
    if redirects.is_file():
        return CheckResult(status="fail",
                           message="public/_redirects present — delete; use wrangler.jsonc not_found_handling")
    return CheckResult(status="pass", message="no _redirects fallback")
