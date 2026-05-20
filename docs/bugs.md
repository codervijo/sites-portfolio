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

### 2026-05-20 — `project check` groups `warn` results inconsistently across the rendered sections

**Repro**

    uv run lamill project check airsucks.com

Run against a site whose CHECK_145 (deploy-fresh, severity=warn) and
CHECK_146 (last-build-success, severity=warn) both return `warn`.

**Expected**

Both `warn` results land in the same section (either both under "Conformance
failures" or both under "Skipped"), with consistent glyph treatment.
Distinct sections for `pass` / `warn` / `fail` would also be acceptable.

**Actual**

The same severity (`warn`) renders into two different buckets depending
on the message wording:

```
Conformance failures (7):
  ...
  ✗ CHECK_145 deploy-fresh — can't read live version.json
    (https://airsucks.com/version.json → 404) — CHECK_144 surfaces the
    underlying cause.
...
Skipped (26): ..., CHECK_146
```

CHECK_145 returned `warn` and landed in *Conformance failures* with a
red ✗. CHECK_146 also returned `warn` but landed in *Skipped*. The
only obvious difference: CHECK_146's message contained the literal
substring `"skipped"`, CHECK_145's didn't.

**Where (guess)**

`src/portfolio/cli.py` — the `project check` renderer (search for
"Conformance failures" string in cli.py). Likely keys "skipped"
bucket off the message text rather than off the `CheckResult.status`
field. Should be a simple status-based split:

  - `pass` → "Passed"
  - `warn` → "Warnings" (new section, OR merge with Skipped)
  - `fail` → "Conformance failures"
  - explicit skipped (status=`skip`?) → "Skipped"

Need to confirm whether `CheckResult` even has a separate `skip`
status or whether `warn`-with-"skipped"-in-message is the existing
convention for skips.

**Severity** — `cosmetic`

**Notes**

Surfaced 2026-05-20 during the v15.D/E hand-test on airsucks.com.
Not a v15 regression — pre-existing renderer quirk that v15.D/E made
visible by adding two new warn-severity checks. Renderer fix lifts
all current warns + future warns consistently.

---

### 2026-05-20 — `project check` deploy summary line shows wrong platform for cf-workers sites

**Repro**

    uv run lamill project check airsucks.com

`airsucks.com/lamill.toml` declares `platform = "cf-workers"`. The
walker / `fleet hosting` agrees:

    $ uv run lamill fleet hosting --provider cloudflare-workers
    ... airsucks.com   cloudflare-workers   DEPLOYED ...

**Expected**

The header line should display the actual declared platform from
`lamill.toml`:

```
Deployment:  cloudflare-workers  via: wrangler.jsonc
```

**Actual**

```
Deployment:  cloudflare-pages  via: wrangler.jsonc
  Live: live-site (HTTP 200, 291ms)  → https://airsucks.com  2026-05-20.json
```

`cloudflare-pages` is wrong — airsucks.com is a CFW project (confirmed
both by `lamill.toml` and the hosting walker). The `via: wrangler.jsonc`
hint is right (CFW does use wrangler), so the inference path is partially
correct, but it mislabels the platform.

**Where (guess)**

The `project check` deploy-summary renderer doesn't appear to read
`lamill.toml [deploy].platform` directly — looks like it heuristically
classifies based on the presence of `wrangler.jsonc` (→ historically
cf-pages, before CFW became its own category). Search `src/portfolio/`
for the "Deployment:" rendering line. Should switch to reading
`lamill_toml.load(repo_dir).deploy.platform` as the authoritative
source, falling back to inference only when the file is absent.

Possible adjacent: CHECK_143 (deploy-drift) on the same run output
shows `declared=cf-workers · actual unknown` — that check reads
lamill.toml correctly, so it's specifically the *Deploy summary*
renderer that's broken.

**Severity** — `minor`

**Notes**

Surfaced 2026-05-20 during the v15.D/E hand-test on airsucks.com.
Not v15-related — pre-existing renderer mismatch. Fix is likely a
one-line change to source the platform field from `lamill.toml`.

Pairs with the inconsistent `warn` rendering bug logged above (same
operator run surfaced both).

---

### 2026-05-20 — v13.B `project seo` GSC diagnostics — 3 rendering/classification issues

**Repro**
    lamill project seo hybridautopart.com --top 30

Run against a live, GSC-verified site. One operator run surfaced
all three sub-issues at once.

**Expected**
- Coverage section accurately reflects GSC URL Inspection verdicts
  (URLs reported as "submitted and indexed" should count as
  indexed and render with a pass marker).
- `--top N` is honored beyond 10 — `--top 30` should inspect up to
  30 URLs.
- Relative-date formatter renders sub-day deltas as "today" or
  "~0d ago", never "0y ago".

**Actual**
Three rendering/classification defects in one run, captured below:

1. **Coverage state misclassified.** Every URL in the output was
   labeled "submitted and indexed" by the GSC URL Inspection API,
   but the renderer marked them all with ✗ (red cross) and counted
   them as **0/10 indexed (0%)**. The classifier likely expects the
   GSC verdict token `submitted_indexed` (underscored) but the API
   is returning `submitted and indexed` (human text), so nothing
   matches the pass case and everything falls through to the fail
   rendering. The header `📊 Coverage (top 10 inspected — 0/10
   indexed, 0%)` is therefore wrong on a healthy site.

2. **`--top N` not honored beyond 10.** Operator passed `--top 30`
   but only 10 URLs were shown. Either the API call caps at 10, or
   the top-N truncation happens before the user's value is applied,
   or both. Either way the flag is silently capped.

3. **Relative-date formatter unit bug.** One row reads `crawled 0y
   ago` — "0 years ago" — for a URL crawled today (or very
   recently). The relative-time formatter is picking the wrong unit
   at the low end. Should read "today" or "~0d ago".

Full operator terminal output:

```
$ lamill project seo hybridautopart.com --top 30
Probing 1 domain(s) — HTTP + GSC (28d) + CrUX...
  [1/1] hybridautopart.com
check --seo · 1 domains · GSC 28d · sort=impressions
 SEO  Domain              HTTP    Robots  Sitemap  GSC  GSC sm     Imp  Clicks   CTR   Pos
 🟡   hybridautopart.com  🟢 200    🟢      🟢     🟢     🟡    26,378     117  0.4%  13.3

  GSC diagnostics
    Property: https://hybridautopart.com/
    📋 Sitemaps (1 submitted)
      ⚠ WARN     /sitemap_index.xml               3 warning(s)  ·  fetched 17h ago
    📊 Coverage (top 10 inspected — 0/10 indexed, 0%)
      ✗ https://hybridautopart.com/            submitted and indexed     crawled 4d ago
      ✗ https://hybridauto…-en/subaru-hybrids/ submitted and indexed     crawled 5d ago
      ✗ https://hybridauto…blog-en/phev-guide/ crawled - currently not indexed  verdict=NEUTRAL · crawled 0y ago
      ✗ https://hybridauto…rgy-drive-problems/ submitted and indexed     crawled 4d ago
      ✗ https://hybridauto…-en/prius-charging/ submitted and indexed     crawled 3w ago
      ✗ https://hybridauto…ing-courses-online/ submitted and indexed     crawled 3w ago
      ✗ https://hybridauto…og-en/mhev-vs-phev/ submitted and indexed     crawled 9d ago
      ✗ https://hybridauto…power-split-device/ submitted and indexed     crawled 9d ago
      ✗ https://hybridauto…ible-link-assembly/ submitted and indexed     crawled 8w ago
      ✗ https://hybridauto…tion-engine-heater/ submitted and indexed     crawled 3d ago
```

**Where (guess)**
`src/portfolio/project_seo_diagnostics.py` — the coverage
classifier + renderer + relative-date formatter all live here (or
in a helper module called from here). Suggested fix directions:

- *Issue 1:* Normalize the GSC verdict string before matching
  against the pass case (`submitted_indexed` / `submitted and
  indexed` → same key). Case-fold + collapse spaces/underscores
  before comparison.
- *Issue 2:* Check the URL Inspection API call's `top_n` path;
  ensure `top_n=30` is plumbed all the way through (from CLI flag
  → diagnostics entry point → API call → result truncation).
  Default cap may be hardcoded to 10 somewhere along the chain.
- *Issue 3:* In the relative-date formatter, add a "today" / "0d"
  branch before the years/weeks/days cascade falls through to
  years for sub-1d deltas. Likely an integer-divide ordering issue
  where `delta_days // 365 == 0` is being formatted as "0y" instead
  of falling through to the days/hours/today branch.

**Severity**
minor — cosmetic + small accuracy issue. The Coverage% misread is
the most visible (operator can't trust the "0/10 indexed" header
on a healthy site), but no data loss; underlying GSC data is
correct, just rendered wrong.

**Notes**
All three issues surfaced in v13.B (per-project GSC diagnostics as
`project seo` default — shipped in commit `a693d96`). Likely
shippable as one small follow-up phase (v13.C?) since they share
a file and a renderer. Self-contained — full repro output captured
above so the bug record stands alone.

---

### 2026-05-20 — tech-debt audit pass

**Repro**
    (no single command — broad codebase concern)

**Expected**
The codebase has accumulated tech-debt across 22 shipped tiers
(v1-v12) over ~6 weeks of rapid feature work. Operator wants a
deliberate pass to identify what's worth cleaning up vs leaving
in place.

**Actual**
No tech-debt review has been done. Candidate areas to audit (not
yet prioritized):
- `cli.py` size — currently 6700+ lines; lots of inline helpers
  that could move out (e.g., `_run_*_pass` helpers could live in
  the relevant `interpretive_pass.py` / `audit_pass.py` modules).
- Duplicate OpenAI HTTP code — `serp.call_openai` + `audit_pass._call_openai_chat`
  diverged in v12.C; consolidate when cost-ledger work needs the
  same shape elsewhere (already flagged in v12.C commit body).
- Inconsistent cache modules — `seo_cache.py` / `hosting_cache.py` /
  `serp_query_cache.py` / `serpapi_quota.py` all do roughly the
  same thing (JSON file in `data/`, daily rollover). A shared
  base would reduce drift risk.
- `CHECK_NNN` skip-conditions — many checks early-return `warn`
  with "not a web project — skipped" or "no index.html — skipped".
  Pattern repeats ~24 times; could centralize via a decorator or
  helper function.
- Test fixtures repetition — several test files re-implement
  `_minimal_cluster()` / `_minimal_payload()` near-identically.
  Shared fixture in a `conftest.py` would deduplicate.
- Cross-cutting renderer helpers in `cli.py` — `_fmt_int`,
  `_fmt_pct`, `_fmt_pos`, `_color_value`, `_verdict_marker`, etc.
  scattered; could move to a `render_helpers.py` module.
- Stale `data/gsc/2026-04-29.json` snapshot — only one GSC
  snapshot, 3+ weeks old; either refresh or document why it's
  intentionally stale.

**Where (guess)**
Project-wide. Suggest starting from the top-noise items
(`cli.py` size + check skip-conditions repetition).

**Severity**
`minor` — none of these block functionality; payoff is
maintainability + future-velocity, not user-visible.

**Notes**
- Don't conflate this with the per-bug list above — those are
  user-visible defects; this is internal hygiene.
- Operator memory `[[feedback-no-self-conformance]]` forbids
  adding `CHECK_NNN` for portfolio itself. Use pytest / git hooks
  for any tech-debt enforcement here.
- Could be a low-priority tier (v23+?) or just an inline cleanup
  pass between feature tiers when motivation strikes. Operator to
  decide scoping.

### 2026-05-18 — `settings deploy set` fails for sites/ dirs missing from portfolio.json

**Repro**
    # Site has sites/<domain>/ directory but no entry in portfolio.json:
    uv run lamill settings deploy set hostkit.app vercel --domain hostkit.app --non-interactive

**Expected**
Writes `sites/hostkit.app/lamill.toml`. The site dir exists; the
operator's intent is clear. Drift between sites/ and portfolio.json
is its own concern (`fleet sync` / `fleet drift`), not a
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
anyway, or (c) suggest `fleet sync` and exit.

**Severity**
minor — workaround is `fleet sync` to reconcile
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

### 2026-05-18 — `settings deploy set` doesn't auto-populate `custom_domains` from dir name

**Repro**
    uv run lamill settings deploy set <domain> cf-pages --non-interactive
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
`settings deploy set <name>` produce different
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

### 2026-05-19 — `fleet hosting` walkers miss ~9 fleet sites declared as `vercel` / `cf-*` *(diagnosed: data-quality, not walker bug — partial wontfix)*

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
`thoralox.com`, `whizgraphs.com`.

**Diagnosis (2026-05-19, via direct Vercel API query)**

Dumped `GET /v9/projects?limit=100` against operator's Vercel
account (22 projects total). The 9 missing fleet sites split
into three categories:

| Category | Sites | Cause | Operator fix |
|---|---|---|---|
| **A. No Vercel project exists** | agesdk.dev · iotbastion.com · iotnews.today · lamill.io · thoralox.com · whizgraphs.com | Site declared `vercel` in `lamill.toml` but no project is registered in operator's Vercel account. iotnews.today is the canonical CHECK_143 drift case (declared vercel, actually serving WP on HG). The others are likely stale decls or sites never deployed to Vercel. | Either deploy the site to Vercel (then it'll surface), or fix the declaration via `lamill settings deploy set <name> <correct-platform>`. |
| **B. Vercel project exists but custom domain not attached** | calcengine.site (project `calcengine-site` exists, `alias` = only `*.vercel.app` URLs) · linkedcsi.live (project `linkedcsi` exists, `alias` = only `linkedcsi.vercel.app`) | Project deployed to Vercel; custom domain CNAME'd via DNS but never bound at the Vercel project level via the dashboard's Domains pane. Vercel only populates `targets.production.alias` for project-bound domains. | Attach the custom domain in the Vercel dashboard (Project → Settings → Domains → Add) for each. |
| **C. Project name mismatch** | homeloom.app (declared, but only `homeloop-app` exists in Vercel — typo? renamed?) | The Vercel project was either renamed, deleted, or has a different name than the operator's declaration assumes. | Confirm whether `homeloop-app` is the same project and rename in Vercel, OR fix the local declaration. |

