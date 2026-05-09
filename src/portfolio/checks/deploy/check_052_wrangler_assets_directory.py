"""CHECK_052 — wrangler.jsonc: assets.directory = "./dist"."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _read_jsonc

CHECK_ID = "CHECK_052"
CHECK_NAME = "wrangler-assets-directory"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = "wrangler.jsonc has assets.directory set to ./dist."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "wrangler.jsonc"
    if not p.is_file():
        return CheckResult(status="warn", message="not a CF Pages project — skipped")
    cfg = _read_jsonc(p)
    if cfg is None:
        return CheckResult(status="warn", message="wrangler.jsonc unreadable — skipped")
    assets = cfg.get("assets")
    if not isinstance(assets, dict):
        return CheckResult(status="fail", message="wrangler.jsonc missing assets block")
    directory = assets.get("directory")
    if directory == "./dist":
        return CheckResult(status="pass", message='assets.directory="./dist"')
    return CheckResult(status="fail",
                       message=f'assets.directory={directory!r}, expected "./dist"')
