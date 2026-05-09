"""CHECK_001 — Has README.md at repo root."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_001"
CHECK_NAME = "has-readme"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "README.md exists at repo root."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "README.md"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message="README.md present")
    return CheckResult(status="fail", message="README.md missing at repo root")
