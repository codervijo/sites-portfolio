---
prd: research-module-v2
status: draft (awaiting review)
author: Vijo (drafted with Claude)
created: 2026-05-14
parent: docs/prd.md (v8 SERP research tier)
---

# Research module v2 — niche evaluation framework + real SERP data

This PRD replaces the current `lamill new research` implementation (v8.A
strict + v8.B cluster) with a multi-gate evaluation framework backed by
real SerpAPI data, an operator-profile config, and a verdict vocabulary
that distinguishes "ship it" from "narrow the wedge first" from
"don't ship."

Implementation is sequenced into three mutually-dependent phases. **No
code is written by this PRD.** Open questions in §8 must be resolved
before any commits.

---

## 1. Problem statement

**Current state.** `lamill new research <topic>` asks gpt-4o-mini to
synthesize a SERP analysis from training data. The output looks
authoritative — ranked domains, content patterns, suggested angles,
ship/mixed/skip decision — but the underlying data is the LLM's guess
about what was ranking at training time, biased toward famous domains,
and blind to AI Overview, Reddit threads, news cycles, programmatic
incumbents, and anything that's appeared since the cutoff.

**What's broken.**
1. **Wrong verdicts in real use.** Four recent niche evaluations got
   verdicts that didn't match what the operator (me) discovered when
   I looked at the SERP myself. The tool was telling me "MIXED" on
   niches that should have been NO-GO, and "SKIP" on niches with
   clear lanes available.
2. **Three-state decision conflates different situations.** A SERP
   dominated by a programmatic incumbent reads the same as a SERP
   where Reddit ranks #3 with a discussion-locked intent. Materially
   different verdicts; current output renders them identically as
   "competition is high."
3. **"Suggested angles" generates content ideas, not moats.** First-
   instinct LLM ideas like "focus on regional cost variations" survive
   no scrutiny when tested against the structural-moat question.
4. **Operator constraints absent.** The tool gives the same verdict to
   a writer with credentialed expertise and to a builder running a
   weekly-cadence portfolio. They face different versions of the same
   niche.

**What good looks like.**
- Real SERP data (organic + SERP features) is the input, with a clearly-
  labeled GPT-synthesis fallback for the missing-key / no-budget path.
- Verdicts come from explicit, separately-reasoned gates, not a single
  LLM judgment.
- The operator profile is read on every run and constrains the verdict.
- The output is honest about uncertainty: "Gate 2 fails" is a different
  message from "Gate 2 fails because of programmatic incumbent X," and
  "operator lacks expertise" is a different message from "SERP is too
  competitive."
- When a niche fails, the tool suggests *how to narrow it* (axes:
  segment / geography / persona / use case / depth / moment) rather
  than just rejecting the topic.

---

## 2. Goals and non-goals

**Goals**

- Replace synthesis-as-primary with **real-SERP-as-primary** via
  SerpAPI; keep synthesis as an explicitly-labeled fallback.
- Encode the three-gate framework (Market / SERP / Moat) as the
  decision engine, not a single LLM judgment.
- Add an **operator profile** read at the start of every research run.
- Introduce a three-state verdict (**GO / NICHE-DOWN / NO-GO**) that
  forces the "narrow the wedge" answer to be a first-class output.
- All three phases land behind the existing `lamill new research`
  command — no new top-level surface.

**Non-goals** (deferred — listed for forward-reference, not designed
in v2)

- DR / domain-authority scoring (manual eyeballing is fine at n=1)
- Cross-niche comparison mode (run two probes back-to-back)
- SERP diff / change-over-time snapshots
- Cost-ceiling / revenue projection math
- Auto-generated moat sentences (requires human judgment)
- Cluster generation from real keyword tools (LLM is the cluster source
  for v2; revisit if the limitation bites)

These are explicitly out-of-scope. If they get added later they get
their own PRD.

---

## 3. User journey (me running this on a new niche idea)

```text
$ lamill new research "ev charger installation cost"

[reads operator.yaml from ~/.lamill/operator.yaml]
[loads SERPAPI_KEY from portfolio.env via load_env()]
[LLM expands "ev charger installation cost" into 5 cluster queries]
[for each query: SerpAPI top-10 organic + SERP features]
[runs Gate 1, Gate 2 against the real SERP data]
[Gate 2 detects specialty incumbent — prompts me interactively for Gate 3]
[applies operator-profile constraints]
[emits verdict + suggested reductions]

  Gate 1 (Market):  ✓ PASS  · 12.4K SV after pollution adjustment
                            · 1 of 5 queries polluted (muscle-car spam)

  Gate 2 (SERP):    ✗ FAIL  · notateslaapp.com programmatic incumbent
                              (Tesla updates) — ranks 5/5 cluster queries
                            · reddit.com #3 (discussion intent locked)
                            · 2 results potentially beatable

  Gate 3 (Moat):    Required because Gate 2 detected programmatic incumbent.
                    Enter a one-sentence testable moat (or press Enter to skip):
                    > _

  Operator fit:     ⚠ WARN  · Builder profile + niche rewards content writing
                            · narrow to tool/data wedge instead

  Verdict: NICHE-DOWN
  Suggested reductions:
    1. By segment: drop Tesla, lead with Rivian/Ford (less programmatic crowding)
    2. By depth: focus only on diagnostic-flow integration (tool wedge)
    3. By moment: trigger-based (post-fault) instead of browse-based

  Source: SerpAPI · 5 queries · cached as data/serp/2026-05-14/<hash>.json
```

