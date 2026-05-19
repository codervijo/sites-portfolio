# Handoff — sites/portfolio (next session)

You are a fresh Claude session picking up work on the `portfolio`
(a.k.a. `lamill`) CLI at `~/work/projects/sites/portfolio/`. This
document is the brief: where work stands at end-of-day 2026-05-19,
what's next, and what changed since the canonical docs were last
updated.

## Read these first (in order)

1. `AI_AGENTS.md` (repo root) — `## Canonical docs` is your map.
2. `docs/CLAUDE.md` — conventions, ADR workflow, heading hygiene,
   locked target shapes.
3. `docs/decisions/README.md` — ADR index. Now includes **ADR-0011**
   (remote-host writes as a separate write-surface category) shipped
   with v11.N.
4. `docs/prd.md § 6 Versions` — tier-grouped phase log.
5. `docs/architecture.md` — HOW (mechanisms / schemas / modules /
   CLI / integrations / active plans).
6. `docs/shipping-history.md` — archived rationale for shipped
   phases. The v11.A-N tier entry near the top covers the whole
   tier (both walker cluster + active deploy verb).
7. `docs/bugs.md` — 7 open bugs as of 2026-05-19 (no bugs addressed
   this session).

## Where the work is

**Last shipped (docs):** `v11.U — docs sync closing v11 tier` (commit
`c20efb7`, local only — not yet pushed). Preceded by code commits
`v11.M` (`84ca891`) and `v11.N` (`ee863f2`), both pushed. Suite at
**2108 passed / 1 skipped** (was 2046).

**v11 tier ✅ COMPLETE + doc-synced.** All 15 sub-phases shipped over
two days (2026-05-18 → 2026-05-19):

| Phase | Scope | Tests | Commit |
|---|---|---|---|
| v11.A | Foundation (apikeys + `HostingRow` + constants) | 25 | `139fb63` `1b59e85` |
| v11.B | Vercel walker | 25 | (in v11.A-B series) |
| v11.C | Cloudflare Pages walker *(+ pagination fix)* | 25 | (+`cb5f4cf`) |
| v11.D | HostGator walker (cPanel UAPI) *(+ HG-auth + bug fixes)* | 17 | (+`42bb98b` `d3bae51`) |
| v11.E | Orchestrator + match + provider-conflict | 15 | |
| v11.F | Snapshot cache (`hosting_cache.py`) | 14 | |
| v11.G | CLI shell (`lamill fleet hosting`) | 11 | |
| v11.H | Cloudflare Workers walker (inserted after hand test) | 19 | |
| v11.I | Renderer upgrade (status emoji + footer) | 28 | `44fe8dc` |
| v11.J | `--apply-declarations` writer (HG-only, dry-run default) | 15 | `47e77f4` |
| v11.K | Dashboard + diagnose integrations | 19 | `afa2031` |
| v11.L | Docs sync closing read-only walker cluster | doc-only | `6704792` |
| **v11.M** | **`new deploy` polymorphic dispatcher** | **22** | **`84ca891`** |
| **v11.N** | **UAPI file-upload deploy for hostgator/custom + ADR-0011** | **40** | **`ee863f2`** |
| **v11.U** | **Docs sync closing v11 tier (architecture.md + shipping-history.md + prd.md design block migration)** | **doc-only** | **`c20efb7`** |

End-to-end verified against operator's real fleet 2026-05-19 for
the read-only half. The active deploy half (M+N) has **not been
hand-tested against the live fleet yet** — see "Suggested next-slice
options" below.

## What v11.M-N shipped (new this session)

**v11.M (`84ca891`).** `new deploy <domain>` is now a polymorphic
dispatcher (`cli.py::new_deploy`). Reads `lamill.toml` and routes
by platform:

  * `cf-pages` → existing `CloudflarePagesDeploy` (extracted into
    private `_deploy_cf_pages_v3c()` — behavior unchanged from v3.C).
  * `cf-workers` → `deploy_cf_workers_via_shell()` runs
    `pnpm run deploy` in the project dir (delegates to wrangler;
    re-implementing wrangler's assets-upload pipeline was rejected
    as too fragile for the maintenance burden).
  * `vercel` → `deploy_vercel_via_shell()` runs `vercel deploy --prod`.
  * `hostgator` / `custom` → v11.N UAPI uploader.
  * `netlify` / `github-pages` → "not implemented yet" exit (no
    operator fleet sites on these platforms).
  * `none` → reject with `settings project set-deploy` hint.
  * missing `lamill.toml` → assume `cf-pages` (legacy default) with
    an explicit notice.

