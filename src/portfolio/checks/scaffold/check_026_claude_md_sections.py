"""CHECK_026 — docs/CLAUDE.md has minimum sections (## Project, ## Commands)."""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_026"
CHECK_NAME = "claude-md-min-sections"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/CLAUDE.md declares both `## Project` and `## Commands` sections."

_REQUIRED = ("Project", "Commands")


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "CLAUDE.md"
    if not p.is_file():
        return CheckResult(status="warn", message="docs/CLAUDE.md missing — skipped")
    text = p.read_text(errors="replace")
    headings = re.findall(r"^##\s+(.+)$", text, flags=re.MULTILINE)
    headings_norm = {h.strip().lower() for h in headings}
    missing = [h for h in _REQUIRED if h.lower() not in headings_norm]
    if not missing:
        return CheckResult(status="pass", message="`## Project` + `## Commands` present")
    return CheckResult(status="fail",
                       message=f"missing section(s): {', '.join('## ' + m for m in missing)}")
