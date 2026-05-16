"""CHECK_013 — AI_AGENTS.md references the two-level versioning convention.

The portfolio uses a strict **two-level `vN.X`** convention canonically
defined in `sites/portfolio/AI_AGENTS.md` under `## Versioning`. Each
sibling project's AI_AGENTS.md should:

1. Reference the convention — either with its own `## Versioning`
   section, or with a marker (`vN.X`) plus a link to the canonical
   statement.
2. Not violate the convention by using three-level identifiers
   (`vN.X.Y`). Lineage markers (`*(was vN.X.Y)*`) introduced during
   a renumber are NOT permitted in the per-project AI_AGENTS file —
   they only belong on the renumbered row inside `docs/prd.md`.

A project that uses `vN.X.Y` anywhere in its AI_AGENTS.md fails fast
with a specific message naming the drift values found, so the operator
sees what to flatten.
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
    "(vN/vN.X) and does not introduce three-level identifiers."
)

# Markers that count as "references the convention." Any one is enough.
_VERSIONING_HEADING = re.compile(r"^##\s+Versioning\b", re.MULTILINE | re.IGNORECASE)
_VN_MARKER = re.compile(r"\bv\d+\.[A-Z]\b")  # `v3.A`, `v5.F`, etc.
_CANONICAL_LINK = re.compile(r"sites/portfolio/AI_AGENTS\.md", re.IGNORECASE)

# Three-level drift — explicitly forbidden by the rule. Catches `v5.F.1`,
# `v6.C.2`, etc. The optional `.<letter-or-digit>` suffix is intentional:
# `\bv\d+\.[A-Z]\.\d+\b` matches the most common drift pattern (suffix is
# a digit, as in `v6.C.2`). Letter suffixes (`v5.A.B`) haven't appeared
# in practice and would require a separate match.
_THREE_LEVEL_DRIFT = re.compile(r"\bv\d+\.[A-Z]\.\d+\b")


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "AI_AGENTS.md"
    if not p.is_file():
        return CheckResult(status="fail", message="AI_AGENTS.md missing")
    text = p.read_text(errors="replace")

    # Drift check first — a project that USES three-level naming is more
    # broken than one that just lacks a Versioning reference. Fail loudly
    # and name the offending identifiers so the operator knows what to
    # flatten.
    drift = _THREE_LEVEL_DRIFT.findall(text)
    if drift:
        offenders = ", ".join(sorted(set(drift)))
        return CheckResult(
            status="fail",
            message=(
                f"AI_AGENTS.md uses three-level versioning ({offenders}) — "
                f"convention is two-level vN.X only; push letters down to flatten."
            ),
        )

    # Reference check — same as before, second priority.
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
- **`vN.X`** — phase letter within a tier (A, B, C, ...). Each
  phase is a shippable slice.

**Two levels only. Never `vN.X.Y`.** When follow-up work emerges
inside an existing tier, push subsequent phase letters down to make
room. Renumbered rows in the canonical `docs/prd.md` carry a
lineage marker (e.g. `*(renumbered YYYY-MM-DD; was v6.A.1)*`) so
the history is preserved on the row that replaced them. Per-project
`AI_AGENTS.md` files should not introduce lineage markers — they
belong only inside `sites/portfolio/`'s `docs/prd.md`.

This standard applies to:

- The phases table in this project's `docs/prd.md`.
- The roadmap-status table in this file.
- Phase references in `docs/Prompts.md` and commit subjects.

Don't introduce parallel schemes (no `0.1.0`, no `Sprint 3`, no
`Phase 1.A`). Don't introduce three-level identifiers under any
circumstance. The canonical statement is in
`sites/portfolio/AI_AGENTS.md`.
"""


fix_tier_1 = section_inject(
    "AI_AGENTS.md", "Versioning",
    render=_versioning_section_template,
    summary="append ## Versioning section to AI_AGENTS.md",
)
