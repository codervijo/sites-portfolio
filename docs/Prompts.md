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
