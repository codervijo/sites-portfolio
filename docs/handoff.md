# Handoff — sites/portfolio (next session)

You are a fresh Claude session picking up work on the `portfolio`
(a.k.a. `lamill`) CLI at `~/work/projects/sites/portfolio/`. This
document is the brief: where work stands at the end of the
2026-05-18 session, what's next, and what changed since the
canonical docs were last updated.

## Read these first (in order)

1. `AI_AGENTS.md` (repo root) — `## Canonical docs` is your map.
2. `docs/CLAUDE.md` — conventions, ADR workflow, heading hygiene,
   locked target shapes.
3. `docs/decisions/README.md` — ADR index. Skim it.
4. `docs/prd.md § 6 Versions` — tier-grouped phase log. Each
   `### vN` carries `#### Phases` (status table) + (for unshipped
   tiers) `#### Design notes`.
5. `docs/architecture.md` — HOW (mechanisms / schemas / modules /
   CLI / integrations / active plans). **`§ 5 Projected CLI
   surface`** has the full command tree with shipped + planned
   markers + open design questions.
6. `docs/shipping-history.md` — archived rationale for shipped
   phases. v10.A and v10.B entries land here.
7. `docs/bugs.md` — open + fixed bug journal. Three entries open
   2026-05-18.

## Where the work is

**Last shipped (code):** `v10.C — fleet repos
--add-deploy-declarations migration sweep` (commit `5ca44af`).
Plus per-sibling-repo commits of `lamill.toml` files across 17
sibling repos (v10.D real-fleet sweep).

**Full test suite:** 1801 passed / 1 skipped (no failures).

**v10 tier status:**

| Phase | Status | What |
|---|---|---|
| v10.A | ✅ | `lamill.toml` foundation — schema, dataclasses, `load()`, `write()`, `infer_from_existing_configs()`, `detect_platform_signals()`, `to_dict()`. 70 tests. |
| v10.B | ✅ | `settings project {set-deploy, show-deploy, set-launched}` CLI. `set-launched` moved here from `project set-launched` for namespace consistency. 29 tests. |
| v10.C | ✅ | Auto-write — `new bootstrap` writes `lamill.toml`; `fleet repos --add-deploy-declarations [--dry-run/--apply] [--include-ambiguous]` migration. 28 tests. |
| v10.D | ✅ (substantively) | Real-fleet sweep — 22 of 23 sites have `lamill.toml`; 17 committed in sibling repos. See "v10.D scoreboard" below. |
| v10.E | ⏳ | **Strict-numerical next.** Drift detection + conformance checks (`has-lamill-toml` / `lamill-toml-valid` / `deploy-drift` CHECK_xxx series). ~6-8h. |
| v10.F | ⏳ | HostGator cPanel integration. **CLI design is OPEN** — first proposal rejected by operator 2026-05-18 ("don't like that CLI at all"). Needs rethink before code lands. ~8-10h. |
| v10.G | ⏳ | SFTP deploy abstraction. ~10-12h. |

**Other recent shipped tiers:**
- v12.A — adversarial audit prompt rendering (shipped 2026-05-17,
  pre-this-session).
- v9 tier — bootstrap UX (canonical AI_AGENTS sections + prompts
  + portfolio.json auto-update + growth.md seed).

## v10.D scoreboard (real-fleet sweep state)

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
- **NO_GIT (own .git missing) — `lamill.toml` untracked:** 5 — iotnews.today · linkedcsi.live · streamsgalaxy.com · thoralox.com · whizgraphs.com. These can't carry committed `lamill.toml` until v6.F runs.

**Out of v10 scope:**
- `hostkit.app` — unregistered domain; stale `sites/` dir.
- `carrepairsite.com` (HG account 1 primary, no local repo) — v10.F surfaces.
- `thakinaam.com` (HG account 2 primary, no local repo) — v10.F surfaces. **Check whether it's in portfolio.json**; surfaced from cPanel screenshot 2026-05-18 and may not be tracked.
- `newiniot.com` — dead (invalid CF nameservers); `portfolio.json` cleanup.

**Drift observation logged in memory:**
`iotnews.today` declared `vercel` in `lamill.toml` but currently
serves from HG account 2 (server: Apache, IP 216.172.184.116
matches HG account 2 shared IP). Either mid-migration or DNS
not switched. v10.E drift detection will catch this — it's
the canonical test case.

## Next step

**Strict-numerical:** v10.E (drift detection + conformance
checks). But consider doing **v6.F first** (own-git-repo guided
migration) so the 5 NO_GIT sites can carry committed
`lamill.toml` files — otherwise v10.E's `has-lamill-toml` check
fails on all 5 by definition.

**Two reasonable next-task framings:**
1. **v6.F before v10.E** — close the NO_GIT loop. 5 sites need
   `git init` + initial commit + remote setup + their pending
   `lamill.toml` committed. Then v10.E starts with a clean
   `has-lamill-toml` baseline.
2. **v10.E directly** — accept that 5 sites will fail
   `has-lamill-toml`; ship drift detection now. v6.F follows.

