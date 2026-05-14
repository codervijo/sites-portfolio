---
prd: research-module-phase4
status: draft (awaiting review)
author: Vijo (drafted with Claude)
created: 2026-05-14
parent: docs/prd/research-module-v2.md
depends_on: Phases 1, 2, 3 of research-module-v2 must be shipped first
---

# Research module — Phase 4: standing prompt + adversarial audit

This PRD layers an **interpretive verdict pass** + an **adversarial audit
pass** on top of the mechanical Phase 1/2/3 stack (SerpAPI fetch →
gate classification → operator-profile filter). Goal: catch errors a
single LLM pass would miss by running two different model families
and surfacing disagreement instead of hiding it.

**Does not modify the mechanical gates.** They keep running first; this
phase consumes their output as input.

**No code is written by this PRD.** Open questions in §10 must be
resolved before commits.

---

## 1. Problem statement

**Current state (after research-v2 ships).** The mechanical gates
(Phase 1/2/3) produce a structured verdict — GO / NICHE-DOWN / NO-GO —
based on classifier rules and the operator profile. The rules are
deterministic, so the same SERP always produces the same verdict.

**What's missing.** Classifier rules catch known patterns but blow on
unknown ones. They can't reason qualitatively about edge cases:

- A SERP where 3 of the top 10 are programmatic-template URLs that
  *don't quite match* the v2 regex library — rules miss them, but a
  human reading the SERP titles would catch it
- Intent misclassification when the SERP looks informational on the
  surface but the SERP features (Local Pack, transactional snippets)
  show commercial intent
- The "KD trap" — keyword difficulty looks low, the rules say PASS,
  but the SERP is structurally owned by a programmatic competitor's
  template
- Moats that are unfalsifiable ("better content") passing the
  human-input gate because the user typed something

**What good looks like.** A primary LLM interpretive pass that reads
the same data the rules read PLUS the raw SERP results and offers a
qualitative verdict. A *different* LLM in adversarial mode that tries
to steel-man the opposite conclusion. Reconciliation logic that
**never hides disagreement** — when the models split, the operator
sees both and decides.

The empirical claim driving this: different model families have
different blind spots. Catching the disagreement is the signal.

---

## 2. Goals and non-goals

**Goals**

- Add a **primary interpretive pass** (Claude Sonnet, default) that
  consumes the mechanical gate output + raw SERP and produces a
  qualitative verdict with confidence rating.
- Add an **adversarial audit pass** using a *different* model
  (GPT-4o default, Gemini fallback) that steel-mans the opposite
  verdict.
- **Reconciliation surfaces disagreement** rather than auto-picking a
  winner. REVIEW_REQUIRED is a first-class verdict for the disagree
  case.
- **Opt-in cost.** Default is primary-only (Phase 4a). The audit
  pass (Phase 4b + 4c) is gated behind `--verify`.
- **Versioned prompts.** Both prompts live in `prompts/` (location
  TBD per Open Question §10.A), versioned (`_v1.md`, `_v2.md`, …),
  and snapshots record which version produced their verdict.
- **Both verdicts always cached.** Even if `--verify` was off,
  re-running on cached data with `--verify` produces an audit without
  re-fetching SERP.

**Non-goals**

- **Three-model consensus / N-way voting.** Two perspectives + honest
  disagreement is the point; adding a third dilutes the signal.
- **Auto-resolution of disagreement.** The PRD intentionally avoids
  any "if audit confidence > primary confidence, audit wins" rules —
  those manufacture false certainty.
- **Prompt-version A/B testing harness.** Versioning lets us track
  which prompt produced what, but comparing prompt versions empirically
  is a future feature.
- **Audit-only mode** (no primary, only adversarial). Audit's
  steel-man-the-opposite role doesn't make sense without a primary.

---

## 3. Where it sits in the pipeline

```
Phase 1: SerpAPI fetch
   ↓ raw SERP per cluster query
Phase 2: Gate classification
   ↓ Gate 1 + Gate 2 + Gate 3-pending
Phase 3: Operator profile filter
   ↓ operator-fit findings, possibly auto-fail Gate 2
─── new in Phase 4 ───────────────────────────
Phase 4a: Primary interpretive pass (Claude Sonnet)
   ↓ verdict + reasoning + confidence + moat-required + blind_spot_self_report
[if --verify:]
Phase 4b: Adversarial audit (GPT-4o)
   ↓ agreement_level + concerns + counter_verdict (if disagree)
Phase 4c: Reconciliation
   ↓ final verdict + confidence + caveats (or REVIEW_REQUIRED)
─────────────────────────────────────────────
   ↓
Output rendering
```