Shell helpers (`deploy.py::deploy_cf_workers_via_shell`,
`deploy_vercel_via_shell`) take a `runner=` injection seam — tests
never fork real subprocesses.

**v11.N (`ee863f2`).** Adds `deploy_source: str = "dist/"` to
`HostingBlock` in `lamill_toml.py` (operator-configurable per site;
serializer omits when default for round-trip determinism). Adds four
cPanel UAPI helpers in `hosting.py` — `_hg_upload_file` (multipart
POST to `Fileman/upload_files`), `_hg_mkdir`, `_hg_rename`,
`_hg_delete_dir` (the last three GET via existing `_call_hg_uapi`).

Orchestrator: `deploy_hg_files(row, *, lamill_toml, token,
cpanel_user, sites_root, dry_run, client) -> HgDeployRow` —
single-row by design per ADR-0011's per-site allowlist. Stage-then-
rename atomicity:

  1. mkdir `<public_html_path>.next/`
  2. upload all files (lazy subdir mkdirs)
  3. rename current → `.prev/`  (benign-failure on first-time deploy)
  4. swap `.next/` → current     ← the load-bearing rename
  5. delete `.prev/`             (best-effort, non-fatal)

On step 4 failure: rename `.prev/` back to current so prod stays up.

CLI wiring in `cli.py::_deploy_hostgator_v11n` reads token via
`apikeys.get_key("HOSTGATOR_TOKEN_<account>")`, cpanel_user via
`apikeys.hg_user_for_account()`, and the matching `HostingRow` via
`hosting_cache.latest_snapshot()`. Refuses to deploy without a
snapshot (hints to run `fleet hosting --refresh` first). New
`--apply` flag on `new deploy` flips dry-run-default → push for the
hostgator/custom branches (other branches keep their existing flag
semantics).

**ADR-0011 (new).** Establishes remote-host writes as a separate
write-surface category from ADR-0003's local-FS scope. ADR-0003 stays
in force, unchanged. The PRD's original gate said "ADR-0009" but that
slot was already taken by `0009-makefile-forwards-to-central-builder`
— ADR-0011 is the next free number. Future remote write surfaces
inherit ADR-0011's constraints (idempotent, dry-run default, per-site
allowlist via `[hosting]` block, stage-then-rename atomicity where
possible).

11.O-T gating questions all resolved 2026-05-19 (see `prd.md § v11`
resolutions block):

| # | Resolution |
|---|---|
| 11.O | One polymorphic `new deploy <domain>` |
| 11.P | `[hosting].deploy_source` configurable, default `dist/` |
| 11.Q | cPanel UAPI `Fileman/upload_files` (reuses v11.D auth) |
| 11.R | Static-only; WP sites skip with footer |
| 11.S | New ADR-0011 (remote-write category); ADR-0003 intact |
| 11.T | Stage-then-rename pair via cPanel Fileman/rename |

## What's next

**Strict-numerical:** Still **v6.F** (own-git-repo guided migration).
Closes the 5 NO_GIT sites baseline-failing CHECK_058 from v10.E
(`iotnews.today`, `linkedcsi.live`, `streamsgalaxy.com`,
`thoralox.com`, `whizgraphs.com`). ~3-5h. No design blockers.
Queue-jumped this session per operator directive "finish v11 first."

**Other queued tiers:**
- v12.B-G — adversarial audit completion (parser → runner → reconciliation → CLI flag → polish → docs)
- v13.B — `project list` roll-up
- v14.A-D — deploy verification (deprioritized per renumber)
- v15.A-E — rich GSC `project seo` view (design notes shipped 2026-05-19, code planned)

**Doc sync — already done as `v11.U`** (commit `c20efb7`). Migrated
the tier-level design block from `prd.md` to `shipping-history.md`
following the v10 wrap pattern; added per-phase v11.M + v11.N
entries; extended `architecture.md` § 2 Write surfaces (now split
into local-FS / remote-host categories) + § 3 Mechanisms (active
deploy verb section) + § 4 Schemas (`deploy_source` field +
`HgDeployRow` dataclass). Letter `U` chosen over `O` per CLAUDE.md
heading-hygiene to avoid the collision with gating-question 11.O
inside `prd.md § v11`.

## State pointers — fleet specifics

### v11 hand-test findings (2026-05-19, read-only half only)