The interactive Gate 3 prompt is the **only** interactive moment.
Everything else is non-interactive output. The `--json` mode skips
Gate 3's prompt entirely and emits `moat_required: true, moat_provided: null`
so a script can handle it.

---

## 4. Functional requirements (the three phases)

### Phase 1 — Real SERP data

**P1.1** Add `SERPAPI_KEY` to the `portfolio.env` template **and** to
`apikeys.KNOWN_KEYS` so `lamill settings apikeys list/set` covers it.
Add a `_probe_serpapi()` connectivity check alongside the existing
OpenAI / CrUX / Porkbun / CF probes.

**P1.2** New module `src/portfolio/serp_fetch.py` (or extend `serp.py`)
with `fetch_serp(query: str) -> dict` returning the SerpAPI response
normalized to a stable shape:
```json
{
  "query": "...",
  "fetched_at": "2026-05-14T...",
  "organic_results": [
    {"position": 1, "domain": "...", "url": "...", "title": "...",
     "snippet": "...", "displayed_link": "..."}
  ],
  "features": {
    "ai_overview": {"present": true, "cited_domains": ["..."]},
    "people_also_ask": ["...", "..."],
    "featured_snippet": {"present": false},
    "image_pack": {"present": true},
    "video_pack": {"present": false},
    "local_pack": {"present": false},
    "reddit_card": {"present": true, "position": 3}
  }
}
```

**P1.3** Cache per-query SerpAPI responses to
`data/serp/<YYYY-MM-DD>/<query-hash>.json` (date subdir, hash per query)
so a day's worth of probes cluster naturally and old days can be
archived/dropped. The cluster-level analysis lives at
`data/serp/<YYYY-MM-DD>/clusters/<cluster-hash>.json` and references
the per-query files. **Schema-version field on every file.**

**P1.4** `--no-cache` re-fetches; default TTL = 7 days (SERPs move
weekly; LLM synthesis used 30, but real SERP should be fresher).

**P1.5** `--synthesis-only` flag short-circuits to the existing GPT
path. Output banner must say:
```
⚠  source: GPT synthesis (fallback) — NOT REAL SERP DATA
   knowledge cutoff applies, verdicts are heuristic only
```
…and the gates still run, but their results are explicitly tagged
`[from LLM guess]` in the rendered output.

**P1.6** If `SERPAPI_KEY` is missing AND `--synthesis-only` is not set,
emit a one-line error pointing at `lamill settings apikeys set
SERPAPI_KEY` and exit 2. Don't silently fall back — that's the bug
the current tool has.

**P1.7** If SerpAPI request fails (rate limit, network, 5xx), retry
once, then fall back to synthesis-only mode with a loud warning. The
cached output of the failed query path is NOT written, so the next
run retries.

### Phase 2 — Three-gate decision logic

**P2.1** New module `src/portfolio/research_gates.py`. Pure logic —
takes a cluster-level dict (output of Phase 1's fetch + LLM cluster
expansion) and returns a `GateResults` dataclass:

```python
@dataclass
class GateResult:
    passed: bool | None    # None = "pending input" (Gate 3 before prompt)
    label: str             # "PASS" | "FAIL" | "PENDING"
    findings: list[str]    # bullet-point reasons, rendered in output
    raw: dict              # debug / json mode

@dataclass
class GateResults:
    gate_1_market: GateResult
    gate_2_serp: GateResult
    gate_3_moat: GateResult
    operator_fit: OperatorFitResult
    verdict: str           # "GO" | "NICHE-DOWN" | "NO-GO"
    suggested_reductions: list[str]
    moat_required: bool
    moat_provided: str | None
```

