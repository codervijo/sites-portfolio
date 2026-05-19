# bugs.md — sites/portfolio/

Bug journal for `portfolio` / `lamill`. Operator-driven intake;
Claude-maintained entries.

## Workflow

1. **Operator drops a brief report in chat** — a sentence or two, no
   structure required. Examples: "found a bug: X command shows N
   but Y shows M", "this thing is slow", "the help text for `foo`
   is wrong."
2. **Claude writes up the structured entry here.** Investigates
   enough to fill Repro / Expected / Actual / Where / Severity /
   Notes. Asks the operator if anything is ambiguous, but doesn't
   block on a perfect repro — captures what's known and proceeds.
3. **The current shippable phase keeps going.** Bug work doesn't
   interrupt v10.A / v10.B / etc. unless the operator escalates
   ("fix this first" / `blocker` severity).
4. **After a phase (`vN.X`) ships,** Claude reviews `## Open
   bugs` and picks up entries before starting the next phase —
   in this order:
   - any `blocker` severity (always first)
   - bugs whose fix overlaps with the just-shipped or next phase
   - everything else by date (oldest first)
5. **Fix → cut entry from `## Open bugs` → append to `## Fixed
   bugs` with the `**Fixed in**` commit SHA.** Don't delete fixed
   entries; they're the project's known-issue archive.

This file is *not* one of the five canonical doc surfaces (prd.md /
architecture.md / shipping-history.md / decisions/ / CLAUDE.md).
It's a maintained journal — same shape relationship as
`docs/Prompts.md`.

## Entry shape

One bug per dated H3 entry. Heading:

```
### YYYY-MM-DD — <one-line headline>
```

Add a sequence suffix on same-day collisions:
`### 2026-05-18 — second-bug` / `### 2026-05-18 — third-bug`.

Body fields, in this order (skip what isn't useful):

- **Repro** — exact command(s) that trigger it.
- **Expected** — what should happen (one line).
- **Actual** — what does happen, with verbatim error output.
- **Where (guess)** — file / module / area Claude suspects.
- **Severity** — `blocker` / `major` / `minor` / `cosmetic`.
  Default: `minor`.
- **Notes** — anything else (related commits, workaround,
  half-investigated hypothesis).

On fix, append a `**Fixed in**` line referencing the commit SHA +
phase:

```
**Fixed in** — `4395e1d` (v10.A — schema + parser)
```

`**Wontfix** — <reason>` or `**Dup of** YYYY-MM-DD — <headline>`
when applicable. Don't delete.

## Open bugs

### 2026-05-18 — `settings project set-deploy` fails for sites/ dirs missing from portfolio.json

**Repro**
    # Site has sites/<domain>/ directory but no entry in portfolio.json:
    uv run lamill settings project set-deploy hostkit.app vercel --domain hostkit.app --non-interactive

**Expected**
Writes `sites/hostkit.app/lamill.toml`. The site dir exists; the
operator's intent is clear. Drift between sites/ and portfolio.json
is its own concern (`fleet info cleanup` / `fleet drift`), not a
blocker for declaring a deploy target.

**Actual**
Errors with `Domain not found in portfolio.json: 'hostkit.app'`
and exits 1. No file written.

This is a behavior discrepancy with the v10.C migration sweep
(`fleet repos --add-deploy-declarations`), which walks
`list_site_dirs()` and writes for any dir regardless of
portfolio.json membership. Both code paths produce a
`lamill.toml`; only one of them requires inventory presence.

**Where (guess)**
`src/portfolio/project_deploy.py:set_deploy` — uses
`resolve_project(name)` which is portfolio.json-keyed. The
migration sweep in the same module bypasses
`resolve_project` and walks the filesystem directly. Make
`set_deploy` either (a) fall back to the dir-name match when
portfolio.json lookup fails, (b) print a warning + proceed
anyway, or (c) suggest `fleet info cleanup` and exit.

**Severity**
minor — workaround is `fleet info cleanup` to reconcile
portfolio.json first, or hand-edit the JSON. Surfaces real drift
(sites/ dirs without inventory entries) which is useful, but the
hard-block on a write-only command is friction.

**Notes**
Discovered during v10.D walk 2026-05-18 — hostkit.app exists on
disk (has sites/hostkit.app/) but never got added to
portfolio.json. The fix conversation can include "should this
drift be treated as bug vs feature" — surfacing the drift early
might be the right behavior; just needs a clearer error.

---

### 2026-05-18 — `settings project set-deploy` doesn't auto-populate `custom_domains` from dir name

**Repro**
    uv run lamill settings project set-deploy <domain> cf-pages --non-interactive
    cat sites/<domain>/lamill.toml

**Expected**
The resulting `lamill.toml` includes
`custom_domains = ["<domain>"]` — matching the convention the v10.C
migration sweep uses (`_execute_write` in `project_deploy.py`
auto-populates from the directory name).

**Actual**
Without explicit `--domain <X>` flag, `set-deploy` writes no
`custom_domains` entry. Operator has to remember to pass
`--domain <domain>` to match the migration sweep's output.
Inconsistency: `fleet repos --add-deploy-declarations` and
`settings project set-deploy <name>` produce different
`lamill.toml` shapes for the same input domain.

**Where (guess)**
`src/portfolio/project_deploy.py:set_deploy` —
`_resolve_domain_list()` returns `[]` when no flag and no
existing entry. Default could be `[name]` (the canonical domain
the operator just typed) when the prompt is skipped via
`--non-interactive`.

**Severity**
minor — workaround is one extra flag (`--domain <name>`); files
written without it are still valid `lamill.toml`, just under-
populated. Worth fixing before the v10.D walk gets serious.

**Notes**
Surfaced during v10.D dry-run apply (2026-05-18). Three
`set-deploy` calls (cricketfansite / isitholiday / voltloop) had
to be re-run with `--domain <name>` for parity with the 9 written
by the migration sweep. Fix is ~15 min: in `set_deploy()`, when
`custom_domains` flag is empty AND no existing entry, default to
`[name]`. Tests need updating to expect the auto-populated value.

---

### 2026-05-19 — `fleet hosting` walkers miss ~9 fleet sites declared as `vercel` / `cf-*`

**Repro**
    lamill fleet hosting --refresh

**Expected**
A row for every fleet site whose `lamill.toml` declares a
v11-supported platform (`vercel` / `cf-pages` / `cf-workers` /
`hostgator`). Per the v10.D scoreboard that's 20 sites (22 minus
the 2 HG ones currently skipped on the 403 issue).

