"""CHECK_141 — Repo has no git submodules (gitlinks in tree).

Cloudflare Pages does NOT clone submodules during its build. A repo
with submodules silently produces broken deploys (missing source
code at runtime). v6.B catches this statically.

Detection: `git ls-files --stage` returns mode `160000` for any
submodule entry. Skip if not a git repo.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_141"
CHECK_NAME = "no-git-submodules"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = (
    "No git submodules in tree (CF Pages doesn't clone them; their "
    "presence silently breaks deploys)."
)


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path)
    if not (p / ".git").exists():
        return CheckResult(status="warn", message="not a git repo — skipped")
    try:
        result = subprocess.run(
            ["git", "ls-files", "--stage"],
            cwd=p, capture_output=True, text=True, check=False, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult(status="warn",
                           message=f"git: {type(e).__name__}")
    if result.returncode != 0:
        return CheckResult(status="warn",
                           message=f"git ls-files failed: {result.stderr.strip()}")
    submodules = []
    for line in result.stdout.splitlines():
        if line.startswith("160000"):
            # Format: "160000 <sha> 0	<path>"
            parts = line.split("\t", 1)
            if len(parts) == 2:
                submodules.append(parts[1])
    if not submodules:
        return CheckResult(status="pass", message="no submodules in tree")
    return CheckResult(
        status="fail",
        message=f"{len(submodules)} submodule(s) — CF Pages won't clone them: {', '.join(submodules[:3])}",
    )
