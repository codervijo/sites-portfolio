# Handoff — sites/portfolio (next session)

You are a fresh Claude session picking up work on the `portfolio`
(a.k.a. `lamill`) CLI at `~/work/projects/sites/portfolio/`. This
document is the brief: where work stands at end-of-day **2026-05-20**,
what's next, and what changed since the previous handoff (2026-05-19).

## Read these first (in order)

1. `AI_AGENTS.md` (repo root) — `## Canonical docs` is your map.
2. `docs/CLAUDE.md` — conventions, ADR workflow, heading hygiene,
   locked target shapes.
3. `docs/decisions/README.md` — ADR index. ADR-0011 covers
   remote-host writes (v11.N). **No new ADR this session.** ADR-0012
   is the planned slot for when v18.D wires Google Trends into the
   v8 cluster snapshot (not yet written).
4. `docs/prd.md § 6 Versions` — tier-grouped phase log. Big plan
   expansion this session (v15.F + v16 + v17 + v18 + v19 + v20 + v22
   tiers all added).
5. `docs/architecture.md` — HOW (mechanisms / schemas / modules /
   CLI / integrations / active plans). Research-module section
   (§3) + cluster schema (§4) rewritten today for the as-shipped
   v12 shape.
6. `docs/shipping-history.md` — archived rationale. Now includes
   the **v12 tier-level entry** (v12.A-G) + per-phase entries for
   v12.A-F.
7. `docs/bugs.md` — **8 open bugs** as of 2026-05-20 (1 new
   tech-debt audit pass + 7 from 2026-05-19).

## Where the work is

**Last shipped (code):** `v13.B — per-project GSC diagnostics`
(commit `a693d96`, pushed to `origin/main`). The new default
output of `lamill project seo <domain>` itemizes sitemap status +
per-URL coverage from URL Inspection API + actionable hints.
Closes the gap `fleet focus` exposes (it flags issues but offers
no drill-down).

**Suite at 2251 passed / 1 skipped** (was 2108 at session start —
+143 tests across v12.B-F + v13.B).

**v12 tier ✅ COMPLETE + doc-synced.** All 7 sub-phases shipped
2026-05-19 → 2026-05-20:

| Phase | Scope | Tests | Commit |
|---|---|---|---|
| v12.A | Audit prompt rendering | 12 | (2026-05-17) |
| v12.B | Audit response parser | 24 | `3d2302e` |
| v12.C | Audit pass runner (OpenAI HTTP + cost) | 19 | `c95b974` |
| v12.D | Reconciliation + REVIEW_REQUIRED | 20 | `5e3de6c` |
| v12.E | `--verify` flag in `new research` | 17 | `7651bb5` |
| v12.F | Cost ledger + `verify_by_default` + `--invalidate` | 30 | `17826f3` |
| v12.G | Docs sync closing v12 tier | doc-only | `3210666` |

**v13.B ✅ shipped 2026-05-20** (commit `a693d96`, 33 tests). v13
tier scope was retheme'd this session — the original "analytical
roll-ups" framing was dropped (redundant with `fleet dashboard`),
v13 became per-project GSC diagnostics. Old v13.C (LLM content
seeding) moved to v14.E (postponed there now).

## What's new in v13.B (CLI-facing)

`lamill project seo <domain>` now renders TWO blocks:

```text
$ lamill project seo homeloom.app

  [v5.D 1-row 28-day aggregate header — unchanged]

  GSC diagnostics
    Property: https://homeloom.app/
    📋 Sitemaps (3 submitted)
      ✓ OK       /sitemap.xml          fetched 1d ago
      ✗ ERROR    /sitemap-pages.xml    14 error(s) · fetched 12d ago
      ⚠ WARN     /sitemap-blog.xml     4 warning(s) · fetched 1d ago

    📊 Coverage (top 10 inspected — 7/10 indexed, 70%)
      ✓ https://homeloom.app/             submitted_indexed   crawled 1d ago
      ✗ https://homeloom.app/about        crawled_not_indexed  crawled 3d ago
      ✗ https://homeloom.app/gone         not_found_404        crawled 5d ago
      ...

    💡 Hints
      · /sitemap-pages.xml parse/fetch error → re-deploy with valid XML;
        run `lamill project fix homeloom.app --apply` to clear CF edge cache
      · /about crawled_not_indexed → expand to ≥300 words or remove from sitemap
      · /gone not_found_404 → remove from sitemap or restore the page
```

