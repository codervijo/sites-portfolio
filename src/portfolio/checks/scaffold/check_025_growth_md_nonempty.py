"""CHECK_025 — docs/growth.md is non-empty (not a stub)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import ai_fixer_factory, project_context

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


# No Tier 1 fixer: a templated growth.md doesn't add usable content
# (boilerplate experiments are worse than no experiments — they pollute
# the log). Tier 2 below uses Claude to write real, project-specific
# experiments based on AI_AGENTS.md + package.json.
def _prompt_tier_2(project_dir):
    domain = project_dir.name
    return f"""You are improving a project file for {domain}.

The file `docs/growth.md` exists but is too short — it's failing the
catalog check `CHECK_025 growth-md-nonempty`, which requires >200
chars of body content (lines that are not just markdown headings).

Edit ONLY `docs/growth.md`. Do not touch any other file. Do not run
any tests or commands.

Append 2-3 realistic growth-experiment entries to the file. Each
entry should be a dated H2 heading (`## YYYY-MM-DD — short title`)
followed by:
  - one-line hypothesis
  - the KPI you'd measure
  - the observation window (default 28d)

Pick experiments that fit THIS project, based on its stack and topic
(see context below). Don't invent users or numbers — keep it
concrete but speculative ("hypothesis: ...", "if true we'd see...").

Project context:
{project_context(project_dir)}
"""


fix_tier_2 = ai_fixer_factory(
    "CHECK_025", _prompt_tier_2,
    summary="fill docs/growth.md with real growth experiments",
)
