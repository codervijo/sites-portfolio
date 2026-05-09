"""CHECK_027 — docs/prd.md has minimum sections (## Problem, ## Users)."""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_027"
CHECK_NAME = "prd-md-min-sections"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/prd.md declares both `## Problem` and `## Users` sections."

_REQUIRED = ("Problem", "Users")


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "prd.md"
    if not p.is_file():
        return CheckResult(status="warn", message="docs/prd.md missing — skipped")
    text = p.read_text(errors="replace")
    headings = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    # Permit numbered heading prefixes ("## 1. Problem", "## 2. Users").
    headings_norm = {
        re.sub(r"^\d+\.\s*", "", h.strip()).strip().lower()
        for h in headings
    }
    missing = [h for h in _REQUIRED if h.lower() not in headings_norm]
    if not missing:
        return CheckResult(status="pass", message="`## Problem` + `## Users` present")
    return CheckResult(status="fail",
                       message=f"missing section(s): {', '.join('## ' + m for m in missing)}")
