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

### 2026-05-22 — `lamill new trends <topic>` on HTTP 429 surfaces a cryptic error with no recovery hint

**Repro**

    portfolio on  main [$?] is 📦 v0.1.0 via 🐍 v3.10.12
    ❯ uv run portfolio new trends 'nanobanana'
    Trends fetch failed: pytrends fetch failed for 'nanobanana': The request failed: Google returned a response with code 429

    portfolio on  main [$!?] is 📦 v0.1.0 via 🐍 v3.10.12
    ❯ uv run portfolio new trends 'nan obanana'
    Trends fetch failed: pytrends fetch failed for 'nan obanana': The request failed: Google returned a response with code 429

**Expected**

The error should:
  1. **Clarify what 429 means**: Google Trends has no official quota
     or API; pytrends scrapes the unofficial endpoint, and Google
     IP-rate-limits it aggressively. 429 is transient, not a
     permanent failure.
  2. **Suggest a wait time**: typical recovery is 10-30 minutes
     (pytrends' GitHub issues report similar windows). No official
     Retry-After header is sent.
  3. **Surface what won't help**: re-running with `--refresh` or a
     different topic will likely also 429 from the same IP since
     the rate limit is IP-based, not topic-based.
  4. **Surface what will help**: wait, or switch IP (VPN), or use a
     cached result if available (24h TTL via `data/gtrends/<hash>.json`).

**Actual**

`Trends fetch failed: pytrends fetch failed for 'X': The request
failed: Google returned a response with code 429` — operator can't
tell from this whether the failure is permanent (wrong topic,
broken auth, dead library) or transient (rate-limit, retry later).

**Where (guess)**

`src/portfolio/gtrends.py:163-167` — `_fetch_from_pytrends`'s broad
`except Exception as e: raise GTrendsError(f"pytrends fetch failed
for {topic!r}: {e}")`. The wrapper loses signal about WHICH failure
mode tripped. Pattern fix:

  - Inspect `str(e)` for `"429"` or `"Too Many Requests"` substring;
    raise a new `GTrendsRateLimitError(GTrendsError)` subclass with
    the actionable message.
  - `cli.py`'s `except GTrendsError` handler at the new_trends
    command renders the rate-limit case as yellow (transient,
    retry-able) instead of red (permanent failure).
  - Bonus: when rate-limited, check if a cached payload exists
    (even stale) and offer it: "rate-limited, but a 26h-old cache
    is available — re-run with `--refresh=false` (default) to use
    it, or wait ~15 minutes and retry."

**Severity** — `minor`

Doesn't lose data; doesn't break workflow; just confuses on first
hit. Operator workaround: wait 10-30 min and re-run.

**Notes**

Surfaced 2026-05-22 by operator immediately post-v19.B ship.
Related to the prior 2026-05-22 bug ("ModuleNotFoundError when
running outside uv venv") — both are `gtrends.py` error-surface
gaps. Worth fixing together as a between-phase polish pass.

Also related: pytrends 4.9 has known reliability issues with
modern Google Trends (issue #563 in their GitHub). If 429s become
chronic, the long-term fix is moving to SerpAPI's `google_trends`
engine (originally in v19's scope, dropped 2026-05-22 per
operator's "serp etc not needed at this time" call). That call
was right for THE FIRST few queries; it might need re-litigating
if pytrends rate-limiting makes the command unreliable in practice.

---

### 2026-05-22 — `lamill new trends <topic>` raises `ModuleNotFoundError: No module named 'pytrends'` when running outside the `uv` venv

**Repro**

    portfolio on  main [$?] is 📦 v0.1.0 via 🐍 v3.10.12
    ❯ lamill new trends 'ai'
    ...
    File "src/portfolio/gtrends.py:158, in _fetch_from_pytrends:
      from pytrends.request import TrendReq
    ModuleNotFoundError: No module named 'pytrends'

Operator's shell prompt shows Python 3.10.12, but the project's
`pyproject.toml` declares `requires-python = ">=3.11"`. The
`lamill` binary on PATH was installed into a Python 3.10
environment (probably an older `pipx install` or `pip install -e .`
predating v19.B), so the new `pytrends>=4.9` dep added to
`pyproject.toml` in commit `38fb240` (v19.B) isn't visible to that
install.

**Expected**

Either (a) the `lamill` binary picks up new deps automatically
after a `git pull`, or (b) the CLI surfaces a clean actionable
error ("re-install lamill with `uv sync` / `pipx reinstall
portfolio` to pick up the new `pytrends` dep") instead of a raw
`ModuleNotFoundError` stack trace.

**Actual**

Raw stack trace from `_fetch_from_pytrends`'s `from pytrends.request
import TrendReq` line. Operator can't tell from the trace what
remediation to take.

**Where (guess)**

`src/portfolio/gtrends.py:158`. Pattern fix: wrap the `from
pytrends.request import TrendReq` in a try/except ImportError that
raises `GTrendsError` with an actionable message ("pytrends not
installed — run `uv sync` or reinstall lamill to pick up the new
dep added in v19.B"). The CLI command's existing
`except GTrendsError` handler at `cli.py:5842` already prints the
message cleanly + exits 3, so the actionable hint reaches the
operator without a stack trace.

Lower-priority alternative: relax `pyproject.toml`'s
`requires-python` to `>=3.10` so the operator's existing Python
3.10 install can `uv sync` cleanly. But the dep itself was just
added; reinstall is needed regardless.

**Severity** — `minor`

Doesn't lose data; just surfaces as an opaque stack trace. Fix is
small (one try/except in gtrends.py). Operator's workaround for
now: run `uv sync` in `~/work/projects/sites/portfolio/` and use
`uv run lamill new trends 'ai'`.

**Notes**

Surfaced 2026-05-22 by operator immediately post-v19.B ship.
v18.D's `_maybe_create_ga4_property` follows the right pattern —
imports happen at module top after pyproject deps are guaranteed
present. v19.B used a lazy import inside the function for "test
environments that don't need pytrends" startup-cost reasons (per
the comment at `gtrends.py:155-157`), which is the precondition
that allowed the bare ModuleNotFoundError to leak. The lazy-import
posture is still right; just needs the try/except wrap.

---

### 2026-05-20 — `make deps` hits pnpm store version mismatch on new-domain builds

**Repro**

After bootstrapping a new domain + running `make deps` inside
the sites Docker container:

    $ make buildsh
    # inside container:
    $ cd <newdomain>
    $ make deps
    ...
    [ERR_PNPM_UNEXPECTED_STORE] Unexpected store location
    The dependencies at "/usr/src/app/node_modules" are currently
    linked from the store at "/usr/src/app/.pnpm-store/v10".
    pnpm now wants to use the store at "/usr/src/app/.pnpm-store/v11"
    to link dependencies.
    If you want to use the new store location, reinstall your
    dependencies with "pnpm install".
    make: *** [Makefile:38: deps] Error 1

**Expected**

`make deps` for a fresh bootstrap should succeed without operator
intervention — either:
  - The bootstrap process pre-detects store version drift and
    wipes/rebuilds, OR
  - The store-dir is pinned per-project via `.npmrc` so each
    domain owns its store and doesn't inherit cross-domain state

**Actual**

Operator hits the error on every new-domain build because the
sites container's pnpm got bumped (v10 → v11) while pre-existing
`/usr/src/app/.pnpm-store/v10` is still on disk. pnpm refuses
to link against a store from a previous major version.

**Workaround**

```bash
make buildsh
# inside container:
rm -rf /usr/src/app/.pnpm-store
rm -rf /usr/src/app/<newdomain>/node_modules
pnpm install
```

Once cleared, subsequent builds work until the next pnpm major
version bump.

**Where (guess)**

Likely the bootstrap template needs an `.npmrc` with:

    store-dir=./.pnpm-store

(per-project store, isolated from the shared workspace store).

OR the parent `~/work/projects/sites/Makefile` (which `make deps`
forwards to) should detect store-version drift and auto-clean
before installing.

OR bootstrap's git-init step could emit a `.gitignore` entry for
`.pnpm-store/` so stale stores aren't committed.

Cleanest fix: per-project store-dir in `.npmrc` template, so each
sites/<domain>/ has its own `.pnpm-store/v<N>` directory under
the project root. Cross-domain isolation; no global state to
drift.

**Severity** — `major`

Blocks every new-domain bootstrap until operator manually clears
the store. Will hit on every pnpm major-version bump.

**Notes**

Surfaced 2026-05-20 by operator during second-domain bootstrap
session. Tied to the pnpm 10 → 11 transition. v15.S candidate.

The error is rooted in pnpm's design (rejects cross-major-version
stores) so it's not a CF/lamill bug per se — but lamill's bootstrap
emits the template that creates the trap. Fix lives in the
bootstrap template.

---

### 2026-05-20 — `new bootstrap` should generate a copy-paste LLM prompt first

**Repro**

    lamill new bootstrap agesdk.dev

Operator runs bootstrap → faced with 5+ paragraph-style prompts
(Summary / Audience / ICP / Goals / Content strategy / Growth
hypothesis) cold. Has to compose each answer in-prompt without
any AI assistance, OR open ChatGPT/Claude in a separate window
and manually feed each prompt one at a time.

**Expected**

BEFORE firing the first interactive prompt, bootstrap renders a
ready-to-paste prompt template the operator can drop into
chatgpt.com / claude.ai. The template asks for all the section
contents at once + the growth hypothesis, organized clearly so
the LLM's response can be split section-by-section into the
bootstrap prompts.

Something like:

```
─── Copy-paste prompt for ChatGPT / claude.ai ─────────────────

I'm scaffolding a new site at agesdk.dev. Topic: <prompt me or use
--topic flag if supplied>.

Please draft the following for me. Keep each section under
the indicated length. Put each section under its labeled H2
heading so I can copy-paste them one at a time:

## Summary
One paragraph (3-5 sentences). What this site IS and what it
DOES. Concrete, not aspirational.

## Audience
One sentence. The broad demographic (e.g. "homeowners with EV
chargers" / "RN/Expo developers shipping consumer apps").

## ICP
One paragraph. The SPECIFIC targetable subset — demographics,
pain points, what they use today. More precise than Audience.
Concrete enough you could write an ad-targeting brief from it.

## Goals
1-2 sentences. The primary business / product goal. Time-bound
if there's a relevant deadline.

## Content strategy
One paragraph. Page types this site needs · initial topics ·
format mix (long-form vs reference vs tool).

## Growth hypothesis
One paragraph. Your bet for how this site reaches its audience.
Distribution channel + why it's defensible + the timing window.

──────────────────────────────────────────────────────────────

When you have the response, the next prompts will ask for each
section one at a time. Paste each one in.
```

The operator can either:
  (a) Type answers freehand (current behavior — preserved); OR
  (b) Open the LLM, paste this template, copy the structured
      response, then paste section-by-section into each prompt.

**Actual**

Bootstrap fires the prompts cold. Operator either composes each
one freehand (slow) or shuttles between windows manually.

**Where (guess)**

Print the template right after the pre-flight question list
banner (the other 2026-05-20 bug). New helper
`_render_llm_prompt_template(domain, topic)` in bootstrap-orchestrator
code. Skip when `--non-interactive` set.

**Severity** — `major`

The cold-prompt experience is a real friction point — operator's
test session showed two sections answered with content from the
NEXT section over (Summary got the Goals content, Audience got the
ICP content), because composing in-prompt without context is hard.
An LLM-staged response makes section-to-prompt mapping mechanical.

**Notes**

Surfaced 2026-05-20 by operator. Pairs naturally with the multi-
paragraph paste fix (also 2026-05-20) — together they make the
LLM-stage → paste-each-section workflow clean.

---

### 2026-05-20 — `new bootstrap` should ask whether the frontend is already designed

**Repro**

    lamill new bootstrap agesdk.dev

The Lovable-repo-URL prompt (separate 2026-05-20 bug) jumps
directly to "paste the URL or skip". But the operator's mental
model has a logically-prior question: "have you designed the
frontend yet?" Two operator states:

  (a) **Frontend already designed in Lovable** → operator has a
      GitHub repo with the export. Bootstrap should ask for the
      URL, clone into `genai/`, run `--from-genai` path.
  (b) **Frontend not yet designed** → operator wants the blank
      template scaffold so they can run `make run` and design
      iteratively in the local dev server.

**Expected**

Replace the single "Lovable repo URL?" prompt with a two-step:

```
Is the frontend already designed? [y/N]:
  >: y
  Lovable / GitHub repo URL:
    >: https://github.com/user/agesdk-dev-ui

Is the frontend already designed? [y/N]:
  >: n
  → Will scaffold the blank Astro template; design in local dev.
```

Or as a single question with branching:

```
Frontend status:
  1. Already designed in Lovable — I have a GitHub repo URL
  2. Not yet designed — scaffold the blank template
  >: 2
  → Will scaffold the blank Astro template; design in local dev.
```

**Actual**

Bootstrap currently has only the implicit `--git-url` flag (no
prompt). The pending Lovable-repo-URL prompt (separate bug) doesn't
ask the prior "is the frontend designed?" question.

**Where (guess)**

The Lovable-repo-URL prompt being added in the same bootstrap-UX
session — extend it to the two-step form. Operator decides which
shape they want at implementation time.

**Severity** — `minor`

The current flag flow works fine; this is an interactive-UX
improvement that pairs with the pending Lovable-repo prompt.

**Notes**

Surfaced 2026-05-20 by operator. Both bugs (this + the Lovable-
repo-URL one) should land together in the same bootstrap-UX fix
commit.

---

### 2026-05-20 — `new bootstrap` prompt layout makes Audience/ICP visually confusable

**Repro**

    lamill new bootstrap agesdk.dev

The operator's 2026-05-20 test session captured this exact
behavior:

```
  Audience — one sentence: who this is for (broad demographic)
  >: ICP: RN/Expo developer or small-team CTO at a consumer app
     with California users. Never dealt with age compliance before.
     Found the law via a legal email or Twitter. Will self-serve,
     will not talk to sales.

  ICP — the specific ideal customer — demographics, pain points,
  what they use today. More detail than Audience: Audience is the
  broad demo ("homeowners with EV chargers"), ICP is the specific
  targetable subset ("Tesla owners in CA who installed in last 90d,
  paid $2k+")
  >: <empty>
```

Operator typed the ICP content into the AUDIENCE prompt because:

  1. Each prompt's instruction text wraps onto multiple lines.
  2. The ICP prompt header (`ICP — the specific ideal customer
     — demographics, pain points, what they use today.`) starts
     immediately after the operator's Audience input.
  3. Operator's eye treated the ICP description text as additional
     context for the Audience question — natural pattern-matching
     failure on the visual hierarchy.

**Expected**

Each prompt is visually distinct enough that the operator can't
accidentally type a later prompt's content into an earlier one.
Concrete options (combinable):

  1. Echo the operator's input back after each prompt with a
     "[saved as <section>]" confirmation before moving on.
  2. Add a visual separator (rule line / blank line / bold
     heading) between sections so the next prompt's intro doesn't
     blend into the prior section's input area.
  3. Show only the H2-name + the `>:` line, with full description
     printed BEFORE the input field rather than between sections.
  4. Number each prompt (`[2/9] Audience:`) so operator can track
     which one they're on without re-reading the surrounding text.

**Actual**

Two operator sections got mis-routed in real testing. Bootstrap
saved incorrect content + left the correct slots empty (rendered
as `(to be filled in)` placeholders, requiring manual edit later).

**Where (guess)**

Whichever function in `src/portfolio/cli.py` /
`src/portfolio/bootstrap.py` orchestrates the v9.B AI_AGENTS
section prompts. The visual layout fix is the same place; the
"[saved as X]" confirmation is the same pattern.

Pairs with the cut-and-paste LLM prompt fix above — when operator
uses the LLM-staged flow (paste structured response section-by-
section), this confusion mostly disappears because each section
is already pre-labeled by the LLM.

**Severity** — `major`

Operator hit it on their first test session.

**Notes**

Surfaced 2026-05-20 by operator during the same test session that
surfaced the multi-paragraph paste + Lovable repo + pre-flight
listing bugs.

---

### 2026-05-20 — `new bootstrap` prompts don't validate input format

**Repro**

Vague — operator flagged "not understanding input" without a
specific repro. Suspected cases:

  1. Registrar prompt accepts arbitrary free text (`other` is the
     only documented fallback but typos like `porbun` get accepted
     verbatim and written into portfolio.json).
  2. Y/n prompts may not handle whitespace / capitalization
     gracefully — `Yes` or ` y` may behave differently than `y`.
  3. Operator's session output showed the ICP prompt's instruction
     text being LITERALLY captured as the answer in one case
     (operator hit Enter at the prompt header then started typing
     the instruction text from below) — suggests the prompt label
     might span multiple lines confusingly.

**Expected**

Each prompt's accepted input set is documented in the prompt
itself + validated. Whitespace-trimmed; case-insensitive where
appropriate; rejection messages list the accepted values.

**Actual**

Free-text accepted without validation in at least the registrar
prompt; behavior on whitespace / multiline pastes unclear.

**Where (guess)**

`_resolve_inventory_inputs()` / `_collect_operator_inputs()`
prompt logic in `src/portfolio/cli.py`. Add explicit `validate=`
arguments via Click or a custom `_prompt_choice()` wrapper that
loops on invalid input.

**Severity** — `minor`

**Notes**

Needs concrete repros from operator. Pairs with the multi-
paragraph paste bug above — both are part of an overall "the
prompt UX in bootstrap needs hardening" theme.

---

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

### 2026-05-20 — tech-debt audit pass

**Expected**
A deliberate pass over the codebase to identify what's worth
cleaning up vs leaving in place, after 22 shipped tiers of rapid
feature work.

**Fixed in** — 2026-05-21: audit done. Major findings landed in
`docs/architecture.md § 11 Tracked refactors`:

  1. **`cli.py` monolith** — 8,782 lines; 4× the next-largest
     module. Proposed split into scope-first modules
     (`cli/project.py`, `cli/fleet.py`, etc.). Trigger: gap between
     feature tiers (post-v23).
  2. **Platform-name enum drift** — three modules with three
     spellings (`cf-pages` vs `cloudflare-pages` etc.); symptom-
     treating translation map added in `project.py` 2026-05-21
     during the bug fix run. Proposed canonical
     `src/portfolio/platforms.py` module.
  3. **v15.K dead-code cleanup confirmed complete** —
     `_deploy_cf_pages_v3c` / `_deploy_cf_workers` /
     `deploy_cf_workers_via_shell` all gone from source. Stale
     comment in `prd.md:546` corrected this commit.

Secondary items from the original wishlist (still valid but lower
priority): cache modules consolidation, render-helpers move,
CHECK_NNN skip-condition decorator, duplicate OpenAI HTTP code,
test-fixture repetition, `stack_translate.py` prompt extraction.
Pick up between feature tiers; none block functionality. Per
`[[feedback_no_self_conformance]]`, use pytest / git hooks for any
tech-debt enforcement on portfolio itself — never new `CHECK_NNN`.

---

### 2026-05-20 — Deploy Step 5.5 (DNS purge) continues on auth failure instead of pausing for manual cleanup

**Repro**
`uv run lamill new deploy <domain> --yes` on a second-attempt deploy
where CF created parking DNS records that conflict with the target
custom-domain attach, when the operator's token lacks DNS:Edit on
the affected zone.

**Expected**
On `HTTP 403` from `purge_conflicting_root_records`, stop and
surface dashboard URL + records to remove (same gate pattern as
zone-create / Pages-project-create / Workers-custom-domain-attach).

**Actual**
Step 5.5 logged a soft `↷ DNS purge probe failed (continuing): ...`
and proceeded. Step 6 attach then failed (or live probe returned
parking page), leaving operator confused about which step actually
broke. Pre-fix output:

    5.5 Purge conflicting DNS records (disclosur.dev)
      ↷ DNS purge probe failed (continuing): DELETE /zones/.../dns_records/...
      → HTTP 403: {"success":false,"errors":[{"code":10000,...

**Fixed in** — 2026-05-21: `cli.py:6263-6294` Step 5.5 catch now
checks for `"HTTP 403"` in the `CloudflareAPIError` message. On
match, prints red ✗ + bold-yellow "Manual DNS cleanup required:"
block with exact dashboard URL
(`https://dash.cloudflare.com/{cf_account}/{domain}/dns/records`)
and the 3 record patterns to delete (`<domain>`, `*.<domain>`,
`www.<domain>`). Exits 7 (matches Step 6's exit-9 family). Non-403
errors (transient network / 5xx) keep soft-warn behavior — Step 6's
GET-then-PUT idempotency (v15.Q) catches stale records on retry.
No unit test added — `_deploy_cf_unified` orchestration is not
unit-testable today (would need full pipeline mock); fix mirrors
the well-tested Step 6 403 pattern.

---

### 2026-05-20 — `project check` deploy summary line shows wrong platform for cf-workers sites

**Repro**

    uv run lamill project check airsucks.com

**Expected**
`Deployment: cloudflare-workers` (the platform declared in
`lamill.toml [deploy].platform`).

**Actual**
`Deployment: cloudflare-pages` — `detect_platform()` matched the
`("cloudflare-pages", "wrangler.jsonc")` marker entry and didn't
consult lamill.toml. Marker map predates CFW becoming its own
deploy surface; CFW projects still carry `wrangler.jsonc` for local
`wrangler dev`.

**Fixed in** — 2026-05-21: `project.detect_platform()` now reads
`lamill.toml [deploy].platform` first via `lamill_toml.load()`. New
`_LAMILL_PLATFORM_TO_DETECT` map translates `cf-workers` →
`cloudflare-workers`, `cf-pages` → `cloudflare-pages`, etc.
Evidence trail surfaces `lamill.toml:[deploy].platform` so operators
can see which signal won. ParseError → silent fall-through to
existing marker-based detection (no crash on malformed declarations).
`platform = "none"` also falls through (operator hasn't declared,
markers are still the best guess). 8 new tests in
`tests/test_project_detect_platform.py` (cf-workers beats marker,
cf-pages, vercel, netlify, hostgator-with-hosting, no-file
fallthrough, malformed-toml fallthrough, none-falls-through). Suite
2507 → 2515.

---

### 2026-05-19 — HG-extra `disk N MB` is account-level total, looks per-domain

**Repro**
    lamill fleet hosting --refresh

**Expected**
Either rename to make the account-level scope clear, or move the
disk info to a footer block ("HG accounts: gator3164 500MB · ...")
so it isn't duplicated per row.

**Actual**
Every HG row from the same account showed the same disk number
(e.g., `disk 4959MB` on all 5 sites under `gator4216`). Operator
reading the table saw "every site uses 4959MB" — misleading; that's
the SHARED account quota, not per-domain usage.

**Fixed in** — 2026-05-21: chose Option 2 (footer aggregation).
Removed `disk N MB` from per-row HG-extra; added new
`_hg_accounts_disk_summary(rows)` helper that aggregates
`disk_used_mb` by `hg_account_id` and emits a single footer line:
`HG accounts: gator3164 500MB · gator4216 4959MB` (sorted by
account name). Suppressed when no HG row has disk data. Updated
`test_fleet_hosting_shows_hg_extra_column_when_hg_row_present` +
added 2 new tests (footer aggregates across multiple accounts;
footer absent without HG disk data). Suite 2505 → 2507.

---

### 2026-05-18 — `domain suggest` menu has letter-keyed option `s` between numbered 7 and 8

**Repro**
    uv run lamill domain suggest <topic>
    # interactive menu renders after first grid

**Expected**
Every menu option keyed by a number (plus `q` for quit). Reads
top-to-bottom as a single numeric sequence — no interleaved letters.

**Actual**
Option `s` ("Show marked names as full grid") was registered in
`MENU_ITEMS` between numbered items 7 and 8, rendering as a
visually out-of-place letter row.

**Fixed in** — 2026-05-21: renumbered `MENU_ITEMS` to pure numeric.
`s` → `8`, `8` (TLD ref) → `9`, `9` (Rerun fresh) → `10`. Updated
dispatch chain at `cli.py:3040-3052`, `_render_menu` count-suffix
check (`("6", "s")` → `("6", "8")`), and 5 test assertions across
`tests/test_suggest.py` + `tests/test_suggest_show_marked.py`. Suite
stays at 2505 / 1 skip.

---

### 2026-05-20 — Bootstrap's `package.json` template ships deprecated pnpm field

**Repro**

After `lamill new bootstrap <newdomain> --git-url <url>` (or any
bootstrap that emits the standard Astro+Vite template), running
`make deps` (or `pnpm install`) inside the sites Docker container
prints:

    [WARN] The "pnpm" field in package.json is no longer read by
    pnpm. The following keys were ignored: "pnpm.onlyBuiltDependencies".
    See https://pnpm.io/settings for the new home of each setting.

**Expected**

No deprecation warning. The bootstrap template's `package.json`
either drops the `pnpm.onlyBuiltDependencies` field entirely or
moves the equivalent setting to its new pnpm-9+ home (probably
`.npmrc` or a top-level `onlyBuiltDependencies` field — needs
checking against current pnpm docs).

**Actual**

Bootstrap-generated `package.json` includes:

```json
{
  "pnpm": {
    "onlyBuiltDependencies": ["..."]
  }
}
```

The field is silently ignored by pnpm 9+. Operator sees the noise
every build.

**Where (guess)**

`src/portfolio/bootstrap.py` — the `ASTRO_FILES` / `VITE_FILES`
template emitters. Search for `onlyBuiltDependencies` in the
package.json string templates. Either remove the `pnpm` block
entirely OR figure out the new equivalent and emit that.

**Severity** — `cosmetic`

Warning noise only; doesn't break the build. But every operator
build for every site prints it, so it's worth fixing for hygiene.

**Notes**

Surfaced 2026-05-20 by operator during a second-domain bootstrap
session after v15.M shipped. Likely related: pnpm 9 → 10 → 11
transition has been deprecating/relocating various
`package.json` pnpm.* fields over the past year. v15.S candidate.

**Fixed in** — verified clean 2026-05-21: `_astro_package_json()` at `bootstrap.py:739-764` carries no `pnpm` field; `_vite_package_json()` likewise. `git log -S "onlyBuiltDependencies" -- src/portfolio/bootstrap.py` returns empty — the template never literally emitted it. The deprecation warning the operator saw was pnpm injecting + complaining post-install; resolved by v15.S's `write_pnpm_workspace_yaml()` which puts the allowlist in the new pnpm v11 location (`pnpm-workspace.yaml`).

---

### 2026-05-20 — All `new` commands leave residue when they fail mid-flight

**Repro**

    lamill new bootstrap agesdk.dev

Operator pasted the multi-section LLM response; smart-paste fired
correctly; the v15.H stack-translation step started; Claude
subprocess hit the `$0.50` budget cap mid-translation
(`error_max_budget_usd` after 22 turns / $0.524). bootstrap raised
`StackTranslationError` and exited. State after:

    sites/agesdk.dev/
    └── genai/              ← the cloned TanStack source

No project scaffolding, no commit, no portfolio.json update — but
the `genai/` clone is sitting there waiting for the operator to
either re-run (which fails because `--git-url` won't clobber an
existing dir) or manually delete it.

**Expected**

Every `new` command (`bootstrap`, `deploy`, future) implements
**transactional rollback**: when any step after the project-dir
creation fails, clean up everything the command wrote so the
operator can re-run from clean state.

For `new bootstrap`:
  - On `BootstrapError` / `StackTranslationError` / KeyboardInterrupt
    raised after `project_dir.mkdir(parents=True)`, remove
    `project_dir` entirely.
  - Pre-existing dirs (operator had something there) detect at
    pre-flight + refuse — already protected today.
  - Smart-paste extras (registrar/registered/growth) that landed in
    `portfolio.json` should also roll back if scaffolding fails
    later in the same run. Cleanest: defer `portfolio.json` write
    until AFTER scaffolding completes successfully.

For `new deploy`:
  - On failure mid-pipeline, the GH repo, CF zone, CF Pages project,
    NS update are NOT trivially reversible (external SaaS state).
    Don't try to delete them — the v15.I pipeline is already
    idempotent so re-running picks up where it left off. Surface
    the partial-state summary on exit.

**Actual**

`new bootstrap`'s failure-path doesn't roll back. Operator must
manually `rm -rf` `sites/<domain>/` to retry. The `genai/` subdir
is the most common residue because translation happens after the
clone step but before the scaffolding step.

**Where (guess)**

`src/portfolio/bootstrap.py` `bootstrap()` function — wrap the
post-`project_dir.mkdir` body in a try/except that on any
exception (other than `BootstrapError("already exists")`):

  1. Logs the failure stage to stderr.
  2. Runs `shutil.rmtree(project_dir, ignore_errors=True)`.
  3. Re-raises.

**Severity** — `major`

Operator's first real-world `--git-url` run hit this. Manual
cleanup is annoying + the failure mode is hidden ("why won't
bootstrap work? oh, there's a `genai/` dir lying around from
yesterday").

**Notes**

Surfaced 2026-05-20 by operator after v15.H + smart-paste shipped.
Pairs with a related concern: the `--budget-usd 0.50` default for
v15.H translations is too low for real-world TanStack→Astro
translations (operator's `agesdk.dev` exceeded $0.524 after 22
turns). Bump default to `2.00` or `5.00` USD, OR add a `--budget`
flag to `new bootstrap` so the operator can override per-run.

Also worth: `genai/node_modules/` is Docker-owned (root-owned from
the host's perspective) and `shutil.rmtree` won't be able to remove
it without `sudo`. Rollback for `genai/` may need to either skip
`node_modules/` (best-effort cleanup) or shell out to a Docker
exec that owns those files.

Tier candidate: v15.K (after wrap) or fold into v17.

**Fixed in** — `3fc0800` (v15.K — resilience pass). `bootstrap()` wraps the post-`project_dir.mkdir` body in try/except; `_rollback_project_dir()` at `bootstrap.py:1645` runs `shutil.rmtree(project_dir, ignore_errors=True)` on any exception and re-raises. Pre-existing dirs detected at pre-flight (raise `BootstrapError("already exists")`) fire BEFORE the dir-tracker flips so they don't trigger rollback. PermissionError fallback for Docker-owned `genai/node_modules/` retries with `ignore_errors=True` and warns the operator with a Docker-cleanup hint.

---

### 2026-05-20 — `new bootstrap` doesn't prompt for Lovable's GitHub repo URL

**Repro**

    lamill new bootstrap agesdk.dev

Operator's workflow is typically: design the UI in Lovable.dev →
Lovable exports a GitHub repo → clone-and-scaffold that repo as a
new sites/<domain>/ project. Bootstrap already supports this via
the `--git-url <repo-url>` flag (which `git clone`s the URL into
`sites/<domain>/genai/` and runs the `--from-genai` path), but the
interactive flow doesn't ask for it.

**Expected**

Bootstrap interactive flow should ask:

```
Lovable GitHub repo URL (or Enter to skip and scaffold blank):
  >: https://github.com/user/agesdk-dev-ui
```

When provided, bootstrap follows the existing `--git-url` path
(clones into `genai/`, applies CF Pages safety fixes, etc.). When
empty, falls through to the standard blank-scaffold template.

Add as the FIRST prompt (before the AI_AGENTS sections) so the
operator's UI work is already in place before they fill in the
docs that should reference it.

**Actual**

Only the 8 prompts listed above (Summary / Audience / ICP / Goals /
Content strategy / Registered / Registrar / Growth hypothesis).
The `--git-url` flag is documented in `--help` but never
surfaces interactively.

**Where (guess)**

`src/portfolio/cli.py @new_app.command("bootstrap")` — add a
9th prompt at the top of the interactive flow (before the
v9.B operator-input sections kick in). Prompt accepts:
  - Empty (Enter) → skip → blank scaffold
  - `https://github.com/...` URL → set `git_url` arg → follow
    the `--from-genai` path
  - Optionally validate URL shape (`re.match(r'^https?://')`).

**Severity** — `major`

Operator's most common bootstrap flow uses Lovable; missing this
prompt forces them to remember the `--git-url` flag or run
bootstrap twice.

**Notes**

Surfaced 2026-05-20 by operator. Pairs with the pre-flight
question listing bug (the upfront list needs to include this new
prompt, becoming 9 questions total). Also adjacent to the multi-
paragraph paste bug (a URL is single-line so isn't hit by the
overflow issue, but the same prompt helper refactor could
benefit).

**Fixed in** — `ada334c` (bootstrap UX — 4 bugs from 2026-05-20). `_resolve_git_url()` helper at `cli.py:3744` prompts FIRST (before any AI_AGENTS section), validates `^https?://` or `^git@`, retries up to 3 times, then warn-skips. Empty input falls through to the standard blank-scaffold template. Skipped when `--git-url <url>` passed explicitly or `--non-interactive` set.

---

### 2026-05-20 — `new bootstrap` doesn't list all prompts upfront

**Repro**

    lamill new bootstrap agesdk.dev

The CLI starts asking questions one-by-one (Lovable-repo-URL →
Summary → Audience → ICP → Goals → Content strategy → registered?
→ registrar → growth hypothesis = 9 prompts total once the Lovable
prompt lands per the bug above) with no advance notice.

**Expected**

Print a single up-front banner before any prompt fires, listing all
8 questions that will be asked + a hint that any of them can be
`Enter`-skipped (and the `--non-interactive` / `--<section>` flag
escape hatches). Operator can either prep answers or hit Enter for
defaults.

**Actual**

Operator gets ambushed prompt-by-prompt with no idea how many more
are coming or what they cover.

**Where (guess)**

`src/portfolio/cli.py @new_app.command("bootstrap")` — between the
`--force` validation step and the first prompt (likely the
`_resolve_inventory_inputs()` / `_collect_operator_inputs()` call
or wherever the orchestrator's interactive phase begins). Print a
formatted table or bulleted list of the 8 upcoming questions before
firing the first prompt.

**Severity** — `minor`

**Notes**

Surfaced 2026-05-20 by operator. Pairs with the input-handling
bugs logged below — knowing what's coming helps the operator
prepare paragraph-length answers in advance.

**Fixed in** — `ada334c` (bootstrap UX — 4 bugs from 2026-05-20). `_render_bootstrap_preflight()` at `cli.py:3790` prints a 9-question banner before the first prompt. Lists each section + length hint + skip-flag. Only fires when at least one prompt would fire (suppressed under `--non-interactive` or when every per-section flag is supplied).

---

### 2026-05-20 — `new bootstrap` prompt input overflow (multi-paragraph paste leaks to shell)

**Repro**

Run `lamill new bootstrap <domain>`. At the Growth Hypothesis prompt
(or any other paragraph-style prompt), paste multi-paragraph text
that contains literal newlines (e.g., the operator's growth-
hypothesis text from the 2026-05-20 session containing 4
paragraphs separated by blank lines).

**Expected**

The full multi-paragraph paste should be captured as one input
field for that prompt — operator's growth hypothesis should land
verbatim into `docs/growth.md` regardless of how many newlines
it contains.

**Actual**

`typer.prompt(...)` accepts only the first line of the paste; the
remaining paragraphs leak out of the prompt and the shell tries
to execute them as commands:

```
The buyer is a developer or a CTO at a small team. They got a legal email…
Command 'The' not found, did you mean:
  command 'the' from deb the (3.3~rc1-3build1)
…
TAM is not the pitch. There are ~4M apps…
TAM: command not found
```

**Where (guess)**

Default `typer.prompt` / Click's `click.prompt` underlying impl
reads until the first newline. For paragraph-style inputs (growth
hypothesis, ICP, content strategy), we need a multiline editor
or a delimiter-based capture. Three approaches:

  1. **End-with-blank-line:** read lines until two consecutive
     blank lines appear (operator types text, hits Enter twice
     to finish).
  2. **`$EDITOR` invocation:** drop the operator into `vi`/`nano`
     with the prompt as a comment header; capture the buffer on
     save+exit. Heavier, but handles arbitrary length.
  3. **Click's `prompt(default="", show_default=False)` already
     supports `confirmation_prompt`** but not multiline. Custom
     multiline-prompt helper is the cleanest.

`_collect_operator_inputs()` / `_collect_growth_hypothesis()` in
`src/portfolio/cli.py` (or wherever those functions live) needs
the multiline helper.

**Severity** — `major`

**Notes**

Operator's pasted text didn't make it into the project, AND the
shell tried to execute each leaked paragraph as a command. The
bootstrap completed but with empty growth.md / partial AI_AGENTS
sections. Workaround until fixed: pass content via per-section
flags (`--summary "..."` / `--growth-hypothesis "..."`).

**Fixed in** — `ada334c` (bootstrap UX — 4 bugs from 2026-05-20). New `_prompt_multiline()` at `cli.py:3690` reads stdin until two consecutive blank lines OR EOF (Ctrl-D); wired into the four paragraph-style prompts (Summary, ICP, Content strategy, Growth hypothesis). Single-line prompts (Audience, Goals, Y/n Registered) stay on `typer.prompt`. Hint text flags "(hit Enter twice when done, or Ctrl-D)". Sister commit `2bda2b8` adds smart multi-section paste detection that previews the matches and auto-fills remaining prompts from one paste.

---

### 2026-05-20 — `new bootstrap` accepts unregistered/typo'd domains silently

**Repro**

    lamill new bootstrap ageskd.dev

Operator ran the above (typo for `agesdk.dev`). Operator owns
`agesdk.dev` at Porkbun (registered 2026-05-17; appears in
`data/domains/porkbun.csv` post `fleet sync --refresh`).

**Expected**

Bootstrap should at least *warn* before scaffolding a domain that's
nowhere in the owned-domains inventory — `data/portfolio.json` or
`data/domains/*.csv`. Either reject outright (default) or require
`--force` to proceed.

**Actual**

Silently scaffolded `~/work/projects/sites/ageskd.dev/` (typo'd dir)
+ appended a `registrar=porkbun, status=Active` row to
`data/portfolio.json` for a domain the operator doesn't actually own.

**Where (guess)**

`src/portfolio/cli.py @new_app.command("bootstrap")` + the bootstrap
orchestrator (likely `src/portfolio/bootstrap.py`). The pre-bootstrap
"Is the domain registered? [Y/n]:" prompt accepted Enter (default Y)
without any inventory cross-check. Add a validation step before that
prompt.

**Severity** — `major`

Causes real cleanup work + pollutes portfolio.json. Default `minor`
is wrong here.

**Notes**

Surfaced 2026-05-20 by operator. Sister bug to consider: registrar
prompt accepts free-text without validating against registrars
actually present in `data/domains/`.

**Fixed in** — `738d14c` (v16.B/C/D — bootstrap typo fix folded in). `validate_owned_domain()` pre-flight at `cli.py:3542` exits 2 with "Did you mean: ..." hint unless `--force` is passed. Sister fix (`ada334c` registrar prompt) restricts the registrar field to `porkbun` / `godaddy` / `namecheap` / `other`.

---

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
