"""CHECK_039 — TypeScript config present (info — TS adoption signal)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_039"
CHECK_NAME = "has-tsconfig"
CATEGORY = "stack"
SEVERITY = "info"
DESCRIPTION = "tsconfig.json present (info — TypeScript adoption signal)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if (Path(repo_path) / "tsconfig.json").is_file():
        return CheckResult(status="pass", message="tsconfig.json present")
    # JS-only projects shouldn't be penalized — only warn when source
    # files indicate the project is using (or trying to use) TypeScript.
    src = Path(repo_path) / "src"
    has_ts_sources = src.exists() and any(src.rglob("*.ts")) or any(src.rglob("*.tsx") if src.exists() else [])
    if not has_ts_sources:
        return CheckResult(status="warn",
                           message="not a TypeScript project (no .ts files) — skipped")
    return CheckResult(status="warn", message="tsconfig.json missing despite .ts sources")
