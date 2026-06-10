"""CHECK_157 — pnpm-lock.yaml is git-tracked (not just present on disk).

v33.N — `CHECK_031` only tests that the lockfile exists *on disk*, so a site
can carry an untracked `pnpm-lock.yaml` that passes CHECK_031 yet isn't
version-controlled — a reproducibility gap (CF builds resolve fresh) and the
same untracked-file class that blocks `project delegate`. Warn-only: the fix
is `git add` + commit, a shared-state git operation outside the file-editing
fixer model, so this surfaces the exact recovery command instead of auto-fixing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_157"
CHECK_NAME = "pnpm-lock-tracked"
CATEGORY = "stack"
SEVERITY = "warn"
DESCRIPTION = "pnpm-lock.yaml is git-tracked (committed, not just present on disk)."


def _is_tracked(repo_path: str, rel: str) -> bool:
    """True if `rel` is tracked by git. On any git error, return True so an
    undeterminable state never produces a false warning."""
    try:
        r = subprocess.run(
            ["git", "ls-files", "--error-unmatch", rel],
            cwd=repo_path, capture_output=True, text=True, timeout=10)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return True


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    lock = Path(repo_path) / "pnpm-lock.yaml"
    if not lock.is_file():
        # Missing lockfile is CHECK_031's domain, not this one.
        return CheckResult(status="pass", message="no pnpm-lock.yaml — n/a (see CHECK_031)")
    if _is_tracked(repo_path, "pnpm-lock.yaml"):
        return CheckResult(status="pass", message="pnpm-lock.yaml is tracked")
    return CheckResult(
        status="fail",
        message="pnpm-lock.yaml present but git-untracked — commit it for "
                "reproducible builds (`git add pnpm-lock.yaml && git commit`)")
