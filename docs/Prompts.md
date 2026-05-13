# Prompt History — sites/portfolio/

<!-- Append new prompts at the bottom, newest last. Format:

## YYYY-MM-DD [optional title]
> <prompt text or summary of the conversation>

The dated H2 (`## YYYY-MM-DD`) is what `portfolio project status` parses
to surface "last AI prompt" per project. Keep entries append-only;
don't rewrite older entries when adding new ones.
-->

## 2026-05-01 — v1.A through v1.C of project status feature

> Multi-turn planning + implementation session that established the canonical
> versioning taxonomy (vN / vN.X), wrote the master phase table for v1–v5,
> shipped v1.A (skeleton + own-git-repo gate), v1.B (full git pulse + Prompts.md
> parser + deploy-platform detection + live-site join + 5 new conformance rules),
> and v1.C (multi-registrar CSV consolidation across GoDaddy / Namecheap /
> Porkbun with format normalization and `domain_to_registrar()` lookup).
>
> Also: established that `docs/prd.md` is the canonical spec for each sites/*
> project (not `AI_AGENTS.md`); added `has-readme` and `has-gitignore`
> conformance rules to v2.A as the standard scaffolding requirement; updated
> the `/project-init` and `/project-check` skills to use `AI_AGENTS.md`
> (plural) instead of singular.

## 2026-05-04 — v3.A bootstrap + v3.B technical-SEO scaffolding

> Implemented `portfolio bootstrap <domain>` as the second project-dir write
> surface: scaffolds a Vite/Astro site under `sites/<domain>/`, writes
> wrangler config + Makefile that forwards to the central `../Makefile`
> builder, enforces pnpm-only via `packageManager`. Then v3.B: technical
> SEO baseline (meta tags + JSON-LD + favicon SVG monogram + sitemap
> generator + a regression test) and v3.B.2 polish.

## 2026-05-06 — v3.C deploy abstraction + v3.D domain suggest

> Built `portfolio deploy <domain>` as a deploy-target abstraction (CF Pages
> only for now; structure leaves room for Vercel/Netlify). v3.D evolved
> domain `suggest` significantly: vocab-anchor ranking, multi-target
> mark/unmark in option 5, AI seed-expansion, expand-row TLD picker (with
> N.tld override), strict porn screen (3-layer), DoH fallback when ISP blocks
> RDAP at L4. Also fixed Porkbun's `/domain/checkAvailability` being dead
> (switched to RDAP + Porkbun `/pricing/get`).

## 2026-05-07 — v3.E launcher menu + v4.A–C shortlist

> v3.E: launching the CLI with no subcommand drops into a Rich grouped menu.
> Then v4.A interactive shortlist (mark/unmark grid + AI seed-expansion),
> v4.B decide-from-shortlist (6-step guided decision aid), v4.C wider Ask AI
> with forgiving parser. Brave Search collision check was tried in v4.B then
> removed when Brave's free tier ended — reverted to AI-only.

## 2026-05-08 — v4.D launcher polish + bootstrap post-summary

> v4.D polished the launcher (Rich-prompt fix, group reorder, "Rerun fresh"
> reset). Bootstrap post-summary enriched: project tree, conformance
> quick-check, predicted live URL, grouped next-steps with concrete commands.

## 2026-05-09 — v5.A–v5.D universal check catalog + cross-repo + SEO runtime

> Major architectural push. v5.A introduced the universal check catalog:
> `src/portfolio/checks/` package with file-per-check registry, auto-
> discovery, stable IDs (CHECK_001+), CheckResult dataclass (status +
> message). 17 initial checks (scaffold + git). v5.B added `check --git` —
> cross-repo catalog runner with summary / detail / single-check / single-
> repo modes. v5.C extended the catalog massively (CHECK_025–CHECK_080):
> docs-quality (`growth.md` non-stub, CLAUDE.md / prd.md min sections),
> last-deploy-date (gated on Makefile `deploy:` target, scans 50 commits),
> has-live-url, stack (pnpm-only / Vite ≥6 / Astro ≥5 / tsconfig), deploy
> (deploy-target uniqueness, wrangler safety rules including no
> `public/_redirects` SPA fallback), SEO assets (favicon / robots.txt /
> sitemap / robots-mentions-sitemap), and SEO meta tags (title, description,
> canonical, viewport [error severity], html lang, robots, OG 5-tag set,
> Twitter Card, JSON-LD presence + Organization/WebSite, analytics).
> Recategorized: docs split out of scaffold, ci split out of git. Added
> category-grouped render (Scaffold → Docs → Git → CI → Stack → Deploy →
> SEO) and "Most common failures across N repos" aggregate. Config gained
> `[git] ignore_repos = ["portfolio"]` default so the CLI tool itself is
> excluded from cross-repo runs. v5.D shipped `check --seo` — per-domain
> runtime probe (separate runner from per-repo registry): HTTP root +
> robots.txt + sitemap.xml + GSC totals (multi-property merge, impression-
> weighted position) + CrUX p75 LCP/INP/CLS for mobile. 🟢/🟡/🟠/🔴 per
> metric vs Web Vitals thresholds. Tests caught a real bug: my robots probe
> accepted any content-type containing `"text"` which matched `text/html`
> — parking pages serving HTML for /robots.txt would have falsely passed;
> tightened to require `text/plain`.
>
> Post-v5.D: HSTS removed from the SEO row-color calculation — it's a
> security signal, not SEO. Belongs in a future `check --security` or as
> a column on `check --live`. Row color in `check --seo` is now driven
> only by impressions, position, robots.txt, and sitemap.

## 2026-05-13 — v6.D / v7.A–v7.C / fleet repos / age-aware grading / tool rename

> Long session covering several connected feature tracks. v6.B added
> per-stack rules (submodules, gitignore-build-output). v6.D landed
> fleetwide `project fix --all` — the v6.C remediation runner extended
> to operate across every project in the workspace. v7.A.1 was a major
> CLI restructure: scope-first namespaces (`project`, `fleet`, `new`,
> `settings`) replacing the v5.F mixed-shape tree, all old paths kept as
> additive aliases. Added a `settings apikeys` feature for managing
> portfolio.env credentials with atomic IO + per-provider connectivity
> probes (OpenAI / CrUX / Porkbun / Cloudflare). "Under build" added to
> WIP_CATEGORIES so newly-bootstrapped sites get included in default
> `fleet live` snapshots.
>
> v7.A.3 shipped `fleet dashboard` — unified per-domain view joining
> live snapshot + SEO snapshot + git status into one row with a worst-of
> rollup dot. Pure cache join by default, `--refresh` re-probes live +
> SEO upstream. Sort modes: attention (default), name, imp, age.
>
> Age tracking (P1+P2+P3): added `launched` and `domain_created` fields
> to `data/portfolio.json`. `launched` auto-inferred from first git
> commit in `sites/<domain>/`, override-able via
> `project set-launched <domain> <YYYY-MM-DD>`. `domain_created` populated
> from RDAP `registration` event date via `fleet info cleanup --refresh-rdap`.
> `cleanup()` now preserves these fields across CSV rebuilds. Both
> surface as columns in `fleet dashboard` (Site age + Domain age).
>
> `fleet focus` got significant work: (a) variant-aware site-down
> detection — only flag dead when *every* probed variant (bare + www)
> failed, fixed false positive on linkedcsi.live where bare timed out
> but www was serving live; (b) platform-aware action text — drop
> hardcoded "Cloudflare Pages" message in favor of detecting wrangler.toml
> / vercel.json / netlify.toml and naming the actual platform; (c)
> `--refresh` flag to re-probe upstream before reading caches; (d)
> age-aware SEO signal suppression — `🟠` zero-impressions + `🟡` bad-
> position signals don't fire on sites <90d old (normal during Google
> freshness window), with `--include-young` to override; (e) idle (🟡)
> signal for forwarder + parked classifications — was previously silent
> when domain was reachable but not serving real content (airsucks.com
> case before bootstrap).
>
> P4 closed the age-awareness loop in `seo_runtime.overall_status` —
> takes optional `site_age_days` param and masks imp + pos cells when
> the site is young. Wired through dashboard's SEO dot and the
> `fleet seo` table grade. Robots/sitemap/GSC-presence still count
> regardless of age. After P4, airsucks.com (launched today, GSC
> active, zero impressions) correctly graded 🟢 instead of 🔴 — exactly
> the case P4 was built for.
>
> `fleet repos` added — read-only audit of every `sites/<domain>/`'s
> git-layer state. Classifies into: clean standalone, nested
> anti-pattern (own .git + tracked by outer monorepo), standalone
> unpublished (no remote), monorepo-only, unversioned, empty stub,
> archived. `--detail` / `--only` / `--json` modes. Write mode
> (`--fix`) intentionally deferred. Three new git-category catalog
> checks landed alongside: CHECK_040 (git-remote-name-matches-domain),
> CHECK_041 (dir-matches-portfolio-entry), CHECK_042 (live-final-url-
> matches-domain) — the naming-consistency cluster.
>
> Archived support added on top of `fleet repos` after the dark-site
> conversation. Two detection signals: `TOMBSTONE.md` marker file at
> project root, or portfolio.json category in `{to be deleted
> immediately, archived, tombstoned}`. Archived sites get their own
> 🪦 row in the audit and are skipped by CHECK_040/041/042. Currently
> 3 sites archived via category (lamill-events, newiniot.com,
> swiftly.co.in).
>
> Two sites went through end-to-end pipeline tests this session.
> lamill.io: migrated Vercel deploy from `codervijo/sites` monorepo
> subdirectory to standalone `codervijo/lamill.io`, untracked from
> outer, full SEO baseline added (robots.txt, sitemap.xml, meta
> description, canonical, OG, Twitter, JSON-LD) — went from 18 fails
> → 6 fails on conformance. airsucks.com: bootstrapped end-to-end from
> a Lovable export via `new bootstrap --from-genai`, deployed by hand,
> live with full SEO baseline + launched-date tracked. Smoothest
> bootstrap run yet — first site through the matured pipeline with
> minimal manual intervention. csinorcal.church flagged as nested
> anti-pattern + truncated naming but deferred (dark site, no SEO
> pressure).
>
> Three GitHub repos renamed for the full-domain naming convention:
> `homeloop.app` → `homeloom.app` (typo fix, not just truncation),
> `lamillrentals` → `lamillrentals.com`, `keralavotemap` →
> `keralavotemap.site`. After all three, CHECK_040 down to one
> violation (csinorcal — dark site, intentional).
>
> Tool renamed: `portfolio` → `lamill` (light rename — `[project.scripts]`
> entry only, Python package stays `portfolio` internally; `portfolio`
> kept as a legacy alias). Made the rename feasible by installing
> system-wide via `uv tool install --editable`, so `lamill` works from
> any directory. Tracks with the user's Lamill Web Systems brand.
>
> Test suite over this stretch: 803 → 877 passing.
