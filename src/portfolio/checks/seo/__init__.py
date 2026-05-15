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


def _parse_html(text: str):
    """Parse the index HTML/Astro content into a BeautifulSoup tree.
    Astro frontmatter (between leading `---` markers) is stripped first
    so the parser sees only the template body."""
    if text.startswith("---"):
        # Astro file: skip frontmatter
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser")
