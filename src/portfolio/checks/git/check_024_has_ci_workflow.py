"""CHECK_024 — Has a CI workflow (.github/workflows/ with at least one *.yml)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_024"
CHECK_NAME = "has-ci-workflow"
CATEGORY = "git"
SEVERITY = "info"
DESCRIPTION = "Has at least one workflow file under .github/workflows/."


def run(repo_path: str) -> CheckResult:
    workflows = Path(repo_path) / ".github" / "workflows"
    if not workflows.is_dir():
        return CheckResult(status="warn", message=".github/workflows/ missing")
    yml = list(workflows.glob("*.yml")) + list(workflows.glob("*.yaml"))
    if not yml:
        return CheckResult(status="warn", message=".github/workflows/ has no *.yml")
    return CheckResult(status="pass",
                       message=f"{len(yml)} workflow file(s)")
