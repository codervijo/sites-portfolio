# Handoff — sites/portfolio (next session)

You are a fresh Claude session picking up work on the `portfolio`
(a.k.a. `lamill`) CLI at `~/work/projects/sites/portfolio/`. This
document is the brief: where work stands at the end of the
2026-05-18 session (post-v10 wrap + v11 design lock), what's next,
and what changed since the canonical docs were last updated.

## Read these first (in order)

1. `AI_AGENTS.md` (repo root) — `## Canonical docs` is your map.
2. `docs/CLAUDE.md` — conventions, ADR workflow, heading hygiene,
   locked target shapes.
3. `docs/decisions/README.md` — ADR index. Skim it.
4. `docs/prd.md § 6 Versions` — tier-grouped phase log. `### v10`
   is wrapped (A-E ✅, F+G absorbed into v11). `### v11` carries
   the expanded Design notes with **11.K-N answered** and
   **11.O-T open** (gate v11.B code).
5. `docs/architecture.md` — HOW (mechanisms / schemas / modules /
   CLI / integrations / active plans). § 3 Provider walkers and
   § 9 v11.A / v11.B sections updated 2026-05-18.
6. `docs/shipping-history.md` — archived rationale for shipped
   phases. v10 tier-level design block + v10.D + v10.E entries
   added 2026-05-18.
7. `docs/bugs.md` — open + fixed bug journal. Four entries open
   as of 2026-05-18.

## Where the work is

**Last shipped (code):** `v10.E — drift detection + lamill.toml
conformance checks` (commit `cda9e28`). Three new deploy-category
checks: `CHECK_058 has-lamill-toml`, `CHECK_059 lamill-toml-valid`,
`CHECK_143 deploy-drift`. 26 new tests. Suite at 1827 passed / 1
skipped.

**Last shipped (docs):** the `portfolio: docs — wrap v10, fold
v10.F+v10.G into v11` commit (see git log for SHA).

**v10 tier status: ✅ WRAPPED 2026-05-18.**

| Phase | Status | What |
|---|---|---|
| v10.A | ✅ | `lamill.toml` foundation — schema, dataclasses, `load()`, `write()`, infer. |
| v10.B | ✅ | `settings project {set-deploy, show-deploy, set-launched}` CLI. |
| v10.C | ✅ | Auto-write — `new bootstrap` writes `lamill.toml`; `fleet repos --add-deploy-declarations` migration. |
| v10.D | ✅ | Real-fleet sweep — 22 of 23 sites have `lamill.toml`; 17 committed in own-git-repos. |
| v10.E | ✅ | Drift detection — `CHECK_058 / 059 / 143`. Canonical `iotnews.today` drift case fires. |
| v10.F | ✅ *(absorbed by v11.A)* | HostGator cPanel integration — folded into v11.A unified hosting walker. |
| v10.G | ✅ *(absorbed by v11.B)* | SFTP deploy — renumbered v11.B; polymorphic `new deploy`. |

## What's next

**Strict-numerical next:** **v6.F** (own-git-repo guided migration).
Closes the 5 NO_GIT sites currently baseline-failing CHECK_058
(iotnews.today, linkedcsi.live, streamsgalaxy.com, thoralox.com,
whizgraphs.com). ~3-5h, single session. No design blockers.

**Active design tier:** v11 — active hosting layer.
- **v11.A** unified 3-provider walker (Vercel + CF Pages +
  HostGator). CLI shape + 11.K-N answers **approved 2026-05-18**;
  code may proceed. ~16-22h, ~14 commits.
- **v11.B** polymorphic `new deploy` with SFTP push for HG/custom.
  **Design open** — gating questions 11.O-T need resolution
  before code lands (verb split, push-source, auth surface, WP
  scope, ADR-0009 for third write surface, atomicity).

**Suggested order**: v6.F next, then v11.A, then v11.B (after
11.O-T are settled).

## v10.D real-fleet scoreboard (still load-bearing for v6.F)

22 of 23 fleet sites have `lamill.toml`:

