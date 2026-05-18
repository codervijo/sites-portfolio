# 0006 — Tier 2 fixers as Claude subprocess

- **Status:** Accepted
- **Date:** 2026-05-09 *(v6.E shipped)*

## Context

Tier 1 fixers (file-writer factories, section-injection, file
deletion via `fix_helpers.py`) handle ~80% of conformance gaps
mechanically. They're idempotent, deterministic, and cheap.

The remaining ~20% need genuine content authoring: real growth
experiments (CHECK_025), real `docs/CLAUDE.md` Project/Commands
content (CHECK_026), real `docs/prd.md` Problem/Users content
(CHECK_027). Templating produces "Fill in here" placeholders that
fail the same check on re-run.

Two architectures were on the table for Tier 2:

1. **Embed the Anthropic SDK directly** in `portfolio`. Call the
   model from inside the CLI process. Manage API keys, retries,
   rate limits, streaming, conversation state, tool use.
2. **Spawn `claude -p` as a subprocess** in the project directory
   with a constrained tool surface and a hard cost cap.

## Decision

**Subprocess.** `claude -p` is invoked non-interactively in the
target project's directory:

- `--allowedTools "Read Edit Glob Grep"` — restricted toolset.
  No `Bash`, no shell, no network beyond what Read/Edit need.
- `--max-budget-usd` as a hard cost cap per fixer invocation.
- Stop criterion: re-run the targeted check after Claude exits.
  Pass → fixer is reported as fixed. Fail → fixer reports error
  with Claude's reason.
- Each fixer module supplies a project-specific prompt builder
  pulling context from `AI_AGENTS.md` + `package.json` /
  `pyproject.toml`.

Three Tier 2 fixers shipped at v6.E: CHECK_025, CHECK_026,
CHECK_027. The pattern extends to any future check needing real
content rather than templates.

## Consequences

**Positive.**
- No embedded SDK to maintain — Claude Code handles auth, retry,
  streaming, conversation state.
- Restricted tool surface inherits Claude Code's tool sandboxing
  (no Bash, no shell escape).
- Hard cost cap per fixer (a runaway loop is bounded).
- Each fixer is a small project-context-aware prompt-builder, not
  a single mega-prompt with branching.
- Leverages Claude Code's existing project-context tooling
  (`@`-references, file globbing, etc.).
- Updates to Claude Code itself (new models, better prompts,
  better tool use) propagate without code changes here.

**Negative.**
- Subprocess overhead per fixer (~1–2 s spin-up + model latency).
- Per-fixer cost is variable and non-deterministic.
- A Claude Code update could change behavior in subtle ways — coupled
  to an external CLI's release cadence.

## References

- `src/portfolio/fix_helpers.py` — `run_claude`, `claude_available`,
  `ai_fixer_factory`, `project_context`.
- `src/portfolio/fix_registry.py` — discovers `fix_tier_1` /
  `fix_tier_2` from each check module.
- v6.E — Remediation Tier 2 + co-located fixer architecture.
- ADR-0005 — File-per-check catalog (the co-location pattern this
  ADR builds on).
