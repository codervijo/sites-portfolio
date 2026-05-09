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