Cached snapshot at `data/hosting/2026-05-19.json` contains 21 rows
across the operator's real fleet:
- **6 Cloudflare Workers**: airsucks · cricketfansite · donready · isitholiday · kwizicle · voltloop
- **5 Vercel**: civictools · csinorcal · keralavotemap · lamillrentals · washcalc
- **10 HostGator** (across gator3164 + gator4216): carrepairsite · hybridautopart × 2 (conflict) · iotnews.today · lamill.us · maslist · streamsgalaxy · thakinaam · ~~virtually.co.in~~ · ~~winmacbook.com~~ (last two deleted from HG by operator 2026-05-19; re-walk will drop them)
- **0 Cloudflare Pages** (operator has no legacy Pages projects — modern wrangler deploys all land as Workers)

**Active deploy half (v11.M-N) NOT yet hand-tested.** The canonical
first hand-test target is `iotnews.today`:

  1. The site is the visible v10.E drift case (`lamill.toml` declares
     `vercel` but actually lives on HG gator4216).
  2. Operator already plans to run
     `lamill settings project set-deploy iotnews.today hostgator`
     + edit the `[hosting]` block as the v10.E remediation.
  3. After that remediation, `lamill new deploy iotnews.today` is
     the natural validation: confirms the dispatcher routes correctly
     (cf-pages → hostgator branch), reads the right `HOSTGATOR_TOKEN_GATOR4216`
     credential, finds iotnews.today in the snapshot, and the UAPI
     upload + stage-then-rename works against real cPanel.
  4. Dry-run first (`new deploy iotnews.today` → no `--apply`), inspect
     the planned file count / bytes / target path. Then `--apply`.

### Known drift cases (v10.E CHECK_143)

- **`iotnews.today`** — declared `vercel` in `lamill.toml` but walks as `hostgator` (gator4216). Canonical drift case. Operator fix: `lamill settings project set-deploy iotnews.today hostgator` + update `[hosting]` block. Natural first hand-test target for v11.M-N.
- **`hybridautopart.com`** — registered as addon on BOTH HG accounts (gator3164 disk 500MB · gator4216 disk 3990MB). Operator-confirmed misconfiguration; CONFLICT flag (🤐) surfacing correctly in dashboard + diagnose. Operator to clean up cPanel side; tool's job done. Note: v11.N will refuse to deploy to either side of the conflict (WP-skipped anyway — WordPress detected).

### v10.D scoreboard (still load-bearing for v6.F)

22 of 23 fleet sites have `lamill.toml`. 5 NO_GIT sites have the
file in working tree but no `.git` to commit it:
`iotnews.today`, `linkedcsi.live`, `streamsgalaxy.com`,
`thoralox.com`, `whizgraphs.com`. v6.F closes the loop.

## Open bugs (`docs/bugs.md`)

7 open as of 2026-05-19 (no bugs addressed this session):

1. *(minor — partial wontfix)* Vercel walker misses ~9 fleet sites — diagnosed as operator-side data quality (no Vercel project / custom domain not bound / name mismatch). Walker is correct.
2. *(minor)* HG walker `install_path` empty — likely `document_root` vs `documentroot` field-name mismatch. Quick fix once curl confirms the real key.
3. *(cosmetic)* HG-extra `disk N MB` is account-level total; misleading per-row. Move to footer or rename column.
4. *(minor)* HG WordPressManager UAPI returns nothing — diagnostic curl docs in bugs.md; could fall back to `Fileman/list_files` looking for `wp-includes/version.php`.
5. *(minor — pre-existing, v11.K made marginally worse)* `fleet dashboard` truncates every cell on standard terminal width. 15 columns squeezed into ~80 cols.
6. *(minor)* `fleet seo --refresh` and `fleet domains` show different counts (silent scope filter).
7. *(minor)* `settings project set-deploy` fails for sites/ dirs missing from portfolio.json.

Per `feedback_bug_intake_workflow` — pick up bugs between phases.
None are blockers for v6.F or the v11.M-N hand test.

## Hard constraints

### Strict two-level `vN.X` for commits AND docs (ADR-0004)

Never `vN.X.Y` / `C1/C2/C3` / `P4.A.1` / `Phase 1 step 2`. Three-
level identifiers are forbidden in commit subjects and on-disk docs.
Memory `[[commit-naming-strict-two-level-vn-x]]`.

### Two local-FS write surfaces (ADR-0003) + remote-host writes (ADR-0011 — NEW)

- **Local-FS:** `new bootstrap` (creates project dirs) and
  `project fix` (remediates existing ones). All other commands are
  read-only against `sites/<domain>/`.
