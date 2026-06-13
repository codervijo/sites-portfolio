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
import re
from dataclasses import dataclass, field
from pathlib import Path

from .fix_helpers import ClaudeResult, claude_available, run_claude
from .stack_classifier import merged_deps

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
            deps = merged_deps(pkg_data)
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
        deps = merged_deps(pkg_data)
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

    # v15.S — dep-import consistency. The translator can faithfully
    # port a `@import "tailwindcss"` line from genai/'s CSS but
    # forget to add the matching dep to package.json. Caught
    # disclosur.dev (2026-05-20): ported globals.css carried the v4
    # import; package.json only had astro + @astrojs/sitemap; dev
    # server failed at "Unable to resolve `@import \"tailwindcss\"`".
    # The validator must catch dep–import drift, not just shape.
    src_dir = project_dir / "src"
    if pkg_path.exists() and src_dir.is_dir():
        tw_usage = _detect_tailwind_usage(src_dir)
        if tw_usage["any"] and "tailwindcss" not in deps:
            issues.append(
                "package.json: source references tailwindcss "
                f"(e.g. {tw_usage['evidence']}) but 'tailwindcss' is "
                "not in dependencies — translator should have ported "
                "the dep from genai/package.json"
            )
        if tw_usage["v4_import"] and "@tailwindcss/vite" not in deps:
            issues.append(
                "package.json: source uses Tailwind v4 "
                f"(`@import \"tailwindcss\"` in {tw_usage['evidence']}) "
                "but '@tailwindcss/vite' is not in dependencies — "
                "Tailwind v4 requires the Vite plugin"
            )

    return ValidationResult(ok=not issues, issues=issues)


# v15.S — tailwind usage detection. Walked from validate_translation.
# Returns evidence + flags so the validator can produce specific
# operator-facing messages instead of generic "missing dep".
_TW_V4_IMPORT = re.compile(r'@import\s+["\']tailwindcss["\']')
_TW_V3_DIRECTIVE = re.compile(r'@tailwind\s+(base|components|utilities)\b')
_TW_SCAN_SUFFIXES = (".css", ".scss", ".sass", ".pcss")


def _detect_tailwind_usage(src_dir: Path) -> dict[str, object]:
    """Scan `src_dir` for Tailwind usage signals.

    Returns dict with:
      - `any` (bool): tailwind referenced anywhere
      - `v4_import` (bool): Tailwind v4 `@import "tailwindcss"` form
        (which requires `@tailwindcss/vite` + the v4 plugin wiring)
      - `evidence` (str): first matching file path (relative) for
        operator-facing error messages

    Scans `.css`/`.scss`/`.sass`/`.pcss` files only. Bounded scope
    (no node_modules, no genai/, no tests).
    """
    result: dict[str, object] = {
        "any": False, "v4_import": False, "evidence": "",
    }
    for path in src_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _TW_SCAN_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = path.relative_to(src_dir.parent)
        if _TW_V4_IMPORT.search(text):
            result["any"] = True
            result["v4_import"] = True
            if not result["evidence"]:
                result["evidence"] = str(rel)
            return result  # v4 is the strictest finding
        if _TW_V3_DIRECTIVE.search(text):
            result["any"] = True
            if not result["evidence"]:
                result["evidence"] = str(rel)
    return result


# v15.S — sweep Claude's atomic-write tmp artifacts. The `claude` CLI
# Write tool writes via `<name>.tmp.<pid>.<hex>` then renames; under
# certain failure modes (timeout, partial state, parallel writes) the
# rename gets skipped and the .tmp.* file lingers. Astro's dev server
# then emits `Unsupported file type` warnings on every reload.
# Caught disclosur.dev (2026-05-20): three .astro.tmp.* files in
# src/pages/dashboard/ after a successful port_to_astro call.
_TMP_ARTIFACT = re.compile(r"\.tmp\.\d+\.[0-9a-f]+$")


def sweep_tmp_artifacts(project_dir: Path) -> list[str]:
    """Remove leftover Claude atomic-write artifacts under `project_dir`.

    Matches files whose name ends in `.tmp.<digits>.<hex>` anywhere
    under the project root (except `node_modules/`, `genai/`,
    `.git/` — which are read-only or vendored and shouldn't have
    been touched anyway).

    Returns the list of relative paths swept (for logging). Empty
    list is the normal post-translation case.
    """
    swept: list[str] = []
    skip_dirs = {"node_modules", "genai", ".git", "dist", ".astro"}
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_dirs for part in path.relative_to(project_dir).parts):
            continue
        if _TMP_ARTIFACT.search(path.name):
            try:
                path.unlink()
                swept.append(str(path.relative_to(project_dir)))
            except OSError:
                pass
    return swept


