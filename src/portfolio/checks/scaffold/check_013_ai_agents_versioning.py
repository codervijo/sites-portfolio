"""CHECK_013 — AI_AGENTS.md references the two-level versioning convention.

The portfolio uses a `vN` / `vN.X` / `vN.X.Y` convention canonically
defined in `sites/portfolio/AI_AGENTS.md`. Each project's AI_AGENTS.md
should reference the convention so contributors (and Claude sessions)
know which numbering scheme to follow when adding phases / sub-phases
to that project's prd.md.

A passing project either has a `## Versioning` section, OR mentions
`vN.X` (or similar marker) and links / references
`sites/portfolio/AI_AGENTS.md` as the canonical source.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import section_inject

CHECK_ID = "CHECK_013"
CHECK_NAME = "ai-agents-references-versioning"
CATEGORY = "scaffold"
SEVERITY = "warn"
DESCRIPTION = (
    "AI_AGENTS.md references the two-level versioning convention "
    "(vN/vN.X) — either a `## Versioning` section or a link to "
    "the canonical statement in `sites/portfolio/AI_AGENTS.md`."
)

# Markers that count as "references the convention." Any one is enough.
_VERSIONING_HEADING = re.compile(r"^##\s+Versioning\b", re.MULTILINE | re.IGNORECASE)
_VN_MARKER = re.compile(r"\bv\d+\.[A-Z]\b")  # `v3.A`, `v5.F`, etc.
_CANONICAL_LINK = re.compile(r"sites/portfolio/AI_AGENTS\.md", re.IGNORECASE)


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "AI_AGENTS.md"
    if not p.is_file():
        return CheckResult(status="fail", message="AI_AGENTS.md missing")
    text = p.read_text(errors="replace")
    if _VERSIONING_HEADING.search(text):
        return CheckResult(status="pass", message="`## Versioning` section present")
    if _VN_MARKER.search(text) and _CANONICAL_LINK.search(text):
        return CheckResult(status="pass",
                           message="versioning marker + canonical reference present")
    return CheckResult(
        status="fail",
        message=(
            "AI_AGENTS.md doesn't reference the two-level versioning "
            "convention — add a `## Versioning` section or link to "
            "sites/portfolio/AI_AGENTS.md"
        ),
    )


def _versioning_section_template(_project_dir):
    return """\
## Versioning

This project follows the sites/* **canonical versioning convention**
(defined in `sites/portfolio/AI_AGENTS.md`):

- **`vN`** — major capability tier (SemVer-MAJOR semantics).
- **`vN.X`** — phase letter within a tier (A, B, C, …) for
  internal slicing.
- **`vN.X.Y`** — numeric sub-phase for follow-up work that lands
  AFTER `vN.X` shipped (polish, bug fixes, scope cuts).

**Always use this numbering when planning or shipping work on this
project.** Specifically:

- Every entry in `docs/prd.md`'s phases table uses `vN.X` (or `vN.X.Y`).
- Every commit message that ships a phase mentions its version
  (e.g. `v1.B — auth flow`).
- Every entry in `docs/Prompts.md` references the version of the
  work it describes when relevant.

Don't introduce a parallel scheme (no `0.1.0` / `Sprint 3` / etc.).
When in doubt, the canonical statement is
`sites/portfolio/AI_AGENTS.md`.
"""


fix_tier_1 = section_inject(
    "AI_AGENTS.md", "Versioning",
    render=_versioning_section_template,
    summary="append ## Versioning section to AI_AGENTS.md",
)
