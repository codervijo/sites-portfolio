"""CHECK_055 — vercel.json parses cleanly (no syntax errors)."""
from __future__ import annotations

import json
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_055"
CHECK_NAME = "vercel-config-sane"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = "vercel.json parses as valid JSON (sanity check; deeper rule analysis deferred)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "vercel.json"
    if not p.is_file():
        return CheckResult(status="warn", message="not a Vercel project — skipped")
    try:
        cfg = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult(status="fail", message=f"vercel.json invalid: {type(e).__name__}")
    if not isinstance(cfg, dict):
        return CheckResult(status="fail", message="vercel.json must be a JSON object")
    return CheckResult(status="pass", message="vercel.json parses cleanly")
