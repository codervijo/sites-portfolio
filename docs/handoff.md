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
4. `docs/prd.md` § 5 (Phases) — current state of every shippable
   slice with `✅ done` / `planned` markers.
5. `docs/architecture.md` — currently mostly TBD; will hold the HOW
   once the migration completes (one of your tasks).
6. `docs/shipping-history.md` — archived rationale for shipped phases
   (v8.D's full detailed PRD is here as the worked example).

## Where the work is

**Project state:** 28 of ~75 phases shipped. Phase table snapshot
lives in `docs/prd.md` § 5 — render the current truth with
`/feature-table` if you have it.

**Last shipped (code):** `v12.A — adversarial audit prompt rendering`
(commit `1ecfebf`). Full test suite: 1672/0/1.

**Most recent commits (docs cleanup, 2026-05-18):**

| Commit   | Subject |
|----------|---------|
| `95cb254` | docs — migrate v8.D detailed PRD to shipping-history.md |
| `2a32445` | v6.D — close fleet-wide heading-hygiene gap in bootstrap path (CHECK_043) |
| `885f997` | docs — adopt ADRs in docs/decisions/ (0001–0010 backfilled) |
| `2d7749b` | docs — establish three-canonical-doc model (architecture + shipping-history) |

Plus 17 sibling-repo commits propagating the Heading hygiene section
to every `sites/<domain>/docs/CLAUDE.md`.

**Next code phase (deferred from this session):** `v12.B — adversarial
audit response parser` — was the original handoff target but the
operator pivoted to doc cleanup first. Resume v12.B after doc cleanup
completes, or sooner if priorities shift.

## Next task in detail — continue doc cleanup

The doc cleanup is **partially done** as of 2026-05-18. Three tasks
remain:

### Task: populate `docs/architecture.md` from prd.md

`docs/architecture.md` was created as a skeleton with 11 sections, all
marked `(TBD)`. Your job: extract technical/implementation content
from the still-inlined detailed PRDs in `prd.md` § 8.2 / § 8.3 / § 8.4
and populate the matching architecture.md sections.

What moves and where:

| From `prd.md`                                          | To `architecture.md`                                     |
|--------------------------------------------------------|----------------------------------------------------------|
| § 8.2 (v8.E–v12.G) — functional requirements, data model, output rendering, implementation plans, risks | § 3 Mechanisms, § 4 Schemas, § 5 CLI/UX, § 9 Plans, § 10 Risks |
| § 8.3 (v10.A) — Schema, Platform enum, Parser module, CLI surface, Bootstrap defaults, Migration command, Data model, Implementation plan | § 4 Schemas (lamill.toml), § 5 CLI/UX, § 8 Module index, § 9 Plans |
| § 8.4 (v11.A) — Provider walkers, Table renderer, Dashboard integration, Data model, Implementation plan | § 3 Mechanisms (Provider walkers), § 4 Schemas (HostingRow + snapshot), § 9 Plans |

What stays in `prd.md` per detailed PRD (becomes the eventual `####
Design notes` for each unshipped phase): Problem statement, Goals (or
fold into top-level §2 Goals), User journey scenarios, Open questions,
Effort estimate, Approval. The technical content moves out.

Estimated reduction: prd.md shrinks by ~700–1000 more lines (currently
2691; target ~1700–2000 after this task).

### Task: restructure `docs/prd.md` to the new 9-section model

Current top-level structure (post-v8.D-migration):

```
## 1. Purpose
## 2. Audience
## 3. Goals & non-goals
## 4. Versions
## 5. Phases
## 6. Conformance rules
## 7. Open questions
## 8. Detailed PRDs       ← container; § 8.2 / § 8.3 / § 8.4 still inlined here
```

Target (agreed 2026-05-18):

```
## 1. Purpose
## 2. Goals & non-goals
## 3. Problem statement       ← NEW (extract from § 1 Purpose if needed; or write fresh)
## 4. Target user             ← merges in current § 2 Audience content
## 5. Spec discipline         ← NEW: reality + code + all five docs must match
## 6. Versions                ← merges current §4 Versions + §5 Phases; grouped by tier
   ### v1 — <theme>
      #### Phases
      | v1.A ✅ | <feature> |
      ...
   ### v8 — <theme>
      #### Phases
      #### Design notes        ← only for versions with unshipped phases
   ...
## 7. Conformance rules       ← was §6
## 8. Open questions          ← was §7
## 9. References              ← NEW: links to architecture.md, shipping-history.md, decisions/, AI_AGENTS.md
```

The `## 8. Detailed PRDs` container goes away entirely. § 8.2 / § 8.3 /
§ 8.4 design-notes content gets merged into the matching `### vN`
section's `#### Design notes` subsection. § 8.2's technical content
moved to architecture.md (previous task).

### Task: verify

After the two tasks above, run a final outline check + cross-ref
sanity pass:

- `grep -nE '^#+ ' docs/prd.md` → confirm 9 top-level `## N.`
  headings, no duplicates, no `## 1. Problem statement` at H2 depth
  anywhere (the v8.D drift case is the canary).
- Confirm `prd.md`'s in-prose references to "§ 8.A" / "§ 6.B" / etc.
  are updated to point at the right new doc + section.
- Confirm AI_AGENTS.md's `## Canonical docs` table still lists all
  five surfaces correctly.
- `uv run pytest -q` is green.

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

After the remaining three doc-cleanup tasks above:

- `prd.md` is ~1700–2000 lines, has 9 top-level sections, has no `##
  1. Problem statement` collisions at any depth.
- `architecture.md` has real content under every section (no more
  `(TBD)` placeholders).
- `shipping-history.md` has v8.D as the only filled entry (others
  remain TBD until those phases ship).
- All five canonical-doc surfaces are listed in AI_AGENTS.md and
  docs/CLAUDE.md, with update-when triggers documented.
- `uv run pytest -q` green; `git status` clean (or only runtime
  data); commits pushed.

Then update this file's "Where the work is" / "Next task in detail"
sections and resume code work on **v12.B — adversarial audit
response parser** per the original handoff (the v12.B brief lives in
git: see commit `2d7749b`'s parent or `git log -p docs/prd.md` for
the v12.B row's design notes).
