"""CHECK_064 — Sitemap-generation runs at build time (chained into build script)."""
from __future__ import annotations

from ..result import CheckResult
from ..stack import _read_package_json
from . import _is_web_project

CHECK_ID = "CHECK_064"
CHECK_NAME = "sitemap-in-build-script"
CATEGORY = "seo"
SEVERITY = "info"
DESCRIPTION = "package.json `build` script invokes the sitemap generator (Vite path) or @astrojs/sitemap is configured (Astro path)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    pkg = _read_package_json(repo_path)
    if pkg is None:
        return CheckResult(status="warn", message="package.json unreadable — skipped")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    # Astro path: @astrojs/sitemap dep
    if "@astrojs/sitemap" in deps:
        return CheckResult(status="pass",
                           message="@astrojs/sitemap configured (Astro path)")
    # Vite path: build script chains generate-sitemap
    build = pkg.get("scripts", {}).get("build", "")
    if "generate-sitemap" in build:
        return CheckResult(status="pass", message="`build` chains generate-sitemap")
    return CheckResult(status="warn",
                       message="no sitemap generation in build pipeline")
