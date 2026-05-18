# 0009 — Makefile forwards to central builder

- **Status:** Accepted
- **Date:** 2026-04-30 *(v3 bootstrap shipped with this pattern)*

## Context

30+ sibling `sites/<domain>/` projects share the same JS-stack build
pipeline: pnpm install, Vite/Astro build, dist/ output, deploy via
`wrangler` or platform-native auto-deploy. Duplicating build logic
across each project's `Makefile` would mean 30+ places to update
when the pipeline evolves (new Vite/Astro major, new linter, new
test runner, ...).

Alternative considered: pure Vite/npm-script-based pipelines without
Makefiles. Rejected because (a) the operator's muscle memory is
`make run`, `make build`, `make test` regardless of stack, (b) some
sites use stacks where the npm-script story is incomplete (Astro
content collections + custom scripts), (c) Makefile-as-thin-wrapper
is trivial to maintain.

## Decision

Each `sites/<domain>/Makefile` is **thin** and **forwards to the
central builder** at `~/work/projects/builder/Makefile` via
`$(MAKE) -C ..`:

```makefile
.PHONY: deps dev build test clean run
deps dev build test clean:
	$(MAKE) -C .. $@ proj=<this-project-name>
run:
	$(MAKE) -C .. run proj=<this-project-name> ARGS="$(ARGS)"
```

- Build logic (deps install, dev server, production build, tests,
  clean) lives **once** in `~/work/projects/builder/Makefile`.
- Per-project Makefiles only add **project-specific** commands when
  needed (rare).
- `CHECK_012 makefile-forwards-to-parent` enforces the forwarding
  pattern across all `sites/*` projects.

**`portfolio` itself is the deliberate exception.** It's a Python+uv
CLI with its own self-contained `Makefile`, not a JS-stack web app.
See ADR-0002.

## Consequences

**Positive.**
- Single point of pipeline maintenance — a new linter, new test
  runner, or new build step lands once.
- Adding a new sibling project costs ~zero build-config setup —
  the bootstrap template includes the forwarding `Makefile` already.
- CHECK_012 keeps the pattern consistent and surfaces drift.

**Negative.**
- Indirection on first read of any sibling `Makefile` — a reader
  has to look at `../Makefile` to understand what targets actually
  do.
- The central builder repo at `~/work/projects/builder/` is a hard
  filesystem dependency. Without it, no sibling can build.
- The central builder must remain backwards-compatible with every
  shipped sibling — a breaking change there breaks all 30+ sites
  at once.

## References

- `CHECK_012 makefile-forwards-to-parent`.
- `~/work/projects/builder/Makefile` (the canonical pipeline).
- `AI_AGENTS.md` § Conventions enforced on siblings.
- `docs/CLAUDE.md` § Conventions.
- ADR-0002 — Python + uv for portfolio CLI (the explicit exemption).