Both LLM passes consume:
- The mechanical gate output (typed dict — exactly what Phase 1/2/3
  emit)
- The raw top-10 organic results per cluster query (so the model can
  sanity-check classifications)
- The operator profile snapshot

Output from Phase 4a feeds Phase 4b (with one open question — whether
the audit sees the primary's `blind_spot_self_report` or is blind to
it; §10.C).

---

## 4. Functional requirements

### Phase 4a — Primary interpretive pass

**P4a.1** Standing prompt at `prompts/niche_evaluation_v1.md` (path
finalized in §10.A). System message; substituted with operator profile
fields at runtime.

**P4a.2** Model: Claude Sonnet (default model TBD by API availability
at build time — `claude-sonnet-4-7` or current). Override via `--model
<id>` flag. Anthropic API integration is new — see §8 implementation
risks.

**P4a.3** User message contains a structured payload:
```python
{
  "topic": str,
  "cluster_queries": list[str],
  "gates": {
    "gate_1_market": GateResult,
    "gate_2_serp": GateResult,
    "gate_3_moat": GateResult,  # status only — not yet user-input
  },
  "operator_fit": OperatorFitResult,
  "operator_profile_summary": str,  # rendered, not raw YAML/TOML
  "raw_top_10_per_query": list[dict],  # title, URL, domain only
  "serp_features_per_query": list[dict],
}
```

**P4a.4** Response is **markdown with strict headers** (not JSON mode):

```markdown
### verdict
GO | NICHE-DOWN | NO-GO

### confidence
HIGH | MEDIUM | LOW

### reasoning
[2-4 paragraphs]

### moat_required
true | false

### moat_prompt
[text shown to operator if moat needed]

### reductions
- [reduction 1]
- [reduction 2]
- [reduction 3]

### operator_fit_warnings
- [conflict 1 with operator profile]
- [conflict 2]

### blind_spot_self_report
[what the primary thinks it might be missing — feeds Phase 4b]
```

