"""CHECK_081 — no AI-builder placeholder metadata/cruft in head or config.

Companion to CHECK_060 (default-favicon hash detection): that catches the
default favicon *asset*; this catches the placeholder *text* an AI builder
leaves in the page head — e.g. Lovable's `title: "Lovable App"`,
`description: "Lovable Generated Project"`, `author: "Lovable"`, or a
`twitter:site: "@Lovable"` handle. All of these leak into the browser tab,
search snippet, and social card — a branding leak that says "this site
isn't really mine."

Why this scans **source files**, not just `index.html`: SSR-head stacks
(TanStack Start / Astro / Next) define the head in code (a route `head()`
definition), so there's no static `index.html` to read. The static
title/meta checks (CHECK_070/071/076/077) are blind to those stacks; this
check greps `src/**` + `index.html` + `package.json`, so it catches the
in-code head too. See docs/bugs.md (2026-06-29 entry).
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project
from ...fix_helpers import ai_fixer_factory, project_context

CHECK_ID = "CHECK_081"
CHECK_NAME = "no-placeholder-metadata"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "No AI-builder placeholder metadata/cruft (e.g. Lovable's "
    "'Lovable App' title or '@Lovable' handle) left in the head or config."
)

# marker substring -> builder label. HIGH-CONFIDENCE cruft only: these
# strings do not appear in legitimate hand-authored content, so the
# false-positive rate is ~zero. Extend as new AI-scaffolder leaks turn up
# (mirrors CHECK_060's `_KNOWN_DEFAULT_FAVICON_HASHES` extensibility).
_PLACEHOLDER_MARKERS: dict[str, str] = {
    "Lovable App": "Lovable",
    "Lovable Generated Project": "Lovable",
    "@Lovable": "Lovable",
    "lovable-tagger": "Lovable",
    "Created with v0": "v0",
    "Bolt Generated": "Bolt",
}

# Head/meta live in different places across stacks: a static index.html
# (Vite/CRA), in-code route heads (TanStack Start / Astro / Next), and
# package.json (dev-only scaffolder artifacts like lovable-tagger).
_TOP_LEVEL_FILES = ("index.html", "package.json")
_SRC_EXTS = (".html", ".tsx", ".ts", ".jsx", ".js", ".astro", ".vue", ".svelte")
_SKIP_DIRS = {
    "node_modules", "dist", ".output", "build", ".tanstack", ".wrangler", ".git",
}


def _iter_scan_files(root: Path):
    for name in _TOP_LEVEL_FILES:
        p = root / name
        if p.is_file():
            yield p
    src = root / "src"
    if src.is_dir():
        for p in src.rglob("*"):
            if (
                p.is_file()
                and p.suffix in _SRC_EXTS
                and not (_SKIP_DIRS & set(p.parts))
            ):
                yield p


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    root = Path(repo_path)
    found: dict[str, str] = {}  # marker -> "Builder (`rel/path`)"
    for f in _iter_scan_files(root):
        if len(found) == len(_PLACEHOLDER_MARKERS):
            break
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for marker, builder in _PLACEHOLDER_MARKERS.items():
            if marker not in found and marker in text:
                found[marker] = f"{builder} (`{f.relative_to(root)}`)"
    if not found:
        return CheckResult(status="pass", message="no AI-builder placeholder metadata")
    detail = "; ".join(f'"{m}" — {where}' for m, where in found.items())
    return CheckResult(status="fail", message=f"AI-builder placeholder cruft: {detail}")


# Tier 2 (Claude subprocess): replacing placeholder identity needs the
# site's REAL brand — which is judgment, not a template — so there is no
# Tier 1 fixer. Mirrors CHECK_026's tier-2-only shape.
def _prompt_tier_2(project_dir: Path) -> str:
    domain = project_dir.name
    return f"""You are removing AI-builder placeholder metadata from {domain}.

This site was scaffolded by an AI builder (e.g. Lovable) and still ships
placeholder identity strings — things like the title "Lovable App", the
description "Lovable Generated Project", an author of "Lovable", or a
"@Lovable" twitter:site handle. They leak into the browser tab, search
results, and social cards.

Replace EVERY such placeholder with the site's REAL brand identity:
- title / og:title: the real site/brand name + a concise positioning line.
- description / og:description: 1-2 sentences on what {domain} actually
  does and for whom.
- author: the real owner/brand — or DROP the tag if unknown.
- twitter:site: the real handle, or REMOVE the tag. Do NOT invent one.

The head may live in a static `index.html` OR in code — a route's
`head()` / `createRootRoute(...).head` (TanStack Start), a layout/`<head>`
(Astro), or a metadata export (Next). Find wherever the meta is defined
and fix it there. Also drop dev-only scaffolder artifacts like a
`lovable-tagger` dependency in package.json if present.

Use this project's `lamill.toml` `[content]` block and `AI_AGENTS.md` as
the source of truth for the real identity. Do NOT invent facts, handles,
or numbers — if you cannot determine a real value, remove the placeholder
rather than guess.

Project context:
{project_context(project_dir)}
"""


fix_tier_2 = ai_fixer_factory(
    "CHECK_081",
    _prompt_tier_2,
    summary="replace AI-builder placeholder metadata with the site's real identity",
)
