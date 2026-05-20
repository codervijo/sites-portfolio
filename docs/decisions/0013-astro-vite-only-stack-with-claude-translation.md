# 0013 — Astro + Vite as the only supported `sites/*` stack; non-Astro `--git-url` repos translated via Claude subprocess

- **Status:** Accepted
- **Date:** 2026-05-20

## Context

The `sites/*` workspace has accumulated stack heterogeneity over time:

- **Astro + Vite** — the operator's primary new-site stack. v3.A's
  blank-template bootstrap produces this shape (`astro.config.mjs`,
  Vite under the hood, pnpm-only per ADR-0008).
- **Vite + React** — earlier sites use this shape (no Astro layer,
  pure SPA).
- **TanStack Start** — `airsucks.com` and the just-bootstrapped
  `agesdk.dev` came from Lovable's exports, which default to
  TanStack Start (TanStack Router + Cloudflare's Vite plugin +
  `main: "src/server.ts"` for SSR via Workers).
- (Latent: Next.js, SvelteKit — could appear if operator uses other
  AI-design tools or hand-builds.)

The fleet of 22 sibling projects today has at least three actively-
used JS framework shapes. Each carries its own build config, its
own bundler quirks, and its own deploy considerations.

Two adjacent decisions force a stack-policy:

1. **ADR-0012 unified CF deploys onto the Pages-API git-integrated
   flow.** The `build_command` in the CF project config is
   `pnpm run build`; CF expects `dist/` output. Frameworks that
   diverge from this (e.g., Next.js's `next` builder; TanStack
   Start's `nitro` output) require per-stack build-config
   accommodation. Maintaining N stack-specific `build_command`
   variations grows linearly with framework count.
2. **v15.H's `--git-url` bootstrap path** (Lovable + similar AI
   design tools) imports arbitrary externally-generated repos.
   Without a stack policy, every Lovable export quirk surfaces as
   a per-project edge case the operator's fleet ops have to
   tolerate.

The operator directive 2026-05-20: *"i dont want to use tanstack, i
want to standardize on astro and vite."* Plus: *"if tanstack, spawn
claude code to translate to Astro."*

## Decision

**`sites/*` projects shipped via `lamill new bootstrap` are Astro +
Vite, full stop.** The supported stack is the one the existing v3.A
blank-template scaffold produces:

- Astro 5+ (per `package.json` `astro` dependency)
- Vite 6+ (transitive via Astro)
- pnpm-only (per ADR-0008)
- Build → `dist/` (matches the CF Pages-API default `destination_dir`)

### Two enforcement paths

1. **Blank scaffold path** (`lamill new bootstrap <domain>` without
   `--git-url` / `--from-genai`) — already Astro+Vite by default.
   No change.
2. **`--git-url` / `--from-genai` path** (Lovable + similar
   external-repo imports) — the cloned repo's stack is detected
   immediately after clone:
   - **Already Astro+Vite** → proceed with existing
     `_copy_from_genai()` path.
   - **TanStack Start / Next.js / SvelteKit / Vite-only-no-Astro /
     other** → spawn the `claude` CLI subprocess (matching the
     Tier-2-fixers pattern of ADR-0006) with a translation prompt
     instructing it to read the cloned source and emit an
     Astro+Vite project in the project root. Validator checks the
     translation's output (package.json mentions `astro` + `vite`;
     `astro.config.{mjs,ts}` exists; no `tanstack` / `next` /
     `@sveltejs` deps remain) before proceeding. On validator
     failure, bail with a clear error.

### Legacy sites

The directive applies to **new** bootstraps. Existing fleet sites
that are not Astro+Vite (e.g., `airsucks.com` TanStack Start, the
4 Vite+React cf-pages sites, Next.js sites if any) **stay as-is**.
Migration of legacy sites is out of scope; per operator 2026-05-20:
*"3 [airsucks], leave."*

### Lovable workflow going forward

Operator commits to asking Lovable for **Astro exports** going
forward (operator note 2026-05-20). The Claude-translation path
exists as a safety net for cases where:

- Lovable can't (yet) produce Astro for a given UI complexity.
- Other AI design tools without Astro export are used.
- An operator hand-clones an existing TanStack/Next/Svelte repo
  that they want to lamill-ify.

## Consequences

### Positive

- **Single build config to maintain.** `pnpm run build` → `dist/`
  works for every sites/* project. CF Pages project shape is the
  same for every site.
- **Conformance check surface stays bounded.** Stack-specific
  checks (`astro-version-ok`, `has-canonical-link` via Astro's
  Layout slot, etc.) target one stack instead of N.
- **Lovable workflow is robust.** Non-Astro exports auto-translate;
  the operator's UI work doesn't dictate stack lock-in.
- **`--from-genai` becomes a uniform shape.** Today the path
  blindly copies Lovable's whatever-stack output verbatim; the
  v15.H translation step makes the output conform.

### Negative / Constraints

- **Claude subprocess cost** at bootstrap-time. Each non-Astro
  translation runs Claude once (~$0.02-0.10 depending on repo
  size). Operator's fleet of ~22 sites typically bootstraps once
  per site, so amortized cost is small.
- **Translation quality is bounded by Claude's understanding of
  the source framework.** Pages with framework-specific server
  code (TanStack Start's `src/server.ts`, Next.js API routes) may
  not translate cleanly. The translator's mandate is to drop
  framework-specific server code with a `TODO:` placeholder rather
  than hand-port complex backend logic. Operator reviews the
  translation diff before committing.
- **Validator must be vigilant.** Claude can produce output that
  *looks* Astro-shaped (right package.json deps, plausible config)
  but doesn't actually build. v15.H's validator runs basic shape
  checks; the operator's first `make build` in Docker is the real
  smoke test.
- **Stack lock-in risk.** If Astro 7 introduces a breaking change
  that the operator can't easily migrate to, the fleet is
  uniformly impacted. Mitigation: ADR-0008's pnpm-only pinning
  plus the operator's right to revisit this ADR if Astro stops
  being a good fit.
- **Future-stack support pathway.** If the operator adds
  "Astro + something" or "X-framework" as a second supported
  stack later, this ADR supersedes via a new ADR; we don't try to
  bolt N-stack support onto the same machinery now.

## Status & supersession

Accepted 2026-05-20. Pairs with ADR-0012 (no-wrangler-deploy;
unified Pages-API). Future re-evaluation triggers: Lovable
discontinues / nerfs Astro export support; Astro itself becomes
a non-viable choice; operator's growth requires a stack the
Claude-translator can't reliably target.

Related: ADR-0006 (Tier 2 fixers as Claude subprocess) — same
subprocess pattern; v15.H reuses the runner + prompt-template
shape, with a different prompt body.