Operator decision; confirm before starting.

## Hard constraints (some new this session)

### Strict two-level `vN.X` for commits AND docs (ADR-0004)

Never `vN.X.Y`, never `C1/C2/C3`, never `P4.A.1`, never `Phase 1
step 2` — those are three-level identifiers in disguise. Memory
[[commit-naming-strict-two-level-vn-x]] has the full rule. Three-
level fixes shipped this session for prd.md (`v3.A.1` → `v3.A`,
`v3.B.2` → `v3.B`) and architecture.md (C1-C8 / Phase 1-4
labels in §9 plans, `v7.A.1/2/3` mention in §5).

### Trust operator fleet categorization

When operator says "X and Y are on hostgator, rest are vercel,"
**accept and act**. Don't re-probe with curl / dig to "verify."
Memory [[feedback-trust-operator-fleet-categorization]] —
established 2026-05-18 after I burned tokens probing 8 sites
the operator had already categorized.

### Bug intake → docs/bugs.md

Operator drops brief reports ("found a bug: X"); Claude writes
the structured entry under `## Open bugs`. Current phase keeps
going; pick up bugs between phases. On fix: cut to `## Fixed
bugs` with `**Fixed in** — <sha>`. Memory
[[feedback-bug-intake-workflow]].

### prd.md tier-grouped structure

Per-tier `### vN` with `#### Phases` table + `#### Design notes`
(only for unshipped tiers). Operator confirmed 2026-05-18:
"one/two outline clicks to get to the info I want." Memory
[[feedback-prd-tier-grouped-structure]].

### Working order = strict numerical

Lowest unshipped `vN.X` in prd.md is next — not session-handoff
suggestions. Memory [[feedback-strict-numerical-working-order]].
Exceptions exist (v6.F has queue-jumped historically; this
handoff suggests v6.F before v10.E for practical reasons —
confirm with operator).

### Other long-standing constraints

- Two write surfaces only (`new bootstrap`, `project fix`) per ADR-0003.
- pnpm-only / Vite ≥6 / Astro ≥5 for `sites/*` per ADR-0008.
- Heading hygiene: grep outline before adding any heading to a
  long-lived `.md` file (CHECK_043).
- No `--no-verify` / `--no-gpg-sign` / amend pushed commits.
- Stage by name; never `git add -A`.

## Open bugs (docs/bugs.md)

Three open as of 2026-05-18:

1. **`fleet seo --refresh` and `fleet domains` show different
   domain counts** — silent scope filter (live-site/forwarder vs
   wip). Severity: minor.
2. **`settings project set-deploy` fails for sites/ dirs missing
   from portfolio.json** — surfaced via `hostkit.app`. Severity:
   minor.
3. **`settings project set-deploy` doesn't auto-populate
   `custom_domains` from dir name** — inconsistency with the
   migration sweep. Severity: minor.

All deferred; fold into v10.B polish pass or v10.E kickoff.

## Memory updated this session

- `feedback-prd-tier-grouped-structure` — per-tier `### vN`
  with `#### Phases` + `#### Design notes`.
- `feedback-strict-numerical-working-order` — lowest unshipped
  `vN.X` first; not session-handoff stale pointers.
- `feedback-commit-naming-convention` (rewritten) — strict
  two-level `vN.X`; extends to on-disk docs.
- `feedback-bug-intake-workflow` — bugs.md operator-intake +
  Claude-maintained.
- `feedback-trust-operator-fleet-categorization` — accept
  categorization without re-probing.
- `project-hostgator-wp-sites` — two HG accounts identified
  (`gator3164` / `/home1`, `gator4216` / `/home3`),
  per-site categorization, iotnews.today drift, carrepairsite +
  thakinaam as v10.F test cases.

## Running things

```bash
# Tests
uv run pytest -q

# Render current feature table
/feature-table        # if the skill is available

# v10.A-C deliverables
uv run lamill settings project set-deploy <name> <platform>
uv run lamill settings project show-deploy <name>
uv run lamill fleet repos --add-deploy-declarations [--dry-run/--apply] [--include-ambiguous]

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
or body (per the strict rule above).

## End state for the next slice

After **v6.F** (if picked up next):
- 5 NO_GIT sibling repos initialized as own-git-repos.
- Each carries the pending `lamill.toml` + initial commit + remote setup.
- `has-lamill-toml` (v10.E) baseline goes from 17/22 to 22/22 (plus the 2 no-remote sites still local-only).

After **v10.E** (if picked up next):
- `CHECK_043 has-lamill-toml` / `CHECK_044 lamill-toml-valid` /
  `CHECK_045 deploy-drift` (or whatever the next free CHECK
  numbers are) ship.
- Drift detection compares declared platform (lamill.toml) vs
  DNS-resolved actual.
- `iotnews.today` declared-vercel-but-serving-from-HG is the
  canonical drift case it should catch.
- ~6-8h.

Either way, after the next slice, the v10 design notes can move
from `prd.md` to `shipping-history.md` once all of v10.A-E land.
