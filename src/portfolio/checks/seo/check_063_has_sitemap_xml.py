"""CHECK_063 — Has public/sitemap.xml OR @astrojs/sitemap OR scripts/generate-sitemap.* (build-time)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_063"
CHECK_NAME = "has-sitemap-xml"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = ("public/sitemap.xml exists, OR @astrojs/sitemap is configured, OR "
               "scripts/generate-sitemap.* generates it at build time.")


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    base = Path(repo_path)
    if (base / "public" / "sitemap.xml").is_file():
        return CheckResult(status="pass", message="public/sitemap.xml present")
    # @astrojs/sitemap emits sitemap-index.xml at build, so an Astro site that
    # uses it ships no static file in the repo — and MUST NOT (a stub would
    # shadow the generated index). Recognize the integration as satisfying this.
    for cfg in ("astro.config.mjs", "astro.config.js", "astro.config.ts"):
        p = base / cfg
        if p.is_file() and "@astrojs/sitemap" in p.read_text(errors="replace"):
            return CheckResult(status="pass",
                               message=f"@astrojs/sitemap in {cfg} (build-time sitemap-index.xml)")
    scripts = base / "scripts"
    if scripts.is_dir():
        for ext in ("js", "mjs", "ts"):
            if list(scripts.glob(f"generate-sitemap.{ext}")) or \
               list(scripts.glob(f"generate-sitemap.*.{ext}")):
                return CheckResult(status="pass",
                                   message=f"scripts/generate-sitemap.{ext} (build-time generation)")
    return CheckResult(status="fail",
                       message="no public/sitemap.xml, no @astrojs/sitemap, "
                               "no scripts/generate-sitemap.*")
