"""v46.G–I — unknown paths must return 404 on static multi-page sites.

Cloudflare's `assets.not_found_handling: "single-page-application"` serves the
homepage (200) for every unknown URL. That's right for a client-rendered SPA,
whose router needs the fallback, and wrong for a static multi-page Astro site:
every typo'd or stale URL becomes a soft-404 duplicate of the homepage.
`new bootstrap` used to write the SPA value for every stack (fleet probe
2026-11-25: 14 Astro sites affected). Shared by `new bootstrap` and CHECK_167.
"""
from __future__ import annotations

import re
from pathlib import Path

SPA_VALUE = "single-page-application"
STATIC_VALUE = "404-page"

# Stacks whose client-side router needs the SPA fallback.
SPA_STACKS = frozenset({"vite", "vite-react", "tanstack", "react", "spa"})

_NFH_RE = re.compile(r'("not_found_handling"\s*:\s*)"([^"]*)"')
_ASSETS_OPEN_RE = re.compile(r'("assets"\s*:\s*\{)')

PAGE_404_CANDIDATES = (
    "src/pages/404.astro", "src/pages/404.md", "src/pages/404.mdx",
    "src/pages/404.html", "public/404.html",
)


def is_astro(project_dir: Path) -> bool:
    return any((project_dir / f"astro.config.{ext}").is_file()
               for ext in ("mjs", "js", "ts", "cjs", "mts"))


def wants_spa_fallback(stack: str | None, project_dir: Path | None = None) -> bool:
    """True only for client-rendered SPA stacks. Unknown stack → decide from
    the files (an Astro config means static multi-page)."""
    if stack:
        return stack.lower() in SPA_STACKS
    if project_dir is not None and is_astro(project_dir):
        return False
    return True


def not_found_value(text: str) -> str | None:
    """The `not_found_handling` value in a wrangler.jsonc body, or None."""
    m = _NFH_RE.search(text)
    return m.group(2) if m else None


def set_not_found_value(text: str, value: str) -> str:
    """Set `assets.not_found_handling` in a wrangler.jsonc body, preserving
    everything else (comments, ordering, formatting). Inserts the key right
    after `"assets": {` when absent. Raises ValueError when there is no
    `assets` block to put it in (the caller reports manual action)."""
    if _NFH_RE.search(text):
        return _NFH_RE.sub(lambda m: f'{m.group(1)}"{value}"', text, count=1)
    m = _ASSETS_OPEN_RE.search(text)
    if not m:
        raise ValueError("wrangler.jsonc has no `assets` block")
    line_start = text.rfind("\n", 0, m.start()) + 1
    indent = re.match(r"[ \t]*", text[line_start:]).group(0) + "  "
    insert = f'\n{indent}"not_found_handling": "{value}",'
    return text[:m.end()] + insert + text[m.end():]


def has_404_page(project_dir: Path) -> bool:
    return any((project_dir / p).is_file() for p in PAGE_404_CANDIDATES)


def page_404_astro(domain: str) -> str:
    """A minimal, standalone 404 page (no site layout assumed). noindex, a
    link home. Restyle into the site's layout if wanted."""
    return f"""---
// src/pages/404.astro — served by Cloudflare for unknown paths
// (wrangler.jsonc `not_found_handling: "404-page"`, CHECK_167).
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex" />
    <title>Page not found — {domain}</title>
  </head>
  <body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;">
    <h1>Page not found</h1>
    <p>There's no page at this address. It may have moved, or the link may be mistyped.</p>
    <p><a href="/">Go to the {domain} homepage</a></p>
  </body>
</html>
"""


def ensure_astro_404(project_dir: Path, domain: str) -> bool:
    """Write `src/pages/404.astro` if the site has no 404 page. True if written."""
    if has_404_page(project_dir):
        return False
    target = project_dir / "src" / "pages" / "404.astro"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(page_404_astro(domain))
    return True
