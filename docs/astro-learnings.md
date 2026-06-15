# Astro learnings

Hard-won, fleet-grounded notes on building and operating Astro sites — the
canonical shape we standardized on, the traps we actually hit, and the
conventions lamill enforces. Written to be **reusable across projects**
(like `docs/coding-agents-survey.md`): the rationale lives here; the
enforcement lives in the `CHECK_NNN` catalog and the ADRs cited below.

As of 2026-06-14 ~27 of the fleet's sites are Astro (the rest are
Vite/React or TanStack Start). Astro is the **default stack for new
`sites/*` projects** (ADR-0013 — "Astro + Vite only").

---

## 1. The canonical config (known-good shape)

Every fleet Astro site converges on this `astro.config.mjs`. If a site
drifts from it, that's the thing to fix first:

```js
// astro.config.mjs
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  site: 'https://example.com',     // REQUIRED — see §3 (sitemap breaks without it)
  integrations: [sitemap()],       // emits /sitemap-index.xml — see §3
  output: 'static',                // prerender everything — see §2
  vite: {
    plugins: [tailwindcss()],      // Tailwind v4 is a Vite plugin, not an Astro integration
  },
});
```

Baselines (enforced): **Astro ≥ 5** (`CHECK_036 astro-version-ok`),
**Vite ≥ 6**, **pnpm-only** (no `package-lock.json` / `bun.lockb` /
`yarn.lock` — those are conformance failures).

---

## 2. Prerendering / output modes — the easy case (contrast with TanStack Start)

This is where Astro is *dramatically* simpler than the framework it's worth
contrasting with. We spent a 5-hour quota window watching an agent fail to
turn on prerendering in a **TanStack Start** site (the config was buried
behind a custom `@lovable.dev/vite-tanstack-config` wrapper; the right knob
was undiscoverable without reading `node_modules`). **Astro has none of that
failure mode:**

- **`output: 'static'` (the default) prerenders every page at build time.**
  No plugin to enable, no crawl config. Crawlable HTML with full `<head>`
  on every route is the *baseline*, not a feature you switch on.
- **Per-page opt-out**, not opt-in: a page that needs SSR sets
  `export const prerender = false` at the top of the `.astro`/endpoint file.
  The inverse of TanStack Start, where SSR is the floor and prerender is the
  thing you fight to configure.
- **`output: 'server'`** flips the default to on-demand SSR for the whole
  site and requires an **adapter** (`@astrojs/cloudflare`, `@astrojs/node`,
  …). Most fleet sites are pure `static` and need no adapter at all.

**Agent-facing lesson:** for an Astro site, "make every route emit crawlable
HTML" is usually *already true* or a one-line `output: 'static'` fix. The
risk on Astro isn't prerender config — it's someone having set
`output: 'server'` without an adapter, or a page that wrongly opted out via
`prerender = false`. Look there first, not at plugin wiring.

---

## 3. Sitemap — two traps that cost real debugging

Astro's sitemap is a one-line integration (`integrations: [sitemap()]`), but
two things bite:

1. **`site:` is mandatory.** `@astrojs/sitemap` emits *nothing* (or wrong
   URLs) without the top-level `site: 'https://domain.com'`. This is the #1
   reason a sitemap silently fails to generate.

2. **It emits `/sitemap-index.xml`, NOT `/sitemap.xml`.** This is the GSC
   trap (architecture.md § v32.G, ADR-0022): submitting the assumed
   `/sitemap.xml` to Search Console fails because an SPA/catch-all serves
   that path as HTML → GSC "couldn't parse" error. The deploy pipeline now
   resolves the real sitemap URL from the live `robots.txt` `Sitemap:` line
   (`gsc_admin.resolve_sitemap_url`) instead of guessing. When wiring GSC for
   an Astro site by hand, submit **`/sitemap-index.xml`**.

`CHECK_064 sitemap-in-build-script` accepts the Astro path by detecting
`@astrojs/sitemap` in deps (the Vite path instead looks for a
`generate-sitemap` step chained into the `build` script).

---

## 4. `<head>` / SEO is layout-owned — nothing is automatic

Astro does **not** inject any SEO tags for you. Everything the SEO checks
look for lives in your layout (`src/layouts/*.astro`) `<head>`, usually
driven by frontmatter/props per page. The fleet enforces this surface via
`CHECK_070–080`:

| Check | Tag |
|-------|-----|
| 070 | `<title>` |
| 071 | `<meta name="description">` |
| 072 | `<link rel="canonical">` |
| 073 | `<meta name="viewport">` |
| 074 | `<html lang="...">` |
| 075 | `<meta name="robots">` |
| 076 | Open Graph (`og:*`) |
| 077 | Twitter card |
| 078 / 079 | JSON-LD (`Organization` or `WebSite`) |

Plus analytics (`CHECK_080 has-analytics`, `148/149` GA4 id + script-src).
Put these in one shared `<BaseHead>` component and feed per-page values via
props — don't scatter them across pages, or they drift and the checks go red
unevenly.

---

## 5. Conventions lamill enforces (and why)

- **`.astro/` must be gitignored** (`CHECK_156 astro-cache-gitignored`).
  Astro's generated cache (`.astro/`) is build output. Pre-v33.I scaffolds
  shipped a `.gitignore` missing it, so the cache accumulated as **untracked
  files** — which is not just noise, it *blocks `project delegate`* (a dirty
  tree fails the clean-tree preflight). If a delegate run "aborts — clean
  tree" oddly, or a site has dozens of untracked `.astro/...` entries, this
  is why. Fix: add `.astro/` (and `dist/`) to `.gitignore`
  (`CHECK_142 gitignore-covers-build-output`).
- **Astro ≥ 5 / Vite ≥ 6.** The CF Pages **bun-detection trap** was hit on
  Vite 5 (CF's build image mis-detected the package manager); Vite ≥ 6 +
  pnpm-only avoids it. Don't downgrade.
- **Tailwind v4 is a Vite plugin** (`@tailwindcss/vite`), passed through
  `vite.plugins`, **not** an Astro integration. Adding it as an integration
  is a common wrong guess.

---

## 6. Deploying Astro on Cloudflare Pages

- `output: 'static'` → build output is `dist/` → CF Pages serves it
  directly. No adapter, no `wrangler deploy` (the unified pipeline uses the
  CF Pages **API**, git-integrated — ADR-0012; see architecture.md § deploy).
- Sitemap lives at `/sitemap-index.xml`; GSC registration submits that URL
  (resolved from live `robots.txt`, never assumed — §3).
- If you ever switch a site to `output: 'server'`, you need
  `@astrojs/cloudflare` and the deploy story changes (cf-workers path). Most
  sites should stay static.

---

## 7. Translation cost (TanStack/other → Astro)

ADR-0013's stack policy translates non-Astro repos to Astro via a
Claude-subprocess (same Tier-2-fixer pattern as ADR-0006). Real-world
finding: **a full framework translation is expensive** — `agesdk.dev`
(TanStack → Astro) hit `error_max_budget_usd` mid-translation. Treat
"port this site to Astro" as a budgeted, supervised job, not a one-shot;
fine-split it the way `project delegate` splits large requests. Sites that
predate the Astro-only policy (e.g. `airsucks.com`, cf-workers TanStack) are
deliberately **left as-is** — don't translate them without a reason.

---

## 8. The cross-stack lesson worth carrying

The TanStack debugging that prompted this doc generalizes to Astro too:
**before editing any framework config, read what the config actually imports
from.** A site's `astro.config.mjs` *looks* standard, but a project may wrap
`defineConfig`, add a custom integration, or inline a build plugin (the fleet
inlines a `versionStamp()` Vite plugin in several configs). When an agent —
or you — is about to change config behavior, read the imported wrapper/plugin
source in `node_modules` first. The textbook snippet from the framework docs
is often *not* how this particular repo is wired, and guessing burns a build
loop per wrong attempt.

---

## References

- `CHECK_036` astro-version · `CHECK_156` astro-cache-gitignored ·
  `CHECK_064` sitemap-in-build · `CHECK_070–080` SEO head ·
  `CHECK_142` gitignore-build-output (`src/portfolio/checks/`)
- ADR-0013 (Astro + Vite only) · ADR-0012 (CF Pages API deploy) ·
  ADR-0022 (honest deploy/sitemap resolution)
- architecture.md § deploy (v32.G sitemap-URL resolution) ·
  shipping-history.md § v3 / v15 (stack policy + translation)
- `docs/coding-agents-survey.md` — the companion cross-project reference.