New flag: `--top N` (default 10) caps URL Inspection daily quota.
Cache at `data/gsc/<domain>/<UTC-today>.json` (24h TTL); `--refresh`
bypasses.

**v13.B has NOT yet been hand-tested against the live fleet.**
Canonical first target: `homeloom.app` (the site `fleet focus`
just flagged with 4 sitemap parse errors). Expect ~20-40s on
first run; subsequent runs read cache.

## What changed in the plan this session

Three threads:

### 1. v12 tier wrapped (code + docs)

v12.B-G shipped on 2026-05-19 (commit dates) — the full v12 tier
is now complete. Architecture.md and shipping-history.md updated;
v12 tier-level design notes migrated from prd.md to
shipping-history.md per the v10/v11 wrap pattern.

### 2. v13 rethemed

Old v13.B "Roll-up" (the `lamill project list` aggregate-verdict
view that originated in v4.B and rode 6+ renumbers since) was
dropped as redundant with `fleet dashboard` + `fleet info summary`
+ `fleet focus`. v13 became **per-project GSC diagnostics drill-
down** (rationale: `fleet focus` detects issues but has no drill-
down path; v13.B fills that gap). Old v13.C (LLM content seeding,
postponed indefinitely) moved to v14.E.

### 3. New planned tiers (no code yet)

| Tier | Scope | Effort |
|---|---|---|
| v15.A-F | Rich GSC `project seo` view — analytics section flags + fleet-level rollup | ~8-11h |
| v16.A-E | SEO check expansion — 14 universal + WordPress lane | ~5-7h |
| v17.A-F | GA4 — install helper active; Data API consumers deferred until fleet GA4 coverage broader | ~10-15h |
| v18.A-B | Google Trends foundation via SerpAPI engine | ~2-3h |
| v19.A-D | Lighthouse + CrUX (lab + field) | ~4-6h |
| v20.A-B | Indexing API hook (`new deploy --reindex`) | ~1-2h |
| v21 | **Reserved** — Gemini for audit-pass diversity (skipped 2026-05-19) | — |
| v22.A-C | GSC Sitemaps + per-URL bulk index status | ~2-3h |

**Adopted convention this session:** every new tier (v16+) starts
with `vN.A — kickoff planning` — re-validate the tier's plan
against learnings from recently shipped tiers before starting the
first concrete sub-phase. v13/v14/v15 carry the kickoff gate as a
one-line tier-preamble note (their letter slots are already
assigned; renumbering would break references).

## What's next

**Strict-numerical next:** **v6.F** (own-git-repo guided migration)
— closes 5 NO_GIT sites baseline-failing CHECK_058 from v10.E
(`iotnews.today`, `linkedcsi.live`, `streamsgalaxy.com`,
`thoralox.com`, `whizgraphs.com`). ~3-5h. No design blockers.
Queue-jumped this session per operator directive — confirm with
operator if re-considering.

**Real-data validation pending:**

| Target | Phase | Why |
|---|---|---|
| `homeloom.app` (sitemap errors) | **v13.B** | First hand-test of just-shipped v13.B; this is the site `fleet focus` flagged 2026-05-20. |
| `iotnews.today` (v10.E drift) | v11.M-N | Active deploy verb (M+N) still has zero real-fleet exercise. Carryover from previous handoff. |

**Other queued tiers** (in priority order):

- **v6.F** — strict-numerical next (above)
- **v13** complete — no more sub-phases planned
- **v14.A-D** — deploy verification (deprioritized; reconsider at v14.A kickoff)
- **v15.A-F** — rich GSC analytics + fleet rollup
- **v16.A-E** — SEO check expansion
- **v17.A-B** — GA4 install helper first (others deferred)
- **v18.B** — Google Trends foundation
- **v19.B-D** — Lighthouse + CrUX
- **v20.B** — Indexing API hook
- **v22.B-C** — GSC Sitemaps + per-URL bulk index

