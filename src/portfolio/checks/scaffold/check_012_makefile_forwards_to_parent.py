"""CHECK_012 — Local Makefile forwards to ../Makefile (kwizicle pattern).

The canonical sites/* Makefile is short and forwards every target to the
parent Makefile (the central builder). Pattern from kwizicle.com:
    PROJ := <name>
    %:
        $(MAKE) -C .. $@ proj=$(PROJ)
"""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import FixResult, FixerSpec
from ... import templates

CHECK_ID = "CHECK_012"
CHECK_NAME = "makefile-forwards-to-parent"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = "Local Makefile forwards every target to ../Makefile (central-builder pattern)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "Makefile"
    if not p.exists():
        return CheckResult(status="fail", message="Makefile missing")
    text = p.read_text(errors="replace")
    # Look for the catch-all forward pattern: %: \n\t$(MAKE) -C .. ...
    if re.search(r"\$\(MAKE\)\s+-C\s+\.\.", text):
        return CheckResult(status="pass", message="Makefile forwards to parent")
    return CheckResult(status="warn",
                       message="Makefile present but doesn't appear to forward to ../Makefile")


# CHECK_012 fix: write a forwarding Makefile, but ONLY if absent. If a
# Makefile exists that doesn't forward, refuse — overwriting an existing
# Makefile is too risky for an auto-fix; the user reviews by hand.
def _fix_check_012(project_dir, dry_run, assume_yes):
    target = project_dir / "Makefile"
    if target.is_file():
        return FixResult("manual",
                         "Makefile exists but doesn't forward — review by hand",
                         [])
    if dry_run:
        return FixResult("would-fix", "write forwarding Makefile", [target])
    target.write_text(templates.local_makefile(project_dir.name))
    return FixResult("fixed", "wrote forwarding Makefile", [target])


fix_tier_1 = FixerSpec(
    check_id="", tier=1,
    summary="write forwarding Makefile (only if absent)",
    apply=_fix_check_012,
)
