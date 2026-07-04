# Advice for future Claude Code projects

**Date:** 2026-05-22
**Source:** Learnings from building `sites/portfolio` (a.k.a. `lamill`)
between ~2026-03 and 2026-05.
**Use:** Reference for starting NEW projects with a Claude Code agent
so they reach this project's level of structure on day 1, instead of
accruing it over weeks of drift.

This is a working doc, not a canonical one. Move pieces into
`~/.claude/CLAUDE.md`, per-project `docs/CLAUDE.md` files, skills, or
memory as makes sense — see the "Where each rule lives" table at the
end for the suggested mapping.

---

## Bundle 1 — Project bootstrap kit

Rules that should be true on day 1 of any new project, before any
features get scoped. Best home: the `/project-init` skill scaffolds
the file structure; per-project `docs/CLAUDE.md` carries the prose.

### 1. `§ 2 Non-goals` exists in the PRD on day 1

A "what this tool does NOT do" section in the PRD, **before any phases
get scoped**. This single discipline dropped 5 tiers in portfolio (v17,
v20, v21, v22, v23) and shrunk 2 more (v18, v19). Without it,
speculative work accumulates and gets withdrawn later at higher cost.

**How to apply:** When scoping a new tier, ask "is this tool's job, or
adjacent territory another tool does better?" — refer back to § 2
Non-goals. Update Non-goals whenever a tier gets dropped; capture the
reason so the next similar proposal gets dropped at scoping, not after
implementation.

### 2. `CLI module-split rule of thumb: ~2,000 lines`

Splitting at 8,000 lines is a multi-hour refactor; at 2,000 it's an
afternoon. Don't let monolithic CLI files accrue.

**How to apply:** Watch `wc -l src/<project>/cli.py`. When it crosses
~1,500, propose a split into scope-first modules (`cli/<group>.py`).
Lock the threshold in per-project `CLAUDE.md` so it's not negotiable.

### 3. Canonical enums from commit 1

Any concept that touches >1 module gets its own constants module
immediately. Don't let three spellings of the same thing emerge
across modules. In portfolio this cost real bug-fix work (platform
naming: `cf-pages` vs `cloudflare-pages` vs `cloudflare-pages` —
three modules each with their own spelling).

**How to apply:** First time you reach for the same string value in
two modules, extract to a shared constants module. Don't wait.

### 4. Lazy-import error pattern

Any module that does `from optional_dep import X` inside a function
must wrap in try/except ImportError → raise typed error with the
fix command:

```python
def _fetch_thing():
    try:
        from some_optional_pkg import Client
    except ImportError as e:
        raise MyTypedError(
            f"some_optional_pkg not installed ({e}). "
            f"Run `uv sync` to install."
        ) from e
    # ...
```

Otherwise raw `ModuleNotFoundError` stack traces reach the operator
and they have no idea what to do. Closed two bugs in portfolio this
session (pytrends ImportError exposed mid-execution).

**How to apply:** Code review for any lazy import → wrap or move to
top-level imports. Optionally enforce via a lint rule.

### 5. httpx-direct over framework SDKs

Hand-written `httpx` clients (with `httpx.MockTransport` for tests)
over heavyweight SDK wrappers like `googleapiclient.discovery.build`.
In portfolio: `gh_repo.py`, `cloudflare.py`, `ga4_admin.py`,
`gsc_admin.py` all follow this pattern. `gsc.py` uses
`googleapiclient` (legacy from v13.B); tests for it are noticeably
harder to write and slower to run than the httpx-direct modules.

**How to apply:** When wiring a new external API, default to httpx
+ MockTransport. Reach for an SDK only if the API has complex
ceremony (e.g., OAuth flows handled by `google-auth-oauthlib`) and
the SDK genuinely reduces code.

### 6. Pipeline idempotency markers at every step

Each step of a multi-step pipeline must:

  - Probe existing state before doing work.
  - Print one of `✓ exists, skipping` / `✓ created` / `↷ warn-skipped:
    <reason>` / `✗ <error>`.
  - Be safe to re-run with the same input + arrive at the same state.

This means re-running after a partial failure is risk-free, and the
operator can scan the log to see exactly which steps actually did
work vs. were already-done.

**How to apply:** Every step in a pipeline starts with `if <state
already correct>: print(skip); return` before the write. Pipeline
helpers return enough info for the orchestrator to render the right
marker.

### 7. Soft-fail on non-load-bearing failures