## State pointers — fleet specifics

### Today's fleet snapshot (`data/checks/2026-05-20.json` + cached)

**1 🟢 green / 15 🟡 yellow / 16 🔴 red** across 32 domains.

**Real concerns flagged 2026-05-20:**
- `iotnews.today` returning HTTP 500 (canonical v10.E drift case;
  hosted on HG gator4216 despite declaring `vercel`)
- `lamill.us` HTTP 404 (no content deployed yet)
- `homeloom.app` GSC: sitemap parse errors (4) — **the v13.B
  hand-test target**
- `kwizicle.com` stale CF edge cache on `/sitemap-index.xml`
  + `/sitemap-0.xml` (`project fix --apply` to purge)

**Healthy:**
- `airsucks.com` — the one all-green site
- All 6 CFW sites (cricketfansite / donready / isitholiday /
  kwizicle / voltloop / airsucks)
- All 5 Vercel sites (civictools / keralavotemap / lamillrentals /
  washcalc / csinorcal — csinorcal red on SEO is **expected dark-
  site behavior**)

### v10.D scoreboard (still load-bearing for v6.F)

22 of 23 fleet sites have `lamill.toml`. 5 NO_GIT sites have the
file in working tree but no `.git` to commit it:
`iotnews.today`, `linkedcsi.live`, `streamsgalaxy.com`,
`thoralox.com`, `whizgraphs.com`. v6.F closes the loop.

## Open bugs (`docs/bugs.md`)

8 open as of 2026-05-20:

1. **`2026-05-20 — tech-debt audit pass`** *(new today; minor)* —
   broad codebase hygiene concern. Candidate areas: cli.py size
   (6700+ lines), duplicate OpenAI HTTP code (serp.py vs
   audit_pass.py), cache-module proliferation, CHECK_NNN skip-
   condition repetition, shared renderer helpers, stale
   `data/gsc/2026-04-29.json` snapshot.
2. *(minor — partial wontfix)* Vercel walker misses ~9 fleet sites
   — diagnosed as operator-side data quality.
3. *(minor)* HG walker `install_path` empty — likely
   `document_root` vs `documentroot` field-name mismatch.
4. *(cosmetic)* HG-extra `disk N MB` is account-level total;
   misleading per-row.
5. *(minor)* HG WordPressManager UAPI returns nothing —
   diagnostic curl docs in bugs.md.
6. *(minor — pre-existing)* `fleet dashboard` truncates every cell
   on standard terminal width.
7. *(minor)* `fleet seo --refresh` and `fleet domains` show
   different counts.
8. *(minor)* `settings project set-deploy` fails for sites/ dirs
   missing from portfolio.json.

Per `feedback_bug_intake_workflow` — pick up bugs between phases.
None are blockers.

## Hard constraints

(All carryover from previous handoff — no new constraints this
session.)

### Strict two-level `vN.X` for commits AND docs (ADR-0004)

Never `vN.X.Y` / `C1/C2/C3` / `P4.A.1`. Memory
`[[commit-naming-strict-two-level-vn-x]]`.

### Three write surfaces

- **Local-FS (ADR-0003):** `new bootstrap` (creates) + `project
  fix` (remediates).
- **Remote-host (ADR-0011):** v11.N's `new deploy` for
  `hostgator`/`custom`.
- **Read-only external API** (no ADR needed): v12's audit pass +
  v13.B's URL Inspection calls — both hit Google/OpenAI APIs but
  don't write to any operator-owned surface.

### Trust operator fleet categorization

When operator says "X and Y are on hostgator, rest are vercel,"
**accept and act**. Memory
`[[feedback-trust-operator-fleet-categorization]]`.

### Bug intake → `docs/bugs.md`

Operator drops brief reports; Claude writes the structured entry.
Memory `[[feedback-bug-intake-workflow]]`.

### prd.md tier-grouped structure

Per-tier `### vN` with `#### Phases` table + `#### Design notes`
(only for unshipped tiers). v10, v11, v12 all wrapped — design
notes migrated to `shipping-history.md`. v13 currently has only
v13.B shipped — design notes stay in prd.md until tier wraps.
Memory `[[feedback-prd-tier-grouped-structure]]`.

