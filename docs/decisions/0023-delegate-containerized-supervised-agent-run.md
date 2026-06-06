# 0023 — `project delegate`: agent-authored site changes run sandboxed in a container, supervised, verify-gated, ending at an uncommitted diff

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

lamill already drives Claude headless inside a site dir: the Tier-2
`ai_fixer` (ADR-0006) spawns `run_claude(prompt, cwd=project_dir)` to fix a
**known** `CHECK_NNN` gap, then re-runs that check to verify. v33 points the
same engine at an **open-ended, multi-step** request — e.g. *"add a
dark/light theme toggle that persists to localStorage and respects
prefers-color-scheme, then add real /privacy and /contact pages the footer
currently 404s on"* — where there is no check to assert against.

That shift surfaces two problems the Tier-2 path never had:

1. **No conformance oracle.** A fixer verifies by re-running its check. An
   open-ended change has nothing fixed to assert — every request differs, and
   the feature is absent by design until asked for.
2. **An unsupervised autonomous run is unsafe.** Pointed at an open-ended
   task, the agent can reach beyond the intended files, run long, or get
   **stuck while still emitting tokens** (observed in practice — token flow
   proves the run is *alive*, not that it is *progressing*).

This is also a **third local-FS write surface** beyond ADR-0003's two
(bootstrap = create new dirs; remediation = fix known gaps in existing
dirs). An open-ended agent-authored change is a new category whose safety
cannot come from a conformance oracle, because there isn't one.

## Decision

**`lamill project delegate <domain> "<request>"` runs the agent in a
sandboxed Docker container, host-side-supervised on two axes, behind a
build + check + visual verify gate, and stops at an uncommitted reviewable
diff.** Single-site only; no `fleet delegate` for now. Concretely:

- **(a) Sandboxed execution — blast radius is one site dir.** Each run uses
  a **fresh, disposable container** (`lamill-delegate-<domain>`) built from
  the builder's stack image, created and torn down per run via direct `docker
  run`/`exec` — *not* the shared interactive `mb1`, because a delegate run
  kills its container on every exit and that must never touch the operator's
  dev session. Claude runs *inside* via `docker exec`, started with the
  instructions. **Only `sites/<domain>/` is bind-mounted RW** — not the
  `sites/` parent, not sibling sites, not the `portfolio` repo. Host
  `~/.claude` is bind-mounted in for auth (the rankmill/threadradar pattern —
  no API-key management).
  *(Refined 2026-06-06 during v33.B implementation: the original "reuse
  `dev_container.sh` / `mb1`" wording fought the clean-kill-on-every-exit
  requirement and that script's single-bind-mount limit. A dedicated
  disposable container — reusing the builder stack image, not the script — is
  the fit. The build step (v33.C) still uses `make buildsh` per ADR-0009.)*

- **(b) Bounded + supervised on two axes.** A host-side supervisor enforces
  **liveness** (Claude's output stream is flowing) *and* **progress** (net
  diff growth + tool-action novelty over a rolling window). Token flow alone
  is **not** progress: a stream that flows with ~0 net change / repeating
  action fingerprints is *spinning* and is killed. Hard backstops underneath:
  a **wall-clock cap** and a **budget cap** (inherited from `run_claude`).
  Every termination path — `done` / `idle` / `spinning` / `timeout` /
  `budget` — clean-kills the container.

- **(c) Refuse on a dirty tree.** `delegate` reports its result as a git
  diff; pre-existing uncommitted changes would blend with the agent's and a
  bad run could not be cleanly discarded. So it refuses on a dirty tree with
  a clear cause + safe-recovery message (commit or stash, copy-paste
  commands); `--force` exists but is demoted to a parenthetical.

- **(d) The verify gate substitutes for the missing oracle.** After the run,
  in-container: `make buildsh` (catches "broke the build") → `lamill project
  check` (catches "regressed conformance") → a **Playwright-in-container**
  visual probe + Claude-as-judge (catches the failure unique to open-ended
  generation — "builds green yet the feature is absent / wrong"), emitting a
  `PASS`/`FAIL` + a screenshot artifact. None of the three links is
  redundant. **Build + check are hard gates** (failure ⇒ `verify-fail`).
  **The visual probe is a soft gate** (operator contract, 2026-06-06): it
  never hard-fails — any failure (no browser, serve error, judge
  inconclusive) degrades to `unavailable`, the run reports **`needs-review`**,
  and it **stops for the operator to eyeball + confirm** rather than
  auto-proceeding or auto-iterating. This keeps the heavy/flaky browser step
  from ever blocking or discarding good work.

- **(e) Never auto-commit, never auto-revert.** The run mutates the working
  tree and stops; the operator reviews `git diff` and commits. Honors the
  global never-auto-commit rule. No branch/worktree ceremony — "one shot" is
  one-shot *to a reviewable state*, not to `main`. On any failure the
  uncommitted (possibly partial) changes are left for the operator, clearly
  labeled.

- **(f) A dedicated verb, not a check/fix.** Open-ended feature work has no
  gap to detect and no fixed green to assert, so it earns its own surface —
  the called-out exception to the prefer-check/fix rule. The verify gate (d)
  substitutes for the conformance oracle a fixer would have.

## Consequences

- **A third local-FS write surface joins ADR-0003.** Its safety comes from
  the **sandbox (a) + supervisor (b) + dirty-tree refusal (c) + verify gate
  (d) + uncommitted-review stop (e)**, not from a conformance oracle. When
  v33.B ships the surface, ADR-0003's "two surfaces only" count and `docs/
  CLAUDE.md § Two local-FS write surfaces` update to three;
  `architecture.md § 2.1` gains the `delegate` row. (Until then both note it
  as accepted-but-planned.)
- **Containerized agent execution enters lamill.** `run_claude` gains a
  containerized sibling (`docker exec` into the dev container) rather than a
  host spawn. The **supervisor** (stream-liveness + progress watchdog) is
  net-new machinery and is **core, not optional** — it ships in the v33.B
  runner, because stream-liveness alone does not catch the observed "tokens
  but stuck" failure.
- **The heaviest-dependency objection to a visual probe dissolves.** Because
  the run is already containerized and `Dockerfile.playwright` already
  exists, the screenshot + judge probe lives in the **container image**, not
  the host Python package — so the full rendered-output probe (v33.D) is
  cheap to justify.
- **A real purpose-expansion.** lamill moves from "lifecycle + conformance"
  toward "agent-orchestrated site development." That expansion — not any
  single mechanism — is why this carries an ADR rather than landing quietly.
- **Reuses, not reinvents.** Container image = the builder's stack image (run
  as a disposable per-run container via direct `docker run`/`exec`); build =
  `make buildsh` (ADR-0009, per the build-in-Docker convention — never host
  `pnpm`); restricted-tools / budget / timeout / cost-capture mirror
  `run_claude` (ADR-0006). Only the supervisor and the containerized
  invocation are new.

## See also

- `docs/prd.md § v33` — phases + design notes
- ADR-0003 (two local-FS write surfaces — this adds the third), ADR-0006
  (Tier-2 fixer as Claude subprocess — the engine this extends), ADR-0009
  (Makefile forwards to the central builder), ADR-0008 (`pnpm`-only / stack)
- `src/portfolio/fix_helpers.py` (`run_claude`),
  `~/work/projects/builder/dev_container.sh` + `Dockerfile.playwright`
- `docs/CLAUDE.md § Two local-FS write surfaces` (flips to three when v33.B
  ships)