**Where**
Not a walker bug — `walk_vercel` correctly reads
`targets.production.alias`. The data reflects reality:
operator has 6 sites with no Vercel project; 2 with project but
no domain binding; 1 likely typo. The walker faithfully reports
what Vercel says.

**Severity**
~~major~~ → **minor (mostly wontfix)** — walker is doing the
right thing. The hand-test "missing rows" is operator-side data
cleanup, not a tool defect. Two small walker enhancements would
help marginally:

1. *(optional)* Add `/v9/projects/{id}/domains` fallback fetch
   for projects whose `targets.production.alias` is empty —
   would catch category B (custom domain attached but not yet
   verified, so not in `alias`). Low priority — operator can
   fix in the dashboard.
2. *(optional)* When the walker can't find a Vercel project for a
   declared `vercel` site, emit a row with `error="no Vercel
   project for declared domain"` so it's visible. Useful for
   surfacing category A in the table without re-running
   diagnostics.

**Notes**
Folds these as future enhancements rather than blockers. Operator
clean-up of stale declarations is the higher-value action.

If the optional enhancements are wanted, both could land as a
small v11.B follow-up commit (the walker already has the right
shape; just needs the fallback fetch + the missing-project
synthesized row).

---

### 2026-05-19 — HG walker `install_path` empty for every row despite addon-domain doc-roots existing