- **Remote-host:** v11.N's `new deploy` for `hostgator`/`custom`
  pushes to a cPanel host via UAPI. Constraints (per ADR-0011):
  idempotent, dry-run default, per-site allowlist via `[hosting]`
  block, stage-then-rename atomicity. Future remote write surfaces
  inherit these.

### Trust operator fleet categorization

When operator says "X and Y are on hostgator, rest are vercel,"
**accept and act**. Don't re-probe with curl / dig. Memory
`[[feedback-trust-operator-fleet-categorization]]`.

### Bug intake → `docs/bugs.md`

Operator drops brief reports; Claude writes the structured entry
under `## Open bugs`. Current phase keeps going; pick up bugs
between phases. On fix: cut to `## Fixed bugs` with `**Fixed in**
— <sha>`. Memory `[[feedback-bug-intake-workflow]]`.

### prd.md tier-grouped structure

Per-tier `### vN` with `#### Phases` table + `#### Design notes`
(only for unshipped tiers). v10 wrapped — design notes moved to
`shipping-history.md`. v11 now wrapped — same migration still
pending (see v11.O docs-sync candidate above). Memory
`[[feedback-prd-tier-grouped-structure]]`.

### Working order = strict numerical

Lowest unshipped `vN.X` in prd.md is next — not session-handoff
suggestions. v6.F is strict-next. This session queue-jumped to
v11.M-N per explicit operator directive — confirm with operator
before doing the same. Memory
`[[feedback-strict-numerical-working-order]]`.

### Other long-standing constraints

- pnpm-only / Vite ≥6 / Astro ≥5 for `sites/*` per ADR-0008.
- Heading hygiene: grep outline before adding any heading to a
  long-lived `.md` file (CHECK_043).
- No `--no-verify` / `--no-gpg-sign` / amend pushed commits.
- Stage by name; never `git add -A`.

## Memory updated this session

None new — existing memories cover everything needed (strict-
numerical, bug-intake, commit-naming, trust-categorization, no
self-conformance). The v11.M-N gating-question resolutions are
captured in `prd.md` and ADR-0011; no memory addition needed.

## Running things

```bash
# Tests
uv run pytest -q
# (suite at 2108 passed / 1 skipped)

# Render current feature table
/feature-table

# v11 deliverables — read-only walker (unchanged from v11.L)
uv run lamill fleet hosting                    # cached snapshot table
uv run lamill fleet hosting --refresh          # re-walk all 4 providers
uv run lamill fleet hosting --only <domain>    # single-domain probe
uv run lamill fleet hosting --provider {vercel|cloudflare-pages|cloudflare-workers|hostgator}
uv run lamill fleet hosting --apply-declarations [--apply]
uv run lamill fleet dashboard                  # gains Host + Prov cols (v11.K)
uv run lamill project diagnose <domain>        # gains Hosting layer (v11.K)

# v11.M-N deliverables — active deploy verb (NEW this session)
uv run lamill new deploy <domain>              # dispatches by lamill.toml platform
uv run lamill new deploy <hg-domain>           # dry-run for hostgator (shows plan)
uv run lamill new deploy <hg-domain> --apply   # actually pushes via UAPI

# v10.E drift detection still active
uv run lamill project check <domain>           # CHECK_058/059/143
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
| **v11 hand test against iotnews.today** | First real validation of v11.M-N against the live fleet; canonical drift case as a stress test. Likely surfaces post-ship bugs the same way v11.D/I did. | ~30-60min + bugfix tail |
| **v6.F** — own-git-repo guided migration | Strict-numerical next; closes 5 NO_GIT failures from v10.E. | ~3-5h |
| **install_path field-name quick fix** (bug #2) | One-line walker fix once curl confirms the field name. | ~10min |
| **Dashboard truncation polish** (bug #5) | `no_wrap=True` on Domain column + drop low-value columns at narrow widths. | ~30min |
| **v15.A** — rich GSC `project seo` foundation | Operator was excited about this 2026-05-19; design notes already shipped. | ~2h |
| **v12.B** — adversarial audit response parser | First step in the audit completion arc. | ~2-3h |

**Default recommendation: hand test v11.M-N against `iotnews.today`
first.** v11.M-N have ~62 tests but zero real-fleet exercise; the
post-ship-fix history of v11.D (HG auth username decoupling) and
v11.I (renderer bugs) shows hand-test bugs are nearly guaranteed
on first-fleet exposure. Catching them while the design is fresh is
faster than after a context switch. v6.F is the strict-numerical
follow-up unless operator queue-jumps.
