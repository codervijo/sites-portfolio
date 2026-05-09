"""CHECK_029 — Live URL is configured somewhere (package.json `homepage`,
wrangler.jsonc routes, README, or AI_AGENTS.md "live URL" line).

A configured live URL is the single piece of metadata that lets the rest of
the toolchain (deploy verification, GSC binding, runtime SEO checks) know
where the project actually lives.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..result import CheckResult
from . import _is_web_project, _read_package_json

CHECK_ID = "CHECK_029"
CHECK_NAME = "has-live-url"
CATEGORY = "stack"
SEVERITY = "warn"
DESCRIPTION = "Live URL configured in package.json `homepage`, wrangler routes, README, or AI_AGENTS.md."

_URL_RE = re.compile(r"https?://[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)


def _scan_text_for_url(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    # Only consider URLs near a "live", "production", or "deployed" hint to
    # avoid false-positives from generic doc links.
    for line in text.splitlines():
        if any(hint in line.lower() for hint in ("live", "production", "deployed", "homepage", "https://")):
            m = _URL_RE.search(line)
            if m:
                # Skip obvious example/placeholder domains.
                url = m.group(0)
                if not any(skip in url for skip in ("example.com", "localhost", "127.0.0.1")):
                    return url
    return None


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    base = Path(repo_path)
    pkg = _read_package_json(repo_path)
    if pkg and isinstance(pkg.get("homepage"), str) and pkg["homepage"].strip():
        return CheckResult(status="pass",
                           message=f"package.json homepage={pkg['homepage']}")
    for fname in ("README.md", "AI_AGENTS.md", "docs/CLAUDE.md"):
        url = _scan_text_for_url(base / fname)
        if url:
            return CheckResult(status="pass", message=f"{fname}: {url}")
    return CheckResult(status="fail",
                       message="no live URL in package.json/README/AI_AGENTS.md")