**P2.2 — Gate 1 (Market):**
- For each cluster query, get a per-query volume estimate (see Open
  Question §8.A — we don't have real volume out of the box).
- **Pollution detection:** for each query, check whether the top-3
  organic result titles contain at least one keyword stem from the
  cluster (defined as: tokenized cluster query, lowercased, stopwords
  removed, simple Porter-stem-equivalent — implementation may use a
  light-weight `re`-based stemmer rather than nltk).
- A query is "polluted" if 0/3 of its top results stem-match the
  cluster.
- `pollution_adjusted_volume = sum_of_unpolluted_query_volumes`
- **Gate 1 PASS** if pollution-adjusted ≥ 5K SV/month. **FAIL** else.

**P2.3 — Gate 2 (SERP):** Classify each top-10 domain in the merged
cluster:

| Classifier | Detection rule |
|---|---|
| `SPECIALTY_INCUMBENT` | Domain ranks for ≥1 query AND URL matches programmatic-pattern regex (`/(?:19\|20)\d{2}/`, `/v\d+\b/`, `/[A-Z]{2}/(?:state)/`, `/[a-z\-]+(?:city\|town)/`, `/(?:model\|version)/[a-z0-9\-]+`) AND domain is not media/Reddit/manufacturer (see §8.D for the major-media allow-list resolution) |
| `PROGRAMMATIC_AT_SCALE` | Same domain in 3+ cluster queries' top-10 with similar URL templates |
| `MEDIA_LOCKED` | ≥2 cluster queries return a result from the major-industry-media list (§8.D) in top 10 |
| `REDDIT_PRESENT` | `reddit.com` in any cluster query's top 10 |
| `BRANDED_LOCKED` | For branded queries (detected via the cluster including a known brand term), the brand's own domain is top 3 |
| `AI_OVERVIEW_DOMINANT` | `ai_overview.present == True` on ≥2 cluster queries |
| `POTENTIALLY_BEATABLE` | A ranking domain not matching any of the above, with weak signals (no `wikipedia.org` link in their SERP entry, no obvious institutional name) |

**Gate 2 FAIL** if ANY of the following:
- `SPECIALTY_INCUMBENT` or `PROGRAMMATIC_AT_SCALE` detected
- `REDDIT_PRESENT` AND `MEDIA_LOCKED` (both intents locked)
- `AI_OVERVIEW_DOMINANT` alone

**Gate 2 PASS** if ≥3 `POTENTIALLY_BEATABLE` results AND no kill-tier
classifiers fire.

Otherwise: **WEAK PASS** — passes but the findings list flags the
specific lock that would force a niche-down.

**P2.4 — Gate 3 (Moat):** Only required if Gate 2 detected
`SPECIALTY_INCUMBENT` or `PROGRAMMATIC_AT_SCALE`. The tool prints:

```
Gate 3 (Moat): Required because Gate 2 detected a specialty incumbent.
Format: "I will win on [query pattern] because [incumbent gap], and the
incumbent cannot close this gap in 6 months because [structural reason]."

Enter your moat sentence (or press Enter to skip and accept NO-GO):
> _
```

If the user enters a sentence, Gate 3 = PASS and the sentence is
stored in the snapshot. If the user presses Enter, Gate 3 = FAIL.

In `--non-interactive` or `--json` mode, Gate 3 = `PENDING` and the
verdict accounts for it as if it had failed (the user can re-run
without `--non-interactive` to fill in).

**P2.5 — Verdict synthesis:**

| Gates | Verdict |
|---|---|
| Gate 1 FAIL | **NO-GO** (market too small) |
| Gate 2 FAIL AND Gate 3 PROVIDED | **NICHE-DOWN** (moat acknowledged, narrow the scope) |
| Gate 2 FAIL AND no moat | **NO-GO** |
| Gate 1 PASS + Gate 2 WEAK-PASS + Gate 3 not required | **NICHE-DOWN** (the "weak pass" findings drive the reductions) |
| All gates PASS | **GO** |

**P2.6 — Suggested reductions** (when verdict = NICHE-DOWN): emit 2-3
concrete reductions across these axes, generated by the LLM given the
gate findings as context:

- segment (drop a brand, vertical, sub-category)
- geography (regional only)
- persona (specific role / experience level)
- use case (one task vs the full workflow)
- depth (tool vs content, data vs explanation)
- moment (triggered vs evergreen, post-event vs browse)

**P2.7** Remove the existing `ship | mixed | skip | unclear` decision
field from snapshots. Mark this as a breaking schema change; the
schema version bumps from `v8.B` to `v8.C-research-v2`. Old caches
become invalid and get re-fetched on next access.

### Phase 3 — Operator profile

**P3.1** New file at `~/.lamill/operator.yaml` (or alternative — see
Open Question §8.B). Schema (proposed):

```yaml
expertise:
  - SEO and programmatic content
  - Python and CLI tooling
  - Domain portfolio management
workflow_preference: builder    # builder | writer | mixed
motivation_cadence: weekly      # weekly | monthly | quarterly
hours_per_week: 10
budget_monthly: 100
existing_fleet:
  - hybridautopart.com
  - voltloop.site
  - lamill.io
```

**P3.2** `OperatorProfile` dataclass + loader in
`src/portfolio/operator_profile.py`. Loader returns an empty profile
(all fields = None / empty lists) if the file is missing — tool still
runs, just without operator-fit gates.

**P3.3** New CLI surface: `lamill settings operator show | edit`.
- `show` prints the loaded profile (or "no profile configured").
- `edit` opens the file in `$EDITOR` (creates it from a template if
  absent).

**P3.4 — Operator-fit constraints (applied after Gate 2):**

- **Expertise check:** if the cluster's primary intent is `informational`
  (≥3/5 queries) AND the SERP rewards E-E-A-T (heuristic: ≥3/10 top
  organic results are institutional or publisher-listicle with named
  authors visible in snippet) AND none of the cluster's primary topic
  terms (extracted via simple noun-phrase split) appear in
  `operator.expertise[]`, then **auto-fail Gate 2** with the finding:
  > "Operator lacks declared expertise; narrow to tool/data wedge."

- **Workflow check:** if `workflow_preference == "builder"` AND the
  cluster has ≥3/5 queries returning publisher-listicle-dominant SERPs
  (content writing rewarded), emit a warning (doesn't fail Gate 2 by
  itself, but adds a `niche-down` finding):
  > "Builder profile + niche rewards content. Narrow to tool wedge."

- **Cadence check:** if `motivation_cadence == "weekly"` AND the
  cluster's intent is "evergreen reference" (proxy: top results are
  >2 years old by visible date), warn:
  > "Cadence: weekly. Niche metrics move monthly+. Watch motivation."