**Actual**
Only 11 rows came back (6 `cloudflare-workers` + 5 `vercel`).
Missing: `agesdk.dev`, `calcengine.site`, `homeloom.app`,
`iotbastion.com`, `iotnews.today`, `lamill.io`, `linkedcsi.live`,
`thoralox.com`, `whizgraphs.com` — ~9 sites the operator declared
as `vercel` (or `cf-pages`/`cf-workers` via wrangler config) in
v10.D but that don't appear in the table.

**Where (guess)**
Most likely culprits:

1. **Vercel walker matches via `targets.production.alias`** only.
   Sites where the custom domain is configured via DNS-only (CNAME
   to the project's `*.vercel.app` but not added as a project alias)
   won't match. Operator commonly adds DNS first and forgets the
   Vercel project's custom-domain pane. Walker should also pull
   from `/v9/projects/{id}/domains` as a fallback.
2. **Vercel pagination** — walker uses 20-per-page with
   `pagination.next` cursor. If operator has > 20 projects, the
   first page returns 20 + cursor; we paginate but the cursor
   semantics differ between Vercel API versions. Worth verifying
   against the operator's actual project count via
   `curl /v9/projects?limit=1` and reading `pagination.total`.
3. **Vercel-declared-but-actually-elsewhere** — `iotnews.today`
   declared `vercel` but CHECK_143 caught it serving WordPress
   from HG account 2 (the canonical drift case). Same diagnosis
   may apply to others on the missing list — declarations may be
   stale. Walker would correctly return 0 rows for those because
   the Vercel project literally doesn't exist.

**Severity**
major — v11's core value prop is "see your whole fleet at a glance"
and we're showing ~55% of it.

**Notes**
Diagnostic next steps:

```bash
ACCOUNT_ID=$(grep "^CF_ACCOUNT_ID=" portfolio.env | cut -d= -f2-)
TOKEN=$(grep "^VERCEL_TOKEN=" portfolio.env | cut -d= -f2-)
# How many Vercel projects in total?
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://api.vercel.com/v9/projects?limit=100" \
  | python3 -m json.tool | head -40
# For one specific missing site, do they have a Vercel project?
curl -s -H "Authorization: Bearer ${TOKEN}" \
  "https://api.vercel.com/v9/projects?search=iotnews"
```

Once we know which of the three causes is in play, the fix is
one of: (1) add `/v9/projects/{id}/domains` fallback fetch in
walk_vercel, (2) fix pagination cursor handling, (3) accept that
stale declarations need operator clean-up via `set-deploy`.

---

### 2026-05-19 — `fleet hosting` table has no summary footer

**Repro**
    lamill fleet hosting --refresh

**Expected**
Footer beneath the table showing per-provider row counts +
skipped-provider count, like:

    11 rows · 6 cloudflare-workers · 5 vercel · 0 cloudflare-pages · 0 hostgator (2 skipped)

Matches the convention `fleet seo` / `fleet check` already follow.

**Actual**
Table renders, then only the per-skipped-provider lines below it.
No row-count footer; no provider breakdown.

**Where (guess)**
`src/portfolio/cli.py:_fleet_hosting_impl` table-rendering block.
Add a footer that aggregates `rows` by `provider` (using
`collections.Counter`) and prints `len(rows)` + per-provider counts
+ `len(skipped)` skipped after the table, before the skipped-list
detail.

**Severity**
minor — output is correct, just less scannable than peer commands.
Pick up in v11.I (renderer upgrade) since that phase is already
about table-rendering polish.

---

### 2026-05-19 — `lamill fleet hosting --provider=X` with 0 matches says only "No hosting rows."

**Repro**
    lamill fleet hosting --provider=cloudflare-pages --refresh

**Expected**
When `--provider <X>` filters every row out but the walker did
return rows for OTHER providers, the message should make the
filter cause obvious. Something like:

    No `cloudflare-pages` rows. (Filtered from 11 total rows: 6
    cloudflare-workers, 5 vercel. Drop the --provider flag to see all.)

**Actual**

    No hosting rows.

…with the skipped-provider footer below. Looks like a zero-walk
result, but it's actually a zero-after-filter result.

**Where (guess)**
`src/portfolio/cli.py:_fleet_hosting_impl` — the "No hosting rows"
branch fires when the post-filter `rows` list is empty. Should
distinguish between (a) `result.rows` was empty pre-filter ("no
data"), (b) `result.rows` had entries but the `--provider` filter
dropped them all ("filtered out"). The latter case should show the
breakdown of what WAS available.

**Severity**
minor — operator can usually tell from the skipped footer + run
again without the filter. But the message is technically
misleading.

---

### 2026-05-19 — `HG-extra` column always rendered, even when no HG rows

**Repro**
    lamill fleet hosting --refresh
    # operator has 0 HG rows (both accounts 403-skipped) — but the
    # table still renders an empty HG-extra column for every row.

**Expected**
Hide the column when no row would populate it. OR: show it as a
right-side column only when at least one HG row is present.

**Actual**
Every row renders an empty `HG-extra` cell, padding the table
width and adding visual noise.

**Where (guess)**
`src/portfolio/cli.py:_fleet_hosting_impl` builds the table with
a fixed set of columns. Make the `HG-extra` column conditional —
only `table.add_column("HG-extra")` when `any(r.provider ==
"hostgator" for r in rows)`.

**Severity**
cosmetic — table readable either way. Fix folds naturally into
v11.I (renderer upgrade).

---

### 2026-05-18 — `domain suggest` menu has letter-keyed option `s` between numbered 7 and 8

**Repro**
    uv run lamill domain suggest <topic>
    # interactive menu renders after first grid

**Expected**
Every menu option is keyed by a number (plus `q` for quit). Reads
top-to-bottom as a single numeric sequence — no interleaved
letters.

**Actual**
Option `s` ("Show marked names as full grid") is registered in
`MENU_ITEMS` between numbered items 7 and 8, rendering as a
visually out-of-place letter row between 7 (Decide from
shortlist) and 8 (Show TLD reference). Was a deliberate v4.A
choice — source comment says *"Letter key keeps numeric muscle-
memory (1-9) intact while adding the new affordance next to its
shortlist siblings."* Operator's directive 2026-05-18 reverses
that call: *"s is wrong place, wrong name, it should have all
been just numbers."*

**Where**
`src/portfolio/cli.py:2084` — `MENU_ITEMS` list. Dispatch chain
at `cli.py:2994-3079` (4 branches affected by the renumber).
`_render_menu` at `cli.py:2300` (the `key in ("6", "s")` count-
suffix check). Tests at `tests/test_suggest_show_marked.py`
(lines 147 / 151 / 156 / 167 reference `"s"`) and
`tests/test_suggest.py` (lines ~1674 / 1681 / 1694 snapshot
MENU_ITEMS keys).

**Severity**
cosmetic — menu still works; reading order is off. Not blocking
any workflow.

**Fix plan** (~20 min)

Renumber `s` → `8`; bump existing `8` (TLD reference) → `9`; bump
existing `9` (Rerun fresh) → `10`. Final order keeps "Show
marked" adjacent to its shortlist siblings (6 Mark / 7 Decide /
8 Show marked), which was the original placement rationale —
just numbered:

```
 1. Pick a row to register
 2. Expand a row (full-ladder detail)
 3. Ask AI about a name
 4. Widen search — more candidates
 5. Add my own names to the grid
 6. Mark / unmark for shortlist
 7. Decide from shortlist
 8. Show marked names as full grid       (was 's')
 9. Show TLD reference                   (was '8')
10. Rerun fresh                          (was '9')
 q. Quit
```

**Notes**
Operator clarified the directive 2026-05-18 mid-session after the
v10 wrap + v11 restructure doc commit. Pick up between phases per
[[feedback-bug-intake-workflow]]. Small commit; expected
`portfolio: vN.X — domain suggest menu fully numbered (drop s key)`
or just a docs-style commit if it doesn't fit a named phase.

---

### 2026-05-18 — `fleet seo --refresh` and `fleet domains` show different domain counts

**Repro**
    uv run lamill fleet seo --refresh
    uv run lamill fleet domains

**Expected**
The two commands should show consistent fleet sizes, or — if the
scope differs — surface that in the output footer so the operator
can see *why* the counts diverge.

**Actual**
`fleet seo --refresh` shows 22 domains; `fleet domains` shows 36.
No visible explanation for the 14-domain gap.

**Where (guess)**
`src/portfolio/cli.py:5324` (`fleet_domains`) and `cli.py:5334`
(`fleet_seo`). Both default `--only wip` but `fleet_seo` calls
through `check_seo` which additionally filters to
`live-site`/`forwarder` classification (the SEO probe skips
parked / dead / archived sites by design). The filter is silent
— the operator sees only the final count.

**Severity**
minor — likely an intentional scope filter, but the silent
discrepancy is a usability gap.

**Notes**
Two fix paths worth considering when this is picked up:
(a) Show a footer note when SEO is filtering: "Showing N of M
WIP domains (excluded: K parked / J dead / I archived)."
(b) Add an explicit `--scope` flag to both commands so the
operator can match scopes when comparing counts.

Either path is small (≤30 min). Defer until after v10.A-D ships,
or fold in alongside v11.A's `fleet hosting` (which has the same
"WIP vs live-site" filter question per resolution 11.B).

