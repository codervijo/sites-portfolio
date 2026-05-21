"""v15.H — Bootstrap stack normalization via Claude subprocess.

Per ADR-0013: `sites/*` projects must be Astro+Vite. When `--git-url`
clones an external repo (typically a Lovable export, but anyone's
GitHub repo works), this module:

  1. **Detects** the cloned repo's stack via `package.json` + config
     files.
  2. If non-Astro, **translates** the source into an Astro+Vite shape
     in-place via the `claude` CLI subprocess (reuses the Tier-2-fixer
     pattern from `fix_helpers.run_claude()`; ADR-0006).
  3. **Validates** the translator's output before bootstrap proceeds —
     bails with `StackTranslationError` if the output doesn't satisfy
     Astro+Vite shape requirements.

The translator's output overwrites the project root. The cloned
`genai/` subdir is preserved untouched as the original-source
reference.

Reads required:
  - `<project_dir>/genai/package.json` (detector)
  - All files under `<project_dir>/genai/` (translator)

Writes:
  - All files under `<project_dir>/` except `genai/` (translator)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .fix_helpers import ClaudeResult, claude_available, run_claude

# Stack values returned by detect_stack(). Use these constants in
# bootstrap.py + tests to avoid string-mismatch bugs.
STACK_ASTRO = "astro"
STACK_VITE_REACT = "vite-react"
STACK_TANSTACK = "tanstack-start"
STACK_NEXTJS = "nextjs"
STACK_SVELTEKIT = "sveltekit"
STACK_UNKNOWN = "unknown"

# Translator budget cap. v15.K bumped from $0.50 → $2.00 after
# operator's `agesdk.dev` (real-world TanStack→Astro) hit
# `error_max_budget_usd` at $0.524 / 22 turns. Empirical baseline:
# typical Lovable exports are 5-30 files; smaller ones run $0.10-0.30;
# complex ones with rich routing + framework-specific server code can
# easily hit $1-2. $2.00 default keeps the safety net while covering
# the common case. Operator can override via `--budget` flag on
# `lamill new bootstrap`.
_DEFAULT_BUDGET_USD = 2.00

# Translator timeout. Empirically Claude takes 30s-3min depending on
# repo size + complexity. 300s (5min) covers worst-case Lovable
# exports without false timeouts.
_DEFAULT_TIMEOUT_S = 300


class StackTranslationError(RuntimeError):
    """Raised by bootstrap when translation can't proceed:
      - `claude` CLI not on PATH
      - Claude subprocess errored (budget exceeded, timeout, etc.)
      - Translator output failed validation
      - Detected stack is `STACK_UNKNOWN` (no policy to translate it)

    Bootstrap catches + cleans up (removes any partial output;
    surfaces the issue to the operator with actionable next steps).
    """


@dataclass(frozen=True)
class StackDetection:
    """Result of inspecting a cloned repo for its framework stack.

    `signals` lists the concrete evidence (e.g. `"dependency:astro"`,
    `"file:src/server.ts"`) so the operator can see why a particular
    stack was inferred. Useful when the detection seems wrong.
    """
    stack: str
    signals: list[str] = field(default_factory=list)


def detect_stack(genai_dir: Path) -> StackDetection:
    """Identify the framework stack of a cloned repo.

    Detection order matters — most specific first:
      1. Astro (dependency + astro.config presence)
      2. SvelteKit (@sveltejs/kit dependency or svelte.config)
      3. Next.js (next dependency)
      4. TanStack Start (any @tanstack/* dep, optionally with
         src/server.ts for SSR)
      5. Vite + React (vite + react deps with no Astro layer)
      6. Unknown (nothing matched)
    """
    signals: list[str] = []

    if not genai_dir.is_dir():
        return StackDetection(STACK_UNKNOWN, ["genai_dir_missing"])

    pkg_path = genai_dir / "package.json"
    deps: dict[str, str] = {}
    if pkg_path.exists():
        try:
            pkg_data = json.loads(pkg_path.read_text())
            deps = {
                **(pkg_data.get("dependencies") or {}),
                **(pkg_data.get("devDependencies") or {}),
            }
        except (json.JSONDecodeError, OSError):
            signals.append("package_json_unreadable")

    # Astro — highest priority (this is the target stack).
    if "astro" in deps:
        signals.append("dependency:astro")
        if any((genai_dir / f"astro.config.{ext}").exists()
               for ext in ("mjs", "ts", "js")):
            signals.append("config:astro.config")
        return StackDetection(STACK_ASTRO, signals)

    # SvelteKit.
    if "@sveltejs/kit" in deps:
        signals.append("dependency:@sveltejs/kit")
        return StackDetection(STACK_SVELTEKIT, signals)
    if (genai_dir / "svelte.config.js").exists():
        signals.append("config:svelte.config.js")
        return StackDetection(STACK_SVELTEKIT, signals)

    # Next.js.
    if "next" in deps:
        signals.append("dependency:next")
        return StackDetection(STACK_NEXTJS, signals)

    # TanStack Start (Lovable's current default).
    if any(k.startswith("@tanstack/") for k in deps):
        tanstack_keys = [k for k in deps if k.startswith("@tanstack/")]
        signals.append(f"dependency:{tanstack_keys[0]}")
        for ext in ("ts", "tsx", "js", "jsx"):
            if (genai_dir / "src" / f"server.{ext}").exists():
                signals.append(f"file:src/server.{ext}")
                break
        return StackDetection(STACK_TANSTACK, signals)

    # Vite + React (no Astro layer).
    if "vite" in deps and "react" in deps:
        signals.append("dependency:vite")
        signals.append("dependency:react")
        return StackDetection(STACK_VITE_REACT, signals)

    return StackDetection(STACK_UNKNOWN, signals or ["no_matching_signals"])


@dataclass(frozen=True)
class ValidationResult:
    """Output of `validate_translation()`. `ok=True` iff `issues` is
    empty; non-empty issues are reportable strings for the operator."""
    ok: bool
    issues: list[str] = field(default_factory=list)


def validate_translation(project_dir: Path) -> ValidationResult:
    """Verify the post-translation `project_dir` conforms to Astro+Vite
    shape. Checks:

      1. `package.json` exists + parses as JSON
      2. `package.json` lists `astro` in deps
      3. `astro.config.{mjs,ts,js}` exists at root
      4. No banned framework deps remain (`next`, `@sveltejs/kit`,
         `@tanstack/react-start*`)
      5. `src/pages/` exists (Astro file-based routing target)
      6. No `wrangler.jsonc` at root (deploy pipeline v15.I owns
         this; translator should not emit it)

    Returns `ValidationResult(ok=False, issues=[...])` on any
    failure. Bootstrap wraps this in `StackTranslationError`.
    """
    issues: list[str] = []

    # 1+2: package.json present + astro dep.
    pkg_path = project_dir / "package.json"
    if not pkg_path.exists():
        issues.append("missing package.json at project root")
    else:
        try:
            pkg_data = json.loads(pkg_path.read_text())
        except json.JSONDecodeError as e:
            issues.append(f"package.json: invalid JSON ({e})")
            pkg_data = {}
        deps = {
            **(pkg_data.get("dependencies") or {}),
            **(pkg_data.get("devDependencies") or {}),
        }
        if "astro" not in deps:
            issues.append("package.json: missing 'astro' dependency")
        # 4: banned frameworks. These are PARTIAL matches because
        # tanstack publishes many packages (@tanstack/react-start,
        # @tanstack/react-start-rsc, @tanstack/react-router, ...).
        banned_prefixes = (
            "@tanstack/react-start",
            "next",
            "@sveltejs/",
        )
        for dep_key in deps:
            for prefix in banned_prefixes:
                # Exact match for "next" (avoid matching "next-link" etc.)
                if prefix == "next" and dep_key != "next":
                    continue
                if dep_key == prefix or dep_key.startswith(prefix):
                    issues.append(
                        f"package.json: banned framework dep present: "
                        f"'{dep_key}' (translator should have replaced)"
                    )
                    break

    # 3: astro.config.*
    if not any((project_dir / f"astro.config.{ext}").exists()
               for ext in ("mjs", "ts", "js")):
        issues.append("missing astro.config.{mjs,ts,js} at project root")

    # 5: src/pages/
    if not (project_dir / "src" / "pages").is_dir():
        issues.append(
            "missing src/pages/ directory "
            "(expected for translated pages — Astro file-based routing)"
        )

    # NOTE — v15.M removed the v15.H "no wrangler.jsonc" check.
    # The original concern was that the translator shouldn't EMIT
    # wrangler.jsonc; but bootstrap's CF safety fixes legitimately
    # write one as part of every Astro scaffold (for local dev /
    # `wrangler dev` etc.). The v15.I deploy pipeline owns the
    # remote CF config; the local wrangler.jsonc is fine + expected.

    return ValidationResult(ok=not issues, issues=issues)


def translate_to_astro(
    project_dir: Path,
    *,
    detection: StackDetection,
    budget_usd: float = _DEFAULT_BUDGET_USD,
    timeout_s: int = _DEFAULT_TIMEOUT_S,
) -> ClaudeResult:
    """Spawn `claude` CLI to translate `<project_dir>/genai/`'s source
    into an Astro+Vite project at `<project_dir>/` root.

    Reuses `fix_helpers.run_claude()` (the Tier-2-fixer subprocess
    pattern; ADR-0006). Same restricted toolset (Read/Edit/Glob/Grep);
    no Bash, no network beyond model calls.

    The `genai/` subdir is preserved untouched — the translator reads
    from it but writes only to project root. Operator keeps the
    original-clone reference for archeology / debugging.

    Returns `ClaudeResult` — bootstrap checks `.ok` and surfaces
    `.error` on failure.
    """
    if not claude_available():
        return ClaudeResult(
            ok=False, cost_usd=0.0, duration_s=0.0,
            error="claude-not-found",
            raw_output=(
                "The `claude` CLI is not on PATH. Stack translation "
                "requires Claude Code installed locally. Install per "
                "https://docs.claude.com/claude-code/quickstart, then "
                "re-run `lamill new bootstrap`."
            ),
        )

    prompt = _build_translation_prompt(project_dir, detection)
    # v15.L hotfix — extended toolset for file CREATION.
    # The default Tier-2-fixer set (Read/Edit/Glob/Grep) can only
    # modify existing files. v15.H needs to write NEW Astro+Vite
    # scaffolding at project root + create directories like
    # `src/pages/`, so add Write + Bash.
    return run_claude(
        prompt,
        cwd=project_dir,
        budget_usd=budget_usd,
        timeout_s=timeout_s,
        allowed_tools="Read Write Edit Glob Grep Bash",
    )


# v15.M — port translator timeout default. The synchronous full-
# translation path was timing out at the 300s default; the port
# path runs slower because it has full Write/Bash + more to do.
# Default 30 minutes; operator can override via --timeout flag on
# `lamill project translate`.
_DEFAULT_PORT_TIMEOUT_S = 1800
_DEFAULT_PORT_BUDGET_USD = 5.00


def port_to_astro(
    project_dir: Path,
    *,
    source_stack: str,
    source_signals: list[str],
    budget_usd: float = _DEFAULT_PORT_BUDGET_USD,
    timeout_s: int = _DEFAULT_PORT_TIMEOUT_S,
) -> ClaudeResult:
    """v15.M — port pages/components from `<project_dir>/genai/` into
    the existing Astro+Vite scaffold at `<project_dir>/` root.

    Used by `lamill project translate <domain>` (separate from
    bootstrap). Smaller delta than `translate_to_astro()` because the
    Astro scaffold + package.json + astro.config + tooling are
    already in place — Claude only needs to port the operator-
    visible content (pages, components, copy, styles).

    Returns `ClaudeResult` — caller checks `.ok` and surfaces
    `.error` on failure.
    """
    if not claude_available():
        return ClaudeResult(
            ok=False, cost_usd=0.0, duration_s=0.0,
            error="claude-not-found",
            raw_output=(
                "The `claude` CLI is not on PATH. Translation requires "
                "Claude Code installed locally. Install per "
                "https://docs.claude.com/claude-code/quickstart."
            ),
        )

    prompt = _build_port_prompt(project_dir, source_stack, source_signals)
    return run_claude(
        prompt,
        cwd=project_dir,
        budget_usd=budget_usd,
        timeout_s=timeout_s,
        allowed_tools="Read Write Edit Glob Grep Bash",
    )


def _build_port_prompt(
    project_dir: Path, source_stack: str, source_signals: list[str],
) -> str:
    """v15.M — port prompt. Smaller scope than the full-translation
    prompt because the Astro scaffold is already in place."""
    return f"""You are porting a `{source_stack}` project's UI into an
already-scaffolded Astro + Vite project.

## Setup

  - The project root (your current working directory) already has an
    Astro + Vite scaffold: `package.json`, `astro.config.mjs`,
    `src/pages/index.astro` placeholder, `src/components/`,
    `src/layouts/`, `src/styles/`, `public/`, etc.
  - The untranslated source is at `genai/` (a subdirectory of your
    cwd). Detection signals:
{chr(10).join(f"      - {s}" for s in source_signals)}

## Task

Port the operator-visible content from `genai/` into the existing
scaffold:

  1. **Pages** → `src/pages/`. Each route in `genai/` becomes a
     `.astro` file (or `.md` for static content) under `src/pages/`.
     Use Astro's file-based routing.
  2. **Components** → `src/components/`. React components can stay
     as React (mount as Astro islands via `client:load` /
     `client:visible` / `client:idle`). UI library components (e.g.
     shadcn/ui) can be copied verbatim if pure presentational; port
     to Astro components if they're trivial.
  3. **Styles** → `src/styles/` or per-component. Copy Tailwind
     classes verbatim. Copy global CSS / Tailwind config.
  4. **Layouts** → `src/layouts/`. Extract shared chrome (header /
     footer / meta) into an Astro Layout component.
  5. **Assets** → `public/`. Copy verbatim from `genai/public/`.

## Do NOT touch

  - `package.json` at root — the existing one is correct.
  - `astro.config.mjs` — leave alone (add to it only if you must
    register a new Astro integration like `@astrojs/react`).
  - `tsconfig.json` / `vite.config.*` — leave alone.
  - `wrangler.jsonc` if present — that's deploy config, not your
    concern.
  - Anything inside `genai/` — read-only reference.

## Drop with TODO markers

Framework-specific server code does NOT translate to Astro's
static-output model. Drop with `TODO:` markers under
`src/lib/server-todo.md`:

  - TanStack Start `src/server.ts` / route handlers
  - Next.js `src/pages/api/*` or `src/app/api/*`
  - SvelteKit `src/routes/**/+server.ts`

## Preserve

  - All operator-visible copy (headings, page text, CTAs).
  - All design (Tailwind classes, layout, spacing, colors).
  - All public assets.
  - Client-side interactivity — React hooks stay, just mount as
    Astro islands.

## Done condition

You're done when:
  - `src/pages/` has files matching the source's routes.
  - `src/components/` has the source's components ported.
  - `public/` has the source's static assets copied.
  - No `@tanstack/*` / `next` / `@sveltejs/*` imports appear in the
    ported files.

The lamill validator will run a basic shape check after; it doesn't
require completeness, just that key files exist and don't import
banned dependencies.
"""


def _build_translation_prompt(
    project_dir: Path, detection: StackDetection,
) -> str:
    """The translation prompt sent to Claude. Spelled out per
    ADR-0013's mandate."""
    return f"""You are translating a `{detection.stack}` project to Astro + Vite.

## Source

Read the source from `genai/` (a subdirectory of your current
working directory). Detection signals:
{chr(10).join(f"  - {s}" for s in detection.signals)}

## Target

Emit an equivalent Astro + Vite project at the **project root**
(your current working directory). Do NOT write inside `genai/` —
preserve it as the original-source reference for archeology.

## Required output files

1. `package.json` — pnpm-only (no bun, no npm). Must list `astro`
   and `vite` in dependencies. Build script: `"build": "astro build"`.
   Dev script: `"dev": "astro dev"`. Preserve any operator-facing
   scripts from the source (e.g. `lint`, `format`, `test:seo`).
2. `astro.config.mjs` — minimal Astro 5+ config. Include the
   `@astrojs/react` integration if the source has React components
   you're preserving as islands. Set `output: "static"`.
3. `src/pages/` — one `.astro` file per route. Use Astro's
   file-based routing convention.
4. `src/components/` — preserve component organization from the
   source. React components stay React (use Astro islands with
   `client:load` or `client:visible` directives for hydration).
5. `src/layouts/` — extract shared chrome (header / footer / meta)
   into an Astro Layout.
6. `src/styles/` — preserve Tailwind / global CSS verbatim.
7. `public/` — copy static assets unchanged from `genai/public/`.
8. `tsconfig.json` — if the source uses TypeScript.

## Drop with TODO markers

Framework-specific server code does NOT translate cleanly to
Astro's static-output model. Drop with a `TODO:` marker:

  - TanStack Start `src/server.ts` / `src/server.tsx`
  - Next.js `src/pages/api/*` or `src/app/api/*`
  - SvelteKit `src/routes/**/+server.ts`

Replace with a `src/lib/server-todo.md` file documenting what was
in the dropped files. Operator hand-ports server logic outside
the translation.

## Preserve

  - All operator-visible content (page copy, headings, ICP-targeting
    text, CTAs).
  - All design (layout, spacing, colors, typography). Tailwind classes
    keep verbatim; convert only the JSX→.astro wrapper.
  - All public assets (images, fonts, favicons).
  - All client-side interactivity. React components with `useState` /
    `useEffect` stay as React; mount them as Astro islands.

## Do NOT write

  - `wrangler.jsonc` — the lamill deploy pipeline (v15.I) writes this.
  - `bun.lock` / `bunfig.toml` — pnpm-only per ADR-0008.
  - `vite.config.ts` at root — Astro owns the Vite config under the hood.
  - Anything inside `genai/` (read-only reference).

When the file emission is complete, your work is done. The lamill
v15.H validator will run next and report any shape issues.
"""