- **Fleet adjacency:** for each of `operator.existing_fleet`, check
  whether the SERP's top-10 includes that domain or whether its
  `lamill fleet info summary` category matches the cluster's topic.
  If yes, surface as a finding:
  > "Adjacent to your existing hybridautopart.com (DR-equivalent in
  >  the auto-repair vertical). Consider extending vs starting fresh."

**P3.5** All operator-fit findings render under a separate
"Operator fit" section in the output, between Gate 3 and the verdict.
They influence the verdict (auto-fail Gate 2 or add reductions) but
don't replace Gate 2.

---

## 5. Data model changes

### Per-query SerpAPI snapshot (new, Phase 1)

`data/serp/<YYYY-MM-DD>/<query-hash>.json`:
```json
{
  "schema": "serp-query-v1",
  "query": "ev charger installation cost",
  "query_hash": "<12-char-sha256>",
  "fetched_at": "2026-05-14T19:00:00+00:00",
  "source": "serpapi",
  "organic_results": [ /* see P1.2 */ ],
  "features": { /* see P1.2 */ }
}
```

### Cluster analysis snapshot (refactor, Phase 1+2)

`data/serp/<YYYY-MM-DD>/clusters/<cluster-hash>.json`:
```json
{
  "schema": "research-cluster-v2",
  "topic": "ev charger installation cost",
  "topic_hash": "...",
  "fetched_at": "...",
  "source": "serpapi",                     // or "gpt-synthesis-fallback"
  "knowledge_caveat": "...",               // present only if source = gpt-...
  "cluster_queries": [...],
  "per_query_files": ["<query-hash>.json", ...],
  "operator_snapshot": { /* copy of operator.yaml at probe time */ },
  "gates": {
    "gate_1_market": {
      "passed": true,
      "label": "PASS",
      "findings": ["12.4K SV after pollution adjustment", "..."],
      "raw": {"pollution_adjusted_volume": 12400, "polluted_queries": [...]}
    },
    "gate_2_serp": {
      "passed": false,
      "label": "FAIL",
      "findings": [...],
      "raw": {"classifications": {...}}
    },
    "gate_3_moat": {
      "passed": null,
      "label": "PENDING",
      "findings": [],
      "raw": {}
    }
  },
  "operator_fit": {
    "warnings": [...],
    "auto_fail_gate_2": false
  },
  "verdict": "NICHE-DOWN",                 // GO | NICHE-DOWN | NO-GO
  "suggested_reductions": [...],
  "moat_required": true,
  "moat_provided": null
}
```

### Removed fields

These v8.B fields disappear from the cluster snapshot:
- `analysis.decision` (replaced by `verdict`)
- `analysis.top_likely_rankers` (replaced by per-query files +
  classifications)
- `analysis.competitive_signal` (replaced by gate findings)
- `analysis.suggested_angles` (replaced by `suggested_reductions`
  which is only present when verdict = NICHE-DOWN)
- `mode` (no more `cluster | strict`; cluster is the only mode)

Old caches are invalidated on schema-version mismatch (see P2.7).

---

## 6. Config schema

### portfolio.env (existing, additive)

Append to the auto-generated template in `suggest.py:ensure_portfolio_env()`:
```
# v8.C — SerpAPI key for real-SERP research (lamill new research).
# Plan: $50/mo for SerpAPI's "Bronze" tier (5000 queries/mo). Sign up
# at https://serpapi.com/. Leave blank to use --synthesis-only fallback.
SERPAPI_KEY=
```