Auxiliary integrations (analytics, search-console registration, etc.)
shouldn't abort the main flow. Capture status in a result field
(`gsc_status: str`, `ga4_status: str`); surface to operator below
the main success line.

**How to apply:** For each pipeline step, ask: "if this fails, is the
deploy/operation still usable?" If yes, wrap in try/except, log,
continue. If no (e.g., site-doesn't-actually-deploy failures), let
it abort cleanly.

### 8. Pre-resource-create → pre-resource-write probes

When a pipeline creates a resource (e.g., CF zone) then writes to it
under separate permissions (e.g., DNS records on that zone), probe
write capability **right after create**, before the dependent write
fails diagnostically less clearly later. v25.B in portfolio
codifies this pattern.

**How to apply:** Whenever you add a "create X then modify X" pair
of steps, add the probe between them. Surface scope gaps at the
cheapest moment.

### 9. PRD as canonical source

The PRD (`docs/prd.md`) is the canonical truth for purpose, scope,
phases, and conformance. Code that contradicts it is drift. Five
canonical doc surfaces total in portfolio: PRD, architecture.md,
shipping-history.md, ADRs, CLAUDE.md. Drift is a conformance failure,
not a backlog item.

**How to apply:** Doc-sync as part of every commit. Never let docs rot
"to be updated later." If the operator approves a tier-level decision
in chat, capture it in the relevant doc surface in the SAME commit
that ships the code.

### 10. ADR workflow from commit 1

Write `ADR-0001` the day the first load-bearing architectural decision
lands. Don't add ADRs late. Use Nygard format (Status / Date /
Context / Decision / Consequences). Lock a `docs/decisions/README.md`
index from the start.

**How to apply:** First time you make a choice between "two reasonable
options + the choice is not obvious from the code," write the ADR.
Update the README index. Heuristic: "would someone six months from
now ask 'why is it this way?' and need the rationale beyond what the
code shows?"

### 11. Tracked-refactors section maintained as you go

When you write `// TODO: fold this into X later`, that's a tracked
refactor — log it in `docs/architecture.md § Tracked refactors`
immediately. Don't wait for an audit pass.

**How to apply:** Open architecture.md, jump to § Tracked refactors,
add a row. Cost is ~30s; benefit is the operator can see at any time
what work is queued at the architectural level.

### 12. Strict two-level versioning convention (`vN.X`)

Never three-level (`vN.X.Y`). Internal task tracking inside a phase
is fine; commit messages and on-disk docs use `vN.X` only. In
portfolio this is ADR-0004 and is enforced by `CHECK_013`.

**How to apply:** Tier (`v15`) + Phase (`v15.A`, `v15.B`, ...). When
a phase has internal sub-tasks, track them in TaskCreate or in the
phase's design notes — never as `v15.A.1`.

### 13. Plateau is a real state

When no concrete work is queued, say so. Don't manufacture work to
fill space. In portfolio, the biggest improvements (v15.K-R, v24.B
fix, v25 kickoff) came from periods where the operator tested
existing work, not when greenlighting new tiers.

**How to apply:** When the queue is empty, the right next action is
"operator soak-tests." Schedule soak time as part of the cadence;
don't treat it as wasted time.

---

## Bundle 2 — Collaboration posture

How you work with Claude across projects. Best home:
`~/.claude/CLAUDE.md` (global, applies to every project).

### 14. Reactive > proactive

The best work in this project came from the operator hitting real
friction in real use. Speculative tiers (v17, v20, v21, v23) tended
to get dropped or withdrawn. Lead with reaction; surface proactive
work only when the operator's stated workflow demands it.

**How to apply:** When proposing new work, ask first: "is this
addressing a specific operator-felt friction, or am I imagining the
need?" If the latter, surface as a question, not as a tier proposal.

### 15. Confirm load-bearing decisions before code

Show three options with tradeoffs; let the operator pick; then code.
Don't shortcut the discussion for substantive choices. In portfolio
this saved real wrong-direction work (v17 scope, v18.B vs SEO
pipeline, v21 drop, v24 Option A vs B).

**How to apply:** For any decision that's hard to reverse (schema
choice, ADR-worthy posture, scope direction), present options + ask.
For routine choices (file naming, where to insert a section, what
test name to use), just pick.

### 16. Don't ask routine questions when operator says "ship"

When operator says `go` / `continue` / `ship it` / `yes`, pick + ship
multi-phase work. Surface only load-bearing decisions or reversals.

