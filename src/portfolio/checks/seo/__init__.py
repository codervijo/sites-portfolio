"""SEO-category checks.

Two sub-families:

  - Static-source (CHECK_060–080) — read files on disk (favicon,
    robots.txt, sitemap.xml, meta tags parsed from index.html or
    src/pages/index.astro). Run by `lamill project check`.

  - Live-runtime (CHECK_090–095, v5.D) — fetch the deployed URLs as
    Googlebot and validate what indexers see. Shared helpers in
    `_live.py`; each check fetches every sitemap URL through a
    per-process cache so the cluster runs in one round-trip. Network
    failures degrade to `warn`, not `fail`.
"""
from __future__ import annotations

import re
from pathlib import Path

# Top-level entry points where SEO meta lives. Vite stack uses index.html;
# Astro stack uses src/pages/index.astro. Either is acceptable.
_HTML_CANDIDATE_PATHS = [
    "index.html",
    "src/pages/index.astro",
    "src/pages/index.html",
]


def _read_index_html(repo_path: str) -> str | None:
    """Return the contents of the project's main HTML/Astro index, or None
    if no recognized entry point exists."""
    base = Path(repo_path)
    for rel in _HTML_CANDIDATE_PATHS:
        p = base / rel
        if p.is_file():
            try:
                return p.read_text(errors="replace")
            except OSError:
                continue
    return None


def _is_web_project(repo_path: str) -> bool:
    return (Path(repo_path) / "package.json").is_file()


def _bs4():
    """Return the `BeautifulSoup` class, wrapping the lazy import with a
    typed error that names the fix command (v35.D — global rule: lazy
    imports of optional/heavy deps must raise an actionable error, not a
    raw ModuleNotFoundError, on a partial/broken install). bs4 is the
    heaviest SEO-check dep + the most likely to be missing. Shared by the
    SEO checks (`_live`, `check_095`) so the wrap lives in one place."""
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover - bs4 is a core dep
        raise RuntimeError(
            f"beautifulsoup4 not importable ({e}). Run `uv sync` to install."
        ) from e
    return BeautifulSoup


def _parse_html(text: str):
    """Parse the index HTML/Astro content into a BeautifulSoup tree.
    Astro frontmatter (between leading `---` markers) is stripped first
    so the parser sees only the template body."""
    if text.startswith("---"):
        # Astro file: skip frontmatter
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return _bs4()(text, "html.parser")


# ---------------------------------------------------------------------------
# SSR-head resolution (docs/bugs.md 2026-06-29).
#
# The meta checks (070/071/076/077) historically read only a static
# index.html / index.astro. Stacks that define the document head in code
# (TanStack Start route `head()`, Astro layouts, Next `metadata`) ship no
# such file, so those checks skipped — a `title: "Lovable App"` sailed
# through. `_read_head_html` falls back to synthesizing a <head> from the
# in-code definition so the same bs4-based checks work unchanged.
# ---------------------------------------------------------------------------

# Homepage route heads come first (their title wins), then the root/layout
# fallback head. Order matters: bs4 `.find("title")` returns the first.
_SSR_HEAD_FILES = [
    "src/routes/index.tsx", "src/routes/index.jsx",
    "src/app/page.tsx", "app/page.tsx",
    "src/routes/__root.tsx", "src/routes/__root.jsx", "src/routes/__root.ts",
    "src/app/layout.tsx", "app/layout.tsx",
]
# Astro puts the head in a layout; scan those too.
_SSR_HEAD_GLOB = ("src/layouts", "*.astro")

# A file is only mined for head content if it actually looks like a head
# definition — keeps a stray `title:`/`content:` prop in some component
# from synthesizing a bogus tag.
_HEAD_MARKERS = (
    "head:", "createRootRoute", "export const metadata", "<head",
)

_JS_TITLE_RE = re.compile(r"""\btitle:\s*['"`]([^'"`]+)['"`]""")
_JS_KEYTYPE_RE = re.compile(r"""\b(name|property):\s*['"`]([^'"`]+)['"`]""")
_JS_CONTENT_RE = re.compile(r"""\bcontent:\s*['"`]([^'"`]*)['"`]""")
_HTML_HEAD_TAG_RE = re.compile(r"<title>.*?</title>|<meta\b[^>]*>",
                               re.IGNORECASE | re.DOTALL)


def _looks_like_head_def(text: str) -> bool:
    return any(m in text for m in _HEAD_MARKERS)


def _synth_head_from_js(text: str) -> str:
    """Turn JS head/meta object literals (TanStack Start / Next metadata
    style) into equivalent HTML head tags. `{ title: "X" }` -> <title>X…,
    `{ name|property: "K", content: "V" }` -> <meta …>."""
    tags: list[str] = []
    m = _JS_TITLE_RE.search(text)
    if m:
        tags.append(f"<title>{m.group(1)}</title>")
    for block in re.findall(r"\{[^{}]*\}", text):
        kt = _JS_KEYTYPE_RE.search(block)
        ct = _JS_CONTENT_RE.search(block)
        if kt and ct:
            tags.append(f'<meta {kt.group(1)}="{kt.group(2)}" content="{ct.group(1)}">')
    return "\n".join(tags)


def _synthesize_head_from_source(repo_path: str) -> str | None:
    """Build a minimal <head> HTML from a project's in-code head
    definition, for SSR-head stacks that ship no static index. Returns
    None if nothing head-like is found."""
    base = Path(repo_path)
    paths = [base / rel for rel in _SSR_HEAD_FILES]
    glob_dir = base / _SSR_HEAD_GLOB[0]
    if glob_dir.is_dir():
        paths.extend(sorted(glob_dir.glob(_SSR_HEAD_GLOB[1])))

    fragments: list[str] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if not _looks_like_head_def(text):
            continue
        fragments.extend(_HTML_HEAD_TAG_RE.findall(text))  # raw HTML (Astro/JSX)
        js = _synth_head_from_js(text)                      # JS object literals
        if js:
            fragments.append(js)

    head = "\n".join(f for f in fragments if f.strip())
    if not head.strip():
        return None
    return f"<!doctype html><html><head>\n{head}\n</head><body></body></html>"


def _read_head_html(repo_path: str) -> str | None:
    """Head HTML for the SEO meta checks. Prefers a static index
    (index.html / index.astro); falls back to synthesizing the head from
    in-code definitions for SSR-head stacks (TanStack Start / Astro /
    Next). Closes the blind spot where those stacks false-passed the
    title/meta checks (docs/bugs.md 2026-06-29)."""
    html = _read_index_html(repo_path)
    if html is not None:
        return html
    return _synthesize_head_from_source(repo_path)