### ~/.lamill/operator.yaml (new, Phase 3)

See P3.1 above. Defaults if the file is missing:

```python
OperatorProfile(
    expertise=[],
    workflow_preference="mixed",   # least-opinionated default
    motivation_cadence="monthly",  # mid
    hours_per_week=None,
    budget_monthly=None,
    existing_fleet=[],             # loaded separately from portfolio.json fallback
)
```

If `existing_fleet` is empty in operator.yaml, the loader falls back to
the canonical inventory (every domain in `data/portfolio.json` whose
category is NOT in `IGNORE_CATEGORIES`).

---

## 7. Output format (target state)

Example output reproduced from §3 above, structurally:

```
SERP research — "<topic>"
  source: SerpAPI · 5 queries · cached 0d ago

  Topic cluster:
    → 1. <literal>
      2. <expanded>
      ... (5 queries total)

  Gate 1 (Market):  ✓ PASS  · <volume> SV after pollution adjustment
                            · <N> of 5 queries polluted (<reason>)

  Gate 2 (SERP):    ✗ FAIL  · <classifier-finding-1>
                            · <classifier-finding-2>
                            · <N> results potentially beatable

  Gate 3 (Moat):    [pending operator input | PASS | FAIL]
                    [moat sentence echoed back if provided]

  Operator fit:     ⚠ WARN  · <fit-finding-1>
                            · <fit-finding-2>

  Verdict: <GO | NICHE-DOWN | NO-GO>

  Suggested reductions:  (only if verdict = NICHE-DOWN)
    1. <reduction-1>
    2. <reduction-2>
    3. <reduction-3>

  Source: SerpAPI · cached as data/serp/<date>/<hash>.json
```

`--brief` collapses to one-line per gate + verdict + 2 reductions.
`--json` emits the full cluster-snapshot JSON shape from §5.

---

## 8. Open questions to resolve before implementation

These are questions where the prompt's spec is under-specified or where
existing-code constraints conflict with the spec. **Resolve these
before any code lands.**

### 8.A — Volume data source

The spec requires Gate 1 to fail when "pollution-adjusted volume <
5K SV/month." **SerpAPI's organic-search endpoint does not return
search volume.** Three options:

1. **Skip real volume entirely.** Use LLM volume estimates as proxy
   (acknowledged unreliable). Gate 1 becomes "LLM estimates X SV;
   confidence: low."
2. **SerpAPI's keyword research add-on** (~+$100/mo). Real volume data
   from Google Ads-style sources. Doubles SerpAPI bill.
3. **Use a free volume proxy** — e.g., the count of unique organic
   results in top 100 (deep results = high-volume signal), or Google
   autocomplete suggestion count, or Reddit/forum mention count via
   SerpAPI's Reddit search. Heuristic, but free.

**My recommendation: option 3 + label honestly as a proxy.** Avoids
the cost bump and gives a usable signal. Real volume becomes a future
upgrade with its own PRD.

**Your call:** which option?

### 8.B — Operator config location

Spec says `~/.lamill/operator.yaml`. Existing convention is per-project
config in `portfolio.env` at the repo root. Three options:

1. **Global at `~/.lamill/operator.yaml`** (per the spec) — fits the
   "this is about me, not the repo" framing, but breaks the
   everything-in-the-repo pattern.
2. **Per-project at `<repo>/operator.yaml`** — fits existing pattern,
   makes the config part of the lamill repo, easier to version.
3. **Hybrid: load `<repo>/operator.yaml` if present, else fall back to
   `~/.lamill/operator.yaml`** — supports both patterns.

**My recommendation: option 1 (global at `~/.lamill/`).** Operator
profile is genuinely about the person, not the repo. Lives outside the
repo for a reason. The existing per-project pattern is the right
default for things like API keys; operator-profile is a different kind
of config.

### 8.C — Config file format (YAML vs TOML vs JSON)

No YAML lib in the codebase today. Adding pyyaml is a new dep.

1. **YAML** (per spec) — most human-friendly, but adds pyyaml dep
2. **TOML** — Python 3.11+ stdlib via `tomllib` (read-only), no new
   dep. Reasonable for read-many-write-rare config.
3. **JSON** — no new dep, no nice config syntax (no comments).

**My recommendation: TOML.** Stdlib, no new dep, supports comments,
and we only need read at runtime (writes happen via `$EDITOR`).

**Your call:** YAML (per spec), TOML, or JSON?

### 8.D — "Major industry publication" classification source

Gate 2's `MEDIA_LOCKED` classifier requires identifying when a SERP
result is from a major industry publication. Three options:

1. **Static allow-list per topic.** `data/research/media_publications.toml`
   with entries like `automotive: [caranddriver.com, motortrend.com,
   autoweek.com, ...]`. Pro: deterministic. Con: requires curation; new
   topics need updates.
