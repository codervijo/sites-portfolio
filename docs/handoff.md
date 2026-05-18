# Handoff — sites/portfolio

You are a fresh Claude session picking up work on the `portfolio`
(a.k.a. `lamill`) CLI at `~/work/projects/sites/portfolio/`. This
document is the brief: where work stands, what's next, and the
non-obvious constraints already litigated.

## Read these first

Read these in this order before doing anything:

1. `AI_AGENTS.md` (repo root) — canonical orientation. **Read the
   `## Canonical docs` section first** (the five-doc model is new
   as of 2026-05-18; this is your map of where to look).
2. `docs/CLAUDE.md` — per-project Claude orientation:
   - `## Conventions` and `## Canonical docs — when to update which`
     are your "what to update where" reference.
   - `## ADR workflow` — when to write an ADR.
   - `## Heading hygiene` — pre-edit ritual for `.md` files. **Honor
     this for every Markdown file you touch.**
3. `docs/decisions/README.md` — the ADR index. Skim it; it tells you
   which load-bearing decisions are already recorded.
4. `docs/prd.md` § 6 (Versions) — tier-grouped phase log. Each
   `### vN` has `#### Phases` (status table) and (for unshipped
   tiers) `#### Design notes` (problem / goals / user journey /
   resolved opens / effort / approval).
5. `docs/architecture.md` — HOW the tool is built. Mechanisms,
   schemas, modules, CLI/UX, integrations, active implementation
   plans (per unshipped phase), risks. **Companion to prd.md** —
   any technical question about HOW lives here.
