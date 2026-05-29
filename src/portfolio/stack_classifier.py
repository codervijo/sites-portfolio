"""v27.C — frontend-stack classifier for `sites/<domain>/` repos.

Single source of truth for the heuristic detection that runs across the
fleet. Used by v27.C's backfill sweep (write `[stack]` to each site's
`lamill.toml`) and by v27.E's `stack-drift` check (compare declared vs
detected). The classifier returns a value from `STACK_FRAMEWORK_VALUES`
or `None` when undetermined; callers layer their own operator policy
(known-WP allow-list, defaulting, ambiguity handling) on top.

Heuristic order (the first match wins):

  1. **`wordpress`** — local repo carries `wp-config.php`,
     `wp-config-sample.php`, `wp-load.php`, or a `wp-content/` dir.
  2. **`tanstack`** — `package.json` lists `@tanstack/react-start`
     (Tanstack Start uses Vite under the hood, but it's a distinct
     framework choice; check it before plain `vite-react`).
  3. **`astro`** — `astro.config.{js,mjs,ts}` exists OR `astro` is in
     `package.json` deps.
  4. **`nextjs`** — `next` in `package.json` deps.
  5. **`sveltekit`** — `@sveltejs/kit` in `package.json` deps.
  6. **`vite-react`** — `vite.config.{js,ts,mjs}` exists OR (`vite` is
     in deps AND `react` is in deps).
  7. **Ambiguous** — both `astro.config.*` and `vite.config.*` exist
     but no `astro` dep. Returns `framework=None` with a note so the
     caller can flag for operator review (the `lamillrentals.com`
     two-config case).
  8. **None** — no recognizable markers. Caller decides whether to
     default to `static`, look it up in a known-WP list, or leave
     undeclared.

The classifier is pure: it only reads the repo path. It does NOT
consult `lamill.toml` (so it works as the "detected" side of the drift
comparison without circularity).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


WP_MARKER_FILES: tuple[str, ...] = (
    "wp-config.php",
    "wp-config-sample.php",
    "wp-load.php",
)


@dataclass(frozen=True)
class StackDetection:
    """Result of inspecting a `sites/<domain>/` directory.

    `framework` is one of `STACK_FRAMEWORK_VALUES` (per
    `lamill_toml.py`) or `None` when no marker is decisive. `signals`
    is the evidence list (e.g. `dep:astro=^5.0.0`, `cfg:vite.config.ts`,
    `file:wp-config.php`) so the operator can see why a particular
    framework was inferred. `notes` carries a human-readable comment for
    the ambiguous / undeterminable cases."""

    framework: str | None
    signals: list[str] = field(default_factory=list)
    notes: str | None = None


def _read_pkg(repo_path: Path) -> dict:
    p = repo_path / "package.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(errors="replace"))
    except Exception:
        return {}


def _list_files_with_prefix(repo_path: Path, prefix: str) -> list[str]:
    if not repo_path.is_dir():
        return []
    try:
        return [n for n in sorted((f.name for f in repo_path.iterdir()))
                if n.startswith(prefix)]
    except OSError:
        return []


def classify_stack(repo_path: Path) -> StackDetection:
    """Return the detected framework + signals for `repo_path`.

    `repo_path` should be the project's root directory (where
    `package.json` / `lamill.toml` / `astro.config.*` would live)."""

    signals: list[str] = []

    # 1. WordPress markers.
    wp_files = [n for n in WP_MARKER_FILES if (repo_path / n).is_file()]
    if wp_files:
        signals.extend(f"file:{n}" for n in wp_files)
        return StackDetection(framework="wordpress", signals=signals)
    if (repo_path / "wp-content").is_dir():
        signals.append("dir:wp-content")
        return StackDetection(framework="wordpress", signals=signals)

    # JS-side markers.
    pkg = _read_pkg(repo_path)
    deps = {
        **(pkg.get("dependencies") or {}),
        **(pkg.get("devDependencies") or {}),
    }
    astro_cfg = _list_files_with_prefix(repo_path, "astro.config.")
    vite_cfg = _list_files_with_prefix(repo_path, "vite.config.")
    for n in astro_cfg:
        signals.append(f"cfg:{n}")
    for n in vite_cfg:
        signals.append(f"cfg:{n}")
    for k, v in deps.items():
        if k in (
            "astro", "vite", "next", "@sveltejs/kit",
            "@tanstack/react-start", "react",
        ):
            signals.append(f"dep:{k}={v}")

    # 2. Tanstack (check before plain vite-react — uses vite under the hood).
    if "@tanstack/react-start" in deps:
        return StackDetection(framework="tanstack", signals=signals)

    # 3. Astro.
    if astro_cfg or "astro" in deps:
        # Ambiguity guard: declared Astro alongside a vite.config.* and
        # no astro dep → likely an unfinished migration. The astro dep
        # is the definitive signal; without it, fall through.
        if "astro" in deps:
            return StackDetection(framework="astro", signals=signals)
        if astro_cfg and not vite_cfg:
            return StackDetection(framework="astro", signals=signals)
        # else: both configs but no astro dep → ambiguous, handled below.

    # 4. Next.
    if "next" in deps:
        return StackDetection(framework="nextjs", signals=signals)

    # 5. SvelteKit.
    if "@sveltejs/kit" in deps:
        return StackDetection(framework="sveltekit", signals=signals)

    # 6. Vite + React.
    if vite_cfg or ("vite" in deps and "react" in deps):
        # If astro.config.* also present + no astro dep, that's the
        # `lamillrentals.com` two-config case — surface ambiguity.
        if astro_cfg:
            return StackDetection(
                framework=None,
                signals=signals,
                notes=(
                    "ambiguous: astro.config.* and vite.config.* both "
                    "present; no `astro` dep — operator review needed"
                ),
            )
        return StackDetection(framework="vite-react", signals=signals)

    # 7. Final ambiguity catch.
    if astro_cfg and vite_cfg:
        return StackDetection(
            framework=None,
            signals=signals,
            notes=(
                "ambiguous: astro.config.* and vite.config.* both "
                "present — operator review needed"
            ),
        )

    # 8. No recognizable markers.
    if not pkg and not signals:
        return StackDetection(
            framework=None,
            signals=["no package.json"],
            notes="no JS / WP markers — caller decides (static? wordpress?)",
        )
    return StackDetection(framework=None, signals=signals)