**Repro**
    lamill fleet hosting --refresh
    # Operator has 10 HG rows; all show disk usage in HG-extra column
    # but no install_path appended.

**Expected**
For addon domains, the walker's `_hg_list_domains` should extract
the `documentroot` field from each entry and pass it as
`install_path` to the HostingRow. v11.D/E/I rendering changes
already added `install_path` to the HG-extra display.

**Actual**
HG rows render `disk 4959MB` but no install_path. Walker's
extraction returns `None` for every addon entry.

**Where (guess)**
`src/portfolio/hosting.py:_hg_list_domains` reads
`entry.get("documentroot")`. Same lesson as the `megabytes_used`
fix from 2026-05-19 — the cPanel field name is likely
`document_root` (with underscore) or `path`. Real cPanel response
shape needs to be checked via curl on
`/execute/DomainInfo/list_domains`. Once the right field name is
confirmed, walker reads both (preferred name first, legacy fallback).

**Severity**
minor — table renders correctly otherwise; install_path is a nice
addition to operator visibility. Fix is one-line once the field
name is confirmed.

**Notes**
Diagnostic curl:

```bash
ACCOUNT="gator3164"
USER=$(grep "^HOSTGATOR_USER_GATOR3164=" portfolio.env | cut -d= -f2-)
TOKEN=$(grep "^HOSTGATOR_TOKEN_GATOR3164=" portfolio.env | cut -d= -f2-)
curl -s -H "Authorization: cpanel ${USER}:${TOKEN}" \
  "https://${ACCOUNT}.hostgator.com:2083/execute/DomainInfo/list_domains" \
  | python3 -m json.tool | head -40
```