**Rationale for markdown over JSON mode:** Easier to evolve the
schema (add a section without breaking parse), more robust to model
variation (Claude Sonnet's JSON mode at temp=0 sometimes truncates;
markdown headers don't), and parseable with simple regex/section
splits.

**P4a.5** Parser splits the response on `### <header>` boundaries.
Required sections: verdict, confidence, reasoning. Missing optional
sections (e.g. `reductions` on a GO verdict) → empty.

**P4a.6** Substitution validator runs before any LLM call: any
`{{placeholder}}` left in the rendered prompt → raise (don't send a
broken prompt to the model).

**P4a.7** Snapshot captures both the rendered prompt AND the response
+ the prompt version + the model id. Reproducibility — old caches can
be re-rendered with their original prompt for audit/comparison.

### Phase 4b — Adversarial audit pass

**P4b.1** Standing prompt at `prompts/adversarial_audit_v1.md` (drafted
inline below in §6). System message.

**P4b.2** Model: **must be different** from the Phase 4a model.
Default: `gpt-4o`. Fallback: Gemini Pro. Override: `--audit-model <id>`.
The "different model" constraint is enforced — if `--model
claude-sonnet-4-7 --audit-model claude-sonnet-4-7` is passed, the tool
rejects with an error pointing at the correlated-blind-spot rationale.

**P4b.3** User message contains:
- The structured payload from P4a.3 (same input)
- The full Phase 4a markdown response (verbatim, not parsed)

Open Question §10.C: should the audit see the primary's
`blind_spot_self_report` section, or be hidden from it?

**P4b.4** Response is markdown with strict headers (mirror P4a.4):

```markdown
### agreement_level
full | partial | disagree

### confidence
HIGH | MEDIUM | LOW   (confidence in YOUR audit, not the primary's verdict)

### specific_concerns
- [concern 1: which failure mode + which data point supports it]
- [concern 2]
- ...

### counter_verdict
[only if agreement_level = disagree]
[GO | NICHE-DOWN | NO-GO]: [1-2 sentences why]

### audit_self_check
[1-2 sentences on what YOU might be wrong about]
```

**P4b.5** Same parser shape as Phase 4a. Strict on the three required
fields (`agreement_level`, `confidence`, `specific_concerns`),
permissive on optional sections.

### Phase 4c — Reconciliation (no LLM call)

Pure logic from the parsed Phase 4a + Phase 4b outputs:

```
IF audit.agreement_level == "full":
    final_verdict = primary.verdict
    final_confidence = min(primary.confidence, audit.confidence)
    note: "✓ Audit agrees ({audit_model}, {audit.confidence} confidence)"

IF audit.agreement_level == "partial":
    final_verdict = primary.verdict
    final_confidence = downgrade(primary.confidence)
        # HIGH → MEDIUM, MEDIUM → LOW, LOW → LOW
    note: "⚠ Audit raises {len(audit.specific_concerns)} concerns"
    caveats: audit.specific_concerns

IF audit.agreement_level == "disagree":
    final_verdict = "REVIEW_REQUIRED"
    primary_verdict_with_reasoning: shown
    counter_verdict_with_reasoning: shown
    note: "Models disagree. High-signal — read both and decide manually."
```

`REVIEW_REQUIRED` is added to the verdict vocabulary (alongside GO /
NICHE-DOWN / NO-GO). Snapshot includes both verdicts plus the
reconciliation outcome.

---

## 5. CLI surface + cost defaults

### Default (primary only)

```
lamill new research "ev charger installation cost"
```
- Runs Phase 1 (SerpAPI) → 2 (gates) → 3 (operator) → 4a (Sonnet primary)
- Output shows: gates + Sonnet verdict + reasoning
- Cost: ~$0.01-0.02 per run (one Sonnet call on ~3K-token payload)

### Verify mode (primary + audit)

```
lamill new research "ev charger installation cost" --verify
```
- Runs everything above PLUS Phase 4b (GPT-4o audit) + Phase 4c
- Output shows: gates + both verdicts + reconciliation outcome
- Cost: ~$0.05-0.10 per run (Sonnet + GPT-4o)

### Re-audit cached primary

```
lamill new research "ev charger installation cost" --verify --no-cache=audit
```
- Reads cached Phase 4a result, runs Phase 4b fresh, runs Phase 4c
- Useful when you ran without --verify, then decided you want the audit

### Other flags (inherited from v2)

- `--synthesis-only` — disables real SERP fetch. Phase 4a still runs
  but with explicit "[from LLM-only data]" tag in its reasoning.
- `--non-interactive` / `--json` — Gate 3 moat prompt skipped; same
  rules apply (verdict accounts for it as if FAIL).
- `--model <id>` — overrides primary
- `--audit-model <id>` — overrides audit; must differ from `--model`

### Documentation recommendation

A line in `lamill new research --help`:

> Use `--verify` when you're about to commit real time/money to a
> niche (week+ of work). Skip it for ideation rounds where 10 niches
> get screened quickly.

---

## 6. Drafted adversarial_audit_v1.md prompt (inline for review)

```markdown
# adversarial_audit_v1.md

You are an adversarial auditor of niche-evaluation verdicts. A primary
model has analyzed a SERP cluster and produced a verdict (GO / NICHE-
DOWN / NO-GO). Your job is to find errors and overlooked risks in that
verdict by steel-manning the OPPOSITE conclusion.

You are not a second opinion. You are a deliberate skeptic. Default
to disagreement when uncertain — the operator can dismiss a wrong
audit but cannot recover from a missed risk that ships.

Specifically check for these six failure modes. Reference specific
data points from the payload when raising any concern:

1. **INCUMBENT UNDER-DETECTION.** Did the primary miss a programmatic
   competitor? Scan the raw organic results for URL patterns
   (`/year/`, `/v[N]/`, `/state/`, `/city/`, `/model/`) the primary
   didn't classify as SPECIALTY_INCUMBENT. Are there domains ranking
   for 3+ queries with templated URL structures that the primary
   called POTENTIALLY_BEATABLE?

2. **INTENT MISCLASSIFICATION.** Did the primary tag a SERP as
   informational when it's actually commercial, or vice versa? Check
   the SERP features: AI Overview + People Also Ask = informational;
   Local Pack + multiple commercial-intent organic = transactional.

3. **KD-TRAP REASONING.** Did the primary conflate keyword difficulty
   (page-level metric) with SERP difficulty (incumbent-level metric)?
   A low-KD keyword can have a top-3 entirely owned by entrenched
   programmatic templates and still be unwinnable for a new site.

4. **OPERATOR-FIT UNDER-WEIGHTING.** Did the primary surface operator-
   profile conflicts as warnings but fail to weight them properly in
   the final verdict? Example: "operator lacks expertise" surfaced as
   a warning while the verdict remains GO — that's almost always a
   miss.

5. **TAM OVER-COUNTING.** Was pollution adjusted for? Are there
   cluster queries returning unrelated-industry results that inflate
   the topline volume? Recompute the pollution rate from the raw
   organic data when it looks off.

6. **MOAT UNFALSIFIABILITY.** If the primary says a moat exists, can
   it be tested in 30 days? "Better content" is unfalsifiable.
   "Faster data freshness than incumbent's static templates" is
   testable. Reject claimed moats that can't be put to a measurable
   test.

Return your audit in this exact markdown shape:

### agreement_level
[full | partial | disagree]

### confidence
[HIGH | MEDIUM | LOW]   — confidence in YOUR audit, not the primary's verdict

### specific_concerns
- [concern: which failure mode + which data point supports the concern]
- [concern: …]
- [concern: …]

### counter_verdict
[only present if agreement_level = disagree]
[GO | NICHE-DOWN | NO-GO]: [1-2 sentences why]

### audit_self_check
[1-2 sentences on what YOU might be wrong about]
```

That's ~310 words. Worth iterating on once we see a few real audits;
the version suffix (`_v1.md`) lets us evolve without breaking
reproducibility on old snapshots.

**niche_evaluation_v1.md draft** — outlined here, full draft in a
follow-up commit (P4.A.1). The skeleton:

> You are evaluating a SERP cluster for a personal portfolio operator
> deciding whether to ship a new site. Read the gate outputs (mechanical
> classification) AND the raw SERP results, and produce a qualitative
> verdict. The mechanical gates are usually right but miss edge cases —
> use the raw SERP to spot what the rules missed. The operator profile
> tells you who's reading: weight expertise + workflow + cadence
> constraints when deciding GO vs NICHE-DOWN vs NO-GO. Return verdict +
> reasoning + a self-reported list of what you might be wrong about
> (`blind_spot_self_report`) so the audit pass has something to attack.

Full draft in P4.A.1 alongside the audit prompt's review iteration.

---

## 7. Data model additions

Extends `data/serp/<YYYY-MM-DD>/clusters/<cluster-hash>.json` (schema
`research-cluster-v2` from v2 PRD) with new top-level fields:

```json
{
  "schema": "research-cluster-v2.1",
  ...existing v2 fields...

  "interpretive_pass": {
    "model": "claude-sonnet-4-7",
    "prompt_version": "niche_evaluation_v1",
    "rendered_prompt_hash": "<sha256-prefix>",
    "raw_response": "<full markdown response, verbatim>",
    "parsed": {
      "verdict": "NICHE-DOWN",
      "confidence": "MEDIUM",
      "reasoning": "...",
      "moat_required": true,
      "moat_prompt": "...",
      "reductions": ["...", "..."],
      "operator_fit_warnings": ["..."],
      "blind_spot_self_report": "..."
    }
  },

  "audit_pass": {
    "ran": true,                         // false if --verify was off
    "model": "gpt-4o",
    "prompt_version": "adversarial_audit_v1",
    "rendered_prompt_hash": "<sha256-prefix>",
    "raw_response": "<full markdown response, verbatim>",
    "parsed": {
      "agreement_level": "partial",
      "confidence": "MEDIUM",
      "specific_concerns": ["...", "..."],
      "counter_verdict": null,
      "audit_self_check": "..."
    }
  },

  "reconciliation": {
    "ran": true,
    "final_verdict": "NICHE-DOWN",
    "final_confidence": "LOW",           // downgraded from MEDIUM due to audit concerns
    "disagreement_surfaced": false,
    "review_required": false
  }
}
```

Schema bump v2 → v2.1 is additive (existing v2 readers ignore new
fields gracefully). Caches written by v2-only research still load
without re-fetch; they just don't have the interpretive_pass /
audit_pass fields.

---

## 8. Implementation risks (surfaced now to design around)

### 8.1 — Cross-provider API setup

Codebase is OpenAI-only today. Anthropic API is new:
- New env var `ANTHROPIC_API_KEY` in portfolio.env template
- Add to `apikeys.KNOWN_KEYS` + new `_probe_anthropic()` connectivity check
- Endpoint: `https://api.anthropic.com/v1/messages` (different shape
  from OpenAI's `/v1/responses`)
- Auth: `x-api-key` header + `anthropic-version` header (not Bearer
  token)
- Model availability: at build time, decide which Sonnet alias to
  default to (`claude-sonnet-4-7` per system prompt's current model
  knowledge, or whatever's current)

**The existing `run_claude()` subprocess wrapper (v6.C.1)** uses the
local Claude Code CLI, not the API. Not suitable for structured-output
verdict calls — wrong I/O shape, wrong cost model, wrong
reproducibility characteristics. Phase 4a needs a fresh
`anthropic_call()` HTTP wrapper.

### 8.2 — Rate-limit handling differs by provider

- OpenAI: `429` with `Retry-After` header
- Anthropic: `429` with `retry-after` (lowercase) + their own
  rate-limit-tokens header
- Gemini: yet another shape

Each needs its own retry-with-backoff. Recommend a small abstraction:

```python
class LLMClient(Protocol):
    def call(self, system: str, user: str) -> str: ...
```

with `AnthropicClient`, `OpenAIClient`, `GeminiClient`
implementations. Each handles its provider's rate-limit dialect.

### 8.3 — Cost surprise

Operator runs `--verify` then forgets it's on. Defensive:
- The `--verify` is **NOT** sticky — every invocation specifies it
  explicitly. No `--remember` shortcut.
- The output banner with `--verify` says "verify mode (Sonnet + GPT-4o,
  ~$0.05/run)" — visible cost per call.
- Optional but recommended: track cumulative spend in a small ledger
  at `data/serp/_cost_ledger.json` so operator can `lamill settings
  cost report` and see month-to-date.

The ledger is **out of scope for v2 of this PRD** — flagging here as
a future hardening pass.

### 8.4 — Response parsing across model styles

Different model families have different markdown habits:
- Claude tends to use proper `### header` consistently
- GPT-4o sometimes uses `**header:**` instead, or wraps in markdown
  fences, or adds a leading "Here's the analysis:" preamble
- Gemini's style is even less predictable

Parser must be permissive about format variation:
- Accept `### foo`, `**foo:**`, `# foo`, `## foo` as section headers
- Strip leading model preamble before parsing
- If a required section is missing, raise `AuditParseError` with the
  raw response stored — surface to the operator as "audit returned
  unparseable output; cached for inspection at <path>"

Test fixtures should include real-world malformed responses from
each model, captured during dev.

### 8.5 — Audit failure modes

- Audit API down → fail the audit pass, present primary-only with a
  clear "audit pass failed: <reason>" warning. **Don't fail the
  whole run.** The primary verdict is still valuable.
- Audit response is unparseable → same: surface as warning, fall back
  to primary-only.
- Audit hits a content-filter refusal → very rare for niche evaluation
  but possible (e.g., topic is a regulated industry). Surface
  explicitly: "audit refused; reason: <model output>." Fall back to
  primary.

In all three cases, the snapshot records `audit_pass.ran = true` but
sets `audit_pass.error = "..."` and `reconciliation.ran = false`.

### 8.6 — Markdown vs JSON mode tradeoff

Spec recommends markdown over JSON mode. Risks:
- Slightly harder to extract typed values (vs schema-validated JSON)
- More format flexibility = more parser code

Benefits per spec:
- Schema evolution is friendlier (add a section without breaking
  old parsers)
- Robust to model truncation (JSON truncation breaks everything;
  markdown truncation loses tail content but earlier sections still
  parse)

Standing call: **markdown for both passes.** Worth a re-eval if parser
maintenance becomes a burden — at which point introducing
`responses.parse` JSON mode is a small refactor.

### 8.7 — Prompt template substitution

Spec mentions Jinja2 or simple `{{var}}` substitution. Codebase has
neither. Options:

| Approach | Pros | Cons |
|---|---|---|
| Jinja2 | Powerful, conditionals possible | New dep |
| `str.format()` | Stdlib | Single `{` becomes a syntax error in code blocks; awkward for prompts with curly braces |
| Custom `{{var}}` regex | Stdlib, no curly-brace gotcha | New code to maintain |

Recommend **custom `{{var}}` substitution** — it's ~20 lines of
regex-based substitution, doesn't conflict with curly braces in
example code blocks within the prompt, and the validator (P4a.6) that
checks for unfilled `{{...}}` post-substitution doubles as a sanity
check.

---

## 9. Output rendering (target state)

### Default mode (no `--verify`)

```
SERP research — "ev charger installation cost"
  source: SerpAPI · 5 queries · primary: claude-sonnet-4-7

  [gate output from v2]

  Verdict: NICHE-DOWN (Sonnet, MEDIUM confidence)

  Reasoning:
    [2-4 paragraphs from primary]

  Suggested reductions:
    1. [from primary]
    2. [from primary]
    3. [from primary]

  Source: SerpAPI · prompt niche_evaluation_v1 · cached at <path>
  Run with --verify to add adversarial audit (~$0.05).
```

### Verify mode — audit fully agrees

```
  [gate output]

  Verdict: NICHE-DOWN
  ✓ Primary  (claude-sonnet-4-7, MEDIUM confidence)
  ✓ Audit    (gpt-4o, agrees, HIGH confidence)
  Final confidence: MEDIUM (lower of two)

  Reasoning:
    [from primary]

  Suggested reductions:
    [from primary]
```

### Verify mode — audit partially disagrees

```
  [gate output]

  Verdict: NICHE-DOWN
  ✓ Primary  (claude-sonnet-4-7, MEDIUM)
  ⚠ Audit raises 2 concerns (gpt-4o, MEDIUM):
     - "Primary missed Reddit presence in 2 cluster queries"
     - "Pollution from muscle-car SERPs may be larger than counted"
  Final confidence: LOW (downgraded from MEDIUM)

  Reasoning:
    [from primary]

  Caveats from audit:
    [each specific_concern]
```

### Verify mode — models disagree (high signal)

```
  [gate output]

  ⚠⚠ REVIEW REQUIRED — models disagree

  Primary (claude-sonnet-4-7, HIGH): NICHE-DOWN
    [reasoning]

  Audit (gpt-4o, HIGH): NO-GO
    [counter_verdict reasoning]

  This is a high-signal disagreement. Read both arguments and decide
  manually. Snapshot at <path>.
```

---

## 10. Open questions to resolve before implementation

### 10.A — Where do `prompts/` live?

Three options:
1. **`src/portfolio/prompts/`** — sits next to the Python package.
   Easy to ship via `pyproject.toml` package-data.
2. **`prompts/` at the repo root** — cleaner for editing,
   conceptually separate from "code."
3. **`data/prompts/`** — fits the existing `data/` pattern for
   non-code data.

**My recommendation: option 2 (`prompts/` at repo root).** Prompts
are data the user edits — having them top-level signals their
first-class status. Same pattern as `tests/` and `docs/`.

### 10.B — Audit model default

GPT-4o or Gemini Pro or operator's choice?

Per spec, GPT-4o is recommended default, Gemini fallback. Adding
Gemini support is its own integration (third provider HTTP wrapper,
third env var).

**My recommendation: GPT-4o default, no Gemini integration in v1.**
The "different model" constraint is met with two providers. Defer
Gemini to v2 of this PRD if GPT-4o proves to have a problematic blind
spot.

### 10.C — Does the audit see the primary's `blind_spot_self_report`?

The spec calls this out as a trade-off:
- **Blind to it** = more adversarial (audit has no shortcuts)
- **Sees it** = more efficient (audit doesn't waste time on issues
  the primary already flagged)

**My recommendation: blind to it.** The audit's value is uncovering
what the primary missed. Seeing the primary's self-report risks the
audit anchoring on the same concerns instead of finding new ones.

Snapshot still stores `blind_spot_self_report` from the primary — the
operator can read it separately. It just doesn't go into the audit's
context window.

### 10.D — `--verify` default-on in operator.yaml?

Should the operator be able to set `verify_by_default: true` in their
profile, so all research runs trigger audit unless `--no-verify` is
passed?

Pro: convenient for operators who always want the audit.
Con: cost-surprise risk — `lamill new research <topic>` doesn't look
like it costs $0.05.

**My recommendation: yes, but ONLY via operator.yaml** (not a sticky
state file). Operator-profile is configuration the user explicitly
edited; they're aware of cost.

Add `verify_by_default: false` (default) to `OperatorProfile` schema.
CLI `--verify` flag overrides to `true`; new `--no-verify` flag
overrides to `false`.

### 10.E — Audit failure handling

When the audit API call fails (network, rate limit, refusal,
unparseable response), three options:

1. **Fail the whole run.** Cleanest, no partial output.
2. **Proceed with primary-only.** Surface "audit pass failed:
   <reason>." Operator gets the primary verdict.
3. **Block the verdict but surface the primary's reasoning.** "We
   asked for verify, got primary-only data, but we won't render a
   final verdict; you have to retry the audit or run without
   --verify."

**My recommendation: option 2.** The primary is still valid signal.
Surface the audit failure as a prominent caveat, but don't waste the
primary's verdict.

### 10.F — Snapshot retention for audit pass

Same as primary (kept forever, git-tracked per v2 PRD §8.E)?

**My recommendation: yes.** No reason to treat audit differently.
Audit responses are part of the verdict's provenance.

### 10.G — Template-substitution engine

Per implementation risks §8.7 — Jinja2, `str.format()`, or custom
`{{var}}` regex?

**My recommendation: custom `{{var}}` regex** (no new dep, no curly-
brace gotcha in code-block examples).

### 10.H — `--model` and `--audit-model` flag override behavior

If operator passes `--model claude-sonnet-4-7 --audit-model
claude-sonnet-4-7`, behavior:

1. **Reject loudly** — error pointing at the correlated-blind-spot
   rationale.
2. **Reject and suggest** — error message includes a suggested
   different model.
3. **Allow with warning** — let the user override the
   different-model invariant; print a banner that the audit may have
   correlated blind spots.

**My recommendation: option 1 with a helpful suggestion in the
message.** The whole point of the audit is to use a different model.
Allowing same-model is a footgun.

### 10.I — Prompt versioning policy

When iterating on `niche_evaluation_v1.md`, when does it become
`_v2.md`?

**My recommendation:** bump to `_v2.md` for any change that would
*meaningfully alter the verdict on cached data*. Typo fixes, wording
clarifications, formatting tweaks don't bump. New failure-mode checks
or instruction-following changes DO bump.

Operationally: when a snapshot's `prompt_version` doesn't match the
current `_vN.md`, the snapshot's verdict is treated as "from old
prompt" and the operator can re-render via `--no-cache=interpretive`
to get a fresh verdict with the current prompt.

### 10.J — Snapshot field for cumulative cost tracking

Should each snapshot record the LLM call's estimated cost? Helpful
for the future cost-ledger feature (§8.3) but premature if we're not
building the ledger yet.

**My recommendation: yes, record it now.** Each snapshot adds:

```json
"interpretive_pass.estimated_cost_usd": 0.012,
"audit_pass.estimated_cost_usd": 0.043
```

Pulled from the provider's response headers when available; estimated
from input/output token counts otherwise. Cheap to add; lets a
future ledger feature aggregate without re-fetching.

---

## 11. Implementation plan (commits + smoke tests)

This builds on top of research-module-v2 (Phases 1-3 shipped). All
commits assume the v2 mechanical pipeline is in place.

### Preamble

**Commit Pre-1** — Create `prompts/` directory at repo root with a
README pointing at the schema convention (`<purpose>_v<N>.md`).

*Smoke:* `ls prompts/README.md` exists.

### Phase 4 setup

**Commit P4.A.1** — Draft `prompts/niche_evaluation_v1.md` (full
text). Document the schema header conventions and the substitution
syntax.

*Smoke:* Manual review of prompt text.

**Commit P4.A.2** — Draft `prompts/adversarial_audit_v1.md` (the
inline text from §6 above, finalized after operator review).

*Smoke:* Manual review.

**Commit P4.A.3** — `src/portfolio/prompt_loader.py`:
`load_prompt(name)`, `render_prompt(template, **vars)` with
`{{var}}` substitution + validator that raises on unfilled
placeholders. Unit tests.

*Smoke:* `pytest tests/test_prompt_loader.py -q`.

### Phase 4a — primary pass

**Commit P4.B.1** — `src/portfolio/llm_clients.py`: `LLMClient`
Protocol + `OpenAIClient` (extracts existing OpenAI HTTP from
`serp.py`) + `AnthropicClient` (new). Both honor per-provider
rate-limit dialects.

*Smoke:* `pytest tests/test_llm_clients.py -q` with mocked HTTP for
each provider's quirks.

**Commit P4.B.2** — Add `ANTHROPIC_API_KEY` to `apikeys.KNOWN_KEYS` +
portfolio.env template + `_probe_anthropic()` in `apikeys.py`.

*Smoke:* `lamill settings apikeys list` shows ANTHROPIC_API_KEY.

**Commit P4.B.3** — `src/portfolio/interpretive_pass.py`:
`run_primary_pass(cluster, gates, operator_profile) -> ParsedVerdict`.
Renders the prompt, calls Anthropic via the client, parses markdown
response.

*Smoke:* `pytest tests/test_interpretive_pass.py -q` with mocked
Anthropic responses.

**Commit P4.B.4** — Wire `interpretive_pass` into the research
orchestrator. Default mode now ends at Phase 4a. Snapshot schema
bumped to v2.1.

*Smoke:* `lamill new research "ev charger installation cost"` runs
end-to-end with primary verdict shown.

### Phase 4b — audit pass

**Commit P4.C.1** — `src/portfolio/audit_pass.py`:
`run_audit_pass(cluster, gates, operator_profile, primary_response)`.
Renders adversarial_audit_v1.md, calls OpenAI (different model from
primary), parses markdown response.

*Smoke:* `pytest tests/test_audit_pass.py -q`.

**Commit P4.C.2** — `same-model` rejection. If `--model` and
`--audit-model` resolve to the same model, error early.

*Smoke:* `lamill new research "x" --verify --model X --audit-model X`
errors with helpful message.

**Commit P4.C.3** — `--verify` flag wired. Output rendering for
agree / partial / disagree paths.

*Smoke:* Run on a cluster where primary and audit agree (verify
output shows "✓ Audit agrees"); run on a cluster known to provoke
partial disagreement (verify output shows audit concerns).

### Phase 4c — reconciliation

**Commit P4.D.1** — `src/portfolio/reconciliation.py`: pure-logic
reconciliation per §4 Phase 4c spec. No LLM calls. Unit tests for
each of the three branches (full/partial/disagree).

*Smoke:* `pytest tests/test_reconciliation.py -q`.

**Commit P4.D.2** — Wire reconciliation into orchestrator. Output
includes `final_verdict` field; REVIEW_REQUIRED renders correctly.

*Smoke:* `lamill new research "<known-disagreement-topic>" --verify`
emits REVIEW_REQUIRED banner.

### Phase 4 polish

**Commit P4.E.1** — Cost-estimate fields added to snapshot
(P4.A.10.J). Pulled from provider headers when present.

*Smoke:* Snapshot inspection shows non-zero `estimated_cost_usd`.

**Commit P4.E.2** — `operator.yaml.verify_by_default` honored.
`--no-verify` flag added for override.

*Smoke:* With `verify_by_default: true` in operator.yaml,
`lamill new research <x>` runs verify; `--no-verify` skips it.

**Commit P4.E.3** — `--no-cache=interpretive` and
`--no-cache=audit` granular flags for re-running individual passes
on cached SERP data.

*Smoke:* Run, modify cached snapshot's interpretive section, re-run
with `--no-cache=interpretive` — interpretive re-runs, SERP doesn't.

**Commit P4.F.1** — Documentation: update `docs/CLAUDE.md`,
`AI_AGENTS.md`, `docs/Prompts.md`, `docs/prd.md` to reflect Phase 4
shipped. Add "when to use --verify" guidance to `lamill new research
--help`.

*Smoke:* `lamill project check sites/portfolio` passes docs checks.

---

## 12. Effort estimate

Honest reading. Assumes v2 (research-module-v2.md) is shipped first.

| Phase | Commits | Hours | Key risk |
|---|---|---|---|
| Preamble | Pre-1, P4.A.1-3 | 2-3h | Prompt drafting iteration (the audit prompt especially needs review with real audit runs) |
| LLM clients + Anthropic | P4.B.1-2 | 4-5h | Anthropic API integration is new; rate-limit handling differs |
| Primary pass | P4.B.3-4 | 4-5h | Markdown parser robustness across model styles |
| Audit pass | P4.C.1-3 | 4-5h | Same-model rejection logic, output rendering for all three reconciliation branches |
| Reconciliation | P4.D.1-2 | 2-3h | Pure logic, but the rendering for REVIEW_REQUIRED needs to be right (it's the high-signal path) |
| Polish | P4.E.1-3 | 3-4h | Cost ledger field, verify_by_default plumbing, granular cache flags |
| Docs | P4.F.1 | 1h | |
| **Total** | **14 commits** | **20-26h** | |

That's on top of the **25-34h** for v2. Combined: **45-60h** for the
full v2+Phase4 stack.

Worth flagging: this estimate doesn't include the **iteration loop on
the prompts themselves**. After the first few real audit runs ship,
both prompts will likely need a v2 version informed by what worked /
didn't. That's separate from this PRD.

---

## 13. Future considerations (deferred, named only)

- Three-way audit (consensus from three different model families)
- A/B harness for comparing prompt versions empirically
- Audit-failure heuristics that auto-retry with a different audit model
- Per-snapshot cost-ledger view (`lamill settings cost report`)
- Operator-tunable confidence-downgrade rules (currently fixed:
  partial → -1 notch; spec might want this configurable later)
- Cache-aware `--verify` that runs only the audit if the primary is
  cached + still fresh
- Multilingual audit prompts (translated to operator's locale)

---

## 14. Approval

This PRD is **draft, awaiting review**. Before any code lands:

1. Resolve the 10 open questions in §10.
2. Review and approve the drafted `adversarial_audit_v1.md` prompt
   (§6 inline).
3. Confirm the effort estimate (20-26h on top of v2's 25-34h).
4. Confirm the prompt-versioning policy (§10.I).

Sign off:

- [ ] Open questions §10.A–J resolved
- [ ] Drafted audit prompt reviewed
- [ ] Effort estimate accepted
- [ ] Author signoff

---