2. **LLM classification.** Send each ranking domain to gpt-4o-mini:
   "Is <domain> a major industry publication in <topic-vertical>?
   yes/no." Pro: flexible. Con: reintroduces LLM at a critical signal
   point, adds ~10 calls per research run.
3. **Heuristic:** check domain via `tldextract` + `data/portfolio.json`
   manual flags + Wikipedia API "does this domain have a Wikipedia
   article?" Pro: free, structural. Con: not all major pubs have WP
   articles; complex.

**My recommendation: option 1 (static allow-list).** It's the
operator's tool, the operator can maintain it. Seeded with ~20 verticals
covering my fleet (automotive, EV, HVAC, indoor air, cricket, …); add
more as new verticals appear. List is data, not code; lives in
`data/research/media_publications.toml`.

**Your call:** confirm option 1 or pick differently.

### 8.E — Snapshot retention policy

Per-query files at `data/serp/<YYYY-MM-DD>/<query-hash>.json` could
accumulate quickly. Three options:

1. **Keep forever.** Same as `data/checks/` and `data/seo/`. Disk usage
   is fine at personal scale (probably < 100MB/yr).
2. **Auto-trim after N days.** Delete date subdirs older than 90 days.
3. **No git-tracking.** Add `data/serp/` to `.gitignore`. Snapshots
   become local-only.

The current `data/checks/`, `data/seo/`, and `data/serp/` are all
git-tracked (we explicitly chose this for v8.A so trend analysis can
read history).

**My recommendation: option 1 (keep forever, git-tracked).** Disk
isn't a constraint; trend data is valuable when a future feature wants
"how has the SERP for X changed in 6 months?"

**Your call:** confirm or change.

### 8.F — `--synthesis-only` and the three-gate logic

Synthesis-only mode runs the gates from LLM-guessed data instead of
real SERP. Gate 2's URL-pattern detection collapses (LLM doesn't return
real URLs — just domain names). Two options:

1. **Run gates anyway** with a loud "[from LLM guess]" tag on every
   finding. Gate 2 mostly skips URL-pattern detection, relies more on
   LLM's qualitative judgment of "is this a programmatic incumbent
   pattern?"
2. **Skip Gate 2 entirely in synthesis-only mode** and emit only Gate
   1 + Gate 3 + operator fit. Verdict becomes mostly operator-fit-driven.

**My recommendation: option 1.** Synthesis-only is for ideation, not
go/no-go. Running degraded gates with explicit tags is better than
hiding them — the user is reminded that the synthesis output is less
trustworthy.

### 8.G — SerpAPI tier / cost expectations

The cheapest paid tier I know of is SerpAPI Bronze: $50/mo for 5000
queries. At 5 queries per cluster, that's 1000 research runs/mo.

**Confirm:** is the $50/mo SerpAPI Bronze subscription within budget,
or should the PRD assume cheaper / different vendor (DataForSEO,
Scraperapi, etc.)?

### 8.H — Cache invalidation on schema bump

When the cluster snapshot schema changes from v8.B → v2 (P2.7), the
existing `data/serp/*.json` files become unreadable. Options:

1. **Delete `data/serp/*.json` on first v2 run** with a one-line
   migration note. Cleanest.
2. **Move them to `data/serp/_archive_v8b/`** for forensics.
3. **Try to migrate** the old shape forward. Most fields don't have
   v2 equivalents; this is mostly a no-op.

**My recommendation: option 2.** Move, don't delete. Zero data loss
risk; the archive can be removed later by hand.

### 8.I — Existing v8.A `--strict` mode

The v8.A literal-topic-only mode (`--strict`) currently exists. The v2
spec doesn't mention it, and the new framework assumes cluster mode
always. Options:

1. **Drop `--strict`** in v2 — cluster is the only mode.
2. **Keep `--strict`** as a parallel path that runs only literal-topic
   SerpAPI + gates on 1 query instead of 5.

**My recommendation: drop `--strict`.** The cluster mode is more useful;
keeping strict around for the rare case adds maintenance burden. If
someone wants literal-topic SerpAPI, they can pass a `--depth 1` flag
later — but for now, drop.

### 8.J — Volume data fallback when SerpAPI proxy fails

When Gate 1 uses the proxy from Option 3 above (organic-count heuristic
or autocomplete), and the proxy fails for a specific query (e.g.,
SerpAPI returned 0 results — query is too niche), Gate 1 needs a
behavior. Options:

1. **Treat 0-results queries as 0 SV.** Pollution-adjusted volume
   drops; Gate 1 may fail. Honest behavior.
2. **Treat 0-results queries as "unknown SV"** and pass the gate if
   ≥3 of 5 queries have data. Less honest but more forgiving.

**My recommendation: option 1.** Honest about the gap.

---

## 9. Implementation plan (commit-by-commit, with smoke tests)