---

### 2026-05-19 — HG-extra `disk N MB` is account-level total, looks per-domain

**Repro**
    lamill fleet hosting --refresh
    # Every row from gator4216 shows `disk 4959MB`.
    # Every row from gator3164 shows `disk 500MB`.

**Expected**
Either rename the field to make it clear it's the ACCOUNT total
(e.g., `acct disk 4959MB`), or move the disk info to a footer
note ("HG account gator4216: 4959/N MB used") so it's not
duplicated per row, or actually fetch per-domain disk usage if
cPanel exposes that.

**Actual**
Every HG row shows the same disk number for sites on the same
account. Operator reading the table sees "every site uses 4959MB"
which is misleading — it's the SHARED account quota.

**Where (guess)**
`Quota/get_quota_info` is account-scoped (no per-domain breakdown
in standard cPanel). Per-domain disk usage would need
`Fileman/list_files --include-size` or similar — heavier query,
arguably out of scope for v11.

**Severity**
cosmetic — data is correct, presentation is misleading. Two paths
to resolve:
1. Rename column or per-row text: `disk(acct) 4959MB` or move
   into the renderer as `acct=gator4216 disk=4959MB`.
2. Move disk usage to a footer block: "HG accounts: gator3164
   500MB used, gator4216 4959MB used."