| Bucket | Count | Sites |
|---|---|---|
| Migration `--apply` (unambiguous via config) | 9 | agesdk.dev · airsucks.com · calcengine.site · donready.xyz · keralavotemap.site · kwizicle.com · lamill.io · lamillrentals.com · washcalc.app |
| `set-deploy cf-pages` (CF dashboard, no wrangler config) | 3 | cricketfansite.com · isitholiday.today · voltloop.site |
| `set-deploy vercel` (unclassified-but-vercel per operator) | 7 | civictools.app · csinorcal.church · iotbastion.com · iotnews.today · linkedcsi.live · thoralox.com · whizgraphs.com |
| `set-deploy vercel` (resolved ambiguous) | 1 | homeloom.app |
| `set-deploy hostgator` (full breadcrumbs) | 2 | hybridautopart.com · streamsgalaxy.com |

**Per-sibling-repo commit state** (17 own-git-repo + 5 NO_GIT):

- **Pushed:** 15 — airsucks · calcengine · civictools · cricketfansite · csinorcal · donready · homeloom · hybridautopart · isitholiday · keralavotemap · kwizicle · lamill.io · lamillrentals · voltloop · washcalc
- **Committed locally, no remote yet:** 2 — agesdk.dev · iotbastion.com (need `origin` setup + push)
- **NO_GIT (own .git missing) — `lamill.toml` untracked:** 5 — iotnews.today · linkedcsi.live · streamsgalaxy.com · thoralox.com · whizgraphs.com. v6.F closes this.

**Out of v10/v11 scope:**
- `hostkit.app` — unregistered domain; stale `sites/` dir.
- `carrepairsite.com` (HG account 1, no local repo) — v11.A surfaces.
- `thakinaam.com` (HG account 2, no local repo) — v11.A surfaces.
- `newiniot.com` — dead (invalid CF nameservers); `portfolio.json` cleanup.

## Open bugs (`docs/bugs.md`)

Four open as of 2026-05-18:

1. **`fleet seo --refresh` and `fleet domains` show different
   domain counts** — silent scope filter (live-site/forwarder vs
   wip). Severity: minor.
2. **`settings project set-deploy` fails for sites/ dirs missing
   from portfolio.json** — surfaced via `hostkit.app`. Severity:
   minor.
3. **`settings project set-deploy` doesn't auto-populate
   `custom_domains` from dir name** — inconsistency with the
   migration sweep. Severity: minor.
4. **`domain suggest` menu shows option `s` between numbered
   options 7 and 8** — sort-order issue (or feature request?).
   Operator brief report 2026-05-18; needs clarification.
   Severity: cosmetic.

Per `feedback_bug_intake_workflow` — pick up bugs between phases.
None are blockers.

## Hard constraints

### Strict two-level `vN.X` for commits AND docs (ADR-0004)

Never `vN.X.Y`, never `C1/C2/C3`, never `P4.A.1`, never `Phase 1
step 2` — those are three-level identifiers in disguise. Memory
[[commit-naming-strict-two-level-vn-x]] has the full rule.

### Trust operator fleet categorization

When operator says "X and Y are on hostgator, rest are vercel,"
**accept and act**. Don't re-probe with curl / dig. Memory
[[feedback-trust-operator-fleet-categorization]].

### Bug intake → docs/bugs.md

Operator drops brief reports ("found a bug: X"); Claude writes
the structured entry under `## Open bugs`. Current phase keeps
going; pick up bugs between phases. On fix: cut to `## Fixed
bugs` with `**Fixed in** — <sha>`. Memory
[[feedback-bug-intake-workflow]].

### prd.md tier-grouped structure

Per-tier `### vN` with `#### Phases` table + `#### Design notes`
(only for unshipped tiers). v10 wrapped 2026-05-18 — its design
notes moved to `shipping-history.md`. Memory
[[feedback-prd-tier-grouped-structure]].

### Working order = strict numerical

Lowest unshipped `vN.X` in prd.md is next — not session-handoff
suggestions. v6.F is the strict-next today. Memory
[[feedback-strict-numerical-working-order]].

