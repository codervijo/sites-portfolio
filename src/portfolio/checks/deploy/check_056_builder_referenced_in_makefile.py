"""CHECK_056 — Makefile references the central builder (BUILDER_PATH or
forwards to ../Makefile)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_056"
CHECK_NAME = "builder-referenced-in-makefile"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = "Makefile references the central builder repo (BUILDER_PATH or `$(MAKE) -C ..`)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "Makefile"
    if not p.is_file():
        return CheckResult(status="warn", message="no Makefile — skipped")
    text = p.read_text(errors="replace")
    if "BUILDER_PATH" in text or "$(MAKE) -C .." in text:
        return CheckResult(status="pass", message="builder reference present")
    return CheckResult(status="warn",
                       message="Makefile present but doesn't reference BUILDER_PATH or ../Makefile")