**How to apply:** Internal heuristic: "would the operator be annoyed
if I asked this?" If yes (e.g., "should I use Python's `json` or
`orjson`?"), just pick. If the question is load-bearing (e.g., "should
this surface live in cli.py or its own module?"), ask.

### 17. Operator keeps strategic control; agent does tactical execution

The successful pattern in this session: operator says `go` / `continue`
/ occasionally asks pointed scope questions. Claude handles the
tactical work between those signals. The operator NEVER had to
review every line — they reviewed the outcomes + the scope decisions.

**How to apply:** When in doubt about how much to do without checking
in — err toward more. Operator can always say "wait, stop, what
are you doing?" Cheap to recover from over-doing; expensive to
recover from constant interruptions.

### 18. Never auto-commit

Only commit when the operator asks. If unclear, ask first. This
prevented several near-misses in portfolio where work-in-progress
would have landed prematurely.

**How to apply:** Default to writing changes, then asking. Operator's
explicit `commit this` / `commit + push` is the trigger.

### 19. Don't conflate "feature works" with "feature tested"

Type checking and test suites verify code correctness, not feature
correctness. State the difference explicitly. In portfolio: every
v15-v24 tier had "suite green" reported alongside "operator should
test this against a real domain" — the two are not interchangeable.

**How to apply:** When reporting completion, distinguish "tests pass"
from "tested by operator in real use." For features that need real-
world validation, say so.

---

## Bundle 3 — Output-quality patterns

How Claude communicates progress during long-running work. Best home:
`~/.claude/CLAUDE.md` (global) + optional per-project tightening.

### 20. `✓ ✗ ↷` markers consistent throughout

Every step in a multi-step process prints one. Operator can scan the
log and immediately see state without parsing prose. In portfolio
this became load-bearing for the v15+ deploy pipeline — operator
could scan 10 steps in 2 seconds.

**How to apply:** Use `✓` for success/skip-because-exists, `✗` for
error, `↷` for soft-skip / warn-skip / dry-run-would-do.

### 21. Surface exact dashboard URLs when manual is unavoidable

Not "edit your token" but `https://dash.cloudflare.com/profile/api-
tokens` with the specific permission groups pre-populated via query
params if supported. Each click the operator has to navigate is a
chance for them to make a mistake or get distracted.

**How to apply:** When a step needs a manual action, print the
deepest-link URL possible. If the target page supports query-param
form-pre-population, use it.

### 22. "Vicarious building" framing

Output that lets the operator *watch* the work happening, not just
wait for a completion line. Per-step descriptions, real-time
progress indicators, timestamps where meaningful. This is more
important than time-savings — the operator's reflection in this
project: "even if it doesn't save time, it saves making mistakes,
redoing, or at least gives me building time vicariously."

**How to apply:** For any multi-step process > 30 seconds, print
per-step output as work happens. Don't batch into a final summary.

### 23. Differentiate transient vs permanent failures via color

Yellow `↷` for transient/retry-able (rate limits, network blips);
red `✗` for permanent/operator-action-needed. Operators learn the
color code quickly and act on it.

**How to apply:** Categorize every failure mode upfront. If unsure,
default red (operator-action-needed); operator can downgrade later.

### 24. Distinguish error causes via response-body parsing

A 403 can mean three different things; don't lump them. Parse the
response and surface the actual cause with a specific remediation.
In portfolio (v25.D): the GSC `siteVerification.getToken` 403
disambiguates between `insufficient_authentication_scopes` (re-auth),
`SERVICE_DISABLED` (enable API in GCP project), `invalid_grant`
(refresh token).

**How to apply:** For every HTTP error code your pipeline can raise,
list the distinct causes + the operator-facing message for each.
Parse response body to disambiguate; surface the right hint.

---

## Bundle 4 — Bug-handling rules