### Working order = strict numerical

Lowest unshipped `vN.X` in prd.md is next — not session-handoff
suggestions. v6.F is strict-next. This session queue-jumped to
v12.B-G + v13.B per explicit operator directive — confirm with
operator before doing the same. Memory
`[[feedback-strict-numerical-working-order]]`.

### Kickoff planning gate (new this session)

Every new tier (v16+) starts with `vN.A — kickoff planning` —
re-validate the tier's plan against recently shipped tiers
before starting the first concrete sub-phase. v13/v14/v15
absorb the gate as a one-line tier-preamble note (existing
letter slots).

### Other long-standing constraints

- pnpm-only / Vite ≥6 / Astro ≥5 for `sites/*` per ADR-0008.
- Heading hygiene: grep outline before adding any heading to a
  long-lived `.md` file (CHECK_043).
- No `--no-verify` / `--no-gpg-sign` / amend pushed commits.
- Stage by name; never `git add -A`.

## Memory updated this session

None new — all guidance covered by existing memories. The v13
retheme + v15-v22 planning expansion are captured in `prd.md`;
no memory addition needed.

## Running things

```bash
# Tests
uv run pytest -q
# (suite at 2251 passed / 1 skipped)

# v12 deliverables — research with --verify
uv run lamill new research "ev charger cost"                    # primary only (~$0.04)
uv run lamill new research "ev charger cost" --verify           # primary + audit + reconciliation (~$0.05)
uv run lamill new research "ev charger cost" --verify --invalidate audit   # re-run audit on cached cluster

# v13.B deliverables — per-project GSC diagnostics (NEW)
uv run lamill project seo homeloom.app                # 1-row aggregate + diagnostics block (~20-40s first run)
uv run lamill project seo homeloom.app --refresh      # bypass cache
uv run lamill project seo homeloom.app --top 25       # inspect more URLs (watch URL Inspection quota: 200/day)

# v11 deliverables — read-only walker + active deploy (unchanged from prior handoff)
uv run lamill fleet hosting                           # cached snapshot
uv run lamill fleet hosting --refresh                 # re-walk all 4 providers
uv run lamill fleet dashboard                         # 14-column rollup
uv run lamill project diagnose <domain>               # six-layer auto-investigate
uv run lamill new deploy <domain> [--apply]           # polymorphic deploy verb

# v10.E drift detection still active
uv run lamill project check <domain>                  # CHECK_058/059/143

# Fleet focus — what to look at today
uv run lamill fleet focus                             # surfaces v13.B's hand-test targets
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

## Suggested next-slice options

| Path | Why | Effort |
|---|---|---|
| **v13.B hand test against `homeloom.app`** | First real validation of just-shipped v13.B; canonical target — fleet focus reports 4 sitemap parse errors on this domain. Likely surfaces 1-3 post-ship bugs (pattern matches v11.D/I post-ship-fix history). | ~10-30min + bugfix tail |
| **v11 hand test against `iotnews.today`** | Carryover from previous handoff — v11.M-N (active deploy verb) still has zero real-fleet exercise. | ~30-60min + bugfix tail |
| **v6.F** — own-git-repo guided migration | Strict-numerical next; closes 5 NO_GIT failures from v10.E. | ~3-5h |
| **v15.A** — rich GSC `project seo` foundation | Operator excited about this 2026-05-19; design done; v13.B already shipped the per-domain cache module v15.A would reuse. | ~2h |
| **install_path field-name quick fix** (bug #3) | One-line walker fix once curl confirms the field name. | ~10min |
| **Dashboard truncation polish** (bug #6) | `no_wrap=True` on Domain column + drop low-value columns at narrow widths. | ~30min |

**Default recommendation: hand test v13.B against `homeloom.app`
first.** v13.B has 33 tests but zero real-fleet exercise; the
post-ship-fix history (v11.D auth, v11.I renderer) shows hand-test
bugs are nearly guaranteed on first-fleet exposure. Catching them
while the design is fresh is faster than after a context switch.
v6.F is the strict-numerical follow-up unless operator queue-jumps.
