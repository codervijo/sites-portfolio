---
project: portfolio
prd_version: 1
project_version: v1.C
status: in-progress
owner: Vijo
last_updated: 2026-05-07
---

# portfolio — PRD

## 1. Purpose

`portfolio` is the **inventory + standards enforcer + production line** for the sites/ workspace. As the number of sibling projects under `sites/` grows, it becomes infeasible to remember per-project state, deploy quirks, build conventions, or where each one is in its lifecycle. portfolio is the single place to:

1. **Ask "what is the status of project X?"** and get an answer drawn from git, project docs (Prompts.md, prd.md), `data/portfolio.json`, live HTTP checks, GSC analytics, and (later) deploy verification.
2. **Detect and flag deviations from sites/* conventions** so the workspace stays uniform rather than drifting into N bespoke setups. portfolio's status output is a conformance report; gaps are surfaced and (from v4.D) optionally fixed.
3. **Manage the domain portfolio itself** — categorize, track expirations across multiple registrars (GoDaddy, Namecheap, Porkbun), cross-reference with Google Search Console.
4. **Find the right domain to register for any new idea** *(Power 1, v2)* — brainstorm SEO-quality candidates from a topic via OpenAI, score them, check availability via RDAP. Prevents bad registrations.
5. **Bootstrap a new commercial site to ship-ready state** *(Power 2, v3)* — given a registered domain + topic, scaffold the project at full conformance: stack (Astro/Vite/etc.) via the central builder, SEO baseline (sitemap/robots/OG/JSON-LD/favicon), deploy-target abstraction (Cloudflare Pages default, swappable), optional LLM-seeded content. The actual scaling lever for the 30-commercial-sites goal — turns "I have an idea" into "indexed live site" in under an hour.

## 2. Audience

Sole user: Vijo. No multi-tenancy, no permissions, no public surface. CLI-only.

## 3. Goals & non-goals

**Goals**:

- Single CLI surface for status, conformance, drift, and (later) remediation across all sites/* projects.
- Multi-registrar consolidation with normalization (GoDaddy, Namecheap, Porkbun).
- Skill-friendly JSON outputs for natural-language wrapping (v1.D ships the project-status skill).
- Read-only through v2 (domain suggest); v3 (bootstrap) and v4.D (remediation) are the two write surfaces. Write operations are explicit (always behind a confirmation or flag).
- Versioning convention canonicalized here, propagated to other sites/* projects opt-in.
- **Standard project scaffolding required across all sites/* projects** — `docs/`, `docs/prd.md`, `docs/Prompts.md`, `AI_AGENTS.md`, `README.md`, `.gitignore` — produced by the `/project-init` slash command and enforced via v2.A conformance rules. Single source of truth for spec/roadmap/conformance lives in each project's `docs/prd.md`; `AI_AGENTS.md` is the agent-orientation doc and references the PRD rather than duplicating it.

**Non-goals (intentionally never)**:

| Item | Why |
|---|---|
| Real SEO analytics (Ahrefs/SEMrush/Moz) | $$ APIs; manual remains best |
| Trademark search (USPTO) | manual at purchase time |
| Domain history (Wayback parsing) | niche |
| Social handle availability | different problem domain |
| Wide registrar API auto-sync | dropped — manual CSV exports cover it |
| ~~Live Porkbun pricing API~~ | reinstated 2026-05-02 — buying-side price is a critical decision criterion (≠ owned-domain valuation, which stays out of scope) |

## 4. Versions

| Version | Theme | Acceptance |
|---|---|---|
| **v1** | project status + multi-registrar inventory | `portfolio project status <name>` ships with full git pulse, Prompts.md parsing, deploy detection, live-site join, conformance reporting; multi-registrar CSVs consolidated; NLP skill wraps the JSON output |
| **v2** | acquisition — domain suggest *(Power 1)* | `portfolio domain suggest <topic>` with OpenAI brainstorm + SEO scoring + RDAP availability — high-ROI scaling lever |
| **v3** | bootstrap — ship-ready scaffold *(Power 2)* | `portfolio bootstrap <domain>` creates a sites/* project at full conformance: git init, Astro/Vite (or other) stack scaffold via the central builder, SEO baseline pack, deploy-target abstraction (CF Pages default), optional LLM content seed — the production line for the 17-site gap |
| **v4** | validation pipeline + launcher *(Power 1 refined)* | Validation-mode `domain suggest` (vocab anchor + grid + decide), shortlist/finalists workflow, ask AI / widen / Brave→AI collision check, interactive top-level launcher menu — the "I have an idea, find me a domain to validate it" pipeline complete |
| **v5** | universal check catalog + check flags | File-per-check registry under `src/portfolio/checks/`; ~85-check canonical catalog covering scaffold/git/stack/deploy/SEO/live; `check --git` and `check --seo` flags; `project status` refactored onto the registry; `bootstrap` post-summary uses it; content-pipeline (hybridautopart-pattern) checks. Absorbs the old v6 (GSC integration as auth/list/sync) and old v7 (stack detection + scaffold completeness). |
| **v6** | drift + per-stack + remediation *(was v8 pre-2026-05-09)* | plan-drift signal, dir↔domain mapping, per-stack rules (pnpm-lockfile-only, etc.); v6.D's `portfolio project fix <name>` is the second project-dir write surface for retro-fixing pre-bootstrap projects |
| **v7** | fleet operations layer ✅ | Scope-first CLI restructure (`project` / `fleet` / `new` / `settings`); unified `fleet dashboard` (live + SEO + git); age tracking (launched + RDAP); fleet focus + SEO grading age-aware so young sites read green; `fleet repos` audit + naming-consistency cluster (CHECK_040/041/042); `project diagnose <domain>` auto-investigation; tool renamed `portfolio` → `lamill`. All seven sub-phases shipped 2026-05-10 → 2026-05-13. |
| **v8** | SERP research for new projects ✅ *(new 2026-05-13)* | `lamill new research <topic>` — AI-only SERP synthesis (gpt-4o-mini), default cluster mode (LLM expands topic into 3-5 related queries with frequency-tagged rankers), `--strict` for literal-topic-only. Closes the gap between domain-availability (v2) and bootstrap (v3): is this topic viable, what's the angle, what's the keyword cluster worth chasing. Integration with `new suggest` was deliberately dropped (v8.C) — research and suggest stay as separate composable steps. |
| **v9** | per-site deploy declarations *(renumbered 2026-05-16; was v11)* | `lamill.toml` at each `sites/<domain>/` root declaring deploy target; drift detection; HostGator cPanel integration; SFTP deploy abstraction. Foundation for multi-host fleet ops. |
| **v10** | fleet hosting view *(renumbered 2026-05-16; was v12.A)* | `lamill fleet hosting` — fleet-wide Vercel/CF deploy state. Walks both APIs; matches projects to fleet domains by configured custom domain. Per-site deploy status + last-success-at + consecutive-failures, cached snapshot. |
| **v11** | analytical roll-ups *(renumbered 2026-05-16; was v9)* | GSC trend correlation over PERSISTED snapshots (week-over-week deltas); `project list` aggregate verdict-counts view; optional LLM content seeding (still postponed indefinitely). All read-only / informational. |
| **v12** | deploy verification *(renumbered 2026-05-16, deprioritized; was v10)* | build-time stamping convention + HEAD vs deployed SHA + Pages/Vercel API integration. Heavy overlap with v10's `fleet hosting`; revisit scope when this tier's slot comes up. |

## 5. Phases

Strict sequence (option a). **Renumbered 2026-05-16** — v9 is now per-site deploy declarations (was v11), v10 is fleet hosting (was v12), v11 is analytical roll-ups (was v9), v12 is deploy verification (was v10; deprioritized to last). **v8.E split 2026-05-17** into v8.E–v8.M (see note below). Working order = strict numerical: v8.I → v8.J → v8.K → v8.L → v8.M → v9.A–D → v10.A → v11.A–C → v12.A–D. **v8.D shipped in full as of 2026-05-15. v8.E–v8.H shipped 2026-05-16/17 (payload builder, prompt renderer, response parser, primary-pass runner — all the data-path primitives for the interpretive verdict). v8.I is the active queue: wire the primary pass into `new research`'s orchestrator + persist the verdict in the cluster snapshot — first user-visible v8.E-series output.** v8.A and v8.B were absorbed by v8.D before any code was written; v8.C was originally a `--research` flag on `new suggest`, dismissed as not needed (research and suggest stay as separate composable steps).

Note on read/write surfaces: portfolio is **read-only** through v2 (domain suggest). **v3 (bootstrap) is the first write surface** — it creates new project dirs, runs `git init`, scaffolds files. **v4 is read-only** (validation-mode domain suggest only prints info and a manual-checkout URL — domain registration is gated behind a Y/n confirmation that calls Porkbun's `/domain/create`; no project-dir writes). **v5 is read-only** (universal check catalog + check flags; v5.D writes only to OAuth token + `data/gsc/` snapshots, not project dirs). **v6.D (remediation) is the second project-dir write surface** — it modifies existing project dirs to fix conformance gaps. **v8.D (domain-list refresh tooling)** writes to `data/domains/*.csv` + `data/portfolio.json` (already user-mutable), not project dirs. Everything else (v6.A–C, v6.E–G, v7, v8.A–C) is read-only.

Note on the v2/v3/v6 reorder (2026-05-02):

- Domain-suggest (Power 1) moved from v3 → v2 — high ROI for the 30-commercial-sites goal: picking the right domain at registration time prevents bad investments.
- Bootstrap (Power 2) added as v3 — the actual scaling lever; turns "I have an idea" → "live commercial site" in under an hour.
- Original v2 (conformance + remediation) → v4. Original v4 (GSC + roll-up) → v5. Original v5 (deploy verification) → v6.
- Rationale: both scaling levers up front; conformance polish and post-deploy verification later.

Note on the v3/v4/v5 reorder (2026-05-07):

- Validation-mode suggest (the v3.F brainstorm) promoted to v3.D — primary scaling lever for the validation pipeline. (Initially landed at v3.E; renumbered to v3.D to close the gap left by the LLM-seeding move.)
- Interactive launcher (was v3.E) deferred to v4.A — UX polish, not a throughput lever.
- Stack detection / drift / per-stack / remediation cascade one letter (v4.A→B, v4.B→C, v4.C→D, v4.D→E).
- Optional LLM content seeding (was v3.D, postponed) moved to v5.A. Existing v5.A (GSC trend) → v5.B; v5.B (roll-up) → v5.C.
- Rationale: get validation-mode suggest in front of the launcher; both LLM-content seeding and GSC are post-validation work.

Note on the v3.E addition (2026-05-08):

- v3.E added: validation-mode polishing pass (post-grid menu UX + ask AI + widen + panel/decide). Same `domain suggest` command, restructured interactive surface. Phase total bumped 23 → 24.
- Rationale: v3.D shipped the validation pipeline; real-world use surfaced UX friction (too many inline picker commands, no way to ask AI about names, no shortlist comparison flow). v3.E folds those polish items into a single phase rather than scattering them across v3.D.* sub-points.

Note on v3-complete + v4.A reshuffle (2026-05-08):

- v3.E declared complete with the menu UX + 3-layer porn screen + TLD reference card shipped. The four sub-features that were stubbed in v3.E's menu (ask AI, widen, mark+decide aka *finalists*) are too substantial to call "polish" — they move out of v3 entirely.
- New **v4.A: validation-suggest extensions** holds those four sub-features (with finalists as the headline). Existing v4 cascades by one: launcher v4.A→v4.B, stack-detect v4.B→v4.C, drift v4.C→v4.D, per-stack v4.D→v4.E, remediation v4.E→v4.F. Phase total 24 → 25.
- Menu in code drops the stubbed items 3/4/6/7; v3.E ships with menu items 1, 2, 5, 8 only. When v4.A lands, those slots fill with finalists / ask AI / widen.
- Rationale: "v3 complete" gives a clean shipping marker. The deferred features are real work, not polish; v4.A treats them as a deliberate phase. Launcher remains the second v4 priority.

Note on v4 split (2026-05-08, same day):

- The combined "validation-suggest extensions" v4.A split into three discrete phases ordered by user workflow priority: **v4.A: Mark/unmark shortlist**, **v4.B: Decide from shortlist**, **v4.C: Widen search + ask AI**. Each is small enough to ship independently and review in isolation.
- Cascading consequences: launcher v4.B→v4.D, stack-detect v4.C→v4.E, drift v4.D→v4.F, per-stack v4.E→v4.G, remediation v4.F→v4.H. Phase total 25 → 27.
- Rationale: shortlist is the headline workflow improvement (compare candidates side-by-side, decide deliberately). Widen + ask AI are useful but secondary — if shortlist + decide land, you have most of the value already. Splitting also lets the launcher slip later without blocking the validation-pipeline work.

Note on v4-complete + shift-right (2026-05-08, evening):

- v4 declared complete with v4.A–v4.D shipped. The four sub-phases that were originally bundled under v4 (stack detection, drift+mapping, per-stack rules, remediation) are conceptually a separate milestone — conformance enforcement is its own arc, distinct from the validation-pipeline work that became the actual v4.
- **Shift right by one major version**: old v4.E → v5.A, v4.F → v5.B, v4.G → v5.C, v4.H → v5.D. Old v5.A (LLM seed, postponed) → v6.A. Old v5.B (GSC) → v6.B. Old v5.C (roll-up) → v6.C. Old v6.A → v7.A, v6.B → v7.B, v6.C → v7.C. Phase total stays 27 (renumbering only).
- v4 theme renamed from "conformance + drift + stack + remediation" → "validation pipeline + launcher (Power 1 refined)" to match what actually shipped.
- Read/write surface note updated: second write surface is now v5.D (was v4.H).
- Rationale: clean shipping marker (v4 complete = "I have an idea → find a domain to validate it" pipeline ships). Conformance/drift/stack/remediation become v5 — read-side enforcer phases that work against existing sites/* projects, distinct from the v3 (build) and v4 (acquire) write/read surfaces.

Note on v5 = stack detection only (2026-05-08, late):

- v5 narrowed to just stack detection + scaffold completeness (v5.A). The remaining items (drift + per-stack + remediation) shift right into v6.
- **Second shift right**: old v5.B → v6.A (drift + mapping), v5.C → v6.B (per-stack rules), v5.D → v6.C (remediation, write surface). Old v6.A (LLM seed, postponed) → v7.A. Old v6.B (GSC) → v7.B. Old v6.C (roll-up) → v7.C. Old v7.A → v8.A. Old v7.B → v8.B. Old v7.C → v8.C. Phase total stays 27.
- v5 theme: "stack detection + scaffold completeness". v6 theme: "drift + per-stack + remediation". v7 theme: "live correlation + roll-up". v8 theme: "deploy verification".
- Read/write surface note: second write surface is now v6.C (was v5.D).
- Rationale: stack detection is its own discrete piece of work and the natural next ship; bundling it with drift + per-stack + remediation under one milestone obscures the natural shipping boundary. Splitting gives each its own version marker.

Note on third shift right (2026-05-08, latest):

- Real use of `portfolio project status` after `bootstrap` surfaced behavior gaps that need a dedicated fix-up phase. Inserting a NEW v5 = "project status check improvements". Existing v5-v8 shift right by one major.
- Then a second shift: NEW v6 = "Google Search Console integration" — formalizes the GSC tooling (auth/list/sync/compare commands partly shipped already) into a dedicated milestone. Existing v6-v9 shift right by one more major.
- Cascade summary:
    - Old v5 (stack detection)              → New v7
    - Old v6 (drift + per-stack + remediation) → New v8
    - Old v7 (LLM seed + GSC trend + roll-up)  → New v9
    - Old v8 (deploy verification)             → New v10
- v9.B (GSC trend correlation, formerly v7.B) is intentionally distinct from new v6: v6 is *integration* (auth, sync, list — the I/O layer); v9.B is the *analytical* trend layer on top of the synced data.
- Phase total 27 → 29 (two new placeholders v5.A and v6.A; sub-phases TBD).
- Rationale: a real-world bug in `project status` is its own ship (v5); GSC integration is a sufficiently large piece to deserve its own milestone (v6). Both move ahead of the conformance-enforcement work which is now further out.

Note on catalog absorption + fourth shift left (2026-05-09):

- After the catalog brainstorm produced ~85 numbered checks (`CHECK_001`+) covering scaffold, git, stack, deploy, SEO assets/meta, live HTTP, GSC, CrUX, and content-pipeline, several previously-discrete milestones got pulled into v5:
    - Old v6 (Google Search Console integration as auth/list/sync) → folded into **v5.D** (`check --seo` uses GSC OAuth + CrUX runtime).
    - Old v7 (Stack detection + scaffold completeness) → folded into **v5.A** (scaffold rules) + **v5.C** (stack rules) of the catalog.
- v5 sub-phases now: v5.A catalog foundation + scaffold/git checks · v5.B `check --git` command · v5.C stack/deploy/SEO-asset/SEO-meta checks · v5.D `check --seo` (live HTTP + GSC + CrUX) · v5.E refactor `project status` onto the registry · v5.F content-pipeline checks.
- Major-version cascade (shift LEFT this time): old v8 → v6, v9 → v7, v10 → v8. Two majors retired.
- New work added at v8.D: "domain-list refresh tooling" (flag-only changes to `cleanup` — no new commands) — last-priority polish on the existing `cleanup`/`portfolio.json` flow.
- Phase total 29 → 33 (catalog work expanded v5 from 1 to 6 sub-phases; +1 v8.D).
- Rationale: the catalog is the structural hub for v5–v8 conformance/SEO/git surfaces; standalone "GSC integration" and "stack detection" don't justify their own majors once the catalog handles them. Keeping the cleanup loop tweaks (v8.D) at the back of the queue per user direction ("getting too complicated already").

Note on v7 expansion (2026-05-13):

- v7 was originally three small phases (CLI restructure + GSC trends + roll-up). It grew into a much larger fleet-operations cluster as 2026-05-10 through 2026-05-13 shipped seven discrete features that all fit "operate the fleet" rather than "build new things":
    - **v7.A** ✅ CLI restructure (already shipped; unchanged)
    - **v7.B** ✅ `fleet dashboard` — unified live + SEO + git view
    - **v7.C** ✅ Age tracking (launched + RDAP)
    - **v7.D** ✅ Fleet focus enhancements + P4 age-aware SEO grading
    - **v7.E** ✅ `fleet repos` audit + naming-consistency cluster (CHECK_040/041/042) + archived state
    - **v7.F** ✅ `project diagnose <domain>` — five-layer auto-investigate
    - **v7.G** ✅ Tool rename: `portfolio` → `lamill` (light; package stays `portfolio` internally)
- Previously-deferred work shifted to v7.H/I/J: GSC trend correlation (was v7.B), roll-up (was v7.C), LLM content seeding (was v7.D, still indefinitely postponed).
- Phase total 33 → 40 (+7 new v7 sub-phases).
- Rationale: each new sub-phase delivered a distinct user-facing surface and merits its own row in the version map. Grouping them under v7.A as "follow-ups" would have made it impossible to refer to e.g. "v7.E archived support" cleanly in commit messages and prompts.

Note on v8 insertion (2026-05-13 PM):

- SERP-research feature designed during the post-v7.G planning session. Inserted as new **v8** (3 sub-phases) because it sits naturally between v3 (bootstrap) and the analytical layers — answers "should I ship this site?" before bootstrap commits real resources.
- v7.H/I/J pushed down to **v9.A/B/C** (analytical roll-ups: GSC trends, project roll-up, LLM seeding-still-postponed). None of these had started yet, so the renumber is cheap.
- Old v8 (deploy verification, 4 sub-phases) pushed down to **v10.A–D**. Also unstarted.
- Phase total 40 → 41 (+1 net — SERP research adds 3 sub-phases, deploy verification reduces from 4 to 4 unchanged; v9 absorbs 3 unchanged).
- Rationale: v8 SERP closes the gap between "pick a domain" (v2) and "ship a site" (v3) — without SERP intel, the bootstrap decision is half-blind. Promoting it ahead of analytical-layer work matches the user's daily-priority order (acquisition > analytics).

Note on v8.E split (2026-05-17):

- The original **v8.E** row covered an umbrella "Phase 4" feature: primary interpretive pass (Claude) + adversarial audit pass (GPT-4o) + reconciliation + polish + docs. As implementation got underway, each shippable slice landed as its own commit — and the umbrella row hid that structure. Worse, the in-flight commits started carrying internal "sub-phase" labels ("wedge 4 of 5", colloquial sub-numbering) which is exactly the `vN.X.Y` violation the canonical rule forbids. **Operator-direction 2026-05-17**: if a phase needs multiple steps, each step gets its own letter — no umbrella + sub-step framing.
- Original **v8.E** is now split into **v8.E–v8.M** (9 rows). E–H ✅ already shipped (the four data-path primitives commits — `a6b6c95`, `1287e91`, `febf82e`, `977c5af`); I–M planned (wiring, audit pass, reconciliation, polish, docs).
- Going forward, the same rule applies to every tier. No `vN.X` row in the table covers >1 shippable commit. Multi-commit work → multiple letters.
- Rationale: keeps the phase table 1:1 with the actual ship cadence; makes commit subjects honest (`portfolio: v8.H — primary interpretive pass runner` not `portfolio: v8.E — runner [wedge 4 of 5]`); preserves the canonical two-level rule in the only place it really matters — the readable history.

Note on v7.H addition (2026-05-16):

- New **v7.H** added to capture the GSC sitemap health + dark-site detection + Cloudflare edge-cache check (`CHECK_057`) work that landed while triaging donready.xyz's "Sitemap could not be read" GSC report. The v7.H/I/J slots had been vacated by the v8 insertion (2026-05-13 PM) so the slot reuse is clean — no further renumber. v8 onward unchanged.
- Phase total 41 → 42.
- Rationale: the work is unambiguously fleet-ops (new check + tier-1 fix + `settings cloudflare {token,status}` command + fleet-focus signal + `check --seo` surface refinements). Same arc as v7.B–v7.F. Splitting into multiple sub-phases would have meant landing as separate commits, but they shipped together as one coherent debugging-driven feature.

| Phase | Theme | Features |
|---|---|---|
| **v1.A** ✅ | Skeleton + repo-isolation gate | `portfolio project status <name>` subcommand · fuzzy resolver against plan.md · `--json` schema_version=1 · C1 own-git-repo gate · last commit (sha, subject, age, author) · binary verdict (Misconfigured / Active) |
| **v1.B** ✅ | Full git pulse + Prompts.md + deploy-detect + live | activity rate (7d/30d) · branch + clean/dirty · uncommitted count · last Prompts.md entry (dated-H2 parser) · plan category · full verdict ladder (Active / Quiet / Stalled / Dormant / Fresh / Misconfigured) · C2 in-plan-md · C3 has-prompts-md · C4 prompts-md-format · C5 has-makefile · C6 has-ai-agents-md · deploy-platform detection (cloudflare / vercel / netlify / unknown / n/a) via filesystem markers · live-site HTTP class joined from `data/checks/` · platform-declared + live-site conformance · rich TTY view |
| **v1.C** ✅ | Registrar consolidation | `data/domains/{godaddy,namecheap,porkbun}.csv` · 3 adapters with format normalization (3 date formats; auto-renew yes/no/ON/OFF) · Porkbun disclaimer-line skip · `Domain` schema gains `registrar` (required), `privacy`, `transfer_locked` · `domain_to_registrar()` shared lookup · `summary` warns on missing renewal_price · Porkbun rows excluded from value rollups (low-value TLDs) |
| **v1.D** ✅ | Cleanup + classification migration (plan.md → portfolio.json) | `portfolio cleanup` subcommand · reads raw registrar CSVs + plan.md · writes `data/portfolio.json` (single canonical record per domain: name, registrar, category, expires, created, auto_renew, renewal_price, estimated_value, privacy, transfer_locked, nameservers, forwarding_url, raw passthrough for forensics) · auto-classification rules: Namecheap rows → "Under build", Porkbun rows → "Under build", GoDaddy rows → plan.md category (or warn if uncategorized) · `load_domains()` pivots to read from `portfolio.json` after cleanup · `load_plan()` is removed (categories now come from `domain.category` directly) · plan.md gets a deprecation comment in v1.D; actual file deletion happens in a later cleanup commit · drift output surfaces uncategorized domains as warnings · resolver in `project status` continues to fuzzy-match, just against `portfolio.json` keys instead of plan.md · typo / fuzzy-similar-name detection deferred to v8.A |
| **v1.E** ✅ | NLP skill | `~/.claude/skills/project-status/SKILL.md` (global; works from any cwd) — routes natural-language questions like "what's the status of iotnews" → `make run ARGS="project status <name> --json"` → short prose answer (1-line headline + up to 3 contextual bullets). Disambiguation: lists `candidates` and asks the user. Read-only by design; defers fixes to v8.C and cross-project roll-up to v9.C. |
| **v1.F** ✅ | Parked-detection accuracy | extend `check.py` `_classify()` with body-content inspection: detect GoDaddy in-line parking (sub-1KB body containing `window.location.href = "/lander"` or similar JS redirect to `/lander` / `/landing` / `/sale` / `/park`) and reclassify from spurious `live-site` → `parked` with reason `js-redirect-to-parking-page` · capture truncated body excerpt in `CheckResult` so future re-classifications run offline against the snapshot · re-run `check --only all` to refresh the 53-domain dataset · `summary` and `project status` now reflect reality for parked GoDaddy domains (newiniot.com etc.) |
| **v2.A** | Multi-strategy brainstorm + score + already-own *(Power 1 — find the right domain)* | `portfolio domain suggest <topic>` interactive subcommand · OpenAI `gpt-5-mini` brainstorm, looped through configurable naming **strategies** (5 default: trendy / dev-technical / benefit-driven / metaphor / abstract-brandable; extensible via config) · per-strategy: ~12 candidates → strict gen rules (≤12 chars, no hyphens, brandable, easy to say) → SEO-weighted scoring (TLD tier · length · keyword presence · hyphen/digit penalty) → top-5 sorted · `history` deduplication so subsequent strategies don't repeat names · already-own intersection against `data/portfolio.json` (depends on v1.C) — surface owned matches *before* generating new ones · 7-day caching by `topic-hash` in `data/cache/suggest/` so iterating on the same idea is cheap · `--non-interactive` flag dumps ranked candidates for piping; default is interactive (per-strategy round → user picks / moves on / types custom) |
| **v2.B** | Availability + **price** via Porkbun (RDAP fallback) | Porkbun `domain/checkAvailability` API by default if `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` env vars present (returns availability **and price** in one call — both are buying-side decision criteria) · RDAP fallback when Porkbun keys unset (availability only, no price) · TLD ladder per the SEO tier config: `.com / .ai / .io / .app / .dev / .co` default; `--tlds=` overrides · stop-at-first-available-TLD per name to keep round time manageable · rate-limited (~3/sec, matching script convention) · per-TLD endpoint cache · **`--max-price=$N` filter** so premium-priced names get excluded — user explicitly does not want to overpay at registration time · output column shape per round: `name · TLD · avail · price · score` |
| **v3.A** ✅ | Bootstrap — scaffold a new project *(Power 2 — ship-ready scaffold)* | `portfolio bootstrap <domain>` typer command with three paths: **(1) template**: empty target → writes minimal Astro (default) or `--stack=vite` (React+JSX) scaffold; **(2) `--from-genai`**: target dir + `genai/` subdir exist → copies `genai/*` to project root and applies CF Pages safety fixes (Vite ≥6 bump, `_redirects` removal, `wrangler.toml` add); **(3) `--git-url=<url>`**: clones URL into `genai/` then proceeds as `--from-genai`. All paths write standard scaffolding (AI_AGENTS with Building/Deployment, docs/prd.md, docs/Prompts.md, README, .gitignore, local `Makefile` that includes `BUILDER_PATH=../../builder`) and run `git init` + initial commit. `--with-ingester` adds `scripts/ingest.py` template. `--topic` injects into AI_AGENTS + PRD. Filesystem-only by default (genai+template paths); `--git-url` is the only network-touching path. |
| **v3.B** ✅ | SEO baseline pack | meta-tag template (title, description, canonical, OG, Twitter card) injected stack-aware into `index.html` (Vite) and `src/pages/index.astro` (Astro); JSON-LD structured data (Organization + WebSite with @id graph); favicon SVG monogram from domain initial (deterministic color from a 12-color palette, hash-picked per domain); `public/robots.txt`; `public/sitemap.xml` stub. **v3.B.2 (2026-05-04):** sitemap-generation: Vite path adds `scripts/generate-sitemap.mjs` (post-build dist/-scan, no deps) and chains it into the `build` script; Astro path adds `@astrojs/sitemap` integration to `astro.config.mjs` with `site` URL set. Technical-SEO regression check: `src/__tests__/seo.test.js` asserts the v3.B baseline (title, meta description, canonical, OG, Twitter card, favicon link, JSON-LD Organization + WebSite); both stacks get a `test:seo` npm script wired up. |
| **v3.C** ✅ | Deploy abstraction + Cloudflare Pages impl | `DeployTarget` Protocol (provider-agnostic: `verify_local_config` / `create_github_repo` / `create_project`); `CloudflarePagesDeploy` concrete impl. `portfolio deploy <domain>` CLI: verifies the local config (wrangler.jsonc, public/_headers, package.json build script, pnpm-lock.yaml, no bun/npm/yarn lockfiles, .git initialized) → `gh repo create <slug> --source=. --remote=origin --push` (idempotent: skips if repo exists) → POST to `/accounts/{id}/pages/projects` with `build_command="pnpm run build"` and `destination_dir="dist"` set explicitly (avoids the bun-detection trap kwizicle.com hit) and `source.config.{owner,repo_name}` linked to the GitHub repo. Auth via portfolio.env: `CF_API_TOKEN` (Pages:Edit), `CF_ACCOUNT_ID`. `--dry-run` shows planned API calls without executing. `--skip-{verify,repo,pages}` for partial runs. Idempotent throughout. Future `VercelDeploy` / `NetlifyDeploy` slot into the same Protocol without callers changing. Custom-domain registration deferred to a later phase (DNS-touching). |
| **v3.D** ✅ | Validation-mode suggest (vocab anchor + registrar grid + cheap-first score) *(was v3.F in 2026-05-07 brainstorm)* | One-shot LLM vocabulary extraction (12-15 practitioner-register concrete-noun/verb terms, ≤9 chars each, no topic-word echo, prompt includes a worked dog-walking example to anchor "concrete vs marketing"); cached with brainstorm in shared topic-hash file (`--no-cache` invalidates both, payload extends `candidates_by_strategy` with `vocab_terms`). Vocab injected as **must-reference anchors** into all default strategies (trendy / dev-technical / benefit-driven / metaphor); abstract-brandable strategy moved behind `--with-abstract` flag (off by default). Registrar-grid output: rows = candidate names, columns = `.com .app .dev .xyz .site .co` (defaults; `--tlds` overrides; full ladder includes `.co .ai .io .xyz .shop .life .info .pro` for power users). Cells: `✓ $N` (available at first-year price) · `✗` / `✗ live` / `✗ park` / `✗ for-sale` (taken; live-site/parked/for-sale classification on `.com` only via `check.py` classifier) · `?` (RDAP gap — picker treats as valid pick → builds Porkbun verify URL) · `$N!` (over `--max-price`, shown unselectable). Pick + Why columns recommend a TLD per row (e.g. `.app +bundle` if `.com` defensible, `skip` if `.com` is a competing live site) and surface defense status. Score reweighted: `.app` and `.dev` to tier-9 (alongside `.com`); `.xyz` to tier-6; `.site` to tier-5; `.ai` to tier-7; `.io` to tier-6 (price-capped out anyway); **+5 if `.com` available** (slice defendable); **−20 if `.com` is a live competing site** (brand poisoned). Keep keyword/length/hyphen/digit components (vocab anchor controls *generation*; score components do *ranking*). Default flow: all 4 default strategies + full ladder run in **one pass** → merged top-15 grid → one pick. After pick, prompt `Register {primary} now via Porkbun API? [y/N]` — if yes, call Porkbun `/domain/create` with `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` from portfolio.env (charges the card on file at Porkbun; requires account-level API access to be enabled, a one-time toggle in Porkbun account settings). Print the order ID on API success; on API failure or missing keys, fall back to printing the manual checkout URL. **One-domain auto-register only** — the defense-bundle prompt (optional, separate) builds a multi-domain Porkbun cart URL at standard price (e.g. primary .xyz $2 + .com $11 + .app $11 = ~$24 first-year for full slice protection) for manual click-through; bundle defenses are never auto-charged. After registration (auto or manual), command exits printing the next-step `portfolio bootstrap <domain> --topic="..."` invocation with vocab terms shown for paste-into-prd.md (no auto-chain into bootstrap; user invokes bootstrap separately). `--browse` flag opts into per-strategy round-by-round flow (current v2.A behavior). `--show-renewal` adds renewal-price stacked sub-row (off by default; validation-mode users mostly drop renewals on failed projects). `--with-abstract` adds the abstract-brandable strategy back into the run. Drop `.tech .site .online .store .fun` from full ladder for *availability checks* (Radix-host RDAP broken via SSL handshake error; `.site` stays in default columns as a `?`-only column for show + manual verify). |
| **v3.E** ✅ | Validation-mode polishing — post-grid menu + porn screen + TLD reference card | Restructures the post-grid interactive surface of `portfolio domain suggest`. Replaces the inline picker prompts (`N`, `N.tld`, `eN`, `e <name>`, auto "Add your own names?" loop) with a numbered menu rendered after each grid update: **1.** Pick a row to register · **2.** Expand a row (full-ladder detail) · **5.** Add my own names to the grid · **8.** Show TLD reference (pricing, SEO, vibe — quick-recall card) · **q.** Quit. (Slots 3/4/6/7 reserved for v4.A features — finalists, ask AI, widen.) Bad input loops with a "Type 1, 2, 5, 8 or q" hint (no silent quit). Menu re-displays after every non-terminating action; only successful registration or `q` exits. Also lands the **3-layer strict porn screen** (always-on, no opt-out): Layer 1 local blocklist of unambiguous terms (porn xxx milf bdsm smut nsfw fetish kink slut whore fuck cunt twat fap incest pedo); Layer 2 OpenAI moderation API at `omni-moderation-latest` with strict thresholds (`sexual > 0.05`, `sexual/minors > 0.01`, no hate/violence filter); Layer 3 gpt-5-mini adjacency + brand-collision check (catches misspellings/different-TLD variants of popular adult brands). Hooked into both `brainstorm()` and the user-added-names path; silently passes through on API failure so the pipeline never breaks. **TLD reference card** (option 8): per-TLD detail card with operator, reg/renew, vibe, trust, SEO, best-for, catch — same data the user kept in chat now recallable in-tool. Only-user-is-Vijo by design; no power-user shortcut surface. |
| **v4.A** ✅ | Mark / unmark shortlist + grid alphabetical sort + AI seed-expansion *(headline; new 2026-05-08; deferred from v3.E menu stub item 6)* | Three coupled changes that ship together. **(1) Grid sort flips from score-desc to alphabetical-by-name** (`row.name` ascending, case-insensitive). Score ranking was right for "show me the best candidate first" but this phase reorients the grid for "build a shortlist by scanning names" — you find a candidate by leading letters, not by ranking. Anchors / Pick / Why columns are unchanged; only the row order. **(2) Mark / unmark shortlist.** Adds menu item **6. Mark / unmark for shortlist** (and item 7 placeholder hint pointing at v4.B). Picker accepts multi-target input — `m N1 N2 ...` or `m alpha beta` or `m 1,3,5` (whitespace and/or comma separated) — to mark several candidates in one call; same for `u`. Per-target errors accumulate (out-of-range / unknown name) without bailing on partial successes. `p` prints the current shortlist with per-candidate cell summary; `b` returns to menu. Shortlist persists across menu iterations until quit. Shortlist count appears in the menu label when nonzero (e.g. `6. Mark / unmark for shortlist (3 marked)`). User-added names are markable just like LLM-generated ones. Implementation: shortlist is a list of names (not row references) so it survives grid mutations from add-names / future widen. **(3) AI seed-expansion in option 5.** After the user types seed names in option 5 (Add my own names), prompt `Expand with AI to get plurals, near-synonyms, etc.? [Y/n]`; on Y, send seeds + topic + vocab to gpt-5-mini for 12-18 closely-related variants (plurals, near-synonyms, prefix/suffix riffs, alternative anchors). Variants pass through the same v3.E porn screen. Cuts the typing cost when the user has a stem in mind but wants broad coverage. Silently falls back to seeds-only on API failure. |
| **v4.B** ✅ | Decide from shortlist — guided 6-step decision aid *(new 2026-05-08; deferred from v3.E menu stub item 7)* | Activates menu item **7. Decide from shortlist**. Renders a focused comparison table (rows = finalists; columns = name · reg · renew · pick · anchors · defense — Renew always shown for keepers; renewal-cliff `↑Nx` flags carried forward from v3.D). Then walks the user through six decision-aid steps in this order — auto steps first, interactive last: **Step 1 (Brand collision check)** — gpt-5-mini "is X a known brand?" check per finalist (1-line verdict). Brave Search API was originally the primary backend (free tier) but was removed 2026-05-08 when Brave's free tier disappeared; AI-only is now the path. **Step 2 (USPTO TESS)** — print `tmsearch.uspto.gov/search?queryString=<name>` URLs per finalist; manual click-through (no clean free live-search API). **Step 3 (Brand-extensibility)** — gpt-5-mini call per finalist with topic + vocab; returns 1-sentence "would this name survive a pivot?" assessment. **Step 4 (5-year cost projection)** — computed from pricing dict: `reg + 4×renewal` per finalist's pick TLD. **Step 5 (Phone test, interactive)** — prompt user to say each finalist out loud, type any names that tripped them (comma-separated; Enter for none). **Step 6 (Memory test, interactive)** — user looks away 30s, types any finalists they couldn't recall (Enter for none). After step 6, print a one-block "Test concerns:" summary listing any names flagged in 5/6, then the pick prompt: row N from the finalists → existing `_post_pick_flow` (defense bundle, register, next-step). `b` at any prompt returns to main menu (shortlist preserved). Empty shortlist on entry → "Shortlist is empty — mark some candidates first." → back. GitHub / npm / PyPI / social-handle / Google-Trends checks are explicitly out of scope (user call: "no need to check gh/npm etc"). New module `src/portfolio/decide.py` houses collision check, extensibility, cost calc, USPTO URL builders. Tests mock OpenAI calls. |
| **v4.C** ✅ | Widen search + ask AI *(new 2026-05-08; deferred from v3.E menu stub items 3 and 4)* | Adds menu items **3. Ask AI about a name** and **4. Widen search — more candidates**. **Ask AI (`? <name>` or via menu 3)**: gpt-5-mini call given topic + vocab + name + question, returns 1-3 sentence explanation; default question "Why was this name chosen and how does it relate to the topic?"; cached by (topic, name, question) hash so re-asking the same question is free. **Widen (`w` / `w <guidance>` or via menu 4)**: LLM call passing existing names as history-dedup + optional user guidance ("shorter", "foreign roots", "more medical-specific"); returns 12-24 fresh candidates merged into the grid after going through the v3.E porn screen. Both go through the v3.E content screen. Tests mock the OpenAI calls; verify dedup against existing grid, anchor injection in widen, cache hit/miss for ask. |
| **v4.D** ✅ | Interactive launcher (menu) *(was v4.B pre-2026-05-08-pm; was v3.E pre-2026-05-07; was v4.A 2026-05-07 → 2026-05-08-am)* | `portfolio` invoked with no subcommand drops into a grouped, rich-rendered menu — solves the "I can't remember the subcommand or the nested-quoting" friction. Groups: **Manage** (summary, project status, cleanup, check) · **Build** (domain suggest, bootstrap, deploy) · **Reports** (expiring, category, wip, list). Per-command flow: prompt for required positional args first, then `use defaults for everything else? [Y/n]`; if `n`, walk through optional flags one at a time. Existing per-command interactive flows (e.g. `domain suggest`'s `--browse` per-strategy round) take over after dispatch — no double-menu. After command exits, returns to menu; `q` from the menu quits. Implementation: `app(invoke_without_command=True)` with a callback that runs `menu()` from new `src/portfolio/menu.py`; nothing else changes — `make run` (no ARGS) and direct `portfolio` invocation both flow through. Bad-syntax `make run ARGS="…"` still surfaces typer's existing error (no fuzzy-match fallback in this phase). Tests use typer's `CliRunner` with mocked stdin. |
| **v5.A** | Universal check catalog foundation + scaffold/git checks *(new 2026-05-09; absorbs old v6 GSC integration and old v7 stack detection)* | New `src/portfolio/checks/` package: file-per-check registry with auto-discovery (`check_NNN_<slug>.py` modules each declaring `CHECK_ID`, `CHECK_NAME`, `CATEGORY`, `SEVERITY`, `DESCRIPTION`, `run(repo_path) -> CheckResult`). `CheckResult` dataclass: `status: "pass"\|"fail"\|"warn"`, `message: str`. `~/.config/portfolio/config.toml` loader (repos_dir, github_token, skip_checks). Initial 17 checks: scaffold (CHECK_001 has-readme, CHECK_002 has-ai-agents-md, CHECK_003 ai-agents-building-info, CHECK_004 ai-agents-deployment-info, CHECK_005 has-docs-prd, CHECK_006 has-docs-claude, CHECK_007 has-docs-prompts, CHECK_008 has-docs-growth, CHECK_009 has-gitignore, CHECK_010 has-tests, CHECK_011 has-env-example, CHECK_012 makefile-forwards-to-parent) + git (CHECK_020 own-git-repo, CHECK_021 last-commit-30d, CHECK_022 clean-tree, CHECK_023 on-main-branch, CHECK_024 has-ci-workflow). Read-only. Does not yet wire into existing CLI commands — that's v5.B/v5.E. |
| **v5.B** ✅ | `check --git` command | New `--git` flag on existing `check` subcommand. Runs scaffold + git subset over all sibling repos (default: `repos_dir` from config.toml, or fallback to ~/work/projects/sites). Output: summary table (Repo · Score · Fails · Warns) by default, sorted by score ascending so problems jump out; `--detail` for full per-repo breakdown; `--check CHECK_xxx` to run one check across all repos (rendered as a per-repo column with fails-first sort); `--repo <name>` for one repo, all checks. |
| **v5.C** ✅ | Stack/deploy/SEO checks + cross-repo aggregate view (CHECK_025–CHECK_080) | Extended catalog with: docs-quality (CHECK_025–027: growth-md non-empty, CLAUDE.md min sections [`## Project` + `## Commands`], prd.md min sections [`## Problem` + `## Users` — accepts numbered prefixes]), git (CHECK_028: last-deploy-date — only when Makefile has `deploy:` target, scans 50 commits for deploy/release/publish/ship markers, fails if >60d), stack (CHECK_029 has-live-url + CHECK_030–039: pnpm-only lockfile discipline, Vite ≥6 / Astro ≥5, build+dev scripts, node_modules-in-gitignore, tsconfig), deploy (CHECK_050–056: deploy-target uniqueness wrangler XOR vercel XOR netlify, wrangler compatibility_date / assets.directory=./dist / no _redirects SPA fallback / name-matches-slug, vercel.json sanity, builder Makefile reference), SEO assets (CHECK_060–064), and SEO meta (CHECK_070–080: title 30–60, meta description 120–160, canonical, viewport [error severity], html lang, meta robots, Open Graph 5-tag set, Twitter Card, JSON-LD presence + Organization/WebSite type, analytics marker). Recategorized CHECK_005–008 from `scaffold` to new `docs` category and CHECK_024 from `git` to new `ci` category. Render order: Scaffold → Docs → Git → CI → Stack → Deploy → SEO. `check --git` adds aggregate "Most common failures across N repos" block (top check IDs by repo count, threshold ≥30%, grouped by category) so fleet-wide gaps surface visibly. Per-repo Fails/Warns columns sort by category for clustered reading. Config gains `[git] ignore_repos = ["portfolio"]` (default) so the CLI tool itself is excluded from cross-repo runs. Bootstrap post-summary refactored to call the registry directly (replaces the legacy `project.build_status` rule list). |
| **v5.D** ✅ | `check --seo` command (live HTTP + GSC + CrUX) | New `--seo` flag on `check`. Per-domain runtime probe — separate runner from the per-repo registry (different input shape). Picks domains from latest `data/checks/*.json` whose classification is live-site/forwarder, dedupes bare/www. Live HTTP probes: HTTPS root status, HSTS header presence, `/robots.txt` (must be `text/plain` — parking pages serving `text/html` for robots are rejected), `/sitemap.xml`. GSC probe via existing `gsc.py` OAuth path: aggregates clicks/impressions/CTR/avg-position across multi-property domains (sc-domain: + url-prefix), with impression-weighted position averaging; counts submitted sitemaps. CrUX probe via `chromeuxreport.googleapis.com/v1/records:queryRecord` with `CRUX_API_KEY` (mobile form factor only): p75 LCP/INP/CLS. Each metric maps to 🟢/🟡/🟠/🔴 against Web Vitals thresholds (LCP 2.5s/4s/6s, INP 200ms/500ms/1s, CLS 0.1/0.25/0.5, position 10/30/50). Overall row status is the worst non-grey cell. Render: Rich table with one row per domain + Status / HTTP / HSTS / Robots / Sitemap / Imp / Clicks / CTR / Pos / LCP / INP / CLS columns, sorted by impressions desc by default. Flags: `--days N` (GSC lookback, default 28), `--domain <one>` (single-domain mode), `--sort impressions\|clicks\|position\|ctr`. Deferred to follow-ups: indexed-pages check (needs URL Inspection API which is per-URL not per-property), desktop CrUX (mobile is the SEO-relevant signal), `--deep` top-5-queries view. New `CRUX_API_KEY` slot in `portfolio.env` template. |
| **v5.E** ✅ | Refactor `project status` onto the catalog | `portfolio project status <name>` now drives its conformance section from the registry. The 9 hand-rolled legacy rules (`own-git-repo`, `has-prompts-md`, `has-makefile`, etc.) are replaced by a `run_checks()` call across scaffold + docs + git + ci + stack + deploy + seo categories — every project gets ~50 catalog checks instead of 9. Output shape preserved (`conformance.passed/failed/skipped`); rule names migrated to CHECK_* IDs (e.g. `own-git-repo` → `CHECK_020`, `has-ai-agents-md` → `CHECK_002`, `has-growth-log` → `CHECK_008`). Two ad-hoc rules without catalog equivalents kept under their legacy names: `has-category` (data-side, reads portfolio.json) and `live-site` (runtime, derived from latest check snapshot). Failed entries now carry `name` + `severity` so the renderer shows `CHECK_006 has-docs-claude — docs/CLAUDE.md missing`. The post-bootstrap surface (already on the registry since v5.C) and `project status` now share the same conformance code path. Static-source SEO checks (CHECK_060–080) are surfaced through `project status` for the first time — favicon, sitemap-in-build-script, OG/Twitter/JSON-LD tags, etc. Removed legacy `has_makefile_with_targets` helper (replaced by CHECK_012). |
| **v5.F** ✅ | Revamp CLI structure — four-group rename | Reorganized the CLI surface into four top-level groups: `focus` (queued v5.G), `check {--live,--git,--seo}`, `new {suggest,bootstrap,deploy}`, `info {summary,status,expiring,wip,list,category,cleanup}`. Old top-level names (`bootstrap`, `summary`, `project status`, `domain suggest`, …) keep working via deprecation aliases that print a one-line yellow nudge and forward to the new home. Top-level `status` was removed (deprecation alias points at `check --live` for live snapshot view, `info status <name>` for project status). `--live` added as the explicit form of the legacy default-no-flag mode on `check`. `--repo` kept as deprecated alias for `--domain` (with warning). Menu rebuilt to the 14-item structure. Templates updated (bootstrap.py output, post-bootstrap "Next steps", env-template comments, scaffold doc). Flag symmetry across `--live`/`--git`/`--seo` (`--detail`, `--refresh`, `--only`, `--sort`) deferred to v5.G alongside the SEO cache infra those flags need. `--live --domain <one>` deferred to v5.G (would need a one-shot probe path that doesn't pollute the snapshot file). `gsc` namespace and `check {catalog,describe,run}` debug subcommands kept where they are. |
| **v5.G** ✅ *(renumbered 2026-05-16; was v5.F.1)* | focus + SEO cache + menu-trim follow-ups | (1) `portfolio focus` shipped: ranks domains by 🔴 site-down (live snapshot) · ⚠️ expiring ≤30d (portfolio.json) · 🟠 indexed-zero-impressions (SEO cache) · 🟡 position >20 (SEO cache). Top 5 default; `--all` for full list. Reads caches only. (2) SEO cache layer: `check seo` now persists results to `data/seo/<date>.json` and reads from cache by default; `--refresh` forces re-probe; `--domain <one>` always probes fresh and skips the cache. New `src/portfolio/seo_cache.py` mirrors the `data/checks/` and `data/gsc/` patterns. (3) `check live --domain <one>` shipped: one-shot HTTP probe that does NOT overwrite the shared snapshot (so `focus` and `check seo` see the cross-portfolio view intact). (4) `info wip` removed (curated subset is now `info list --grouped` + visual pick). (5) `info category` merged into `info list` — same single command supports flat (default), `--grouped`, and `--category <substring>` (implies grouped + filter). Menu trimmed from 14 items to 12. Deprecation shims at both top-level and `info` group point users at the new home. **Deferred items** from the original v5.G spec (no compelling need yet): `--detail` for `live`/`seo`, `--sort` columns for `live`/`git`, `--only=wip\|all` on `git`. Re-open if a use-case lands. |
| **v5.H** ✅ *(renumbered 2026-05-16; was v5.F.2)* | check live/git/seo as real subcommands | Pre-v5.H: `check --live` / `--git` / `--seo` were callback flags. Made `check` symmetric with `new` and `info` — `check live`, `check git`, `check seo` are now proper subcommands. Mode-specific options moved off the callback to the relevant subcommand. The flag form (`check --live` etc.) kept as deprecation alias with one-line nudge. Templates + tests updated; one test specifically exercises the deprecation alias path so we know the old form still works. |
| **v5.I** ✅ *(renumbered 2026-05-16; was v5.G)* | Content-pipeline checks (hybridautopart pattern) | CHECK_130–CHECK_137 (new `content` category): has-seo-dir, seo-pyproject, seo-uv-lock, seo-claude-md, seo-pipeline-prompt (accepts SEO_PIPELINE_PROMPT.md / SEO_PIPELINE.md / PIPELINE_PROMPT.md), content-plan-json (accepts topics.json / content-plan.json — also validates the JSON parses), seo-makefile-pipeline, seo-tests-dir. Auto-skip pattern: every check returns warn-skip when `seo/` is absent at project root, so non-content projects don't see false failures. CHECK_130 is the gate (skip on absence, pass on presence — info severity since it's a marker not a requirement). New `content` category added to `_GIT_FLAG_CATEGORIES`, `_CATEGORY_ORDER`, `_CATEGORY_LABEL`, and `applicable_categories` for `info status`. Live-verified: 8/8 pass on hybridautopart.com (the canonical content-pipeline project); 8/8 auto-skip on kwizicle (plain web project). 20 unit tests covering the gate + per-check pass/fail + auto-skip path. |
| **v6.A** ✅ | Drift detection — `info drift` | New `portfolio info drift` subcommand cross-checks the four sources of truth (data/portfolio.json, registrar CSVs, sites/* dirs, GSC properties, latest check snapshot) and surfaces six signals: (1) registered-but-never-bootstrapped (in portfolio.json, no `sites/<domain>/`), (2) CSV-only domains (cleanup hasn't run), (3) expiry mismatch CSV vs portfolio.json, (4) GSC orphans (verified in Search Console but missing from portfolio.json), (5) deployed-but-flagged-for-deletion (live-site/forwarder classification on a domain in 'To be deleted immediately' category — caught the user shipping on domains slated for retirement), (6) duplicate across registrars (transfer didn't clean up source registrar). Domains in 'To be deleted immediately' are excluded from signal 1 (no point flagging absence on retired domains). New `src/portfolio/drift.py` module is pure data analysis (no CLI side effects); CLI subcommand renders. GSC + snapshot signals gracefully skip when the source isn't available. **Cut from original v6.A scope:** the dir↔domain override map was rejected by the user — unresolved dirs are signal that something needs cleanup, not a config problem to silence. CHECK_141 (no-git-submodules) and v6.C's three per-stack checks deferred to a follow-up. |
| **v6.B** ✅ *(renumbered 2026-05-16; was v6.A.1)* | Catalog↔bootstrap reconciliation | New CHECK_013 `ai-agents-references-versioning` (warn) — every project's AI_AGENTS.md should reference the `vN`/`vN.X` versioning convention, either via a `## Versioning` section or a link to the canonical statement at `sites/portfolio/AI_AGENTS.md`. Tier 1 fixer appends a versioning section to existing AI_AGENTS.md files via section_inject. **Bootstrap output reconciled with catalog:** previously, freshly-bootstrapped projects failed CHECK_006 (no docs/CLAUDE.md), CHECK_011 (no .env.example), CHECK_024 (no .github/workflows), CHECK_029 (no homepage in package.json), CHECK_003 (heading was "Build tooling" not "Building info"), CHECK_004 (heading was "Deployment" not "Deployment info"), and CHECK_079 (Astro JSON-LD used `set:html={JSON.stringify(...)}` template syntax that the static-source parser couldn't read). All seven gaps closed: bootstrap now writes docs/CLAUDE.md (from templates.docs_claude_md), .env.example, .github/workflows/ci.yml (runs `make test` on push), homepage field in package.json (vite + astro both), AI_AGENTS heading rename, and static-JSON-LD in Astro index template (still produces correct schema.org metadata, just statically parseable by both Astro and the catalog). New regression test `test_template_path_passes_day_zero_catalog` runs every applicable check against fresh bootstrap output and locks in zero day-zero failures. 745 tests pass. |
| **v6.C** ✅ *(renumbered 2026-05-16; was v6.B)* | Per-stack rules — submodules + gitignore-build-output | Two new checks closing real bootstrap-time gaps. **CHECK_141 `no-git-submodules`** (deploy/error): CF Pages doesn't clone submodules, so a repo with gitlinks silently produces broken deploys; detection via `git ls-files --stage` mode 160000. Skipped on non-git repos. **CHECK_142 `gitignore-covers-build-output`** (stack/warn): extends CHECK_038 (which only checks `node_modules`) — at minimum `dist/` must be in `.gitignore`. Tier 1 fixer appends `dist/`, `build/`, `.next/`, `.astro/` (idempotent — skips entries already present). Cut from original v6.C scope (no urgent trigger): CHECK_143 python-uses-uv, CHECK_144 pnpm-lock-required-for-vite-astro. |
| **v6.D** ✅ *(renumbered 2026-05-16; was v6.C)* | Remediation Tier 1 (templated; second project-dir write surface) | `portfolio project fix <name>` — 16 templated fixers covering the most-common fleet-wide gaps. Dry-run by default; `--apply` to write; `--rule CHECK_xxx` (repeatable) for surgical fixes; `--yes` skips lockfile-deletion confirmations. All fixers idempotent (file-existence: skip if present; section-injection: skip if heading already present; deletion: skip if absent). New `src/portfolio/templates.py` (public API around bootstrap.py's existing private template strings + new templates for docs/CLAUDE.md, .env.example, and section-emitters); new `src/portfolio/fixers.py` (registry, dry-run/apply runner). Fixable: CHECK_001 (README), CHECK_002 (AI_AGENTS), CHECK_003/004 (AI_AGENTS section appends), CHECK_005 (docs/prd), CHECK_006 (docs/CLAUDE), CHECK_007 (docs/Prompts), CHECK_008 (docs/growth), CHECK_009 (.gitignore), CHECK_011 (.env.example), CHECK_012 (Makefile if absent only — refuses to overwrite existing), CHECK_026/027 (CLAUDE/prd section appends), CHECK_032/033/034 (lockfile deletions, with per-file confirm unless --yes). Manual-only (printed in the plan as "needs human" with a one-line reason): has-tests, has-ci-workflow, clean-working-tree, has-live-url, content-pipeline checks, deploy/wrangler safety rules. Tier 2 (Claude subprocess for content-quality checks) is queued as v6.E; the `--ai` flag is accepted now but no-ops with a deferred note. Side effect: bootstrap's `_docs_prd_md` template renamed `## 1. Purpose` → `## 1. Problem` and `## 2. Audience` → `## 2. Users` to align with CHECK_027 (pre-existing inconsistency where bootstrap's own output failed CHECK_027). 51 new tests; 727 total. **`project` namespace revived** (it was retired in v5.F when its only command was the read-only `status`); now hosts `project fix`, with `project status` kept as the deprecation alias from v5.F. |
| **v6.E** ✅ *(renumbered 2026-05-16; was v6.C.1)* | Remediation Tier 2 — Claude subprocess for content-quality fixes + co-located fixer architecture | Two pieces shipped together. **(1) Architecture migration**: moved from centralized `fixers.py` / `ai_fixers.py` to per-check co-location — each check module declares `fix_tier_1` and/or `fix_tier_2` as module-level FixerSpec attributes, and a new `fix_registry.py` discovers them by walking the existing check registry. Same locality pattern as ESLint/Ruff. New `src/portfolio/fix_helpers.py` houses factories (`file_writer`, `section_inject`, `file_deleter`) and Claude-subprocess infra (`run_claude`, `claude_available`, `ai_fixer_factory`, `project_context`). Old `fixers.py` and `ai_fixers.py` deleted. **(2) Tier 2 wired live**: `--ai` flag now spawns `claude -p` non-interactively in the project dir with `--allowedTools "Read Edit Glob Grep"` (no Bash, no shell) and `--max-budget-usd` as a hard cost cap. Three Tier 2 fixers shipped: CHECK_025 (real growth experiments), CHECK_026 (real CLAUDE.md Project/Commands content), CHECK_027 (real prd.md Problem/Users content). Each has a project-specific prompt builder pulling from AI_AGENTS.md + package.json/pyproject.toml as context. Stop criterion: re-run the targeted CHECK; pass → fixed, else error with Claude's reason. CLI reports cost and duration per fixer. Tier 1 always runs before Tier 2 in the apply path. Deferred to v6.F: own-git-repo guided migration (CHECK_020). Deferred to future cleanup (no slot allocated): HTML meta-tag content fillers (CHECK_071/076/077 — need brand assets). |
| **v6.F** *(renumbered 2026-05-16; was v6.C.2)* | own-git-repo guided migration | `portfolio project fix --rule CHECK_020` carved out as its own phase since it touches the parent repo (parent `git rm --cached` + parent `.gitignore` entry + project `git init` + initial commit). Explicit confirmation each step touching parent repo. Riskier than templated writes; deserves its own slice. |
| **v6.G** ✅ *(renumbered 2026-05-16; was v6.D)* | Fleetwide `project fix --all` | New `--all` flag on `project fix` iterates every fleetwide-eligible project (`repos_dir` minus `ignore_repos` config minus domains in 'To be deleted immediately' category). Default: dry-run plan with per-project compact summary + fleet totals (Tier 1 count + Tier 2 count + cost estimate when `--ai` is set). `--apply` writes; single confirm-once prompt unless `--yes`. Continue-on-error — per-project failures don't halt the sweep; fleet summary at end shows count of changed projects + count of errored projects. Lockfile deletions (CHECK_032/033/034) auto-skipped in fleetwide mode unless `--yes` (avoid N×3 per-file confirm prompts). Eligibility filter resolves dirs to portfolio.json domains for the deletion-category check; dirs that don't resolve (e.g. `harmonia`, `levents`) are STILL eligible — drift dirs need fixing too. Catalog runs directly against project_dir (no `build_status`/resolver dependency) so fleetwide works on dirs even when they don't match a portfolio.json entry. New `_run_project_fix_all` helper + 9 tests covering eligibility filter, dry-run rendering, --apply with --yes, mutually-exclusive name+--all, empty-fleet path, deletion-marked filter. |
| **v7.A** ✅ | CLI restructure — scope-first (`project` / `fleet` / `new` / `settings`) | Reorganized the CLI surface around scope-first namespaces. `project` for ops on one project, `fleet` for cross-portfolio, `new` for creation, `settings` for setup/debug. New commands: `project check` (replaces `info status`, with `--catalog-only` flag for the rules-only view from old `check git --domain`), `project fix` (unchanged), `project seo` (replaces `check seo --domain`), `fleet focus`/`live`/`seo`/`check`/`fix`/`drift` (each formerly top-level or under `check`), `fleet info {summary,expiring,cleanup}` (the inventory views formerly under `info` — `summary --verbose` replaces `info list`), `settings catalog {list,describe,run}` (formerly `check catalog/describe/run`), `settings gsc {auth,status}` (status with `--refresh` folds in old `sync`/`list`/`compare`), `settings apikeys {list,set,delete}` (NEW — replaces manual `portfolio.env` editing; `list` shows set/not-set + connectivity tick per provider via OpenAI/CrUX/Porkbun/Cloudflare API probes; `set` is strict on known keys with `--force` override; atomic write preserves comments). Old paths kept as additive aliases (no deprecation prints yet — that's v7.A.2). Menu rebuilt to 18-item structure across the four namespaces. Bootstrap templates + AI_AGENTS.md + docs/CLAUDE.md updated to reference new paths. Tests: 19 new for apikeys (env IO + probe shape), menu tests rewritten for new structure. 792 tests pass. v7.A.2 (deprecation prints) and v7.A.3 (final cleanup) deferred until user wants to push migration. |
| **v7.B** ✅ | `fleet dashboard` — unified live + SEO + git view | Single per-domain row joining `data/checks/<date>.json` (live class + HTTP status) + `data/seo/<date>.json` (robots/sitemap/GSC totals) + local git state (own-repo, last-commit age, catalog pass%). Worst-of rollup dot leftmost so problem domains surface immediately. Read-only cache join by default; `--refresh` re-probes live + SEO upstream (≈ same cost as `fleet live` + `fleet seo --refresh`). Sort modes: attention (worst rollup first — default), name, imp, age. Dot thresholds: 🟢 live-site, 🟡 parked/forwarder, 🔴 dead/error/ssl-broken for the Live column; conformance + commit-age combined for the Git column; reuses `seo_runtime.overall_status` for the SEO column. 11 unit tests for the dot/rollup/sort helpers; integration paths covered by existing snapshot + project_status tests. |
| **v7.C** ✅ | Age tracking — `launched` + `domain_created` | Two new fields on each row in `data/portfolio.json`: `launched` (when *this* site went live — manual via `lamill project set-launched <domain> <YYYY-MM-DD>`, falls back to first-commit-date inference) and `domain_created` (RDAP `registration` event date — when the domain was first registered globally). `cleanup()` preserves both across CSV rebuilds. RDAP refresh via `lamill fleet info cleanup --refresh-rdap` (~0.5s per domain). Both surface as columns in `fleet dashboard` (Site age + Domain age) with compact age formatting (d/w/mo/y). New `rdap_creation_date()` helper in `availability.py` reuses the existing IANA RDAP bootstrap. **Motivation:** SEO grading for sites <90d old looked red because position 60 / clicks 0 are normal for the freshness window — having the age columns visible lets the reader interpret red rows correctly. 12 new tests covering Domain age properties, JSON round-trip, cleanup preservation, atomic update_domain_field, RDAP event parsing (no network), age formatting, git inference. |
| **v7.D** ✅ | `fleet focus` enhancements + P4 age-aware SEO grading | Five fixes to `fleet focus`: (1) **variant-aware site-down** — only flag dead when *every* probed variant (bare + www) failed, fixed false positive on linkedcsi.live where bare timed out but www was serving live; (2) **platform-aware action text** — drop hardcoded "Cloudflare Pages" message, detect wrangler.toml / vercel.json / netlify.toml and name the actual platform; (3) **`--refresh` flag** — re-probe upstream before reading caches; (4) **age-aware SEO signal suppression** — 🟠 zero-imp + 🟡 bad-position signals don't fire for sites <90d old (normal during Google freshness window), with `--include-young` to override; (5) **idle (🟡) signal for forwarder/parked** — was previously silent when domain was reachable but not serving real content (airsucks.com case before bootstrap). **P4** closed the age-awareness loop in `seo_runtime.overall_status` — takes optional `site_age_days` param and masks imp + pos cells when site is young; wired through dashboard's SEO dot and the `fleet seo` table grade. Robots/sitemap/GSC-presence still count regardless of age. After P4, airsucks.com (launched today, GSC active, zero impressions) correctly graded 🟢 instead of 🔴. ~15 new tests. |
| **v7.E** ✅ | `fleet repos` audit + naming-consistency cluster + archived state | Read-only audit of every `sites/<domain>/`'s git-layer state. Classifies into: clean standalone, nested anti-pattern (own .git + tracked by outer monorepo), standalone unpublished (no remote), monorepo-only, unversioned, empty stub, archived. `--detail` / `--only` / `--json` modes. Write mode (`--fix`) intentionally deferred — design space around per-site prompts + pre-flight comparator needs more thought. Three new git-category catalog checks landed alongside: **CHECK_040** (git-remote-name-matches-domain — full-domain naming convention, e.g. `codervijo/airsucks.com` not `codervijo/airsucks`), **CHECK_041** (dir-matches-portfolio-entry — typo'd directories), **CHECK_042** (live-final-url-matches-domain — forwarder/redirect mismatch). **Archived support**: two detection signals (`TOMBSTONE.md` marker file at project root, or portfolio.json category in `{to be deleted immediately, archived, tombstoned}`). Archived sites get a dedicated 🪦 row and skip all three naming checks. 38 new tests. |
| **v7.F** ✅ | `project diagnose <domain>` — five-layer auto-investigate | Replaces the manual dig/curl/openssl flow when a dashboard row goes red and the rollup isn't enough to explain why. Probes DNS / HTTP / TLS / repo / inventory and synthesizes a root cause + suggested fix. Seven heuristics catching real-world patterns from this session: Vercel deployment-not-found (lamill.us), Namecheap parking (linkedcsi.live pre-deploy), intent-vs-actual mismatch (lamill.io's wrangler.jsonc-vs-Vercel-serving case), TLS alert 112 on intended platform, no-DNS-at-all, normal live site, forwarder/parked decision. Fallback message when nothing matches (never guesses). Platform detection from DNS recognizes Vercel anycast IPs, Cloudflare Pages / Netlify / GitHub Pages CNAMEs, and Namecheap parking IPs. 17 tests. |
| **v7.G** | Tool rename: `portfolio` → `lamill` (light) | `[project.scripts]` entry exposes both `lamill` (canonical) and `portfolio` (legacy alias). Python package stays `portfolio` internally — no import sweep. Installed system-wide via `uv tool install --editable` so `lamill` works from any directory. Brand reference to user's Lamill Web Systems / lamill.io. Heavier rename (package + imports + filesystem sweep, ~30 files) deferred indefinitely — light + alias is enough. ✅ |
| **v7.H** ✅ | GSC sitemap health + dark-site detection + CF edge-cache check (`CHECK_057`) | Three threads landed together while triaging donready.xyz's "Sitemap could not be read" GSC report (commit `357a29f`). **(1) GSC sitemap health:** `probe_gsc` keeps per-sitemap `errors`/`warnings`/`isPending`/`lastDownloaded` from `sitemaps().list()` instead of only counting submissions; new `gsc_sitemap_health` signal in `_OVERALL_KEYS` correctly grades a row 🔴 when GSC reports parse errors on a submitted sitemap (previously the dashboard stayed green by absence). New `gsc_sitemap_cell()` merges presence + health for the `check --seo` "GSC sm" column; footer callout lists "sites with sitemap errors in GSC" with one-line diagnostic hints. Fleet focus gains 🔴 sitemap-parse-errors + 🟡 sitemap-warnings signals (errors suppress warnings to avoid duplication). **(2) Dark-site detection from robots.txt:** new `_robots_intent_from_body` classifies robots.txt as `dark` when `User-agent: *` or `User-agent: Googlebot` carries `Disallow: /` with no overriding `Allow: /` in the same block (multi-agent groups + blank-line block boundaries handled correctly; AI-bot disallow blocks ignored). `SEORow.robots_intent` feeds new 🔒 glyph in the robots column; `overall_status` + `gsc_sitemap_cell` short-circuit to 🔒 on dark rows; fleet focus suppresses public-web-discovery signals (no-sitemap-submitted, sitemap-errors, zero-imp, bad-pos). Site-down + expiry signals still fire — broken hosting is broken regardless of crawler policy. Wires up cleanly to a future `lamill.toml [dark]` flag (same downstream behavior, two possible inputs). **(3) `CHECK_057 cf-edge-cache-fresh` + tier-1 fix + `settings cloudflare`:** new deploy check probes `/`, `/robots.txt`, `/sitemap*.xml` against the live origin with `follow_redirects=False` (load-bearing — a legitimate 301 isn't stale; commented as such after a self-inflicted regression caught by `test_run_does_not_flag_legitimate_301_as_stale`); fails when a critical path returns 200 but is absent from `dist/`. New `portfolio/cloudflare.py` module: token read/save, zone-id resolution with persistent `data/cloudflare/zones.json` cache (gitignored — operator-specific), `purge_files` (caps at 30 URLs per CF policy — raises rather than silently truncates), `verify_token` via `GET /user/tokens/verify`, `token_status` snapshot for the settings command. Tier-1 fix on the check module re-probes, purges via the API, re-probes once more to verify HIT→MISS; verify-still-HIT downgrades to error so silent partial-purges surface. New `settings cloudflare {token,status}` CLI surface: `token` prompts hidden, saves at mode 0600, verifies against CF in one step (`--no-verify` skips); `status` reports config state without leaking the token value, `--verify` hits CF on demand. `MissingCredentialsError` and `CloudflareAPIError` paths in the fix point at `settings cloudflare token` / `--verify` for one-line diagnostic paths. Fleet focus surfaces failing `CHECK_057` as 🔴 "Stale CF edge cache" with the purge command in the action text; CF probes parallelized via `ThreadPoolExecutor` (max 8) and only run against CF Pages projects (filesystem filter on `wrangler.jsonc`). +86 tests across `test_seo_runtime`, `test_focus`, `test_cloudflare`, `test_settings_cloudflare_cli`, and `tests/checks/test_check_057_*`. 1421 tests pass. |
| **v8.A** ✅ | `new research <topic>` core command *(absorbed by v8.D 2026-05-14)* | Originally planned: gpt-4o-mini synthesizing SERP analysis from training data (top rankers, content patterns, gap analysis, ship/skip recommendation). 2026-05-14 brainstorm replaced the AI-only approach with real SerpAPI primary + synthesis fallback before any code was written. v8.D's `lamill new research <topic>` command fulfills this row's intent — see §8.1. |
| **v8.B** ✅ | Multi-keyword cluster mode *(absorbed by v8.D 2026-05-14)* | Originally planned: LLM-generated cluster (3-5 related queries) from a single topic, merged SERP across the cluster, deduped + scored by frequency, with `--strict` to fall back to literal-topic-only. Shipped as part of v8.D — cluster expansion is the default behavior; `--strict` flag preserved. See §8.1. |
| **v8.D** ✅ | Research module v2 — real SERP + three-gate framework + operator profile *(full PRD inlined in §8.1)* | Rebuild of v8.A/B from AI-only synthesis to SerpAPI primary with synthesis fallback. All three phases shipped: Phase 1 (SerpAPI fetch + per-query dated snapshots, commit `9cd3993`+ series); Phase 2 (three-gate logic — Market / SERP-with-7-classifiers / Moat-interactive-prompt); Phase 3 (operator profile read from `sites/portfolio/lamill.toml [operator]` — 4 commits: `c095ad8` loader + dataclass · `1480caa` operator-fit logic · `9ac1866` `settings operator show` CLI · `df86195` wire into research gates). Verdict vocabulary: GO / NICHE-DOWN / NO-GO. Schema bumped; old caches archived. |
| **v8.E** ✅ | Primary-pass payload assembly | `interpretive_pass.build_payload(cluster, operator_profile)` (commit `a6b6c95`). Pure data-shaping helper: takes the v8.D `research-cluster-v2` snapshot + an OperatorProfile and produces the structured user-message body the primary interpretive pass consumes — topic, cluster queries, gates (pass-through), operator fit, operator-profile summary, raw_top_10_per_query (title/URL/domain only — snippet + displayed_link stripped, capped at 10), serp_features_per_query (only `present: true` entries, padding stripped). 16 tests. |
| **v8.F** ✅ | Primary-pass prompt rendering | `interpretive_pass.render_primary_prompt(payload, operator_profile)` (commit `1287e91`). Combines `prompts/niche_evaluation_v1.md` with the payload to produce the final string `run_claude_text` consumes — operator-var placeholders substituted from profile (`(not configured)` fallbacks when profile is default/None), payload JSON in a fenced block after a `---` delimiter. Raises `UnfilledPlaceholderError` at render time if the prompt template references an unknown placeholder (drift safety — fires before the LLM call burns a subscription quota slot). 11 tests. |
| **v8.G** ✅ | Primary-pass response parser | `interpretive_pass.parse_verdict(markdown)` + `ParsedVerdict` dataclass + `VerdictParseError` (commit `febf82e`). Splits the LLM's markdown response on `### <header>` boundaries. Strict on the three required sections (`### verdict` / `### confidence` / `### reasoning`) and on canonical token sets ({GO, NICHE-DOWN, NO-GO} / {HIGH, MEDIUM, LOW}); tolerant on optional sections, bullet markers (`-` / `*` / `+` / `N.`), header case, trailing punctuation, NICHE-DOWN separator variants (`NICHE_DOWN`, `NICHE DOWN`), preamble chatter, and `moat_required` hedge values ("likely" / "depends" → None). 19 tests. |
| **v8.H** ✅ | Primary interpretive pass runner | `interpretive_pass.run_primary_pass(cluster, *, operator_profile, cwd, budget_usd, timeout_s, claude_runner=None)` (commit `977c5af`). End-to-end orchestration of build_payload → render → run_claude_text → parse_verdict. Returns `InterpretivePassResult` carrying parsed verdict + rendered prompt (for snapshot audit) + prompt version + model id + cost + duration. Raises `InterpretivePassError` wrapping CLI errors (ok=False — claude-not-found, timeout, quota exhausted) or parse errors (VerdictParseError). `claude_runner` is the testing seam — production callers leave it None and fall back to `fix_helpers.run_claude_text`. 10 tests. |
| **v8.I** | Wire primary pass into `new research` orchestrator | First user-visible v8.E-series feature. Call `run_primary_pass` from `new_research` after the mechanical gates step; render a new "Interpretive verdict (Claude):" section in the human output (default-on, no flag — adds ~5-15s per run, $0 incremental cost via Claude CLI subscription); persist `primary_verdict` + `rendered_prompt` + `prompt_version` + `model_id` + `interpretive_cost_usd` + `interpretive_duration_s` in the cluster snapshot. Snapshot schema bumps to v2.1. ~3-4h. |
| **v8.J** | Adversarial audit pass (GPT-4o + `--verify` flag) | New `audit_pass.py` mirroring `interpretive_pass.py`'s shape against `prompts/adversarial_audit_v1.md`. Uses existing OpenAI client (`OPENAI_API_KEY` already configured). Same-model rejection — errors when `--model X --audit-model X` resolve to the same model id (correlated-blind-spot rationale per PRD §10.B). Render agreement / partial / disagree sections in `--verify` output. ~4-5h. |
| **v8.K** | Reconciliation logic + REVIEW_REQUIRED first-class verdict | New `reconciliation.py`: pure logic per PRD §4 reconciliation spec. Full-agree → confident final verdict; partial → caveats; disagree → REVIEW_REQUIRED banner that the operator must look at (intentionally NO auto-resolution — manufacturing false certainty defeats the audit purpose). No LLM calls. Wire into orchestrator; output `final_verdict` field. ~2-3h. |
| **v8.L** | Polish — cost ledger + `verify_by_default` + granular cache | (a) Cost-estimate fields aggregated in the snapshot (primary + audit totals + cumulative). (b) `verify_by_default` operator flag honored from `sites/portfolio/lamill.toml [operator]` (resolved §10.D); `--no-verify` overrides. (c) `--no-cache=interpretive` / `--no-cache=audit` granular flags to re-run individual passes against cached SERP data without re-fetching. ~3-4h. |
| **v8.M** | Docs — `docs/CLAUDE.md`, `AI_AGENTS.md`, `Prompts.md`, `--help` | Update operator-facing docs to reflect v8.E–v8.K capabilities. Add "when to use `--verify`" guidance to `lamill new research --help`. Dated H2 entry in `docs/Prompts.md`. ~1h. |
| **v9.A** | `lamill.toml` per-site deploy declaration *(planned 2026-05-14, full PRD inlined in §8.3)* | Visible TOML file at each `sites/<domain>/` repo root declaring where the site deploys. Closes the gap for hosts without canonical configs (HostGator, WordPress, custom VPS). Schema: `[deploy]` (platform, account, branch, custom_domains) + `[hosting]` (cPanel/FTP breadcrumbs when applicable) + `[notes]`. CLI: `project set-deploy`, `project show-deploy`, `fleet repos --add-deploy-declarations` migration. `new bootstrap` writes it automatically. ~12-16h. 8 open questions in PRD. |
| **v9.B** | Drift detection + lamill.toml conformance checks *(deferred from v9.A; full PRD TBD)* | CHECK_xxx series comparing `lamill.toml` declaration vs DNS-resolved actual + live HTTP probe (extends `project diagnose`'s existing inference). `has-lamill-toml` + `lamill-toml-valid` + `deploy-drift` checks. ~6-8h. |
| **v9.C** | HostGator cPanel integration *(deferred; full PRD TBD)* | API pull of domains / WordPress installs / disk usage via cPanel API. Auto-writes `lamill.toml` for HostGator-hosted sites. Inventory awareness only (no write surface yet). ~8-10h. |
| **v9.D** | SFTP deploy abstraction *(deferred; full PRD TBD)* | `lamill new deploy <domain>` reads `lamill.toml`, dispatches to existing CF Pages logic OR new SFTP target for HostGator/custom. Adds a write surface; needs careful design. ~10-12h. |
| **v10.A** | `fleet hosting` — fleet-wide Vercel/CF deploy state *(planned 2026-05-15, full PRD inlined in §8.4)* | Read-only fleet view: walks Vercel + Cloudflare Pages APIs, matches each fleet domain to a project by configured custom domain, reports `latest_deploy_status` / `last_successful_deploy_at` / `consecutive_failures`. Cached snapshot at `data/hosting/<date>.json` mirroring `data/seo/` shape; `--refresh` re-walks. Status emoji table (✓ / ⚠ / ✗ / 💤 / —). Three phases: P1 walkers + cache, P2 renderer + CLI, P3 dashboard + diagnose integration. ~12-17h. 10 open questions. |
| **v11.A** | GSC trend correlation *(was v7.B pre-2026-05-13; was v7.H pre-2026-05-13-pm)* | GSC trend per project (28d clicks/imp/pos, w/w delta) over PERSISTED `data/gsc/` snapshots. **Distinct from v5.D** — v5.D is the runtime live check (one query, current state); v11.A is the longitudinal analytical layer (week-over-week deltas, trend lines). |
| **v11.B** | Roll-up *(was v7.C pre-2026-05-13; was v7.I pre-2026-05-13-pm)* | `portfolio project list` · `--stale N` filter · `--json` · aggregate verdict counts |
| **v11.C** | Optional LLM content seeding *(was v3.D pre-2026-05-07; was v9.A pre-2026-05-09; was v7.A pre-2026-05-10; was v7.D pre-2026-05-13; was v7.J pre-2026-05-13-pm; postponed indefinitely)* | `--seed-content` flag on `portfolio new bootstrap`: OpenAI gpt-4o-mini generates a starter home page + 1–2 supporting pages from the topic (similar prompt pipeline to v2.A's brainstorm) · cached by topic-hash · user reviews + commits manually before pushing · skipped by default since some projects are app-style (no narrative content) · *postponed indefinitely (2026-05-04 user call); v3.D built first* |
| **v12.A** | Build-time stamping *(was v10.A pre-2026-05-09; was v8.A pre-2026-05-13-pm)* | convention: every sites/* project writes `version.json` at build (commit + built_at) · new conformance check: has-version-stamp |
| **v12.B** | HEAD vs deployed *(was v10.B pre-2026-05-09; was v8.B pre-2026-05-13-pm)* | deploy-freshness signal · deploy-fresh conformance check · reads `version.json` from live URL |
| **v12.C** | Build status + deploy lag *(was v10.C pre-2026-05-09; was v8.C pre-2026-05-13-pm)* | deploy lag (push → live) · last build status via Cloudflare/Vercel API · last-build-success conformance · *requires platform tokens — major new infra* |
| **v12.D** | Domain-list refresh tooling *(new 2026-05-09; last-priority; was v8.D pre-2026-05-13-pm)* | Flag-only enhancements to existing `cleanup` (no new commands per user direction): `--refresh` pulls live from registrar APIs (Porkbun ready; GoDaddy/Namecheap require account API setup) into `data/domains/<reg>.csv` before merging. `--watch` re-merges whenever a CSV in `data/domains/` changes on disk. Direct $EDITOR on `data/portfolio.json` is documented in AI_AGENTS.md as the no-tooling path. |

## 6. Conformance rules

portfolio enforces these on sibling sites/* projects via `project status`. Failures show in the `failed` list with optional fix hints. Skipped rules don't apply (e.g. `live-site` for a CLI project that doesn't deploy).

| Rule | Pass condition | Lands in |
|---|---|---|
| `own-git-repo` | `git rev-parse --show-toplevel` resolves to project dir itself | v1.A |
| `in-plan-md` → `has-category` | domain has a category set (originally from plan.md; renamed in v1.D once `portfolio.json` is canonical) | v1.B (renamed in v1.D) |
| `has-prompts-md` | `docs/Prompts.md` exists | v1.B |
| `prompts-md-format` | last H2 matches `^## \d{4}-\d{2}-\d{2}` | v1.B |
| `has-makefile` | `Makefile` with `run` and `build` targets | v1.B |
| `has-ai-agents-md` | `AI_AGENTS.md` exists | v1.B |
| `has-growth-log` | `docs/growth.md` exists — per-project growth-experiment log; bootstrap scaffolds it with a self-sustaining workflow guide + first dated H2 entry | v3.A.1 |
| `platform-declared` | filesystem markers identify cloudflare/vercel/netlify, OR project is n/a (CLI/library) | v1.B |
| `live-site` | latest check classification is `live-site` | v1.B |
| `vite-version-ok` | Vite ≥6 for React projects | v7.A |
| `has-prd-md` | `docs/prd.md` exists | v7.A |
| `has-readme` | `README.md` exists at project root | v7.A |
| `has-gitignore` | `.gitignore` exists at project root | v7.A |
| `ai-agents-md-has-building-info` | `AI_AGENTS.md` contains a `## Building info` heading (referencing the central builder at `~/work/projects/builder/` + `../Makefile`) | v7.A |
| `ai-agents-md-has-deployment-info` | `AI_AGENTS.md` contains a `## Deployment info` heading (platform / live URL / deploy trigger) | v7.A |
| `cf-pages-deployable` | frozen-lockfile install OK; no stray gitlinks; no `_redirects` SPA fallback | v8.A |
| `domain-dir-match` | dir name matches a plan.md domain (or in override map) | v8.A |
| `gsc-verified` | dir's eTLD is a verified GSC property | v9.B |
| `has-version-stamp` | project writes `version.json` at build time | v10.A |
| `deploy-fresh` | HEAD SHA matches deployed SHA | v10.B |
| `last-build-success` | last Cloudflare/Vercel build succeeded | v10.C |

## 7. Open questions

Append-only log. Questions get answered (with date) but never deleted.

- *(no open questions at this time — all v1 scoping decisions are locked in AI_AGENTS.md and this PRD)*

## 8. Detailed PRDs

The phase rows above (v8.D / v8.E / v9.A / v10.A) reference detailed designs.
Inlined here rather than living as separate files in docs/prd/.
Each retains its own structure (problem statement → goals → requirements
→ open questions → effort estimate → approval).

---

### 8.1 — v8.D · Research module v2 (real SERP + three-gate + operator profile)


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

**P1.4** `--no-cache` re-fetches; default TTL = **30 days** (was 7 in
the original draft — bumped per §8.G.1 to stretch the SerpAPI free-
tier quota; SERPs change but gate-level verdicts don't move weekly).

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

**Location decided 2026-05-16:** profile lives at
`sites/portfolio/lamill.toml` under an `[operator]` section (same TOML
file v9.A specifies for per-site deploy declarations — see §8.3 §4.1
for the schema). NOT at `~/.lamill/operator.yaml`. Visible, in-repo,
one file per operator. Loader reads `[operator]` keys from the
portfolio repo's `lamill.toml`; absent file or section → defaults
(`expertise=[], workflow_preference="mixed", motivation_cadence="monthly"`).
The original P3.1 spec below is preserved for historical context; the
TOML schema replaces the YAML one.

**Three fields actually wired** (rest from the original spec dropped
as unused): `expertise[]`, `workflow_preference`, `motivation_cadence`.
`hours_per_week`, `budget_monthly`, and `existing_fleet[]` from the
original spec are dropped — never referenced by any gate, and
`existing_fleet` is already derivable from `data/portfolio.json`.

**P3.1** ~~New file at `~/.lamill/operator.yaml`~~ (or alternative — see
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

### 8.G — SerpAPI tier / cost expectations  *(RESOLVED 2026-05-14)*

**Decision:** SerpAPI **free tier** (250 queries/month, no cost).

At 5 queries per cluster, that's ~50 research runs/month. Sufficient
for personal portfolio operator scale (a few cluster runs per week).

Three implications flow from this choice — applied to the PRD below:

**8.G.1 — Cache TTL:** Bumped from 7 days → **30 days** (PRD §P1.4
amended below). SERPs move weekly, but the gate-level verdict
they drive doesn't move with them. A weekly re-fetch would burn
quota without changing the call. `--no-cache` still forces a
fresh probe when needed.

**8.G.2 — Quota tracking:** New ledger at `data/serp/_quota.json`
tracks queries used in the current UTC month. The tool:
  - Soft-warns at 80% (200/250): "⚠ SerpAPI quota: 200/250 this month"
  - Hard-refuses at 100% (250/250): "✗ SerpAPI quota exhausted —
    falling back to synthesis-only mode for this run."
  - Resets at the first day of each UTC month.
  - `lamill settings cost report` (future ledger feature) can read
    this file later.

**8.G.3 — Auto-fallback when quota exhausted:** When the quota refuses
a fresh fetch AND `--no-cache` was not passed AND a v2 cache is
unavailable, the tool **automatically falls back to synthesis-only
mode** with a loud banner:

```
⚠  SerpAPI quota exhausted (250/250 this UTC month).
   Falling back to GPT synthesis — NOT REAL SERP DATA.
   Quota resets <YYYY-MM-01>.
```

Better than failing the run; the operator sees what happened and
gets a degraded-but-useful answer. The synthesis-only result is
cached under a separate cache key so it doesn't pollute the
real-SERP cache when quota returns.

These three implementation details are now part of P1 scope.

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

**Add `SERPAPI_KEY` to `KNOWN_KEYS` + portfolio.env
template + connectivity probe in `apikeys.py`. Update
`lamill settings apikeys list` to report it.

*Smoke test:* `lamill settings apikeys list` shows SERPAPI_KEY as
"unset" or "set + connectivity ✓".

**`src/portfolio/serp_fetch.py` with `fetch_serp(query)`
returning the normalized shape from P1.2. Includes retry logic,
SerpAPI-error to ResearchError mapping. No CLI wiring yet.

*Smoke test:* `python -c "from portfolio.serp_fetch import fetch_serp;
import json; print(json.dumps(fetch_serp('ev charger installation cost'),
indent=2)[:500])"` returns a real SERP. Required: SERPAPI_KEY set.

**Per-query caching to `data/serp/<YYYY-MM-DD>/<query-
hash>.json` with `schema: serp-query-v1`. `load_cached_query(query,
ttl_days=7)`, `save_cached_query(...)`. Tests against tmp_path.

*Smoke test:* `pytest tests/test_serp_fetch.py -q` (~10 new tests).

**Refactor `serp.py:research()` to: (a) load the
cluster query list from gpt-4o-mini (existing code), (b) for each
query, call `fetch_serp()`, (c) cache + return a NEW cluster snapshot
shape that's just the per-query results merged (no gates yet, no
verdict — that's Phase 2). Synthesis-only path preserved behind
flag, marked clearly.

*Smoke test:* `lamill new research "ev charger installation cost"`
runs end-to-end against SerpAPI, writes one cluster file + 5 per-query
files, output shows raw SERP data (no gates).

**`--synthesis-only` flag wired with loud banner.
`--no-cache` re-fetches both LLM cluster expansion AND per-query SERPs.
Error paths (missing key, SerpAPI 5xx, rate limit) tested.

*Smoke test:* `lamill new research "test" --synthesis-only` shows
banner; `lamill new research "test" --no-cache` re-fetches; missing
SERPAPI_KEY errors with the right pointer.

**Quota ledger at `data/serp/_quota.json` (per §8.G.2).
Tracks queries used in the current UTC month; auto-resets on
month-boundary. Soft-warns at 200/250; hard-refuses at 250/250 with
auto-fallback to synthesis-only mode (loud banner per §8.G.3). New
helper `lamill settings serpapi-quota` shows current usage.

*Smoke test:* Mock a 251st-query call → fallback banner shown,
synthesis-only output produced; ledger reset on simulated month
change.

### Phase 2 commits

**`src/portfolio/research_gates.py` skeleton:
dataclasses (`GateResult`, `GateResults`), `evaluate_gate_1(cluster)`,
`evaluate_gate_2(cluster)`, `evaluate_gate_3(cluster, moat_input)`.
Pure logic, no CLI. Unit tests with synthetic cluster fixtures.

*Smoke test:* `pytest tests/test_research_gates.py -q` (~25 tests).

**Gate 1 (Market) — volume estimate via the chosen
proxy (§8.A), pollution detection, pollution-adjusted volume math.
Unit tests for: clean cluster, polluted cluster, mixed cluster, edge
cases (0 results, all polluted).

*Smoke test:* `lamill new research "ev charger installation cost"
--debug-gates` shows Gate 1 output but skips 2 and 3.

**Gate 2 (SERP) — classifiers in priority order.
Static `media_publications.toml` (§8.D — assuming option 1 chosen)
seeded with ~20 verticals. Programmatic-URL regex library. Tests
cover each classifier individually + combinations.

*Smoke test:* Cluster with known programmatic incumbent (e.g.,
`notateslaapp.com`) → classifier fires; cluster without one → doesn't.

**Gate 3 (Moat) — interactive prompt, snapshot
storage, `--non-interactive`/`--json` mode handling.

*Smoke test:* Running interactively on a cluster that fails Gate 2
prompts for moat; entering text → PASS; Enter → FAIL; `--json` skips.

**Verdict synthesis (§5 table) + suggested-reductions
generator (LLM call with the gate findings as context). Renderer
updated to show gates + verdict + reductions.

*Smoke test:* `lamill new research "ev charger installation cost"`
end-to-end produces the target output from §3.

**Snapshot schema migrated to v2 (`research-cluster-v2`).
Old `data/serp/*.json` were already archived in P0. Cache invalidation
on schema mismatch. Tests confirm v1 cache is treated as miss.

*Smoke test:* `lamill new research "<previously-cached topic>"` does
NOT serve from a v1 cache; re-fetches fresh.

### Phase 3 commits

**`src/portfolio/operator_profile.py`:
`OperatorProfile` dataclass, `load_profile()`, `default_profile()`,
TOML-or-YAML reader (§8.C decided). Tests against tmp_path with
synthetic profiles.

*Smoke test:* `pytest tests/test_operator_profile.py -q` (~12 tests).

**`lamill settings operator show` + `edit` CLI
commands.

*Smoke test:* `lamill settings operator show` prints the profile (or
"no profile configured"); `lamill settings operator edit` opens
`$EDITOR`.

**Operator-fit constraints wired into
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

**Documentation update:**
- `docs/CLAUDE.md`: brief on the new `new research` flow + operator
  profile location
- `AI_AGENTS.md`: note the v8.C → v2-research-module migration
- `docs/Prompts.md`: dated H2 entry
- `docs/prd.md`: mark v8.C in v8 tier table as ✅ (renamed from the
  dropped one — see PRD note on the redefinition)

*Smoke test:* `lamill project check sites/portfolio` passes the docs
checks; full suite still passes.

**PRD update** — `docs/prd.md` reflects v8.C shipped, feature-table
entries refreshed.

*Smoke test:* manual review.

---

## 10. Effort estimate

Honest reading, not padded, not shrunk:

| Phase | Commits | Estimated hours | Key risks |
|---|---|---|---|
| Preamble | P0 | 1h | Archive migration script |
| Phase 1 |  9–11h | SerpAPI integration, quota ledger + auto-fallback, error paths, retry logic, test coverage |
| Phase 2 |  10–14h | Gate 2 classifier rules, programmatic-URL regex (hard to get right), verdict-synthesis LLM call wired correctly, schema migration |
| Phase 3 |  5–7h | Operator-fit heuristics, especially the expertise check |
| Docs + cleanup | P4 | 1–2h | |
| **Total** | **16 commits** | **26–35h** | (+1h vs original estimate for quota ledger work) |

The wider range comes from Gate 2 — the classifier rules will need
iteration once real-SERP data shows edge cases. Plan for ≥2 rounds
of refinement after the verdict-synthesis commit lands.

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

---

### 8.2 — v8.E–v8.M · Interpretive verdict + adversarial audit


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

- Standing prompt at `prompts/niche_evaluation_v1.md` (path
  finalized in §10.A). System message; substituted with operator profile
  fields at runtime.

- Model: Claude Sonnet (default model TBD by API availability
  at build time — `claude-sonnet-4-7` or current). Override via `--model
  <id>` flag. Per the 2026-05-16 decision the implementation runs via the
  Claude CLI subprocess (reuses `run_claude_text` from `fix_helpers.py`)
  rather than the Anthropic SDK — avoids a second API-key surface and
  rides the operator's existing Claude subscription quota.

- User message contains a structured payload:
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

- Response is **markdown with strict headers** (not JSON mode):

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

- Parser splits the response on `### <header>` boundaries.
  Required sections: verdict, confidence, reasoning. Missing optional
  sections (e.g. `reductions` on a GO verdict) → empty.

- Substitution validator runs before any LLM call: any
  `{{placeholder}}` left in the rendered prompt → raise (don't send a
  broken prompt to the model).

- Snapshot captures both the rendered prompt AND the response
  + the prompt version + the model id. Reproducibility — old caches can
  be re-rendered with their original prompt for audit/comparison.

### Phase 4b — Adversarial audit pass

- Standing prompt at `prompts/adversarial_audit_v1.md` (drafted
  inline below in §6). System message.

- Model: **must be different** from the Phase 4a model.
  Default: `gpt-4o` via OpenAI SDK (`OPENAI_API_KEY` already in
  `portfolio.env`). Fallback: Gemini Pro. Override: `--audit-model <id>`.
  The "different model" constraint is enforced — if `--model
  claude-sonnet-4-7 --audit-model claude-sonnet-4-7` is passed, the tool
  rejects with an error pointing at the correlated-blind-spot rationale.

- User message contains:
  - The structured payload from Phase 4a (same input)
  - The full Phase 4a markdown response (verbatim, not parsed)

  Open Question §10.C: should the audit see the primary's
  `blind_spot_self_report` section, or be hidden from it?

- Response is markdown with strict headers (mirror Phase 4a):

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

- Same parser shape as Phase 4a. Strict on the three required
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
follow-up commit. The skeleton:

> You are evaluating a SERP cluster for a personal portfolio operator
> deciding whether to ship a new site. Read the gate outputs (mechanical
> classification) AND the raw SERP results, and produce a qualitative
> verdict. The mechanical gates are usually right but miss edge cases —
> use the raw SERP to spot what the rules missed. The operator profile
> tells you who's reading: weight expertise + workflow + cadence
> constraints when deciding GO vs NICHE-DOWN vs NO-GO. Return verdict +
> reasoning + a self-reported list of what you might be wrong about
> (`blind_spot_self_report`) so the audit pass has something to attack.

Full draft to be committed alongside the audit prompt's review iteration.

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

**The existing `run_claude()` subprocess wrapper (v6.E)** uses the
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
example code blocks within the prompt, and the substitution validator
(see Phase 4a above) that checks for unfilled `{{...}}` post-
substitution doubles as a sanity check.

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

### 10.A — Where do `prompts/` live?  *(RESOLVED 2026-05-16)*

**Decision:** option 2 — `prompts/` at the repo root. First-class
status alongside `tests/` and `docs/`; operator edits prompts directly.

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

### 10.B — Audit model default  *(RESOLVED 2026-05-16)*

**Decision:** GPT-4o default. No Gemini integration in v1 — defer the
third-provider HTTP wrapper + third env var. Different-model invariant
is already met with Anthropic + OpenAI.

GPT-4o or Gemini Pro or operator's choice?

Per spec, GPT-4o is recommended default, Gemini fallback. Adding
Gemini support is its own integration (third provider HTTP wrapper,
third env var).

**My recommendation: GPT-4o default, no Gemini integration in v1.**
The "different model" constraint is met with two providers. Defer
Gemini to v2 of this PRD if GPT-4o proves to have a problematic blind
spot.

### 10.C — Does the audit see the primary's `blind_spot_self_report`?  *(RESOLVED 2026-05-16)*

**Decision:** blind to it. The audit's value is uncovering what the
primary missed; visibility into the self-report risks anchoring on the
same concerns. The field is still stored on the snapshot — operator can
read it separately.

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

### 10.D — `--verify` default-on in operator profile?  *(RESOLVED 2026-05-16)*

**Decision:** yes, via the operator profile only (not a sticky state
file). Add `verify_by_default: bool` (default false) to
`[operator]` in `sites/portfolio/lamill.toml`. CLI `--verify`
overrides to true; new `--no-verify` overrides to false. The PRD's
original yaml reference predates v8.D P3 — the profile now lives at
the TOML path; loader picks up the new field on next P3 schema bump.

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

### 10.E — Audit failure handling  *(RESOLVED 2026-05-16)*

**Decision:** option 2 — proceed with primary-only on audit failure.
Surface the failure prominently in output; record `audit_pass.error`
in the snapshot. Don't waste the primary's verdict because the audit
hit a transient API issue.

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

### 10.F — Snapshot retention for audit pass  *(RESOLVED 2026-05-16)*

**Decision:** same as primary — kept forever, git-tracked per v8.D
PRD §8.E. Audit responses are part of the verdict's provenance.

Same as primary (kept forever, git-tracked per v2 PRD §8.E)?

**My recommendation: yes.** No reason to treat audit differently.
Audit responses are part of the verdict's provenance.

### 10.G — Template-substitution engine  *(RESOLVED 2026-05-16)*

**Decision:** custom `{{var}}` regex. No new dep; no curly-brace
collision with code-block examples in prompts; substitution validator
(the substitution validator in Phase 4a) is the natural place to
enforce no-unfilled-placeholders.

Per implementation risks §8.7 — Jinja2, `str.format()`, or custom
`{{var}}` regex?

**My recommendation: custom `{{var}}` regex** (no new dep, no curly-
brace gotcha in code-block examples).

### 10.H — `--model` and `--audit-model` flag override behavior  *(RESOLVED 2026-05-16)*

**Decision:** option 1 — reject loudly with a suggested different
model in the error message. Allowing same-model defeats the
correlated-blind-spot rationale that justifies the audit pass.

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

### 10.I — Prompt versioning policy  *(RESOLVED 2026-05-16)*

**Decision:** bump to `_v2.md` only when the change would meaningfully
alter the verdict on cached data. Typo / wording / formatting tweaks
stay at `_v1.md`. New failure-mode checks, structural instruction
changes, or output-shape edits bump the version. Snapshots store
`prompt_version`; mismatch with the current `_vN.md` is treated as
"stale verdict — re-render via `--no-cache=interpretive`."

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

### 10.J — Snapshot field for cumulative cost tracking  *(RESOLVED 2026-05-16)*

**Decision:** yes — record `estimated_cost_usd` on each pass
(`interpretive_pass.estimated_cost_usd` and
`audit_pass.estimated_cost_usd`). Pulled from provider response headers
when available, estimated from token counts otherwise. Cheap to add;
unblocks a future cost-ledger aggregation without re-fetching.

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

**Commit-message convention:** every v8.E commit subject is
`portfolio: v8.E — <what landed>`. No sub-phase identifiers in
the subject — the description names the wedge (preamble, primary
pass, audit, reconciliation, polish, docs) and git history orders
them. The strict two-level versioning rule (`AI_AGENTS.md` §
Versioning) forbids `vN.X.Y` prefixes in commit subjects.

### Preamble (✅ shipped 2026-05-16)

- Created `prompts/` directory at repo root with a README
  pointing at the schema convention (`<purpose>_v<N>.md`).
- Drafted `prompts/niche_evaluation_v1.md` (full text).
- Drafted `prompts/adversarial_audit_v1.md` (finalized from the §6 inline).
- `src/portfolio/prompt_loader.py`: `load_prompt(name)`,
  `render_prompt(template, **vars)` with `{{var}}` substitution +
  validator that raises on unfilled placeholders. Unit tests.
- `src/portfolio/fix_helpers.py:run_claude_text()` — Claude CLI
  text-capture helper. LLM-call substrate for the primary pass; no
  Anthropic SDK / no new env var (runs via the operator's existing
  Claude subscription via subprocess).

(The shipped commits' subject lines pre-date the 2026-05-16
two-level enforcement and stay as-is in `git log`; future v8.E
commits use the convention above.)

### Phase 4a — primary pass (next up)

- **Payload assembly** — `src/portfolio/interpretive_pass.py`:
  `build_payload(cluster, gates, operator_profile, operator_fit) -> dict`
  shaped per Phase 4a spec. Unit tests on a synthesized gate result.

- **Response parser** — same module: `parse_verdict(markdown_text)
  -> ParsedVerdict` (dataclass with `verdict`, `confidence`,
  `reasoning`, `moat_required`, `moat_prompt`, `reductions`,
  `operator_fit_warnings`, `blind_spot_self_report`). Strict on the
  three required sections; permissive on the optional ones.

- **Primary-pass runner** — same module:
  `run_primary_pass(cluster, gates, operator_profile, operator_fit)
  -> ParsedVerdict`. Renders the prompt, calls `run_claude_text`,
  parses the response, returns the dataclass. Failure modes: render
  error (raises), CLI error (raises with the underlying
  `ClaudeTextResult.error`), parse error (raises with the offending
  section name).

  *Smoke:* `pytest tests/test_interpretive_pass.py -q` with mocked
  `run_claude_text` returning canned markdown responses.

- **Orchestrator wiring** — call `run_primary_pass` from the
  `new research` command after the mechanical gates land. Snapshot
  schema bumped to carry `primary_verdict`, `rendered_prompt`,
  `prompt_version`, `model_id`. Default mode now ends at Phase 4a.

  *Smoke:* `lamill new research "ev charger installation cost"`
  runs end-to-end with primary verdict shown.

### Phase 4b — audit pass

- **OpenAI audit-pass runner** — `src/portfolio/audit_pass.py`:
  `run_audit_pass(cluster, gates, operator_profile, operator_fit,
  primary_response) -> ParsedAudit`. Renders
  `adversarial_audit_v1.md`, calls the existing OpenAI client (the
  one already in use for `new suggest` brainstorm), parses the
  markdown response.

  *Smoke:* `pytest tests/test_audit_pass.py -q`.

- **Same-model rejection** — if `--model` and `--audit-model`
  resolve to the same model, error early with the
  correlated-blind-spot rationale.

  *Smoke:* `lamill new research "x" --verify --model X --audit-model X`
  errors with helpful message.

- **`--verify` flag wired** — output rendering for agree / partial /
  disagree paths.

  *Smoke:* Run on a cluster where primary and audit agree (verify
  output shows "✓ Audit agrees"); run on a cluster known to provoke
  partial disagreement (verify output shows audit concerns).

### Phase 4c — reconciliation

- **Reconciliation logic** — `src/portfolio/reconciliation.py`:
  pure-logic reconciliation per §4 Phase 4c spec. No LLM calls. Unit
  tests for each of the three branches (full / partial / disagree).

  *Smoke:* `pytest tests/test_reconciliation.py -q`.

- **Reconciliation wiring** — into orchestrator. Output includes
  `final_verdict` field; REVIEW_REQUIRED renders correctly.

  *Smoke:* `lamill new research "<known-disagreement-topic>" --verify`
  emits REVIEW_REQUIRED banner.

### Phase 4 polish

- **Cost-estimate fields** — added to snapshot (resolved §10.J).
  `run_claude_text` already returns `cost_usd`; OpenAI cost pulled
  from provider response headers when present.

  *Smoke:* Snapshot inspection shows non-zero `estimated_cost_usd`.

- **`verify_by_default` honoring** — read from
  `sites/portfolio/lamill.toml [operator]` (resolved §10.D).
  `--no-verify` flag added for override.

  *Smoke:* With `verify_by_default = true` in the operator profile,
  `lamill new research <x>` runs verify; `--no-verify` skips it.

- **Granular cache invalidation** — `--no-cache=interpretive` and
  `--no-cache=audit` for re-running individual passes on cached
  SERP data.

  *Smoke:* Run, modify cached snapshot's interpretive section,
  re-run with `--no-cache=interpretive` — interpretive re-runs,
  SERP doesn't.

### Phase 4 docs

- **Docs update** — `docs/CLAUDE.md`, `AI_AGENTS.md`,
  `docs/Prompts.md`, `docs/prd.md` reflect Phase 4 shipped. Add
  "when to use --verify" guidance to `lamill new research --help`.

  *Smoke:* `lamill project check sites/portfolio` passes docs checks.

---

## 12. Effort estimate

Honest reading. Assumes v2 (research-module-v2.md) is shipped first.

| Wedge | Hours | Key risk |
|---|---|---|
| Preamble ✅ | 2-3h | Shipped 2026-05-16 |
| Primary pass (payload + parser + runner + wiring) | 4-5h | Markdown parser robustness across CLI sessions / model styles |
| Audit pass (OpenAI runner + same-model reject + --verify) | 4-5h | Output rendering for all three reconciliation branches |
| Reconciliation (logic + wiring) | 2-3h | Pure logic, but the rendering for REVIEW_REQUIRED needs to be right (it's the high-signal path) |
| Polish (cost ledger + verify_by_default + granular cache) | 3-4h | Cost ledger field, verify_by_default plumbing, granular cache flags |
| Docs | 1h | |
| **Total** | **16-21h remaining** | (down from 20-26h after CLI-subprocess decision removed the LLM-clients/Anthropic-SDK wedge) |

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

## 14. Approval  *(approved 2026-05-16)*

- [x] Open questions §10.A–J resolved (2026-05-16 — author's
      recommendations accepted across the board)
- [x] Drafted audit prompt reviewed (§6 inline accepted as
      `prompts/adversarial_audit_v1.md`; will be revised after first
      real audit runs ship)
- [x] Effort estimate accepted (20–26h, 14 commits)
- [x] Author signoff

Implementation may proceed. v8.D shipped 2026-05-16; v8.E preamble
shipped 2026-05-16 (prompts directory, niche-evaluation prompt,
adversarial-audit prompt, prompt loader / renderer). Primary-pass
orchestration is the next wedge — see §11.

---

---

### 8.3 — v9.A · lamill.toml per-site deploy declaration


## 1. Problem statement

**Current state.** Determining "what platform does this site deploy
to?" requires triangulating three separate signals:

1. **Repo config files** — `wrangler.jsonc` / `vercel.json` /
   `netlify.toml`. Present for modern platforms, absent for
   HostGator / WordPress / custom-VPS sites.
2. **DNS lookup** — A records or CNAME targets. Tells you what's
   *actually* serving at the edge, not what was intended.
3. **HTTP probe** — `Server:` header, cert issuer, response shape.
   Same — tells you actual, not intended.

When these disagree (lamill.io: wrangler.jsonc said CF Workers, DNS
said Vercel, Vercel was actually serving), the operator has to read
the disagreement and decide which is the canonical declaration.

**What's broken.**
1. **No declaration mechanism for HostGator, WordPress, custom
   VPS, or static FTP-deployed sites.** There's nothing in the repo
   that says "this is deployed at cPanel account X" or "this is
   a WordPress install at example.com." Without that, `lamill
   project diagnose` can only guess via DNS heuristics.
2. **Drift between intent and actual is invisible until probed.**
   The repo's config file declares one platform; the DNS may have
   moved. Today the tool has to do live network calls every time
   to compare.
3. **Cross-site queries can't answer "show me all sites on Vercel."**
   `fleet repos` doesn't know which platform each site targets.

**What good looks like.**
- Every `sites/<domain>/` repo has a `lamill.toml` at root with a
  `[deploy]` section declaring platform, account/team, custom
  domains, and (for hosts without canonical configs) hosting
  breadcrumbs.
- `lamill new bootstrap` writes it as part of scaffolding.
- `lamill project set-deploy` lets the operator manually create or
  edit it on existing sites.
- `lamill fleet repos --add-deploy-declarations` does a one-time
  bulk migration for existing sites — infers from existing platform
  configs where possible, surfaces manual-entry-required cases.
- Downstream tools (`project diagnose`, `fleet repos`, conformance
  checks, future HostGator integration) read from this one file.

---

## 2. Goals and non-goals

**Goals**

- Schema for `lamill.toml` covering the common platforms + an
  extension slot for HostGator / custom hosts.
- `lamill new bootstrap` writes the file as part of scaffolding —
  inferred from `--stack` with a sensible default.
- `lamill project set-deploy <name> <platform>` to manually create or
  update on existing sites.
- `lamill project show-deploy <name>` to inspect.
- `lamill fleet repos --add-deploy-declarations` migration for
  existing sites — safe-by-default (refuses ambiguous cases).
- A `LamillToml` parser/writer module reused by future tools.

**Non-goals** (deferred, named only)

- **Drift detection** (declared vs DNS-actual) — v11.B
- **Conformance checks** (`CHECK_xxx deploy-declared`,
  `CHECK_xxx deploy-drift`) — v11.B
- **HostGator API integration** (cPanel pull, inventory sync) —
  v11.C
- **Deploy abstraction** (`new deploy` writes to HostGator via SFTP)
  — v11.D
- **Multi-platform site declarations** (apex on platform A, www on
  platform B) — could go in v9.A schema but defer the use case
  until a real site needs it
- **Validation against live state** (does the declared cPanel user
  actually exist?) — out of scope for read-only declaration

---

## 3. User journey

### Scenario A — bootstrapping a new site

```
$ lamill new bootstrap newdomain.com --stack astro

Scaffolding sites/newdomain.com/...
  ✓ git init
  ✓ package.json (astro template)
  ✓ AI_AGENTS.md, docs/{prd.md, CLAUDE.md, Prompts.md, growth.md}
  ✓ Makefile (forwards to central builder)
  ✓ public/{robots.txt, sitemap.xml}
  ✓ lamill.toml — platform=cf-pages (inferred from --stack astro)
    └─ edit `sites/newdomain.com/lamill.toml` to override platform

Conformance: 38 pass / 4 fail / 11 skipped
  ✗ CHECK_010 has-tests
  ✗ CHECK_022 clean-working-tree (initial commit needed)
  ✗ CHECK_024 has-ci-workflow
  ✗ CHECK_036 astro-version-ok (skipped — Astro project, version check skipped)

Next: lamill new deploy newdomain.com
```

The `lamill.toml` was written automatically; operator can edit it
before `new deploy`.

### Scenario B — manually setting deploy on an existing site

```
$ lamill project set-deploy hybridautopart.com hostgator

Looking up sites/hybridautopart.com/...
  No `lamill.toml` found — will create.

Platform: hostgator. Hostgator requires the [hosting] block.
Enter HostGator account context (or press Enter to skip):
  cPanel user (e.g. vikt): vikt
  cPanel URL (e.g. https://server.hostgator.com:2083): https://gator4045.hostgator.com:2083
  FTP user (e.g. vikt@example.com): vikt@hybridautopart.com
  public_html path (e.g. /home/vikt/public_html/example.com/):
    /home/vikt/public_html/hybridautopart.com/

Wrote sites/hybridautopart.com/lamill.toml:

  [deploy]
  platform = "hostgator"
  production_branch = "main"
  auto_deploy = false
  custom_domains = ["hybridautopart.com"]

  [hosting]
  cpanel_user = "vikt"
  cpanel_url = "https://gator4045.hostgator.com:2083"
  ftp_user = "vikt@hybridautopart.com"
  public_html_path = "/home/vikt/public_html/hybridautopart.com/"

Note: file written to working tree. Commit + push to make it
persistent in the repo.
```

### Scenario C — reading the declaration

```
$ lamill project show-deploy hybridautopart.com

hybridautopart.com — declared deployment
  source: sites/hybridautopart.com/lamill.toml (committed)
  platform:    hostgator
  account:     —
  branch:      main
  auto-deploy: no
  domains:     hybridautopart.com
  hosting:
    cpanel:    vikt @ https://gator4045.hostgator.com:2083
    ftp:       vikt@hybridautopart.com
    path:      /home/vikt/public_html/hybridautopart.com/

  Last edited: 2026-05-14 via `project set-deploy` (per git log)
  Drift check: deferred (v11.B)
```

### Scenario D — bulk migration of existing sites

```
$ lamill fleet repos --add-deploy-declarations --dry-run

Scanning sites/* for existing platform configs...

  ✓ airsucks.com         wrangler.jsonc      → would write platform = "cf-workers"
  ✓ lamill.io            (none — but vercel.json + dns=vercel) → platform = "vercel"
  ✓ calcengine.site      netlify.toml        → would write platform = "netlify"
                                                ⚠ but DNS resolves to Vercel — manual review needed
  ✓ hybridautopart.com   (none — likely HostGator / WordPress)  → manual entry required
  ✓ donready.xyz         wrangler.jsonc      → would write platform = "cf-workers"
  ⚠ swiftly.co.in        archived (TOMBSTONE.md) — skipping
  ...

Summary: 14 unambiguous · 3 manual-review · 2 manual-entry · 3 skipped (archived)

Re-run without --dry-run to write the 14 unambiguous lamill.toml files.
Manual-review and manual-entry cases need `project set-deploy <name>`.
```

The migration is **safe by default** — only writes when the platform
config is single + unambiguous. Anything else is surfaced for the
operator to handle.

---

## 4. Functional requirements

### 4.1 — Schema

The full proposed schema:

```toml
# lamill.toml — declared deployment for sites/<domain>/.
# Source of truth for "where does this site deploy?" Compared against
# DNS + live HTTP to detect drift (v11.B).

# Schema version. Bumped when the parser becomes incompatible with
# older files. Old files invalidated, not migrated.
schema = "lamill-toml-v1"

[deploy]
# REQUIRED — one of:
#   cf-pages | vercel | netlify | cf-workers | hostgator
#   github-pages | custom | none
platform = "hostgator"

# OPTIONAL — which account/team at the platform.
# Used by future tools to disambiguate when an operator has multiple
# accounts (e.g. personal Vercel + work Vercel).
account = "vik@hostgator"

# OPTIONAL — production branch. Default: "main".
production_branch = "main"

# OPTIONAL — does push-to-main trigger a build?
# Default: true for platforms with native git integration (CF Pages,
# Vercel, Netlify, GitHub Pages); false for hostgator / custom.
auto_deploy = false

# OPTIONAL — custom domains the deploy serves.
# Free-form list; the operator declares what this deploy is responsible
# for. Doesn't have to be exhaustive (Vercel internal preview domains
# are noise).
custom_domains = ["hybridautopart.com"]


[hosting]
# OPTIONAL — only used when platform doesn't have a canonical config
# file (hostgator, custom, github-pages). Provides the breadcrumbs
# needed to reach the actual deploy surface.

# cPanel breadcrumbs (when platform = "hostgator" or "custom" with cPanel):
cpanel_user = "vikt"
cpanel_url = "https://gator4045.hostgator.com:2083"

# FTP/SFTP breadcrumbs:
ftp_host = "ftp.hybridautopart.com"
ftp_user = "vikt@hybridautopart.com"
ftp_port = 21

# Where the public files live on the host:
public_html_path = "/home/vikt/public_html/hybridautopart.com/"


[notes]
# OPTIONAL — free-form prose for special cases (transition states,
# deploy quirks, manual-only deploy steps, etc.).
text = """
Currently in WordPress; planning React migration in v2.
Backups via cPanel UI; no automated backup yet.
"""

[operator]
# OPTIONAL — global operator profile. In practice ONLY filled on
# `sites/portfolio/lamill.toml` (the tool's own repo). Other sites
# omit this section. Used by v8.D Phase 3 research gates.
expertise = ["SEO and programmatic content", "Python CLI tooling"]
workflow_preference = "builder"   # builder | writer | mixed
motivation_cadence  = "weekly"    # weekly | monthly | quarterly
```

**Defaults applied if section absent:**
- `[deploy]` is required; the file is invalid without it.
- `[hosting]` is optional. Required if `platform ∈ {hostgator, custom}`.
- `[notes]` is optional.
- `[operator]` is optional. Only the portfolio repo's `lamill.toml`
  fills it; every other site omits the section. Loader: read
  `<sites>/portfolio/lamill.toml` and pull `[operator]` keys; defaults
  to `expertise=[], workflow_preference="mixed", motivation_cadence="monthly"`
  when the section is absent or the file is missing.

### 4.2 — Platform enum

| Value | Canonical config in repo | Notes |
|---|---|---|
| `cf-pages` | wrangler.toml or wrangler.jsonc | Cloudflare Pages (Pages mode) |
| `cf-workers` | wrangler.jsonc | Cloudflare Workers (server mode) |
| `vercel` | vercel.json (optional) | Vercel auto-deploy from Git |
| `netlify` | netlify.toml | Netlify auto-deploy |
| `github-pages` | (none — GH-side config) | Static via repo settings |
| `hostgator` | (none) | Shared hosting; requires `[hosting]` |
| `custom` | (none) | VPS / dedicated / unusual setup; requires `[hosting]` |
| `none` | (none) | Site is not deployed (CLI, library, scratch project) |

### 4.3 — Parser module (`src/portfolio/lamill_toml.py`)

```python
@dataclass
class DeployBlock:
    platform: str
    account: str | None = None
    production_branch: str = "main"
    auto_deploy: bool | None = None         # default depends on platform
    custom_domains: list[str] = field(default_factory=list)

@dataclass
class HostingBlock:
    cpanel_user: str | None = None
    cpanel_url: str | None = None
    ftp_host: str | None = None
    ftp_user: str | None = None
    ftp_port: int | None = None
    public_html_path: str | None = None

@dataclass
class LamillToml:
    schema: str = "lamill-toml-v1"
    deploy: DeployBlock
    hosting: HostingBlock | None = None
    notes: str | None = None

def load(repo_path: Path) -> LamillToml | None:
    """Returns LamillToml if sites/<repo_path>/lamill.toml exists,
    else None. Raises ParseError on malformed file."""

def write(repo_path: Path, payload: LamillToml) -> None:
    """Atomic write of lamill.toml. Preserves the file's existing
    comments/formatting if it already existed (uses tomlkit if
    needed; otherwise plain tomllib + a clean re-render)."""

def infer_from_existing_configs(repo_path: Path) -> DeployBlock | None:
    """Used by the migration command. Reads wrangler.jsonc /
    vercel.json / netlify.toml in repo and returns a best-guess
    DeployBlock. None if no recognizable config found."""
```

**Format choice:** TOML, parsed via stdlib `tomllib` (Python 3.11+).
Round-trip writing uses `tomli-w` (small new dep, ~15KB, no
transitive deps) to preserve quoting. **No comments preserved on
round-trip** — accepted limitation; the operator's edits via
`$EDITOR` are direct file writes that don't go through this path.

### 4.4 — CLI surface

**New commands:**

```
lamill project set-deploy <name> <platform>
  Manually create or update sites/<name>/lamill.toml.
  Interactive prompts for required fields based on platform.
  --non-interactive: refuse interactive prompts; fail if any
                     required field is missing.
  --account <X>      pre-fill account value
  --branch <X>       pre-fill production_branch (default: main)

lamill project show-deploy <name>
  Render sites/<name>/lamill.toml in a human table.
  --json: emit raw lamill.toml contents as JSON.

lamill fleet repos --add-deploy-declarations
  Migration: walk every sites/<domain>/ that doesn't have a
  lamill.toml, infer platform from existing configs, write the
  file. Safe-by-default — only writes for unambiguous cases.
  --dry-run: show what would be written, don't write.
  --include-ambiguous: also write for ambiguous cases (DNS
                       conflicts with config — uses config's
                       declaration; surfaces a warning).
```

**Modified commands:**

```
lamill new bootstrap <domain>
  Now writes sites/<domain>/lamill.toml as part of scaffolding.
  Platform inferred from --stack:
    --stack astro  → platform = "cf-pages"   (current default deploy target)
    --stack vite   → platform = "cf-pages"
  --platform <X>: override the inferred default.
```

### 4.5 — Bootstrap defaults

| `--stack` | Default `platform` in lamill.toml |
|---|---|
| `astro` | `cf-pages` |
| `vite` | `cf-pages` |
| (no stack — fresh genai-export) | `cf-pages` |

The default reflects the current v3.C deploy convention. Operator can
override via `--platform <X>` at bootstrap time, or via `project
set-deploy` later.

**Why `cf-pages` not `vercel`?** v3.C's deploy abstraction shipped
with CF Pages as the canonical target. Most existing portfolio sites
use it. Sites that use Vercel (lamill.io, lamillrentals.com,
keralavotemap.site) are explicit migrations; the default stays at the
shipped convention.

### 4.6 — Migration command behavior

`lamill fleet repos --add-deploy-declarations` walks every
`sites/<dir>/` and classifies into:

| Classification | Behavior |
|---|---|
| Has `lamill.toml` already | Skip; report "already declared" |
| `wrangler.jsonc` present, no other platform config | Write `platform = "cf-workers"` (or `cf-pages` based on the wrangler.jsonc's `pages_build_output_dir` field) |
| `vercel.json` present, no other platform config | Write `platform = "vercel"` |
| `netlify.toml` present, no other platform config | Write `platform = "netlify"` |
| Multiple platform configs (drift case) | **Refuse without `--include-ambiguous`**; surface for manual review |
| No platform configs, archived (`TOMBSTONE.md` or category in `IGNORE_CATEGORIES`) | Skip; report "archived" |
| No platform configs, not archived | Surface for manual entry via `project set-deploy` |

In `--include-ambiguous` mode, the migration uses the
filesystem-config-detection rules (vercel.json > wrangler.jsonc >
netlify.toml priority) and writes with a `notes.text` warning about
the conflict.

---

## 5. Data model

### lamill.toml at `sites/<domain>/lamill.toml`

Schema documented in §4.1.

### Updates to existing data

- **`data/portfolio.json`**: NO changes. The per-site declaration is
  the source of truth. `portfolio.json` stays as the cross-site
  inventory view.
- **`fleet repos` output**: gains a new column showing the declared
  platform (from `lamill.toml`). When no lamill.toml exists, column
  shows `—`.
- **`fleet repos --json` shape**: each site entry gains:
  ```json
  "deploy_declaration": {
    "exists": true,
    "platform": "vercel",
    "account": null
  }
  ```

### Conformance checks (deferred to v11.B)

The natural follow-on checks are:

- `CHECK_043 has-lamill-toml`: file exists at repo root. Severity:
  info. Skipped on archived sites.
- `CHECK_044 lamill-toml-valid`: file parses cleanly + has required
  fields. Severity: error.
- `CHECK_045 lamill-toml-platform-matches-config`: declared platform
  agrees with any platform-config file present (e.g. if
  `wrangler.jsonc` exists, declared platform should be `cf-pages` or
  `cf-workers`). Severity: warn (drift signal).

**Out of v9.A scope** — design listed here so the schema choice
doesn't paint v11.B into a corner.

---

## 6. Open questions

### 6.A — TOML writer library

Three options:

1. **`tomllib` (stdlib, read-only) + manual write via f-strings.**
   No dep, but writing is fragile (manual quoting, no preserved
   comments).
2. **`tomli-w` (~15KB, no transitive deps).** Stdlib-equivalent for
   writing. No comment preservation on roundtrip.
3. **`tomlkit` (~80KB).** Full round-trip with comments + formatting
   preserved. Bigger dep but matches "human-editable file" goal.

**My recommendation: tomli-w.** Operator edits go through `$EDITOR`
on the raw file — comments are preserved by hand. Tool-side writes
(`set-deploy`, migration) only happen on fresh files or full
re-renders, so comment preservation isn't load-bearing.

Tomlkit is heavier than the value it provides at personal scale.

### 6.B — Inference priority when multiple platform configs exist

Site has `wrangler.jsonc` AND `vercel.json` (lamill.io case). Which
wins in the migration?

Three options:

1. **Refuse — surface for manual review.** Safe but creates work.
2. **Prefer the one that matches DNS.** Smart but requires a DNS
   call per site during migration.
3. **Priority order: vercel.json > wrangler.jsonc > netlify.toml.**
   Arbitrary but deterministic.

**My recommendation: option 1.** The migration is a one-time
operation. The operator can handle ~5 ambiguous cases manually with
better info than an automated guess.

`--include-ambiguous` lets the operator skip the manual step at the
cost of a possibly-wrong default.

### 6.C — Bootstrap default platform

Spec says `cf-pages` per current v3.C convention. But the recent
move to Vercel for lamill.io / lamillrentals.com suggests Vercel may
be the personal default going forward.

**My recommendation: keep cf-pages as the default for now.**
Current convention; existing bootstrap output is stable. If the next
3-4 sites you bootstrap all end up on Vercel, that's the signal to
switch the default. Don't pre-optimize.

**Your call:** stay with cf-pages, switch to Vercel, or no default
(require `--platform` at bootstrap time)?

### 6.D — Should `set-deploy` commit + push automatically?

Two options:

1. **Just write the file.** Operator commits when they're ready.
2. **Write + commit + push automatically.**

**My recommendation: just write.** Same posture as `project
set-launched` — it edits `portfolio.json` and doesn't commit. The
operator decides when to commit + push.

### 6.E — Schema version handling

When the schema bumps (`lamill-toml-v1` → `v2`), what happens to
existing files?

1. **Auto-migrate.** Tool detects v1 file, writes v2 in place.
2. **Reject loudly.** Tool refuses to load v1 files; operator must
   migrate manually or via a `lamill project upgrade-lamill-toml`
   command.
3. **Read v1 with fallback defaults; never write v1.** Tolerant on
   read; strict on write.

**My recommendation: option 3.** Operator-friendly without
introducing complex migration paths. Schema bumps should be rare
for a personal tool; we can add migration commands when needed.

### 6.F — What about WordPress sites that have no project directory under sites/?

Some sites might be WordPress installs that don't live in
`sites/<domain>/` at all — they're WordPress installs at HostGator
that lamill knows about via `portfolio.json` but has no local
checkout for.

**My recommendation: skip them in v11.A.** Sites without a local
repo can't have a `lamill.toml` in the repo. v11.C (HostGator
integration) will surface them differently.

### 6.G — Multi-deploy declarations

Some sites might serve apex from one platform and `www.*` from
another (rare; usually a transition state). Should `lamill.toml`
support multi-platform decl?

**My recommendation: not in v11.A.** Single platform per site for
now. If a multi-deploy case appears in your portfolio, we add a
follow-on PRD to extend the schema. YAGNI for now.

### 6.H — Where does `account` come from for new bootstraps?

If `--platform cf-pages`, what account/team is the default?

Two options:

1. **Read from operator profile** (the future v8.D Phase 3 `~/.lamill/operator.yaml`).
2. **Leave blank, require manual fill via `set-deploy`.**

**My recommendation: option 2 for v11.A.** Operator profile isn't
shipped yet. When it is, `bootstrap` reads it and populates
`account` from there. For now, blank with a `# TODO` comment in the
generated file.

---

## 7. Implementation plan (commits + smoke tests)

### Preamble

**P0 (already-done equivalent):** No archiving needed; this is
purely additive. New files in new locations.

### Phase 1 — schema + parser

- `src/portfolio/lamill_toml.py`: dataclasses for
`DeployBlock`, `HostingBlock`, `LamillToml`. `load()` returns
`LamillToml | None`. Pure parser, no CLI. New dep `tomli-w` added
to `pyproject.toml`.

*Smoke test:* `pytest tests/test_lamill_toml.py -q` (~15 tests:
load valid file, load missing file, load malformed, schema
validation, all platform enum values, hosting-required when
platform=hostgator).

- `write()` function with atomic tmpfile + rename. Tests
for round-trip determinism (write → load → write → compare).

*Smoke test:* `pytest tests/test_lamill_toml.py -q` extended.

- `infer_from_existing_configs()`: reads wrangler.jsonc /
vercel.json / netlify.toml and returns a `DeployBlock | None`.
Tests cover each platform + the multiple-config "ambiguous" return.

*Smoke test:* `pytest tests/test_lamill_toml.py -q` extended.

### Phase 2 — CLI commands

- `lamill project set-deploy <name> <platform>` command.
Interactive prompts when stdin is a TTY; non-interactive failure
when not.

*Smoke test:* `lamill project set-deploy airsucks.com cf-workers
--non-interactive` writes the file; with hostgator + no
`--non-interactive`, runs interactive prompts.

- `lamill project show-deploy <name>` command. Pretty
table renderer + `--json`.

*Smoke test:* `lamill project show-deploy airsucks.com` shows
declared platform table; `--json` emits raw payload.

### Phase 3 — Bootstrap integration

- `lamill new bootstrap` writes lamill.toml as part of
scaffolding. Platform inferred from `--stack` (cf-pages default).
`--platform <X>` flag overrides.

*Smoke test:* `lamill new bootstrap testsite.com` writes
`lamill.toml` with `platform = "cf-pages"`. With `--platform vercel`
overrides.

### Phase 4 — Migration

- `lamill fleet repos --add-deploy-declarations
[--dry-run] [--include-ambiguous]`. Walks every `sites/<dir>/`,
classifies, writes safe cases.

*Smoke test:* `lamill fleet repos --add-deploy-declarations
--dry-run` shows ~14 unambiguous + ~3 ambiguous + ~2 manual-entry
breakdown on current fleet (matches the example output in §3).

### Final commit

- Documentation update:
- `docs/CLAUDE.md`: brief on `lamill.toml`
- `AI_AGENTS.md`: note the new file convention
- `docs/Prompts.md`: dated H2 entry
- `docs/prd.md`: mark v11.A ✅; add v11.B/C/D rows

*Smoke test:* Manual review.

---

## 8. Effort estimate

Honest reading.

| Phase | Commits | Hours | Risk |
|---|---|---|---|
| Phase 1 (schema + parser) |  4-5h | tomli-w roundtrip determinism; inference logic |
| Phase 2 (CLI) |  3-4h | Interactive prompt UX for hostgator |
| Phase 3 (bootstrap) |  1-2h | Wire into existing bootstrap flow |
| Phase 4 (migration) |  3-4h | Classification rules; ambiguous-case handling |
| Final |  1h | |
| **Total** | **8 commits** | **12-16h** | |

Wider range mostly comes from Phase 4 — the migration logic has to
handle the messy real-world cases without auto-corrupting deploys.

---

## 9. Forward links

After v11.A ships, the natural follow-ons:

- **v11.B** — Drift detection. Conformance checks (`CHECK_043/044/045`)
  that compare `lamill.toml` declarations against DNS + live HTTP
  to surface drift. Builds on `project diagnose`'s existing
  inference. ~6-8h.
- **v11.C** — HostGator API integration. cPanel pull of domains /
  WordPress installs / disk usage. Auto-writes `lamill.toml` for
  HostGator-hosted sites discovered via cPanel. ~8-10h.
- **v11.D** — SFTP deploy abstraction. `lamill new deploy <domain>`
  reads `lamill.toml`, dispatches to the right deploy target
  (existing CF Pages logic OR new SFTP-via-FileZilla-style logic).
  Adds a write surface. ~10-12h.

Each gets its own PRD when its time comes.

---

## 10. Approval

This PRD is **draft, awaiting review**. Before any code lands:

1. Resolve the 8 open questions in §6.
2. Confirm the schema (§4.1) is right shape.
3. Confirm the 12-16h effort estimate is acceptable.

Sign off:

- [ ] Open questions §6.A–H resolved
- [ ] Schema reviewed
- [ ] Effort estimate accepted
- [ ] Author signoff

---

---

### 8.4 — v10.A · `fleet hosting` — fleet-wide Vercel/CF deploy state


## 1. Problem statement

**Current state.** The tool infers each site's deploy platform from
filesystem markers (`wrangler.toml` / `vercel.json` / package.json
deps — see `project.py:25-30`) and from DNS heuristics during
`project diagnose`. It never asks Vercel or Cloudflare directly.
That leaves three blind spots:

1. **Stale deploys.** A site can have a clean `vercel.json` checked
   in and a Vercel project that hasn't built successfully in months.
   Today nothing surfaces that — the operator only notices when a
   visitor reports a broken URL.
2. **Forgotten projects.** Older sites that were spun up, deployed
   once, then ignored. Still consuming a Vercel project / CF Pages
   project slot; status invisible.
3. **Build regressions.** A push that breaks the build → Vercel /
   CF Pages quietly leaves the previous version live (`READY`) but
   the latest deploy is `ERROR`. `project check` shows the local
   repo as clean and a casual look at the live URL works fine.
   Fleet view should call this out — *something* about this site
   regressed.

**What's broken.**

1. No fleet-wide view of "which sites deployed successfully recently"
   vs. "which sites are erroring on every push" vs. "which sites
   haven't deployed in months."
2. The deploy-platform inference (from local files) is intent, not
   reality. A site could declare Vercel locally but actually serve
   from Cloudflare Pages (or vice versa, after a migration). Without
   walking the provider APIs, the tool can't see the drift.
3. The operator has to log into each platform dashboard to check
   build status. Doesn't scale past ~5 sites.

**What good looks like.**

- One `lamill fleet hosting` command that returns a per-domain
  status table covering every live-site/forwarder domain.
- Per-row: provider, last deploy status, last successful deploy
  timestamp, consecutive-failure count.
- Status emoji that compresses the four dimensions into a glance:
  ✓ healthy, ⚠ degraded, ✗ failing, 💤 stale, — no project found.
- Cached like `fleet seo` — daily snapshot in `data/hosting/`; cache
  hit by default; `--refresh` re-walks the APIs.
- Scoped to live-site/forwarder domains only (skip parked/dead).
- Read-only — no triggering of deploys, no writes. Existing `new
  deploy` covers the create-and-write surface; this is the read-back.

---

## 2. Goals and non-goals

**Goals**

- Add `lamill fleet hosting` as a peer of `fleet seo` — same shape:
  read-only, cached, refreshable, emoji table.
- Walk both Vercel and Cloudflare Pages APIs using existing tokens
  (no new credentials beyond `VERCEL_TOKEN`, which gets added to
  `apikeys.KNOWN_KEYS`).
- Match each Vercel / CF Pages project to a fleet domain by the
  project's configured custom domain — server-side truth, not
  local-file inference.
- Persist results to `data/hosting/<YYYY-MM-DD>.json` mirroring
  `data/seo/` shape. Snapshot is git-tracked (same convention as
  the other layers) so trend analysis later can read history.
- Surface a deploy-platform conflict signal when the same domain
  appears on both providers (drift).

**Non-goals** (deferred — listed for forward-reference, not designed
in v12.A)

- Triggering deploys (write surface; `new deploy` already exists for
  the bootstrap-and-create path).
- Netlify / GitHub Pages / direct-Worker / HostGator / Render walkers
  (designed as pluggable providers from v1 but only Vercel + CF Pages
  ship in v12.A).
- Cost / pricing reports.
- Auto-flagging consecutive failures as a `fleet focus` signal.
- Integration with v11.A `lamill.toml` declarations (separate PRD
  once v11.A ships — `fleet hosting` reads server truth, `lamill.toml`
  declares intent; comparing the two is the drift detector).
- Real-time webhooks (Vercel / CF can both push deploy events but
  v12.A is pull-only).

---

## 3. User journey

```text
$ lamill fleet hosting
[dim]Reading data/hosting/2026-05-15.json (1.2h old · use --refresh to re-fetch)[/]

Domain                Provider          Status  Last Success           Failures
airsucks.com          cloudflare-pages  ✓       2026-05-14 16:12 UTC   0
calcengine.site       vercel            ✓       2026-05-13 09:44 UTC   0
hybridautopart.com    vercel            ⚠       2026-05-09 11:00 UTC   2
linkedcsi.live        vercel            ✗       —                      5
kwizicle.com          cloudflare-pages  💤      2026-02-08 22:01 UTC   0
csinorcal.church      —                 —       —                      —

  6 live-site/forwarder domains · 1 ERROR · 1 stale · 1 unowned
  [dim]Run `lamill fleet hosting --refresh` to re-probe (Vercel + CF API).[/]
```

```text
$ lamill fleet hosting --refresh
[cyan]Walking Vercel (1 team, 14 projects)...[/]
[cyan]Walking Cloudflare Pages (1 account, 8 projects)...[/]
[cyan]Resolving 22 fleet domains against 22 projects...[/]
[green]Snapshot:[/] data/hosting/2026-05-15.json
<same table as above, fresh data>
```

```text
$ lamill fleet hosting --only linkedcsi.live
<single-row probe; bypasses snapshot>
```

`--refresh` and `--only` follow the existing `fleet seo` conventions.

---

## 4. Functional requirements (the three phases)

### Phase 1 — Provider walkers + per-domain match (~6–8h)

**P1.1** Add `VERCEL_TOKEN` to `apikeys.KNOWN_KEYS` (matches the
existing `CF_API_TOKEN` / `CF_ACCOUNT_ID` pattern) and a
`_probe_vercel()` connectivity check in `apikeys.py`.

**P1.2** New module `src/portfolio/hosting.py` with the
`HostingRow` dataclass (see §5.1) plus two walkers:

- `walk_vercel(token: str, only_domain: str | None = None) -> list[HostingRow]`
- `walk_cf_pages(api_token: str, account_id: str, only_domain: str | None = None) -> list[HostingRow]`

Each walker:
- Paginates the projects-list endpoint.
- For each project, reads the latest deploy + walks deployment
  history (capped at N=10 — see §6.D) to find the most recent
  successful build and count consecutive failures from the head.
- Maps custom domains to fleet domains via a bare-host match
  (resolves `www.` prefix to the bare form).
- Returns one `HostingRow` per matched fleet domain; unmatched
  projects are dropped silently (they're not in the fleet).

**P1.3** Top-level orchestrator `run_hosting(domains: list[str]) ->
list[HostingRow]`:
- Calls both walkers in parallel via `ThreadPoolExecutor`
  (matches `seo_runtime.run_seo` pattern).
- For each fleet domain not matched by either walker, emits a row
  with `provider=None`.
- For domains matched by BOTH providers, emits a row with both
  providers plus a `provider_conflict: True` flag in `notes[]`.

**P1.4** New module `src/portfolio/hosting_cache.py` mirroring
`seo_cache.py`:
- `save_snapshot(rows, *, scope)` → `data/hosting/<UTC-date>.json`
- `latest_snapshot()` / `load_snapshot(path)` / `rows_from_snapshot`
- `is_stale(path, max_age_hours=24)` — same 24h threshold as SEO

**P1.5** No CLI wiring yet — Phase 1 is library-only. Smoke test:
direct Python call producing a valid snapshot file.

### Phase 2 — Table renderer + CLI surface (~4–6h)

**P2.1** New `fleet hosting` Typer command at `cli.py:fleet_hosting`
near `fleet_seo`. Flags:
- `--refresh` (force re-walk + overwrite snapshot)
- `--only <DOMAIN>` (single-domain probe, bypass snapshot)
- `--json` (raw snapshot JSON)
- `--scope wip|all` (matches `fleet seo`'s `--only` semantics — see
  §6.B; renamed here to avoid shadowing `--only DOMAIN`)

**P2.2** Cache-eligibility logic identical to `_run_check_seo_mode`:
- Default: read latest snapshot if it exists AND covers every
  domain in the requested scope.
- `--refresh`: force walker run, overwrite snapshot.
- `--only DOMAIN`: bypass cache entirely.

**P2.3** Scope filter: read the latest `data/checks/<date>.json`
classification snapshot, keep only domains classified
`live-site` or `forwarder`. Refresh the live snapshot first if
it's older than the SEO-style threshold (matches `fleet seo`).

**P2.4** `_render_hosting_table(rows, console)` produces the table
in §3. Five columns: Domain · Provider · Status · Last Success ·
Failures. Status glyph rules (PRD §3 table reproduced in
`hosting.py` as a constant). Footer shows rollup counts.

**P2.5** Loud-warning surface when a `VERCEL_TOKEN` or
`CF_API_TOKEN` is missing on `--refresh` — partial coverage is
clearly labeled in the table footer ("Vercel skipped: token
missing").

### Phase 3 — Dashboard + diagnose integration (~2–3h)

**P3.1** `fleet dashboard` gains a `Hosting` column joined from
the latest hosting snapshot (same shape as the existing Live /
SEO / Git triad). Glyph derives from the hosting row's status.

**P3.2** `project diagnose <domain>` surfaces a "Hosting:" section
when the latest hosting snapshot covers the domain. Renders
provider + status + last-success date. Failures show the failure
count; READY shows nothing beyond "✓ healthy."

**P3.3** Docs:
- `docs/CLAUDE.md` brief on the new view + cache file.
- `AI_AGENTS.md` mention of the new command for the curious.
- `docs/Prompts.md` dated H2 entry.

---

## 5. Data model

### 5.1 — `HostingRow` dataclass

```python
@dataclass
class HostingRow:
    """One domain's deploy state across Vercel + Cloudflare Pages."""
    domain: str

    # Provider mapping (None when neither walker matched).
    provider: str | None             # "vercel" | "cloudflare-pages" | None
    project_slug: str | None         # vercel/cf-pages project name
    project_id: str | None           # opaque API ID

    # Latest deploy state.
    latest_deploy_status: str | None # READY | ERROR | BUILDING | CANCELED | None
    latest_deploy_at: str | None     # ISO 8601 UTC
    last_successful_deploy_at: str | None
    consecutive_failures: int = 0

    # Diagnostic + drift signals.
    provider_conflict: bool = False  # set when both walkers matched
    error: str | None = None         # walker-level error (auth, rate-limit, …)
    notes: list[str] = field(default_factory=list)
```

### 5.2 — Snapshot file shape

`data/hosting/<YYYY-MM-DD>.json`:

```json
{
  "schema": "hosting-v1",
  "fetched_at": "2026-05-15T...",
  "providers_walked": ["vercel", "cloudflare-pages"],
  "scope": "live-site",
  "rows": [
    {
      "domain": "calcengine.site",
      "provider": "vercel",
      "project_slug": "calcengine-site",
      "project_id": "prj_abc123",
      "latest_deploy_status": "READY",
      "latest_deploy_at": "2026-05-15T09:44:00+00:00",
      "last_successful_deploy_at": "2026-05-15T09:44:00+00:00",
      "consecutive_failures": 0,
      "provider_conflict": false,
      "error": null,
      "notes": []
    }
  ]
}
```

Schema-versioned for forward-compatibility (same pattern as
`research-cluster-v2` from v8.D).

### 5.3 — Status emoji rules

The glyph is derived at render time, not stored on disk (cheaper
to update rendering than to migrate snapshots).

| Glyph | Condition |
|---|---|
| `✓` | `latest_deploy_status == "READY"` AND `latest_deploy_at` within `RECENT_DAYS` (default 30) |
| `⚠` | `latest_deploy_status == "ERROR"` AND `last_successful_deploy_at` is non-null AND within 30d |
| `✗` | `latest_deploy_status == "ERROR"` AND no successful deploy in last 30d (or never) |
| `💤` | `latest_deploy_at` older than `STALE_DAYS` (default 90), regardless of status |
| `—` | `provider is None` |
| `?` | walker `error` populated (token, rate-limit) — shown but doesn't roll up |

`BUILDING` and `CANCELED` render as `⏳` / `⊘` with the deploy
timestamp; for rollup purposes they're treated as "no current
verdict" (skipped from the counts).

---

## 6. Open questions (resolve before implementation)

### 6.A — VERCEL_TOKEN scope

A Vercel personal access token sees only the personal account's
projects, not other teams the user belongs to. Vercel team tokens
see only one team. Three options:

1. **Personal token only.** Document the expectation ("create at
   vercel.com/account/tokens"). Operators with multi-team setups
   need to consolidate or stitch manually.
2. **Multi-token support.** Accept `VERCEL_TOKEN_PERSONAL`,
   `VERCEL_TOKEN_TEAM_X` env vars. Walker concatenates results.
   More flexible, more config burden.
3. **Single token + team-list config.** One token; `portfolio.env`
   lists team slugs to query.

**Recommendation: option 1.** Operator-scale tool, single user.

### 6.B — `--only` flag name collision

`fleet seo --only wip|all` and the prompt's "Scope: live-site
domains only" suggest a scope flag, but I also want `--only DOMAIN`
for single-domain probes. Three options:

1. Keep `--only DOMAIN` for single-domain probe; rename the scope
   flag to `--scope wip|all`. Diverges from `fleet seo`.
2. Use `--domain DOMAIN` for single-domain probe; `--only wip|all`
   for scope. Matches the old `check seo --domain` form.
3. Drop the scope flag entirely — always operate on live-site +
   forwarder. The user's prompt suggests this is fine.

**Recommendation: option 3.** Scope is always live-site +
forwarder; `--only DOMAIN` is the single-domain probe.

### 6.C — `RECENT_DAYS` / `STALE_DAYS` thresholds

Hardcoded 30 / 90 in `hosting.py`, or configurable via
`portfolio.env`? Three options:

1. Hardcoded constants — change in code if needed.
2. Two new env keys: `HOSTING_RECENT_DAYS`, `HOSTING_STALE_DAYS`.
3. Per-domain override via `lamill.toml` (depends on v11.A).

**Recommendation: option 1 for v12.A.** Revisit if real fleet data
shows the thresholds are wrong.

### 6.D — Deployment history lookback

`consecutive_failures` requires walking deployments back to the
last `READY`. How far back?

1. **Cap at N=10 per project.** Common case: 0-2 failures. Worst
   case ~10 deployments × N projects API calls. ~50 calls for a
   25-domain fleet, well within rate limits.
2. **Page until READY found.** Unbounded — could explode if a
   project has never succeeded.
3. **Two-tier: stop at N=10, mark as "≥10 consecutive failures."**
   Worst-case bounded but signal preserved.

**Recommendation: option 3.** Honest about the cap; surfaces the
runaway-failures case in findings.

### 6.E — Domain ↔ project matching

The prompt says "Match projects to fleet domains by configured
custom domain." Bare-host match:

1. **Bare-host normalize.** Strip leading `www.` from both sides
   before comparison. `calcengine.site` matches both
   `["www.calcengine.site"]` and `["calcengine.site"]`.
2. **Exact match.** A project with only `www.X` doesn't match the
   bare-X fleet entry. (Probably wrong for the user's case — more
   restrictive than they want.)

**Recommendation: option 1 (bare-host normalize).**

### 6.F — Provider conflict (same domain on both)

When the same domain appears on both a Vercel project and a CF
Pages project — that's deploy drift, possibly accidental.

1. **Two rows in the snapshot, one for each provider.** Renderer
   shows both; rollup counts as a single conflict.
2. **One row with both providers in a `providers` list; status
   from the "active" one (DNS-resolved).** Simpler row, requires
   DNS lookup to decide which is active.
3. **One row, first provider wins, conflict noted in `notes[]`.**
   Simplest, least diagnostic.

**Recommendation: option 1.** Drift should be visible — two rows
make it obvious; renderer can deduplicate visually with the
conflict glyph.

### 6.G — Snapshot interpretation of "add a hosting slot"

The prompt: "Snapshot: add a `hosting` slot to the existing snapshot
model so it can be refreshed independently from other layers."

Two readings:

1. **New file `data/hosting/<date>.json`** — mirrors the per-layer
   separation pattern (`data/seo/`, `data/checks/`, `data/gsc/`,
   `data/serp/`). Refresh independence comes for free since each
   file has its own lifecycle.
2. **Join into a unified snapshot.** Add a `hosting` key to the
   existing fleet-dashboard model. Different lifecycle problem.

**Recommendation: option 1.** Matches every other layer in this
tool. Confirm interpretation with user.

### 6.H — Walker error surfaces

A 401 from Vercel (bad token) or 5xx from CF API: how should the
table render rows for affected domains?

1. **Per-row `error` field.** Affected rows render with `?` glyph
   and an error count in the footer. Other provider's rows still
   render normally.
2. **Hard exit on auth failure.** Don't render a partial table
   when half the data is missing.
3. **Skip the affected provider entirely.** Footer says "Vercel
   skipped: 401."

**Recommendation: option 3.** A 401 means the entire walker
returns nothing useful; clearer to skip + warn than to render N
empty rows. 5xx + rate-limit get per-row `error` (option 1).

### 6.I — Snapshot retention

Same as v8.D §8.E: keep forever (git-tracked) vs trim vs untracked.

**Recommendation: keep forever, git-tracked.** Same as every other
layer. Disk isn't a constraint.

### 6.J — Test strategy

All real API calls mocked at the `httpx`/`requests` layer (same
pattern as `tests/test_gsc_recrawl.py` from the
`feat/gsc-recrawl-subcommand` branch). No CI calls to real Vercel
or Cloudflare APIs.

**Recommendation: confirm option, then proceed.**

---

## 7. Implementation plan (commit-by-commit)

### Phase 1 commits

- `apikeys.py`: add `VERCEL_TOKEN` to `KNOWN_KEYS` +
`_probe_vercel()` (`GET /v2/user`, 5s timeout). One new test in
`test_apikeys.py`.

- `src/portfolio/hosting.py`: dataclasses (`HostingRow`),
constants (`RECENT_DAYS`, `STALE_DAYS`, `MAX_DEPLOY_LOOKBACK`).

- `walk_vercel()` — paginated projects list + per-project
deployments. Mocked unit tests.

- `walk_cf_pages()` — same shape against the CF API.

- `run_hosting()` orchestrator + domain-match logic +
provider-conflict detection.

- `hosting_cache.py` mirroring `seo_cache.py`. Save / load
/ is_stale / rows_from_snapshot. Atomic write.

### Phase 2 commits

- `fleet hosting` CLI shell + cache-eligibility logic +
`--refresh` / `--only` / `--json` flags. No render yet (prints
"render coming in the next commit" or similar to keep the shell testable).

- `_render_hosting_table()` + status-emoji helper. Five
columns; footer with rollup counts.

- Token-missing surface (P2.5) + walker-error rendering
(per §6.H). Tests for partial-coverage flows.

### Phase 3 commits

- `dashboard.py`: new `Hosting` column joining the latest
`data/hosting/` snapshot.

- `diagnose.py`: optional "Hosting:" section when a hosting
snapshot covers the diagnosed domain.

- Docs (docs/CLAUDE.md, AI_AGENTS.md, docs/Prompts.md dated
entry).

---

## 8. Effort estimate

| Phase | Commits | Hours | Risk |
|---|---|---|---|
| P1 walkers + cache |  6–8 | Vercel + CF API pagination, deploy-history shape variability |
| P2 renderer + CLI |  4–6 | Edge cases in domain↔project matching (subdomains, `www.`, provider conflicts) |
| P3 dashboard + diagnose |  2–3 | Minimal — both surfaces already do joins from snapshot files |
| **Total** | **12 commits** | **12–17h** | Real API quirks surface only on first run against the user's fleet |

---

## 9. Future considerations (deferred, named only)

- **Netlify / GitHub Pages / direct-Worker walkers** — pluggable
  provider pattern was designed in §4 P1.2 to support these. One
  new walker per platform.
- **`lamill.toml` cross-reference** — once v11.A ships, compare
  declared platform vs. observed platform. Drift becomes a CHECK
  catalog entry.
- **Build-failure root-cause** — fetch the build log for the
  latest ERROR deploy and surface the failing step. Separate PRD;
  needs careful scope (logs can be MB-scale).
- **Deploy-trigger CLI** — `lamill new redeploy <domain>` to
  retry the latest failed deploy. Write surface, separate PRD.
- **Snapshot diff renderer** — "what changed in deploy state vs
  yesterday's snapshot?" View on top of the existing snapshots.
- **Webhook subscriber** — Vercel / CF can push deploy events;
  receive them and update the snapshot incrementally instead of
  polling. Out of scope for v12.A (poll is fine at fleet scale).
- **Cost / pricing reporting** — Vercel and CF expose usage
  metrics; could land in a `fleet costs` view. Separate PRD.

---

## 10. Approval

This PRD is **draft, awaiting review**. Before any code lands:

1. Resolve the 10 open questions in §6.
2. Confirm the snapshot shape (§5.2) is right (esp. §6.G).
3. Confirm the 12–17h effort estimate is acceptable.
4. Confirm provider scope (Vercel + CF Pages only; deferred list
   in §9 is acceptable).

Sign off:

- [ ] Open questions §6.A–J resolved
- [ ] Snapshot schema reviewed
- [ ] Effort estimate accepted
- [ ] Provider scope confirmed (Vercel + CF Pages for v12.A)
- [ ] Author signoff
