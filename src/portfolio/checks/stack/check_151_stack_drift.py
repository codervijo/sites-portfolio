"""CHECK_151 — stack-declaration drift.

Compares the framework declared in `lamill.toml [stack].framework`
against what's actually detected in the project dir. Mirrors
`CHECK_143 deploy-drift` for the deploy platform.

Two drift signals:

  1. **Primary mismatch** — `stack_classifier.classify_stack()` detects a
     framework different from the declaration. Catches an accidental
     in-flight migration where the primary framework changed but the
     declaration didn't (e.g. a site re-scaffolded to nextjs while
     `[stack]` still says astro).

  2. **Foreign config files** — a framework-specific config file present
     that doesn't belong to the declared framework (e.g. a root
     `vite.config.ts` lingering on an astro-declared site — the
     `lamillrentals.com` two-config case from the v27.C backfill).

Category `stack`, severity `warn` — drift is a heads-up, not a hard
failure; the declaration may be intentionally ahead of a migration in
progress. Honors the additive-optional invariant: no `lamill.toml` or no
`[stack]` table → warn-skip (nothing to compare), never fail. A parse
error defers to CHECK_059 (same posture as CHECK_143).
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import foreign_config_markers
from ...lamill_toml import LAMILL_TOML_FILENAME, ParseError, load
from ...stack_classifier import classify_stack

CHECK_ID = "CHECK_151"
CHECK_NAME = "stack-drift"
CATEGORY = "stack"
SEVERITY = "warn"
DESCRIPTION = (
    "`lamill.toml` declared `[stack].framework` matches the framework "
    "detected from project markers (catches stale declarations + "
    "migration-artifact config files)."
)


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)

    if not (base / LAMILL_TOML_FILENAME).is_file():
        return CheckResult(status="warn",
                           message="no lamill.toml — drift not checkable")

    try:
        decl = load(base)
    except ParseError as e:
        return CheckResult(
            status="warn",
            message=f"{LAMILL_TOML_FILENAME} invalid — see CHECK_059 ({e})",
        )

    if decl is None or decl.stack is None:
        return CheckResult(status="warn",
                           message="no [stack] declaration — drift not checkable")

    declared = decl.stack.framework
    reasons: list[str] = []

    # Signal 1 — primary framework mismatch. `classify_stack().framework`
    # is None when detection is inconclusive (e.g. no package.json),
    # which is not drift — there's simply nothing to compare against.
    detected = classify_stack(base).framework
    if detected is not None and detected != declared:
        reasons.append(f"detected {detected} from project markers")

    # Signal 2 — stray framework config files.
    foreign = foreign_config_markers(base, declared)
    if foreign:
        reasons.append(f"foreign config: {', '.join(foreign)}")

    if reasons:
        return CheckResult(
            status="fail",
            message=(
                f"DRIFT — declared [stack]={declared} but "
                f"{'; '.join(reasons)}. Update lamill.toml or remove the "
                f"migration artifact."
            ),
        )

    return CheckResult(status="pass",
                       message=f"declared {declared} matches detected signals")
