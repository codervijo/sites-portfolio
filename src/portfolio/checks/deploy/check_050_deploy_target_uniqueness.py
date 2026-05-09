"""CHECK_050 — Exactly one deploy target declared.

A project should commit to one of: wrangler.jsonc (CF Pages),
vercel.json (Vercel), netlify.toml (Netlify). Multiple is a drift signal.
"""
from __future__ import annotations

from ..result import CheckResult
from . import _deploy_target_files

CHECK_ID = "CHECK_050"
CHECK_NAME = "deploy-target-uniqueness"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = "Exactly one deploy target declared (wrangler/vercel/netlify) or none."


def run(repo_path: str) -> CheckResult:
    targets = _deploy_target_files(repo_path)
    if len(targets) == 0:
        return CheckResult(status="warn",
                           message="no deploy target declared (CLI/library?)")
    if len(targets) == 1:
        return CheckResult(status="pass", message=f"deploy target: {targets[0]}")
    return CheckResult(status="fail",
                       message=f"multiple deploy targets declared: {', '.join(targets)}")