# v15.S — pnpm v11 build-script allowlist. Caught disclosur.dev
# (2026-05-20): pnpm install in a freshly-translated project hit
# `[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: esbuild, sharp`
# and silently wrote a stub `pnpm-workspace.yaml` with placeholder
# `allowBuilds:` lines into the project root — which then overrides
# the parent sites/pnpm-workspace.yaml. Operator has to delete the
# stub + re-run install, OR run interactive `pnpm approve-builds`.
#
# Fix: lamill pre-seeds a correct per-project pnpm-workspace.yaml
# at the end of every translate/port so pnpm never enters the
# interactive approval flow. The allowlist matches the parent
# sites/pnpm-workspace.yaml — universal across the Astro+Vite stack
# (esbuild is Vite's bundler; sharp is Astro's image optimizer).
#
# 2026-05-22 PM hotfix — pnpm v11.1.3 changes the schema:
#   - Requires `packages:` field to recognize this as a workspace
#     root (else `pnpm install` may not read `pnpm-workspace.yaml`
#     for build-script approval at all).
#   - Reads `allowBuilds:` dict (package → bool) preferentially
#     over `onlyBuiltDependencies:` list. When `allowBuilds:` is
#     absent for packages that have build scripts, pnpm v11
#     INJECTS a `set this to true or false` placeholder block
#     above any existing content — clobbering our v15.S-vintage
#     allowlist semantics.
#
# Empirically validated against `disclosur.dev` whose hand-edited
# file (operator approved esbuild/sharp via interactive flow) is:
#
#     packages:
#       - .
#     allowBuilds:
#       esbuild: true
#       sharp: true
#
# We emit the same shape pre-emptively so pnpm v11 finds it
# satisfactory and never enters the interactive flow.
_PNPM_WORKSPACE_CONTENT = """\
# Generated by lamill v15.S — pre-approved build-script allowlist
# so `pnpm install` doesn't enter the interactive approve-builds
# flow on first run. Add packages here if a new dep needs its
# install scripts to run (rare for Astro+Vite projects).
packages:
  - .
allowBuilds:
  esbuild: true
  sharp: true
"""


def write_pnpm_workspace_yaml(project_dir: Path) -> bool:
    """Write a pre-approved `pnpm-workspace.yaml` to `project_dir/`
    when no operator-customized file exists. Detects the two known
    stale-content patterns and overwrites them:

      1. pnpm v11's interactive-flow stub — recognizable by the
         literal `"set this to true or false"` placeholder text.
      2. v15.S-vintage content — emits `onlyBuiltDependencies:` list
         instead of `allowBuilds:` dict. Was correct under earlier
         pnpm versions; pnpm v11 ignores it and re-injects the
         interactive stub on next `pnpm install`. Recognized by the
         lamill-header comment + absence of `allowBuilds:`.

    Returns True iff the file was written. Idempotent — if a valid
    operator-customized file is already present, leaves it alone.
    """
    target = project_dir / "pnpm-workspace.yaml"
    if target.exists():
        try:
            existing = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        pnpm_stub = "set this to true or false" in existing
        # v15.S-vintage content under pnpm v11 → silently broken.
        # Identify by lamill header + missing the new `allowBuilds:`
        # field. Won't false-positive on operator hand-edits because
        # those wouldn't carry our generated-comment header.
        old_v15s_format = (
            "Generated by lamill v15.S" in existing
            and "allowBuilds:" not in existing
        )
        if not pnpm_stub and not old_v15s_format:
            return False  # operator-customized — leave alone
    try:
        target.write_text(_PNPM_WORKSPACE_CONTENT, encoding="utf-8")
        return True
    except OSError:
        return False


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
    result = run_claude(
        prompt,
        cwd=project_dir,
        budget_usd=budget_usd,
        timeout_s=timeout_s,
        allowed_tools="Read Write Edit Glob Grep Bash",
    )
    # v15.S — sweep Claude's atomic-write tmp artifacts whether the
    # subprocess succeeded or failed. On failure they leak; on success
    # most are cleaned but partial-rename races still leave some.
    sweep_tmp_artifacts(project_dir)
    # v15.S — pre-seed pnpm-workspace.yaml so `pnpm install` doesn't
    # enter the interactive approve-builds flow on first run.
    write_pnpm_workspace_yaml(project_dir)
    return result


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
    result = run_claude(
        prompt,
        cwd=project_dir,
        budget_usd=budget_usd,
        timeout_s=timeout_s,
        allowed_tools="Read Write Edit Glob Grep Bash",
    )
    # v15.S — sweep Claude's atomic-write tmp artifacts. See
    # translate_to_astro() for full rationale.
    sweep_tmp_artifacts(project_dir)
    # v15.S — pre-seed pnpm-workspace.yaml so `pnpm install` doesn't
    # enter the interactive approve-builds flow on first run.
    write_pnpm_workspace_yaml(project_dir)
    return result


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

  - `tsconfig.json` / `vite.config.*` — leave alone.
  - `wrangler.jsonc` if present — that's deploy config, not your
    concern.
  - Anything inside `genai/` — read-only reference.

