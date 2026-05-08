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
| **v4** | conformance + drift + stack + remediation | stack identifier, plan-drift signal, dir↔domain mapping; v4.D's `portfolio project fix <name>` is the second write surface for retro-fixing pre-bootstrap projects |
| **v5** | live correlation + roll-up | GSC trend join; `portfolio project list` aggregate view |
| **v6** | deploy verification | build-time stamping convention + HEAD vs deployed SHA + Pages/Vercel API integration |

## 5. Phases

Strict sequence (option a). 27 phases total; v1.A–v1.F + v2.A + v2.B + v3.A + v3.B + v3.C + v3.D + v3.E shipped (13/27). **v3 complete.** v4.A (mark/unmark shortlist) queued next.

Note on read/write surfaces: portfolio is **read-only** through v2 (domain suggest). **v3 (bootstrap) is the first write surface** — it creates new project dirs, runs `git init`, scaffolds files. **v4.H (remediation) is the second write surface** — it modifies existing project dirs to fix conformance gaps. Everything else (v4.A–G, v5, v6) is read-only.

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

| Phase | Theme | Features |
|---|---|---|
| **v1.A** ✅ | Skeleton + repo-isolation gate | `portfolio project status <name>` subcommand · fuzzy resolver against plan.md · `--json` schema_version=1 · C1 own-git-repo gate · last commit (sha, subject, age, author) · binary verdict (Misconfigured / Active) |
| **v1.B** ✅ | Full git pulse + Prompts.md + deploy-detect + live | activity rate (7d/30d) · branch + clean/dirty · uncommitted count · last Prompts.md entry (dated-H2 parser) · plan category · full verdict ladder (Active / Quiet / Stalled / Dormant / Fresh / Misconfigured) · C2 in-plan-md · C3 has-prompts-md · C4 prompts-md-format · C5 has-makefile · C6 has-ai-agents-md · deploy-platform detection (cloudflare / vercel / netlify / unknown / n/a) via filesystem markers · live-site HTTP class joined from `data/checks/` · platform-declared + live-site conformance · rich TTY view |
| **v1.C** ✅ | Registrar consolidation | `data/domains/{godaddy,namecheap,porkbun}.csv` · 3 adapters with format normalization (3 date formats; auto-renew yes/no/ON/OFF) · Porkbun disclaimer-line skip · `Domain` schema gains `registrar` (required), `privacy`, `transfer_locked` · `domain_to_registrar()` shared lookup · `summary` warns on missing renewal_price · Porkbun rows excluded from value rollups (low-value TLDs) |
| **v1.D** ✅ | Cleanup + classification migration (plan.md → portfolio.json) | `portfolio cleanup` subcommand · reads raw registrar CSVs + plan.md · writes `data/portfolio.json` (single canonical record per domain: name, registrar, category, expires, created, auto_renew, renewal_price, estimated_value, privacy, transfer_locked, nameservers, forwarding_url, raw passthrough for forensics) · auto-classification rules: Namecheap rows → "Under build", Porkbun rows → "Under build", GoDaddy rows → plan.md category (or warn if uncategorized) · `load_domains()` pivots to read from `portfolio.json` after cleanup · `load_plan()` is removed (categories now come from `domain.category` directly) · plan.md gets a deprecation comment in v1.D; actual file deletion happens in a later cleanup commit · drift output surfaces uncategorized domains as warnings · resolver in `project status` continues to fuzzy-match, just against `portfolio.json` keys instead of plan.md · typo / fuzzy-similar-name detection deferred to v4.F |
| **v1.E** ✅ | NLP skill | `~/.claude/skills/project-status/SKILL.md` (global; works from any cwd) — routes natural-language questions like "what's the status of iotnews" → `make run ARGS="project status <name> --json"` → short prose answer (1-line headline + up to 3 contextual bullets). Disambiguation: lists `candidates` and asks the user. Read-only by design; defers fixes to v4.H and cross-project roll-up to v5.C. |
| **v1.F** ✅ | Parked-detection accuracy | extend `check.py` `_classify()` with body-content inspection: detect GoDaddy in-line parking (sub-1KB body containing `window.location.href = "/lander"` or similar JS redirect to `/lander` / `/landing` / `/sale` / `/park`) and reclassify from spurious `live-site` → `parked` with reason `js-redirect-to-parking-page` · capture truncated body excerpt in `CheckResult` so future re-classifications run offline against the snapshot · re-run `check --only all` to refresh the 53-domain dataset · `summary` and `project status` now reflect reality for parked GoDaddy domains (newiniot.com etc.) |
| **v2.A** | Multi-strategy brainstorm + score + already-own *(Power 1 — find the right domain)* | `portfolio domain suggest <topic>` interactive subcommand · OpenAI `gpt-5-mini` brainstorm, looped through configurable naming **strategies** (5 default: trendy / dev-technical / benefit-driven / metaphor / abstract-brandable; extensible via config) · per-strategy: ~12 candidates → strict gen rules (≤12 chars, no hyphens, brandable, easy to say) → SEO-weighted scoring (TLD tier · length · keyword presence · hyphen/digit penalty) → top-5 sorted · `history` deduplication so subsequent strategies don't repeat names · already-own intersection against `data/portfolio.json` (depends on v1.C) — surface owned matches *before* generating new ones · 7-day caching by `topic-hash` in `data/cache/suggest/` so iterating on the same idea is cheap · `--non-interactive` flag dumps ranked candidates for piping; default is interactive (per-strategy round → user picks / moves on / types custom) |
| **v2.B** | Availability + **price** via Porkbun (RDAP fallback) | Porkbun `domain/checkAvailability` API by default if `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` env vars present (returns availability **and price** in one call — both are buying-side decision criteria) · RDAP fallback when Porkbun keys unset (availability only, no price) · TLD ladder per the SEO tier config: `.com / .ai / .io / .app / .dev / .co` default; `--tlds=` overrides · stop-at-first-available-TLD per name to keep round time manageable · rate-limited (~3/sec, matching script convention) · per-TLD endpoint cache · **`--max-price=$N` filter** so premium-priced names get excluded — user explicitly does not want to overpay at registration time · output column shape per round: `name · TLD · avail · price · score` |
| **v3.A** ✅ | Bootstrap — scaffold a new project *(Power 2 — ship-ready scaffold)* | `portfolio bootstrap <domain>` typer command with three paths: **(1) template**: empty target → writes minimal Astro (default) or `--stack=vite` (React+JSX) scaffold; **(2) `--from-genai`**: target dir + `genai/` subdir exist → copies `genai/*` to project root and applies CF Pages safety fixes (Vite ≥6 bump, `_redirects` removal, `wrangler.toml` add); **(3) `--git-url=<url>`**: clones URL into `genai/` then proceeds as `--from-genai`. All paths write standard scaffolding (AI_AGENTS with Building/Deployment, docs/prd.md, docs/Prompts.md, README, .gitignore, local `Makefile` that includes `BUILDER_PATH=../../builder`) and run `git init` + initial commit. `--with-ingester` adds `scripts/ingest.py` template. `--topic` injects into AI_AGENTS + PRD. Filesystem-only by default (genai+template paths); `--git-url` is the only network-touching path. |
| **v3.B** ✅ | SEO baseline pack | meta-tag template (title, description, canonical, OG, Twitter card) injected stack-aware into `index.html` (Vite) and `src/pages/index.astro` (Astro); JSON-LD structured data (Organization + WebSite with @id graph); favicon SVG monogram from domain initial (deterministic color from a 12-color palette, hash-picked per domain); `public/robots.txt`; `public/sitemap.xml` stub. **v3.B.2 (2026-05-04):** sitemap-generation: Vite path adds `scripts/generate-sitemap.mjs` (post-build dist/-scan, no deps) and chains it into the `build` script; Astro path adds `@astrojs/sitemap` integration to `astro.config.mjs` with `site` URL set. Technical-SEO regression check: `src/__tests__/seo.test.js` asserts the v3.B baseline (title, meta description, canonical, OG, Twitter card, favicon link, JSON-LD Organization + WebSite); both stacks get a `test:seo` npm script wired up. |
| **v3.C** ✅ | Deploy abstraction + Cloudflare Pages impl | `DeployTarget` Protocol (provider-agnostic: `verify_local_config` / `create_github_repo` / `create_project`); `CloudflarePagesDeploy` concrete impl. `portfolio deploy <domain>` CLI: verifies the local config (wrangler.jsonc, public/_headers, package.json build script, pnpm-lock.yaml, no bun/npm/yarn lockfiles, .git initialized) → `gh repo create <slug> --source=. --remote=origin --push` (idempotent: skips if repo exists) → POST to `/accounts/{id}/pages/projects` with `build_command="pnpm run build"` and `destination_dir="dist"` set explicitly (avoids the bun-detection trap kwizicle.com hit) and `source.config.{owner,repo_name}` linked to the GitHub repo. Auth via portfolio.env: `CF_API_TOKEN` (Pages:Edit), `CF_ACCOUNT_ID`. `--dry-run` shows planned API calls without executing. `--skip-{verify,repo,pages}` for partial runs. Idempotent throughout. Future `VercelDeploy` / `NetlifyDeploy` slot into the same Protocol without callers changing. Custom-domain registration deferred to a later phase (DNS-touching). |
| **v3.D** ✅ | Validation-mode suggest (vocab anchor + registrar grid + cheap-first score) *(was v3.F in 2026-05-07 brainstorm)* | One-shot LLM vocabulary extraction (12-15 practitioner-register concrete-noun/verb terms, ≤9 chars each, no topic-word echo, prompt includes a worked dog-walking example to anchor "concrete vs marketing"); cached with brainstorm in shared topic-hash file (`--no-cache` invalidates both, payload extends `candidates_by_strategy` with `vocab_terms`). Vocab injected as **must-reference anchors** into all default strategies (trendy / dev-technical / benefit-driven / metaphor); abstract-brandable strategy moved behind `--with-abstract` flag (off by default). Registrar-grid output: rows = candidate names, columns = `.com .app .dev .xyz .site .co` (defaults; `--tlds` overrides; full ladder includes `.co .ai .io .xyz .shop .life .info .pro` for power users). Cells: `✓ $N` (available at first-year price) · `✗` / `✗ live` / `✗ park` / `✗ for-sale` (taken; live-site/parked/for-sale classification on `.com` only via `check.py` classifier) · `?` (RDAP gap — picker treats as valid pick → builds Porkbun verify URL) · `$N!` (over `--max-price`, shown unselectable). Pick + Why columns recommend a TLD per row (e.g. `.app +bundle` if `.com` defensible, `skip` if `.com` is a competing live site) and surface defense status. Score reweighted: `.app` and `.dev` to tier-9 (alongside `.com`); `.xyz` to tier-6; `.site` to tier-5; `.ai` to tier-7; `.io` to tier-6 (price-capped out anyway); **+5 if `.com` available** (slice defendable); **−20 if `.com` is a live competing site** (brand poisoned). Keep keyword/length/hyphen/digit components (vocab anchor controls *generation*; score components do *ranking*). Default flow: all 4 default strategies + full ladder run in **one pass** → merged top-15 grid → one pick. After pick, prompt `Register {primary} now via Porkbun API? [y/N]` — if yes, call Porkbun `/domain/create` with `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` from portfolio.env (charges the card on file at Porkbun; requires account-level API access to be enabled, a one-time toggle in Porkbun account settings). Print the order ID on API success; on API failure or missing keys, fall back to printing the manual checkout URL. **One-domain auto-register only** — the defense-bundle prompt (optional, separate) builds a multi-domain Porkbun cart URL at standard price (e.g. primary .xyz $2 + .com $11 + .app $11 = ~$24 first-year for full slice protection) for manual click-through; bundle defenses are never auto-charged. After registration (auto or manual), command exits printing the next-step `portfolio bootstrap <domain> --topic="..."` invocation with vocab terms shown for paste-into-prd.md (no auto-chain into bootstrap; user invokes bootstrap separately). `--browse` flag opts into per-strategy round-by-round flow (current v2.A behavior). `--show-renewal` adds renewal-price stacked sub-row (off by default; validation-mode users mostly drop renewals on failed projects). `--with-abstract` adds the abstract-brandable strategy back into the run. Drop `.tech .site .online .store .fun` from full ladder for *availability checks* (Radix-host RDAP broken via SSL handshake error; `.site` stays in default columns as a `?`-only column for show + manual verify). |
| **v3.E** ✅ | Validation-mode polishing — post-grid menu + porn screen + TLD reference card | Restructures the post-grid interactive surface of `portfolio domain suggest`. Replaces the inline picker prompts (`N`, `N.tld`, `eN`, `e <name>`, auto "Add your own names?" loop) with a numbered menu rendered after each grid update: **1.** Pick a row to register · **2.** Expand a row (full-ladder detail) · **5.** Add my own names to the grid · **8.** Show TLD reference (pricing, SEO, vibe — quick-recall card) · **q.** Quit. (Slots 3/4/6/7 reserved for v4.A features — finalists, ask AI, widen.) Bad input loops with a "Type 1, 2, 5, 8 or q" hint (no silent quit). Menu re-displays after every non-terminating action; only successful registration or `q` exits. Also lands the **3-layer strict porn screen** (always-on, no opt-out): Layer 1 local blocklist of unambiguous terms (porn xxx milf bdsm smut nsfw fetish kink slut whore fuck cunt twat fap incest pedo); Layer 2 OpenAI moderation API at `omni-moderation-latest` with strict thresholds (`sexual > 0.05`, `sexual/minors > 0.01`, no hate/violence filter); Layer 3 gpt-5-mini adjacency + brand-collision check (catches misspellings/different-TLD variants of popular adult brands). Hooked into both `brainstorm()` and the user-added-names path; silently passes through on API failure so the pipeline never breaks. **TLD reference card** (option 8): per-TLD detail card with operator, reg/renew, vibe, trust, SEO, best-for, catch — same data the user kept in chat now recallable in-tool. Only-user-is-Vijo by design; no power-user shortcut surface. |
| **v4.A** | Mark / unmark shortlist + grid alphabetical sort + AI seed-expansion *(headline; new 2026-05-08; deferred from v3.E menu stub item 6)* | Three coupled changes that ship together. **(1) Grid sort flips from score-desc to alphabetical-by-name** (`row.name` ascending, case-insensitive). Score ranking was right for "show me the best candidate first" but this phase reorients the grid for "build a shortlist by scanning names" — you find a candidate by leading letters, not by ranking. Anchors / Pick / Why columns are unchanged; only the row order. **(2) Mark / unmark shortlist.** Adds menu item **6. Mark / unmark for shortlist** (and item 7 placeholder hint pointing at v4.B). Picker accepts multi-target input — `m N1 N2 ...` or `m alpha beta` or `m 1,3,5` (whitespace and/or comma separated) — to mark several candidates in one call; same for `u`. Per-target errors accumulate (out-of-range / unknown name) without bailing on partial successes. `p` prints the current shortlist with per-candidate cell summary; `b` returns to menu. Shortlist persists across menu iterations until quit. Shortlist count appears in the menu label when nonzero (e.g. `6. Mark / unmark for shortlist (3 marked)`). User-added names are markable just like LLM-generated ones. Implementation: shortlist is a list of names (not row references) so it survives grid mutations from add-names / future widen. **(3) AI seed-expansion in option 5.** After the user types seed names in option 5 (Add my own names), prompt `Expand with AI to get plurals, near-synonyms, etc.? [Y/n]`; on Y, send seeds + topic + vocab to gpt-5-mini for 12-18 closely-related variants (plurals, near-synonyms, prefix/suffix riffs, alternative anchors). Variants pass through the same v3.E porn screen. Cuts the typing cost when the user has a stem in mind but wants broad coverage. Silently falls back to seeds-only on API failure. |
| **v4.B** | Decide from shortlist *(new 2026-05-08; deferred from v3.E menu stub item 7)* | Adds menu item **7. Decide from shortlist** with auto-checks per finalist. `d` (or selecting menu 7) runs in parallel against each finalist: GitHub user availability (`api.github.com/users/<name>`, no auth, 60/hr rate-limit), npm package name (`registry.npmjs.org/<name>`, no auth), PyPI package name (`pypi.org/pypi/<name>/json`, no auth). Renders a side-by-side comparison table — domain · reg · anchors · GitHub · npm · PyPI · other-TLDs-taken — so the user can pick deliberately. Final numeric choice from the comparison proceeds to the existing post-pick flow (defense bundle, register, next-step). USPTO / social-handle / Google-Trends pre-checks remain deferred (paid APIs / scraping concerns; revisit as a separate phase if needed). Tests mock the three API endpoints. |
| **v4.C** | Widen search + ask AI *(new 2026-05-08; deferred from v3.E menu stub items 3 and 4)* | Adds menu items **3. Ask AI about a name** and **4. Widen search — more candidates**. **Ask AI (`? <name>` or via menu 3)**: gpt-5-mini call given topic + vocab + name + question, returns 1-3 sentence explanation; default question "Why was this name chosen and how does it relate to the topic?"; cached by (topic, name, question) hash so re-asking the same question is free. **Widen (`w` / `w <guidance>` or via menu 4)**: LLM call passing existing names as history-dedup + optional user guidance ("shorter", "foreign roots", "more medical-specific"); returns 12-24 fresh candidates merged into the grid after going through the v3.E porn screen. Both go through the v3.E content screen. Tests mock the OpenAI calls; verify dedup against existing grid, anchor injection in widen, cache hit/miss for ask. |
| **v4.D** | Interactive launcher (menu) *(was v4.B pre-2026-05-08-pm; was v3.E pre-2026-05-07; was v4.A 2026-05-07 → 2026-05-08-am)* | `portfolio` invoked with no subcommand drops into a grouped, rich-rendered menu — solves the "I can't remember the subcommand or the nested-quoting" friction. Groups: **Manage** (summary, project status, cleanup, check) · **Build** (domain suggest, bootstrap, deploy) · **Reports** (expiring, category, wip, list). Per-command flow: prompt for required positional args first, then `use defaults for everything else? [Y/n]`; if `n`, walk through optional flags one at a time. Existing per-command interactive flows (e.g. `domain suggest`'s `--browse` per-strategy round) take over after dispatch — no double-menu. After command exits, returns to menu; `q` from the menu quits. Implementation: `app(invoke_without_command=True)` with a callback that runs `menu()` from new `src/portfolio/menu.py`; nothing else changes — `make run` (no ARGS) and direct `portfolio` invocation both flow through. Bad-syntax `make run ARGS="…"` still surfaces typer's existing error (no fuzzy-match fallback in this phase). Tests use typer's `CliRunner` with mocked stdin. |
| **v4.E** | Stack detection + scaffold completeness *(was v4.C pre-2026-05-08-pm; was v4.B pre-2026-05-07; was v3.A pre-2026-05-02)* | stack identifier (React+Vite / Astro / Python+uv / Go+Fiber / scaffold-only) · C7 vite-version-ok · C9 has-prd-md · **scaffolding-required rules: has-readme · has-gitignore · ai-agents-md-has-building-info · ai-agents-md-has-deployment-info** (every sites/* project must have the standard scaffolding produced by `/project-init` or v3 bootstrap) |
| **v4.F** | Drift + mapping *(was v4.D pre-2026-05-08-pm; was v4.C pre-2026-05-07)* | plan-drift signal · C10 domain-dir-match (override map for harmonia / etc.) · C8 cf-pages-deployable |
| **v4.G** | Per-stack rules *(was v4.E pre-2026-05-08-pm; was v4.D pre-2026-05-07)* | placeholder for emerging conventions: pnpm-lockfile-only · no-package-lock-json · gitignore-covers-build-output · python-uses-uv |
| **v4.H** | Remediation (second write surface) *(was v4.F pre-2026-05-08-pm; was v4.E pre-2026-05-07)* | `portfolio project fix <name>` subcommand · dry-run by default; `--apply` required to write · `--rule R` for surgical fixes · all fixes idempotent · auto-fixes: has-prompts-md · has-ai-agents-md · has-makefile (depends on v4.E's stack identifier) · prompts-md-format · own-git-repo guided migration (parent `git rm --cached` + parent `.gitignore` entry + project `git init` + initial commit; explicit confirmation each step touching parent repo) · `--yes` skips prompts for scripted runs · templates embedded in `src/portfolio/templates.py` · `platform-declared` and `has-category` deferred (require user choice / curation) |
| **v5.A** | Optional LLM content seeding *(was v3.D pre-2026-05-07 reorder; postponed indefinitely)* | `--seed-content` flag on `portfolio bootstrap`: OpenAI gpt-4o-mini generates a starter home page + 1–2 supporting pages from the topic (similar prompt pipeline to v2.A's brainstorm) · cached by topic-hash · user reviews + commits manually before pushing · skipped by default since some projects are app-style (no narrative content) · *postponed indefinitely (2026-05-04 user call); v3.D built first* |
| **v5.B** | GSC trend correlation *(was v5.A pre-2026-05-07 reorder)* | GSC trend per project (28d clicks/imp/pos, w/w delta) · C12 gsc-verified · reads existing `data/gsc/` snapshots |
| **v5.C** | Roll-up *(was v5.B pre-2026-05-07 reorder)* | `portfolio project list` · `--stale N` filter · `--json` · aggregate verdict counts |
| **v6.A** | Build-time stamping | convention: every sites/* project writes `version.json` at build (commit + built_at) · new conformance: has-version-stamp |
| **v6.B** | HEAD vs deployed | deploy-freshness signal · C13 deploy-fresh · reads `version.json` from live URL |
| **v6.C** | Build status + deploy lag | deploy lag (push → live) · last build status via Cloudflare/Vercel API · last-build-success conformance · *requires platform tokens — major new infra* |

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
| `vite-version-ok` | Vite ≥6 for React projects | v4.E |
| `has-prd-md` | `docs/prd.md` exists | v4.E |
| `has-readme` | `README.md` exists at project root | v4.E |
| `has-gitignore` | `.gitignore` exists at project root | v4.E |
| `ai-agents-md-has-building-info` | `AI_AGENTS.md` contains a `## Building info` heading (referencing the central builder at `~/work/projects/builder/` + `../Makefile`) | v4.E |
| `ai-agents-md-has-deployment-info` | `AI_AGENTS.md` contains a `## Deployment info` heading (platform / live URL / deploy trigger) | v4.E |
| `cf-pages-deployable` | frozen-lockfile install OK; no stray gitlinks; no `_redirects` SPA fallback | v4.F |
| `domain-dir-match` | dir name matches a plan.md domain (or in override map) | v4.F |
| `gsc-verified` | dir's eTLD is a verified GSC property | v5.B |
| `has-version-stamp` | project writes `version.json` at build time | v6.A |
| `deploy-fresh` | HEAD SHA matches deployed SHA | v6.B |
| `last-build-success` | last Cloudflare/Vercel build succeeded | v6.C |

## 7. Open questions

Append-only log. Questions get answered (with date) but never deleted.

- *(no open questions at this time — all v1 scoping decisions are locked in AI_AGENTS.md and this PRD)*
