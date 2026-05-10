"""CHECK_142 — `.gitignore` covers stack-specific build output dirs.

Extends CHECK_038 (which only checks `node_modules`). Build output
dirs that should be ignored:
  - `dist/`     — Vite, Astro
  - `build/`    — generic
  - `.next/`    — Next.js
  - `.astro/`   — Astro cache

Check passes if at least the relevant ones for the project's stack
are present. Skip on non-web projects (no package.json).
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import FixResult, FixerSpec
from . import _is_web_project

CHECK_ID = "CHECK_142"
CHECK_NAME = "gitignore-covers-build-output"
CATEGORY = "stack"
SEVERITY = "warn"
DESCRIPTION = (
    "`.gitignore` covers stack-specific build output dirs "
    "(dist/, build/, .next/, .astro/)."
)

# We require at least dist/ (most universal). build/, .next/, .astro/
# are nice-to-have but their absence isn't a fail since most stacks
# don't produce all four.
_REQUIRED = ("dist/",)
_OPTIONAL = ("build/", ".next/", ".astro/")


def _gitignored_lines(text: str) -> set[str]:
    """Return the set of non-comment, non-empty lines (stripped)."""
    return {
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    p = Path(repo_path) / ".gitignore"
    if not p.is_file():
        return CheckResult(status="warn",
                           message=".gitignore missing — skipped")
    text = p.read_text(errors="replace")
    entries = _gitignored_lines(text)
    missing_required = [e for e in _REQUIRED if e not in entries
                        and e.rstrip("/") not in entries]
    if missing_required:
        return CheckResult(
            status="fail",
            message=f".gitignore missing build-output entries: {', '.join(missing_required)}",
        )
    return CheckResult(status="pass",
                       message="dist/ in .gitignore (build output covered)")


# Tier 1 fixer: append missing required + optional entries that aren't
# already in .gitignore. Idempotent (skip what's already there).
def _fix_check_142(project_dir, dry_run, assume_yes):
    target = project_dir / ".gitignore"
    if not target.is_file():
        return FixResult("manual",
                         ".gitignore doesn't exist — fix CHECK_009 first",
                         [])
    text = target.read_text()
    entries = _gitignored_lines(text)
    to_add = [e for e in (_REQUIRED + _OPTIONAL)
              if e not in entries and e.rstrip("/") not in entries]
    if not to_add:
        return FixResult("nothing-to-do",
                         ".gitignore already covers all build-output dirs", [])
    if dry_run:
        return FixResult("would-fix",
                         f"append {', '.join(to_add)} to .gitignore",
                         [target])
    new_text = text.rstrip("\n") + "\n\n# Build output\n" + "\n".join(to_add) + "\n"
    target.write_text(new_text)
    return FixResult("fixed",
                     f"appended {', '.join(to_add)} to .gitignore",
                     [target])


fix_tier_1 = FixerSpec(
    check_id="", tier=1,
    summary="append build-output entries to .gitignore",
    apply=_fix_check_142,
)
