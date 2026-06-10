"""CHECK_156 — Astro's generated cache (.astro/) is gitignored.

v33.N — the deferred existing-sites half of v33.I. Pre-v33.I Astro sites were
scaffolded with a `.gitignore` that doesn't list `.astro/`, so the generated
cache accumulates as untracked files — noise that blocks `project delegate`'s
dirty-tree precondition. `fix_tier_1` backfills the entry; `fleet fix` sweeps
the fleet.
"""
from __future__ import annotations

from pathlib import Path

from ... import templates
from ...fix_helpers import FixResult, FixerSpec
from ..result import CheckResult
from . import NON_JS_FRAMEWORKS, _has_astro_config, _is_web_project, declared_stack

CHECK_ID = "CHECK_156"
CHECK_NAME = "astro-cache-gitignored"
CATEGORY = "stack"
SEVERITY = "warn"
DESCRIPTION = (
    "Astro's generated .astro/ cache is gitignored "
    "(keeps the working tree clean for `project delegate`)."
)


def _gitignore_lists_astro(repo_path: str) -> bool:
    gi = Path(repo_path) / ".gitignore"
    if not gi.is_file():
        return False
    return any(
        line.strip().rstrip("/") == ".astro"
        for line in gi.read_text(errors="replace").splitlines()
    )


def run(repo_path: str) -> CheckResult:
    # Mirror CHECK_036's stack-gating: [stack] declaration first (skip non-JS),
    # then the astro.config.* heuristic — so this works whether or not the site
    # carries a [stack] table (additive-optional invariant).
    declared = declared_stack(repo_path)
    if declared in NON_JS_FRAMEWORKS:
        return CheckResult(status="warn",
                           message=f"stack declared {declared} — not an astro site")
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if not _has_astro_config(repo_path):
        return CheckResult(status="warn", message="not an Astro project — skipped")
    if _gitignore_lists_astro(repo_path):
        return CheckResult(status="pass", message=".astro/ is gitignored")
    return CheckResult(
        status="fail",
        message=".astro/ not in .gitignore — generated cache accumulates as "
                "untracked files (blocks `project delegate`)")


_ASTRO_BLOCK = "# Astro (generated content cache + types — never tracked)\n.astro/\n"


def _fix(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    gi = project_dir / ".gitignore"
    if _gitignore_lists_astro(str(project_dir)):
        return FixResult("nothing-to-do", ".astro/ already gitignored", [])
    if not gi.is_file():
        # No .gitignore at all — write the full standard one (now includes
        # .astro/), which also satisfies CHECK_009.
        if dry_run:
            return FixResult("would-fix", "write standard .gitignore (incl .astro/)", [gi])
        gi.write_text(templates.gitignore(), encoding="utf-8")
        return FixResult("fixed", "wrote standard .gitignore", [gi])
    if dry_run:
        return FixResult("would-fix", "append .astro/ to .gitignore", [gi])
    existing = gi.read_text(errors="replace")
    sep = "" if existing.endswith("\n") else "\n"
    gi.write_text(existing + sep + "\n" + _ASTRO_BLOCK, encoding="utf-8")
    return FixResult("fixed", "appended .astro/ to .gitignore", [gi])


fix_tier_1 = FixerSpec(
    check_id="",
    tier=1,
    summary="gitignore Astro's .astro/ cache",
    apply=_fix,
)