Option 2 is cleaner — drops per-row duplication. Folds into
v11.I-followup or a separate polish commit.

---

### 2026-05-19 — HG walker reports no `wp_version` for any row (WP detection blind)

**Repro**
    lamill fleet hosting --refresh
    # 10 HG rows; none show `WP <version>` in HG-extra column.

**Expected**
For WordPress installs on the HG fleet (operator's known
WP-on-HG sites are `hybridautopart.com` + `streamsgalaxy.com`),
v11.D should report `WP <version>` in HG-extra.

**Actual**
No WP version surfaces. `wp_version` is `None` on every HG row.

**Where (guess)**
`src/portfolio/hosting.py:_hg_list_wp_installs` calls
`WordPressManager/list_installations`. Walker is 404-tolerant — if
the module isn't available (older cPanel, no Softaculous/WP Manager
addon), the function returns `{}` silently. Three possible causes:

1. WordPressManager UAPI module isn't installed on operator's
   cPanel builds — walker correctly reports nothing.
2. Module is available but returns a different response shape
   than the walker expects (look for `installations` array vs
   top-level array, vs `installation_path` vs `path` field).
3. The doc_root match between `WordPressManager` response and
   `DomainInfo` response is failing (different path formats).

**Severity**
minor — table renders correctly; WP version is a nice-to-have
operator signal. Could fix with a different detection path —
e.g., scan `<doc_root>/wp-includes/version.php` via
`Fileman/list_files` or `Fileman/get_file_information`.

**Notes**
Diagnostic curl:

```bash
ACCOUNT="gator3164"
USER=$(grep "^HOSTGATOR_USER_GATOR3164=" portfolio.env | cut -d= -f2-)
TOKEN=$(grep "^HOSTGATOR_TOKEN_GATOR3164=" portfolio.env | cut -d= -f2-)
curl -s -H "Authorization: cpanel ${USER}:${TOKEN}" \
  "https://${ACCOUNT}.hostgator.com:2083/execute/WordPressManager/list_installations" \
  | python3 -m json.tool | head -40
```

If returns 404 → option 3 (alt detection path). If returns JSON
with installations → option 2 (field-name mismatch, fix walker).

---

### 2026-05-19 — `fleet dashboard` truncates every cell on standard terminal width

**Repro**
    lamill fleet dashboard
    # Standard 80-col-ish terminal; output shows `hyb…`, `iot…`, `air…`
    # for every domain.

**Expected**
Domain column wide enough to render the actual domain in the
common-fleet-size case. Other columns either widen or accept
narrower rendering — but domain (the row identifier) should never
be truncated to "_xyz…_" unreadable form.

**Actual**
With 15 columns (12 original + Host + Prov added in v11.K + Site +
Domain age), rich.Table squeezes every column to fit terminal
width. Result: `hyb…` instead of `hybridautopart.com`.

**Where (guess)**
`src/portfolio/dashboard.py:render_dashboard` adds 13-15 columns
with default sizing. Rich uses proportional shrinking. Options:

1. Mark `Domain` as `no_wrap=True` + `min_width=25` so it gets
   priority space.
2. Drop the Live + Conf columns (less actionable than the dots)
   when terminal width is < 120 columns.
3. Default sort changes — surface most-actionable-first (already
   sort=attention default) AND limit display to top-N by default
   with --all to render everything.

**Severity**
minor — predates v11.K (was already truncating columns; v11.K just
made it slightly worse by adding 2 more). Information is in the
rendered cells, just unreadably narrow at standard width.

**Notes**
Pick up in a future v11 polish phase. Probably fold into v11.L
docs sync if there's slack, or its own commit.

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

### 2026-05-19 — `fleet hosting` table has no summary footer

**Repro**
    lamill fleet hosting --refresh

**Expected**
Footer beneath the table showing per-provider row counts +
skipped-provider count.

**Actual**
Table rendered, then only the per-skipped-provider lines below
it. No row-count footer; no provider breakdown.

**Fixed in** — v11.I commit (see git log). Renderer now prints a
one-line summary via `hosting.hosting_footer_summary()` right
under the table:

    N rows · M cloudflare-workers · L vercel · K cloudflare-pages
    · J hostgator (X skipped, Y conflicts)

Zero counts surface — they're load-bearing for diagnostics
(silent walkers no longer hide). Skipped + conflict tallies only
appear when non-zero.

---

### 2026-05-19 — `lamill fleet hosting --provider=X` with 0 matches says only "No hosting rows."

**Repro**
    lamill fleet hosting --provider=cloudflare-pages --refresh

**Expected**
When `--provider` filters every row out, the message should
distinguish "walker returned nothing" from "filtered out".

**Actual**
Always said "No hosting rows." regardless of which case applied.

**Fixed in** — v11.I commit. Renderer now distinguishes the two
cases. When `--provider` filters away non-empty pre-filter rows:

    No `cloudflare-pages` rows. (Filtered from 11 total. Drop the
    --provider flag to see all.)
      Available: 11 rows · 6 cloudflare-workers · 5 vercel ·
      0 cloudflare-pages · 0 hostgator

When walker genuinely returned 0 rows, message stays
"No hosting rows." (no filter to blame).

---

### 2026-05-19 — `HG-extra` column always rendered, even when no HG rows

**Repro**
    lamill fleet hosting --refresh  (with 0 HG rows)

**Expected**
Hide the column when no row would populate it.

**Actual**
Empty `HG-extra` cell rendered for every Vercel / CF row.

**Fixed in** — v11.I commit. Renderer adds the HG-extra column
only when `any(r.provider == "hostgator" for r in rows)`. Plus
a status-emoji column at the left (✓ recent / ⚠ stale / 💤
dormant / ✗ runaway / 🤐 conflict / — unowned per resolution
11.C). 8 new CLI tests cover the column conditional + emoji
priority cascade.

---

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
