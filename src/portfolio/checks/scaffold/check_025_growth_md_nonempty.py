"""CHECK_025 — docs/growth.md is non-empty (not a stub)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_025"
CHECK_NAME = "growth-md-nonempty"
CATEGORY = "docs"
SEVERITY = "warn"
DESCRIPTION = "docs/growth.md has substantive content (>200 chars after stripping headings)."

_MIN_CONTENT_CHARS = 200


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "docs" / "growth.md"
    if not p.is_file():
        return CheckResult(status="warn", message="docs/growth.md missing — skipped")
    text = p.read_text(errors="replace")
    # Strip heading-only lines so a wall of #-headers doesn't pass.
    body_lines = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    body = "\n".join(body_lines).strip()
    if len(body) >= _MIN_CONTENT_CHARS:
        return CheckResult(status="pass",
                           message=f"{len(body)} chars of body content")
    return CheckResult(status="fail",
                       message=f"only {len(body)} chars of body (stub — needs >{_MIN_CONTENT_CHARS})")