### Other long-standing constraints

- Two write surfaces only (`new bootstrap`, `project fix`) per
  ADR-0003. **v11.B needs ADR-0009** (third write surface for
  SFTP push) before code lands.
- pnpm-only / Vite ≥6 / Astro ≥5 for `sites/*` per ADR-0008.
- Heading hygiene: grep outline before adding any heading to a
  long-lived `.md` file (CHECK_043).
- No `--no-verify` / `--no-gpg-sign` / amend pushed commits.
- Stage by name; never `git add -A`.

## What changed this session

### Code (v10.E)
- 3 new check modules: `check_058_has_lamill_toml.py`,
  `check_059_lamill_toml_valid.py`, `check_143_deploy_drift.py`.
- 3 new test files (26 tests).

### Docs (v10 wrap + v11 expansion)
- `docs/prd.md` — v10 section ✅ + intro updated; v10.F/G rows
  flipped to "absorbed by v11.A/B"; v10 Design notes block
  removed (moved to shipping-history). v11 intro + phase table
  + design notes expanded to cover 3-provider walker + SFTP
  deploy + 11.K-T questions.
- `docs/architecture.md` — § 3 Provider walkers expanded for HG
  walker. § 4 `HostingRow` schema gains HG-specific typed
  optional fields (resolution 11.M). § 5 CLI surface updated for
  3-provider `fleet hosting` + polymorphic `new deploy`. § 9
  v11.A re-scoped to 14-commit unified plan; v11.B section
  added.
- `docs/shipping-history.md` — v10 tier-level design block
  added + v10.E + v10.D per-phase entries.
- `docs/bugs.md` — new "option s between 7 & 8" entry.
- `docs/handoff.md` — this rewrite.

### Memory updated this session

(None — no new behaviors to capture. Existing memories cover
strict-numerical + bug-intake + commit-naming rules already.)

## Running things

```bash
# Tests
uv run pytest -q

# Render current feature table
/feature-table

# v10 deliverables (still useful)
uv run lamill settings project set-deploy <name> <platform>
uv run lamill settings project show-deploy <name>
uv run lamill fleet repos --add-deploy-declarations [--dry-run/--apply]

# v10.E drift detection
uv run lamill project check <name>                     # surfaces CHECK_058/059/143
uv run lamill settings catalog run <path> --check CHECK_143

# Heading-outline check on any doc
grep -nE '^#+ ' docs/prd.md
```

## Commit style

```
portfolio: vN.X — <slice description>

<2-5 short paragraphs. WHY this slice exists and what shipped.
Mention test count and prior commit refs where helpful.>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

For doc-only work: `portfolio: docs — ...`. For runtime data:
`data: refresh — ...`. Never three-level identifiers in subject
or body.

## End state for the next slice

After **v6.F** (if picked up next):
- 5 NO_GIT sibling repos initialized as own-git-repos.
- Each carries the pending `lamill.toml` + initial commit + remote setup.
- `CHECK_058 has-lamill-toml` baseline reaches ~22/22 (modulo the
  2 no-remote sites which stay local-only until pushed).

After **v11.A** (active design — code may proceed):
- `lamill fleet hosting` ships as a peer of `fleet seo` /
  `fleet live`.
- 3 walkers (Vercel + CF Pages + HostGator UAPI) populate
  `data/hosting/<date>.json`.
- `--apply-declarations` flag writes `lamill.toml` for HG sites
  with local repos but no declaration (closes the v10.F use case).
- `fleet dashboard` + `project diagnose` gain a Hosting column /
  section.
- ~14 commits. Test strategy: mock at `httpx`/`requests` layer.

After **v11.B** (design open — 11.O-T must be answered first):
- `lamill new deploy <domain>` becomes polymorphic. Reads
  `lamill.toml`, dispatches CF Pages / Vercel / SFTP-to-HG.
- ADR-0009 lands first (third write surface justification).
- SFTP push flow for HG/custom platforms.
