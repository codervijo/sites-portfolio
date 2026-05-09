"""CHECK_028 — Last deployment commit within the last 60 days.

A "deployment commit" is heuristically detected by scanning recent commit
subjects for deploy/release markers. Only applicable to repos whose
Makefile has a `deploy:` target — pure libraries are skipped.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_028"
CHECK_NAME = "last-deploy-date"
CATEGORY = "git"
SEVERITY = "info"
DESCRIPTION = "Most recent deploy-marked commit is within the last 60 days (only when Makefile has a deploy target)."

_DEPLOY_PATTERNS = re.compile(
    r"(deploy|release|publish|ship|cf pages|cloudflare)",
    re.IGNORECASE,
)
_MAX_AGE_DAYS = 60


def _has_deploy_target(repo_path: str) -> bool:
    mk = Path(repo_path) / "Makefile"
    if not mk.is_file():
        return False
    try:
        text = mk.read_text(errors="replace")
    except OSError:
        return False
    return bool(re.search(r"^deploy\s*:", text, flags=re.MULTILINE))


def run(repo_path: str) -> CheckResult:
    if not (Path(repo_path) / ".git").exists():
        return CheckResult(status="warn", message="not a git repo — skipped")
    if not _has_deploy_target(repo_path):
        return CheckResult(status="warn", message="Makefile has no `deploy:` target — skipped")
    try:
        # Last 50 commits, ISO-formatted dates, subject lines only.
        out = subprocess.run(
            ["git", "log", "-n", "50", "--format=%cI%x09%s"],
            cwd=repo_path, capture_output=True, text=True, timeout=10, check=True,
        ).stdout
    except (subprocess.SubprocessError, OSError) as e:
        return CheckResult(status="warn",
                           message=f"git log failed: {type(e).__name__}")
    deploy_iso: str | None = None
    deploy_subject: str | None = None
    for line in out.splitlines():
        iso, _, subject = line.partition("\t")
        if _DEPLOY_PATTERNS.search(subject):
            deploy_iso = iso
            deploy_subject = subject
            break
    if deploy_iso is None:
        return CheckResult(status="fail",
                           message="no deploy-marked commit in the last 50")
    try:
        when = datetime.fromisoformat(deploy_iso)
    except ValueError:
        return CheckResult(status="warn", message=f"unparseable date: {deploy_iso}")
    age_days = (datetime.now(timezone.utc) - when).days
    snippet = (deploy_subject or "")[:60]
    if age_days <= _MAX_AGE_DAYS:
        return CheckResult(status="pass",
                           message=f"{age_days}d ago — {snippet!r}")
    return CheckResult(status="fail",
                       message=f"{age_days}d ago (stale) — {snippet!r}")
