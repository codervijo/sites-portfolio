"""CHECK_159 — the sitemap lists only apex-host URLs.

Host-consistency triad (v26.G), the sitemap half of canonicalization.
A sitemap whose `<loc>` entries use `www` (or any non-apex host) feeds
Google the non-canonical host directly — splitting signals even when the
www→apex redirect (CHECK_150) is correct. Apex is the ONLY canonical host
fleet-wide (see `docs/CLAUDE.md § Locked target shapes`). The apex is the
repo's directory name.

Discovers the sitemap via robots.txt (reusing the live-SEO machinery) and
fails if any `<loc>` URL's host isn't the apex.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..result import CheckResult
from . import _is_web_project
from ._live import LiveFetchError, get_sitemap_urls, resolve_live_url

CHECK_ID = "CHECK_159"
CHECK_NAME = "sitemap-host-is-apex"
CATEGORY = "seo"
SEVERITY = "error"
DESCRIPTION = "Every <loc> URL in the sitemap uses the apex host (no www)."


def _host(u: str) -> str:
    return (urlparse(u).hostname or "").lower()


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    apex = Path(repo_path).name.lower()
    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    try:
        urls = get_sitemap_urls(origin)
    except LiveFetchError as e:
        return CheckResult(status="warn", message=f"sitemap unreachable ({e})")
    if not urls:
        return CheckResult(status="warn", message=f"sitemap empty at {origin}")

    bad = [u for u in urls if _host(u) != apex]
    if not bad:
        return CheckResult(
            status="pass",
            message=f"all {len(urls)} sitemap <loc> URL(s) use apex {apex!r}",
        )
    sample = "; ".join(f"{_host(u) or '∅'} ({u})" for u in bad[:3])
    return CheckResult(
        status="fail",
        message=f"{len(bad)}/{len(urls)} sitemap <loc>(s) not apex — {sample}",
    )