### Preamble commit (zero-risk refactor)

**Commit P0** — Move `data/serp/*.json` and `data/serp/_index.json`
into `data/serp/_archive_v8b/`. Update `serp.py` to point at the
archive read-only for `lamill new research --replay-cache <topic>` (a
debugging flag — not user-facing). Sets up the migration path before
schema changes.

*Smoke test:* `lamill new research "anything" --synthesis-only` still
works (uses LLM, doesn't touch the archived caches).

---

### Phase 1 commits

**Commit P1.A** — Add `SERPAPI_KEY` to `KNOWN_KEYS` + portfolio.env
template + connectivity probe in `apikeys.py`. Update
`lamill settings apikeys list` to report it.

*Smoke test:* `lamill settings apikeys list` shows SERPAPI_KEY as
"unset" or "set + connectivity ✓".

**Commit P1.B** — `src/portfolio/serp_fetch.py` with `fetch_serp(query)`
returning the normalized shape from P1.2. Includes retry logic,
SerpAPI-error to ResearchError mapping. No CLI wiring yet.

*Smoke test:* `python -c "from portfolio.serp_fetch import fetch_serp;
import json; print(json.dumps(fetch_serp('ev charger installation cost'),
indent=2)[:500])"` returns a real SERP. Required: SERPAPI_KEY set.

**Commit P1.C** — Per-query caching to `data/serp/<YYYY-MM-DD>/<query-
hash>.json` with `schema: serp-query-v1`. `load_cached_query(query,
ttl_days=7)`, `save_cached_query(...)`. Tests against tmp_path.

*Smoke test:* `pytest tests/test_serp_fetch.py -q` (~10 new tests).

**Commit P1.D** — Refactor `serp.py:research()` to: (a) load the
cluster query list from gpt-4o-mini (existing code), (b) for each
query, call `fetch_serp()`, (c) cache + return a NEW cluster snapshot
shape that's just the per-query results merged (no gates yet, no
verdict — that's Phase 2). Synthesis-only path preserved behind
flag, marked clearly.

*Smoke test:* `lamill new research "ev charger installation cost"`
runs end-to-end against SerpAPI, writes one cluster file + 5 per-query
files, output shows raw SERP data (no gates).

**Commit P1.E** — `--synthesis-only` flag wired with loud banner.
`--no-cache` re-fetches both LLM cluster expansion AND per-query SERPs.
Error paths (missing key, SerpAPI 5xx, rate limit) tested.

*Smoke test:* `lamill new research "test" --synthesis-only` shows
banner; `lamill new research "test" --no-cache` re-fetches; missing
SERPAPI_KEY errors with the right pointer.

### Phase 2 commits

**Commit P2.A** — `src/portfolio/research_gates.py` skeleton:
dataclasses (`GateResult`, `GateResults`), `evaluate_gate_1(cluster)`,
`evaluate_gate_2(cluster)`, `evaluate_gate_3(cluster, moat_input)`.
Pure logic, no CLI. Unit tests with synthetic cluster fixtures.

*Smoke test:* `pytest tests/test_research_gates.py -q` (~25 tests).

**Commit P2.B** — Gate 1 (Market) — volume estimate via the chosen
proxy (§8.A), pollution detection, pollution-adjusted volume math.
Unit tests for: clean cluster, polluted cluster, mixed cluster, edge
cases (0 results, all polluted).

*Smoke test:* `lamill new research "ev charger installation cost"
--debug-gates` shows Gate 1 output but skips 2 and 3.

**Commit P2.C** — Gate 2 (SERP) — classifiers in priority order.
Static `media_publications.toml` (§8.D — assuming option 1 chosen)
seeded with ~20 verticals. Programmatic-URL regex library. Tests
cover each classifier individually + combinations.

*Smoke test:* Cluster with known programmatic incumbent (e.g.,
`notateslaapp.com`) → classifier fires; cluster without one → doesn't.

**Commit P2.D** — Gate 3 (Moat) — interactive prompt, snapshot
storage, `--non-interactive`/`--json` mode handling.

*Smoke test:* Running interactively on a cluster that fails Gate 2
prompts for moat; entering text → PASS; Enter → FAIL; `--json` skips.

**Commit P2.E** — Verdict synthesis (§5 table) + suggested-reductions
generator (LLM call with the gate findings as context). Renderer
updated to show gates + verdict + reductions.

*Smoke test:* `lamill new research "ev charger installation cost"`
end-to-end produces the target output from §3.

**Commit P2.F** — Snapshot schema migrated to v2 (`research-cluster-v2`).
Old `data/serp/*.json` were already archived in P0. Cache invalidation
on schema mismatch. Tests confirm v1 cache is treated as miss.

*Smoke test:* `lamill new research "<previously-cached topic>"` does
NOT serve from a v1 cache; re-fetches fresh.

### Phase 3 commits

**Commit P3.A** — `src/portfolio/operator_profile.py`:
`OperatorProfile` dataclass, `load_profile()`, `default_profile()`,
TOML-or-YAML reader (§8.C decided). Tests against tmp_path with
synthetic profiles.

*Smoke test:* `pytest tests/test_operator_profile.py -q` (~12 tests).

**Commit P3.B** — `lamill settings operator show` + `edit` CLI
commands.

*Smoke test:* `lamill settings operator show` prints the profile (or
"no profile configured"); `lamill settings operator edit` opens
`$EDITOR`.

**Commit P3.C** — Operator-fit constraints wired into
`research_gates.py`:
- Expertise check (auto-fail Gate 2)
- Workflow check (warning + niche-down trigger)
- Cadence check (warning)
- Fleet adjacency (finding)

Tests for each constraint individually + integration test on a known
cluster + profile combination.

*Smoke test:* `lamill new research "ev charger installation cost"`
with `workflow_preference: builder` in operator.yaml emits the
"Builder profile + niche rewards content" warning.

### Final commits

**Commit P4.A** — Documentation update:
- `docs/CLAUDE.md`: brief on the new `new research` flow + operator
  profile location
- `AI_AGENTS.md`: note the v8.C → v2-research-module migration
- `docs/Prompts.md`: dated H2 entry
- `docs/prd.md`: mark v8.C in v8 tier table as ✅ (renamed from the
  dropped one — see PRD note on the redefinition)

*Smoke test:* `lamill project check sites/portfolio` passes the docs
checks; full suite still passes.

**Commit P4.B** — Update PRD (`docs/prd.md`) to reflect v8.C shipped.
Update feature-table entries.

*Smoke test:* manual review.

---

## 10. Effort estimate

Honest reading, not padded, not shrunk:

| Phase | Commits | Estimated hours | Key risks |
|---|---|---|---|
| Preamble | P0 | 1h | Archive migration script |
| Phase 1 | P1.A–E | 8–10h | SerpAPI integration, error paths, retry logic, test coverage of failure modes |
| Phase 2 | P2.A–F | 10–14h | Gate 2 classifier rules, programmatic-URL regex (hard to get right), verdict-synthesis LLM call wired correctly, schema migration |
| Phase 3 | P3.A–C | 5–7h | Operator-fit heuristics, especially the expertise check |
| Docs + cleanup | P4 | 1–2h | |
| **Total** | **15 commits** | **25–34h** | |

The wider range comes from Gate 2 — the classifier rules will need
iteration once real-SERP data shows edge cases. Plan for ≥2 rounds
of refinement after P2.E lands.

Critique-suggested 12–15h was optimistic. It didn't account for the
volume-data problem (§8.A), the operator-profile gates (Phase 3), or
test work proper.

---

## 11. Future considerations (deferred, named only)

For forward-reference, in case any of these become relevant later:

- Real-time keyword volume via SerpAPI keyword add-on or DataForSEO
- DR / domain-authority scoring (Ahrefs / Moz API)
- Cross-niche comparison mode
- SERP diff / snapshot tracking over time
- Cost-ceiling / revenue projection math
- Auto-generated moat sentences (would need a moat-validator LLM step)
- Cluster generation from real keyword tools (Google autocomplete,
  Ahrefs related terms, People Also Ask scraping)
- Operator-profile inference from `data/portfolio.json` (auto-detect
  existing fleet, infer expertise from `docs/CLAUDE.md` files across
  the fleet)
- A `lamill new research --watch <topic>` mode that re-runs weekly and
  surfaces SERP changes

These are explicitly NOT designed in v2.

---

## 12. Recommended preamble refactor (NOT part of v2)

While reading the existing code I noticed a small refactor that would
make v2 cleaner but is NOT required:

- `src/portfolio/serp.py` is 673 LOC and mixes: prompt building, OpenAI
  HTTP, cache I/O, response parsing, orchestrator. Could be split into
  `serp_llm.py` (prompt + OpenAI), `serp_cache.py` (I/O), and
  `research.py` (orchestrator + the new gates module). This would
  parallel the existing pattern of `seo_runtime.py` + `seo_cache.py`.

Not required for v2 to ship — the existing code is workable. But if
the v2 work gets close to ~900 LOC in one file, the split becomes
worth doing.

---

## 13. Approval

This PRD is **draft, awaiting review**. Before any code lands:

1. Resolve the 10 open questions in §8.
2. Confirm the 3-phase scope is right (no expansion).
3. Confirm the effort estimate is acceptable for the value delivered.
4. Confirm the snapshot retention policy (§8.E).

Sign off below when reviewed:

- [ ] Open questions §8.A–J resolved
- [ ] Effort estimate accepted
- [ ] Preamble refactor (§12) — yes or no
- [ ] Author signoff

---
