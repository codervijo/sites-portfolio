"""CHECK_135 — `seo/topics.json` (or content-plan.json) exists and parses."""
from __future__ import annotations

import json
from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_135"
CHECK_NAME = "content-plan-json"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = (
    "Content plan JSON exists and parses (seo/topics.json or "
    "seo/content-plan.json) — the input the worker iterates over."
)

_CANDIDATES = ("topics.json", "content-plan.json")


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    seo = Path(repo_path) / "seo"
    found: Path | None = None
    for name in _CANDIDATES:
        p = seo / name
        if p.is_file():
            found = p
            break
    if found is None:
        return CheckResult(status="fail",
                           message="seo/topics.json (or content-plan.json) missing")
    try:
        json.loads(found.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return CheckResult(status="fail",
                           message=f"seo/{found.name} invalid: {type(e).__name__}")
    return CheckResult(status="pass", message=f"seo/{found.name} parses cleanly")