## You MAY (and often must) edit

  - `package.json` — to add CSS toolchain deps (Tailwind / PostCSS /
    Sass) that the source uses. See "CSS toolchain" section below.
    Do NOT change `astro`, `vite`, or scripts the scaffold set up.
  - `astro.config.mjs` — to register integrations and plugins the
    ported code needs (e.g. `@astrojs/react`, `@tailwindcss/vite`).
    Preserve existing config; add, don't replace.

## CSS toolchain — port deps + plugin wiring

The scaffold's `package.json` does NOT include CSS toolchain deps
(Tailwind, PostCSS, Sass) — those depend on what the source uses
and are your responsibility to port. Drift here is the most common
post-port failure (caught `disclosur.dev` 2026-05-20: ported
`@import "tailwindcss"` without adding `tailwindcss` to deps).

Rule: **any CSS import or directive you port must have its dep in
`package.json`** AND its plugin wired into `astro.config.mjs`.

  - `genai/package.json` has `tailwindcss` → add to root `package.json`
  - `genai/package.json` has `@tailwindcss/vite` (Tailwind v4) → add
    BOTH `tailwindcss` and `@tailwindcss/vite` to root `package.json`;
    in `astro.config.mjs` add:
    ```js
    import tailwindcss from "@tailwindcss/vite";
    export default defineConfig({{ vite: {{ plugins: [tailwindcss()] }} }});
    ```
  - `tailwind-merge`, `clsx`, `class-variance-authority` → port if
    ported `.tsx`/`.astro` files import them
  - `postcss`, `autoprefixer` → port if `genai/postcss.config.*`
    exists; copy the config file too
  - `sass`, `sass-embedded`, `less`, `stylus` → port if any
    `.scss`/`.sass`/`.less`/`.styl` files are being ported

The lamill v15.S validator rejects port output that references
`tailwindcss` in src/styles/ without the matching dep.

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
   **CSS toolchain deps MUST be ported** from `genai/package.json`
   if the source uses them — see "CSS toolchain" section below.
2. `astro.config.mjs` — minimal Astro 5+ config. Include the
   `@astrojs/react` integration if the source has React components
   you're preserving as islands. Set `output: "static"`. **Wire any
   CSS toolchain Vite plugin** here (see "CSS toolchain" below).
   **Canonical host (required):** set `site: "https://{project_dir.name}"`
   — the bare apex, NEVER a `www.` host — and add the `@astrojs/sitemap`
   integration (`@astrojs/sitemap` in deps + `integrations: [sitemap()]`).
   Astro derives every page's `<link rel="canonical">` and the sitemap
   `<loc>` URLs from `site`, so the apex value makes the port
   canonicalization-conformant (CHECK_150 / CHECK_158 / CHECK_159) by
   construction. Do not hardcode a `www.` host anywhere.
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

## CSS toolchain — port deps + plugin wiring

If `genai/package.json` lists any of these, port them to the new
`package.json` AND wire the corresponding plugin into
`astro.config.mjs`. This is a frequent translation gap and the
validator will reject the output if you miss it.

  - `tailwindcss` (any version) → keep `tailwindcss` in dependencies
  - `@tailwindcss/vite` (Tailwind v4) → keep BOTH `tailwindcss` and
    `@tailwindcss/vite`. In `astro.config.mjs` add:
    ```js
    import tailwindcss from "@tailwindcss/vite";
    export default defineConfig({{ vite: {{ plugins: [tailwindcss()] }} }});
    ```
  - `tailwind-merge`, `clsx`, `class-variance-authority` → port if
    any ported `.tsx` / `.astro` file imports them
  - `postcss`, `autoprefixer` → port if `postcss.config.*` exists in
    source; copy the config file too
  - `sass`, `sass-embedded`, `less`, `stylus` → port if any `.scss`/
    `.sass`/`.less`/`.styl` files are being ported

The matching rule: **any CSS import or directive ported to the target
must have its dep present in `package.json`**. Tailwind v4's
`@import "tailwindcss"` is the highest-frequency case to watch.

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