6. `docs/shipping-history.md` — archived rationale for shipped phases
   (v8.D's full detailed PRD is here as the worked example).

## Where the work is

**Project state:** 28 of ~75 phases shipped. Phase table now lives
tier-grouped under `docs/prd.md § 6. Versions` — render the current
truth with `/feature-table` if you have it.

**Last shipped (code):** `v12.A — adversarial audit prompt rendering`
(commit `1ecfebf`). Full test suite: 1672/0/1.

**Most recent docs work (2026-05-18 — completed this session):**

- `docs/architecture.md` populated from prd.md §8.2/§8.3/§8.4 — every
  section has real content; no more `(TBD)` placeholders. ~978 lines.
- `docs/prd.md` restructured to the 9-section model. Tier-grouped
  `### vN` headings under `## 6. Versions`, each with `#### Phases`
  and (for unshipped tiers v10/v11/v12) `#### Design notes`. The
  `## 8. Detailed PRDs` container is gone. ~696 lines (down from
  2691).
- Cross-ref sweep: stale `§8.2`/`§6.A`-style refs in architecture.md
  updated to point at the new doc + section.
- Tests green: 1672/0/1.

**Earlier doc-cleanup commits (2026-05-18 morning, before this
session):**

| Commit   | Subject |
|----------|---------|
| `95cb254` | docs — migrate v8.D detailed PRD to shipping-history.md |
| `2a32445` | v6.D — close fleet-wide heading-hygiene gap in bootstrap path (CHECK_043) |
| `885f997` | docs — adopt ADRs in docs/decisions/ (0001–0010 backfilled) |
| `2d7749b` | docs — establish three-canonical-doc model (architecture + shipping-history) |

Plus 17 sibling-repo commits propagating the Heading hygiene section
to every `sites/<domain>/docs/CLAUDE.md`.

**Next code phase:** `v12.B — adversarial audit response parser`.
Doc cleanup is now done; resume code work on v12.B.

## Next task in detail — v12.B: adversarial audit response parser

Spec lives in `docs/prd.md § 6 Versions → v12 → #### Phases (v12.B
row)` plus the audit-pass arc in `docs/prd.md § 6 Versions → v12 →
#### Design notes`. Cross-doc HOW lives in `docs/architecture.md
§ 3 Mechanisms (Research module)` + `§ 4 Schemas (data model:
ParsedAudit)` + `§ 9 Active implementation plans (v12.B onward)`.

**Goal.** Add `audit_pass.parse_audit(markdown) → ParsedAudit` +
`AuditParseError`. Parallel to v8.G's `parse_verdict` /
`VerdictParseError`. Schema is different:

- Required `### agreement_level` ∈ {full, partial, disagree}
- Required `### confidence` ∈ {HIGH, MEDIUM, LOW}
- Required `### specific_concerns` (≥1 bullet)
- Optional `### counter_verdict` (only present when
  `agreement_level == disagree`)
- Optional `### audit_self_check`

**Tolerances same as `parse_verdict`:** case-insensitive headers,
bullet markers (`-`, `*`, `+`, `N.`), trailing punctuation, leading
preamble. Different model styles → also accept `**foo:**`, `# foo`,
`## foo` as section headers.

**Where to write.** `src/portfolio/audit_pass.py`. Module already
exists (v8.J shipped `build_audit_payload`; v12.A shipped
`render_audit_prompt`). Add `ParsedAudit` dataclass next to those
helpers, then the parser, then the error class.

**Tests.** `tests/test_audit_pass.py` — start with the success cases
(full / partial / disagree), then add tolerance cases (case
variants, bullet markers, preamble), then add failure cases
(missing required section → `AuditParseError`, bad
`agreement_level` token → `AuditParseError`). Aim for ~15-20 tests
to match the v8.G parser's coverage.

**Effort estimate.** ~2h.

**Commit-message format.**

```
portfolio: v12.B — adversarial audit response parser

<2–5 short paragraphs. WHY this slice exists and what shipped.
Mention test count and prior commit refs.>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

## Hard constraints — read before editing

### Versioning (canonical: AI_AGENTS.md § Versioning; ADR-0004)

**Two levels only: `vN.X`.** Never `vN.X.Y`. Never `Phase N`. Never
colloquial "wedge"/"sub-phase". Multi-step work → more letters
(`v12.A`, `v12.B`, `v12.C`). No umbrella+sub-letter framing.

Enforced by `CHECK_013 ai-agents-references-versioning`. PRD rows
that violate are swept — don't reintroduce.

### Doc model (new 2026-05-18; ADR-0010)

**Five canonical doc surfaces.** Each has a specific update-when
trigger:

| Doc | Update when |
|---|---|
| `docs/prd.md` | Goals shift, phase planned/shipped, open question resolved, conformance rule changes |
| `docs/architecture.md` | Mechanism/schema/module change, new integration |
| `docs/shipping-history.md` | A phase ships → move design notes here (append-only) |
| `docs/decisions/` (ADRs) | A new load-bearing decision is made or reversed — write an ADR **in the same commit** |
| `docs/CLAUDE.md` | Claude-specific convention or locked target shape changes |

Plus `AI_AGENTS.md` (agent orientation) at root.

**Spec discipline rule:** reality + code + all five doc surfaces must
match. Stale docs are a conformance failure, not a backlog item. If
you change a mechanism, update `architecture.md` in the same commit.

### Heading hygiene (new 2026-05-18; CHECK_043; memory `feedback-md-heading-outline-first`)

**Before adding any heading to any `.md` file, grep the outline
first:**

```bash
grep -nE '^#+ ' path/to/file.md
```

Confirm in your reply that the planned new heading's depth and label
don't collide. Then write. This is enforced by CHECK_043 against
`docs/CLAUDE.md` specifically; the *principle* applies to all
long-lived `.md` files (`prd.md`, `architecture.md`, `AI_AGENTS.md`).

**Why this matters:** the entire doc cleanup work today was triggered
by `prd.md` accumulating four parallel `## 1. Problem statement`
headings at H2 depth (one per inlined detailed PRD). The pre-edit
ritual catches collisions at the point of writing.

### Fleet-wide changes go in the bootstrap template (memory `feedback-fleet-wide-changes-in-bootstrap`)

When adding a rule that applies across every `sites/<domain>/` repo:

1. Update `src/portfolio/templates.py` (the canonical template
   source).
2. Add a `*_section_*()` emitter so the `project fix` section-
   injection fixers can apply the change to existing drifted
   projects.
3. Add a `CHECK_xxx` to flag missing content + co-locate the Tier 1
   fixer.
4. Confirm `tests/test_template_path_passes_day_zero_catalog` still
   passes.

Don't propagate to existing projects without also updating the
template, or new bootstraps will silently regress.

### Two write surfaces only (ADR-0003)

- `new bootstrap <domain>` — creates new project dirs.
- `project fix <domain> --apply` — modifies existing dirs.

Everything else is read-only. Don't add a third write surface without
explicit operator direction.

### pnpm-only, Vite ≥6, Astro ≥5 (ADR-0008)

For `sites/*` projects only. `package-lock.json` / `bun.lockb` /
`yarn.lock` are conformance failures (CF Pages bun-detection trap).

### Don't commit destructively

- Never `--no-verify`, `--no-gpg-sign`, force-push, `reset --hard`,
  amend a pushed commit, or delete a branch without explicit
  instruction.
- Pre-commit hook failures mean **fix the issue and create a new
  commit** — never `--amend` past a hook failure.
- Stage files by name, not `git add -A` (avoids accidentally
  committing `.env` / runtime data / SerpAPI cache).
- Runtime data files (`data/serp/_quota.json`, `data/serp/<date>/`,
  `data/seo/<date>.json`, `data/checks/<date>.json`) are tracked but
  commit them as separate `data: refresh — ...` commits, not bundled
  with feature commits.

## Decisions made 2026-05-18 (this session)

Captured as ADRs (`docs/decisions/`) and via inline rule statements
in `docs/CLAUDE.md` / `AI_AGENTS.md`:

- **ADR-0001** Record architecture decisions (the meta-ADR).
- **ADR-0002** Python + uv for the portfolio CLI.
- **ADR-0003** Two write surfaces only.
- **ADR-0004** vN.X two-level versioning.
- **ADR-0005** File-per-check catalog.
- **ADR-0006** Tier 2 fixers as Claude subprocess.
- **ADR-0007** Audit pass uses different model family.
- **ADR-0008** pnpm-only for sites/*.
- **ADR-0009** Makefile forwards to central builder.
- **ADR-0010** Three-canonical-doc model + heading hygiene.

Also resolved (mid-design for v10.A; not yet captured in ADRs because
v10.A hasn't shipped):

- TOML writer library for v10.A: `tomli-w`.
- Bootstrap default platform: `cf-pages` (status quo).
- Inference priority on ambiguous deploy configs during v10.A
  migration: hit Vercel + CF Pages APIs to detect which owns the
  domain; fall back to interactive prompt on tie. (Not standard
  Nygard "refuse" recommendation.)
- `lamill.toml` includes a `dark_site` flag for members-only sites
  (memory `project-lamill-dark-sites`).

The remaining v10.A open questions (set-deploy auto-commit, schema
bumps, WordPress-without-repo, multi-deploy, account source for
bootstrap) are unresolved.

## Running things

```bash
# Tests
uv run pytest -q

# Targeted tests
uv run pytest tests/test_v12a_audit_prompt_rendering.py -v

# Render current feature table
/feature-table        # if the skill is available

# Heading-outline check on any doc
grep -nE '^#+ ' docs/prd.md
```

## Commit style

```
portfolio: v12.B — adversarial audit response parser

<2–5 short paragraphs. WHY this slice exists and what shipped.
Mention test count and prior commit refs where helpful.>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

For doc-only work, the subject prefix is `portfolio: docs —` rather
than a phase number.

Push after each shippable commit. Don't batch.

## End state for the next slice

After v12.B ships:

- `audit_pass.parse_audit(markdown) → ParsedAudit` lands in
  `src/portfolio/audit_pass.py` alongside the existing
  `build_audit_payload` (v8.J) + `render_audit_prompt` (v12.A).
- `AuditParseError` defined; raised on missing required section or
  bad enum token.
- `tests/test_audit_pass.py` covers success / tolerance / failure
  cases (~15-20 tests).
- `prd.md § 6 v12 #### Phases` v12.B row marked ✅; `prd.md` v12
  Design notes unchanged (still describes the unshipped audit arc;
  v12.C-G remain ⏳).
- `docs/shipping-history.md` gains a one-line `## v12.B · ... —
  shipped YYYY-MM-DD` entry (full design notes stay in prd.md until
  v12.G ships the whole audit arc).
- `uv run pytest -q` green; commit pushed.

After v12.B, the next slice is v12.C (audit-pass runner — orchestrates
build_audit_payload → render_audit_prompt → OpenAI chat-completions →
parse_audit). Same `audit_pass.py` module. ~3h.
