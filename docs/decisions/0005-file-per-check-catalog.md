# 0005 — File-per-check catalog (not centralized registry)

- **Status:** Accepted
- **Date:** 2026-05-09 *(v5.A — catalog foundation shipped)*

## Context

The conformance rule catalog grew during v5 design to ~85 numbered
checks across categories: scaffold, git, stack, deploy, SEO,
content-pipeline, live HTTP, GSC, CrUX. Two organizational shapes
were considered:

1. **Centralized registry.** A single `checks.py` (or a few
   category-grouped modules) holds all rule definitions as a list
   of objects, each pointing at a `run()` function.
2. **File-per-check.** Each rule lives in its own module file
   (`check_NNN_<slug>.py`) with module-level constants and `run()`.
   A registry walks these modules at import time and auto-discovers.

Forces:
- The catalog was expected to keep growing — adding rules should be
  cheap.
- Some checks pair with fixers (Tier 1 templated; Tier 2 Claude
  subprocess). Co-locating check + fixer reduces context-switching.
- Operator familiarity with ESLint / Ruff / Stylelint rule
  organization (file-per-rule patterns).

## Decision

**File-per-check.**

- Path shape: `src/portfolio/checks/<category>/check_NNN_<slug>.py`.
- Each module declares module-level constants:
  `CHECK_ID`, `CHECK_NAME`, `CATEGORY`, `SEVERITY`, `DESCRIPTION`.
- Each module declares `run(repo_path) -> CheckResult` where
  `CheckResult` is a dataclass with `status: "pass" | "fail" | "warn"`
  and a `message: str`.
- Optional `fix_tier_1` / `fix_tier_2` module-level attributes hold
  `FixerSpec` records that the fix registry discovers (see ADR-0006).
- A registry (`registry.py`) walks the `checks/` package at import
  time and auto-discovers; no manual registration list.

## Consequences

**Positive.**
- Adding a check is a single small file — high-friction "register
  in N places" workflows avoided.
- Co-located fixers — the check and its fix templates live next to
  each other, matching ESLint/Ruff conventions.
- Easy to grep (`CHECK_032` → `check_032_*.py`).
- Removing or renaming a check is a single file delete or rename;
  the registry adapts automatically.

**Negative.**
- ~85 files in `src/portfolio/checks/` (today). Discovery requires
  walking the tree, not reading a single index file.
- Auto-discovery has a small import-time cost (~tens of ms).

## References

- `src/portfolio/checks/` layout.
- `src/portfolio/registry.py`.
- `src/portfolio/fix_registry.py`.
- ADR-0006 — Tier 2 fixers as Claude subprocess (uses the
  co-located-fixer pattern this ADR establishes).
- v5.A — Universal check catalog foundation.