Workflow for managing operator-reported friction. Best home:
per-project `docs/bugs.md` carries the workflow + entries; per-
project `CLAUDE.md` references the file; memory captures
operator-specific preferences (e.g., "operator says 'found a bug'
→ Claude writes the structured entry").

### 25. Structured bug-intake workflow

Operator drops a brief report in chat ("found a bug: X command shows
N but Y shows M") → Claude writes the structured entry in
`docs/bugs.md` `## Open bugs` section with Repro / Expected / Actual
/ Where / Severity / Notes fields.

**How to apply:** First time operator reports a bug, ask the format
question if unclear. Then auto-fill the structured entry on each
subsequent bug report.

### 26. "Fixed in" lines with commit SHA + phase

Move entries from `## Open bugs` to `## Fixed bugs` with traceability.
Format: `**Fixed in** — <SHA> (<phase or description>)`. Don't delete
fixed entries; they're the project's known-issue archive.

**How to apply:** When fixing a bug, the same commit moves the entry +
adds the Fixed-in line. Both in one commit for atomicity.

### 27. Diagnose root cause before fixing symptom

A symptom-treating patch is a tracked-refactor candidate; document
the underlying issue even if you ship the patch. In portfolio: the
platform-name enum drift between `lamill_toml.py` / `hosting.py` /
`project.py` got a symptom patch (translation map in `project.py`),
but the underlying drift remained a tracked refactor.

**How to apply:** Before fixing a bug, ask: "is this a symptom of a
larger pattern?" If yes, ship the patch + log the tracked refactor.

### 28. Pick up bugs between phases

Bug work doesn't interrupt current shippable phase unless escalated
("fix this first" / `blocker` severity). After a phase ships, Claude
reviews `## Open bugs` and picks up entries before starting the next
phase, in this order: blockers first → bugs whose fix overlaps with
the just-shipped or next phase → everything else by date (oldest
first).

**How to apply:** Schedule bug-fix passes between phases as a default
cadence. Don't let bug debt accumulate.

---

## Bundle 5 — Session management

Stateful concerns across multiple Claude sessions. Best home: a per-
project `docs/handoff.md` (never committed); memory for the rule
about it being never-committed.

### 29. `docs/handoff.md` — never committed

A session-bridging snapshot only. Write freely; never `git add` it.
Update at end-of-session with: current state, what just shipped,
known bugs, what to pick up next session.

**How to apply:** Operator runs `head -80 docs/handoff.md` at the
start of a new session to get cold-context. Claude updates it at the
end of any session of substantive work.

### 30. Soak between tiers

The biggest improvements come from periods where the operator tests
existing work, not when greenlighting new tiers. Plan for soak time;
don't treat it as wasted time.

**How to apply:** After a tier ships, default action is "operator
soak-tests; bugs surface; we react." Don't proactively start the
next tier without operator's explicit signal.

---

## Where each rule lives — destination mapping

| Rule | Where | Why |
|---|---|---|
| 1 (§ 2 Non-goals on day 1) | Per-project `prd.md` template (in `/project-init` skill) | Structural; lives in the project's PRD |
| 2 (CLI ~2,000 line split) | Per-project `CLAUDE.md` | Code-shape rule for THIS project |
| 3 (canonical enums day 1) | Per-project `CLAUDE.md` | Code-shape rule |
| 4 (lazy-import wrap) | Per-project `CLAUDE.md` + global `~/.claude/CLAUDE.md` | Code-shape rule + universal Claude behavior |
| 5 (httpx-direct over SDKs) | Per-project `CLAUDE.md` | Code-shape rule |
| 6 (pipeline idempotency markers) | Per-project `CLAUDE.md` | Code-shape rule |
| 7 (soft-fail non-load-bearing) | Per-project `CLAUDE.md` | Pipeline design |
| 8 (pre-create → pre-write probes) | Per-project `CLAUDE.md` (when project has pipelines) | Pipeline design |
| 9 (PRD as canonical source) | Per-project `CLAUDE.md` template | Doc discipline |
| 10 (ADR workflow from commit 1) | `decisions/README.md` template + per-project `CLAUDE.md` cross-reference | Doc discipline |
| 11 (tracked-refactors maintained) | Per-project `CLAUDE.md` + `architecture.md § Tracked refactors` section template | Doc discipline |
| 12 (vN.X strict two-level) | Per-project `AI_AGENTS.md` (per ADR-0004 pattern) | Versioning convention |
| 13 (plateau is real state) | Global `~/.claude/CLAUDE.md` | How Claude approaches "what's next" |
| 14 (reactive > proactive) | Global `~/.claude/CLAUDE.md` | Collaboration posture |
| 15 (confirm load-bearing decisions) | Global `~/.claude/CLAUDE.md` | Collaboration posture |
| 16 (don't ask routine questions on "ship") | Global `~/.claude/CLAUDE.md` + memory (operator-specific phrasing) | Collaboration posture |
| 17 (operator strategic / agent tactical) | Global `~/.claude/CLAUDE.md` | Collaboration posture |
| 18 (never auto-commit) | Global `~/.claude/CLAUDE.md` | Safety / collaboration posture |
| 19 (feature works ≠ tested) | Global `~/.claude/CLAUDE.md` | Output discipline |
| 20 (✓ ✗ ↷ markers) | Global `~/.claude/CLAUDE.md` | Output discipline |
| 21 (exact dashboard URLs) | Global `~/.claude/CLAUDE.md` | Output discipline |
| 22 (vicarious building) | Global `~/.claude/CLAUDE.md` | Output discipline |
| 23 (transient vs permanent via color) | Global `~/.claude/CLAUDE.md` | Output discipline |
| 24 (distinguish errors via response body) | Global `~/.claude/CLAUDE.md` | Output discipline |
| 25 (structured bug intake) | Per-project `bugs.md` template + memory ("operator says 'found a bug' → Claude writes entry") | Workflow |
| 26 (Fixed-in lines) | Per-project `bugs.md` template | Workflow |
| 27 (root cause before symptom) | Per-project `CLAUDE.md` + global `~/.claude/CLAUDE.md` | Engineering posture |
| 28 (pick up bugs between phases) | Per-project `bugs.md` template + memory | Workflow |
| 29 (handoff.md never committed) | Memory ("docs/handoff.md is freely-written but never committed") | Per-operator preference |
| 30 (soak between tiers) | Global `~/.claude/CLAUDE.md` | Cadence |

---

## Suggested implementation path

Three pieces, in order of leverage:

### Piece 1 — Enhance `/project-init` skill

Current state: `~/.claude/commands/project-init.md` creates only
`AI_AGENTS.md` (good template) / `docs/prd.md` (just phase
checkboxes) / `docs/Prompts.md` / `README.md` / `.gitignore`.

Should create: full doc scaffold including `docs/CLAUDE.md` (with
bundle 1 rules baked in), `docs/architecture.md` (with section
scaffold including § Tracked refactors), `docs/decisions/README.md`
(ADR workflow), `docs/decisions/0001-record-architecture-decisions.md`
(seed ADR), `docs/bugs.md` (workflow + empty sections),
`docs/shipping-history.md` (empty append-only log), `docs/prd.md`
(with `§ 1 Purpose`, **`§ 2 Non-goals`**, `§ 3 Goals`, `§ 4 Target
user`, `§ 5 Versions/phases (vN.X)`, `§ 6 Conformance`, `§ 7 Open
questions`, `§ 8 References` — not just phase checkboxes).

Effort: ~1h to write + test on a fresh dir.

### Piece 2 — Write a global `~/.claude/CLAUDE.md`

Add bundles 2 + 3 (collaboration posture + output discipline) as
global rules that apply across all your projects.

Effort: ~30 min.

### Piece 3 — Distill portfolio's `docs/CLAUDE.md` into the `/project-init` template

Read portfolio's existing CLAUDE.md; separate the universal parts
(locked target shapes, heading hygiene, ADR workflow, doc-update
table) from the portfolio-specific parts (v7.A CLI restructure
locked target shape, etc.). The universal parts become template
content baked into `/project-init`; portfolio-specific parts stay
only in portfolio.

Effort: ~30 min.

**Total: ~2h** to make all of this concrete + portable across all
future projects.

---

## What to NOT do

A short list of anti-patterns observed in this project that you
should NOT bake into the future template:

- **Don't let `cli.py` grow past 2,000 lines unchecked.** Portfolio's
  is now 8,800+; the tracked refactor sits in architecture.md but
  splitting at 2k vs 8k is a 4x time difference.
- **Don't accept three spellings of the same concept across modules.**
  The platform-name drift between `lamill_toml.py` / `hosting.py` /
  `project.py` caused real bug-fix work to symptom-patch rather than
  fix at root.
- **Don't commit `docs/handoff.md`.** It's session-bridging only;
  per-project state that doesn't belong in version control.
- **Don't auto-add `CHECK_NNN` for the meta-project itself.** The
  meta-project (the CLI tool) should be exempted from its own
  conformance checks; use pytest + git hooks for tool-internal rules.
- **Don't propose work without the operator hitting friction first.**
  Speculative tiers tend to get dropped. Reactive > proactive.

---

*Generated 2026-05-22 PM at operator request, end of the v25.A kickoff
session, based on learnings from ~2.5 months of v1-v25.A development.*