## Fixed bugs

### 2026-05-18 — `test_serp_fetch.py` not isolated from real `data/serp/_quota.json`

**Repro**
    # With data/serp/_quota.json at queries_used == limit (250/250):
    uv run pytest tests/test_serp_fetch.py -q

**Expected**
All `test_serp_fetch.py` tests pass regardless of the real
quota counter state. Tests should monkeypatch the quota path to
`tmp_path` (mirroring `test_settings_serpapi_cli.py`'s
`_patch_quota_path` fixture pattern).

**Actual**
18 of 21 tests fail with
`portfolio.serpapi_quota.QuotaExhausted: SerpAPI free-tier quota
exhausted for this UTC month.` The failure is at
`src/portfolio/serp_fetch.py:56` calling the production
`is_quota_available()` — confirming the tests hit the real
`data/serp/_quota.json` rather than a mocked one. Triggered
today when the operator's actual SerpAPI quota hit 250/250 mid-
session; previously masked because the counter was at 127/250
and the gate was open.

**Where (guess)**
`tests/test_serp_fetch.py` is missing a `monkeypatch.setattr(
serpapi_quota, "QUOTA_PATH", tmp_path / "_quota.json")` fixture
like the one in `tests/test_settings_serpapi_cli.py:18-20`.
Probably one fixture at the top + per-test inclusion fixes all 18.

**Severity**
major — breaks the test suite when production quota is full.

**Fixed in** — `62376f8` (test — isolate test_serp_fetch from
real quota ledger). Added an `autouse=True` fixture mirroring
the `_patch_quota_path` pattern; full suite back to green.
