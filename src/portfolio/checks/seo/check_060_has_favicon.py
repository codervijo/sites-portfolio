"""CHECK_060 — Has public/favicon.* and it's not a known AI-builder default.

Severity is **error**: a missing favicon AND a default-builder favicon
are both branding leaks. Deploying a site that still ships the Lovable
heart-mark (or v0 / Bolt / etc.) tells visitors the site isn't really
yours — bigger problem than tweet-width meta tags.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_060"
CHECK_NAME = "has-favicon"
CATEGORY = "seo"
SEVERITY = "error"
DESCRIPTION = (
    "public/favicon.* exists (any common extension) and isn't a known "
    "AI-scaffolder default (Lovable, …)."
)

# SHA-256 → human label. To add a new entry: `sha256sum public/favicon.ico`
# on a project where the AI builder's default leaked through, then append.
_KNOWN_DEFAULT_FAVICON_HASHES: dict[str, str] = {
    # Lovable's heart/L mark (orange→pink→blue gradient), 256×256 ICO,
    # 20,373 bytes. Verified 2026-05-09 from sites/newiniot.com/.
    "dd821076a9b03adc2173c93956226aea3d92482d7578fc4339c5d3a2e9c24586": "Lovable",
}

_FAVICON_EXTENSIONS = ("ico", "png", "svg", "jpg", "jpeg", "webp")


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    public = Path(repo_path) / "public"
    if not public.is_dir():
        return CheckResult(status="fail", message="public/ missing")
    for ext in _FAVICON_EXTENSIONS:
        matches = list(public.glob(f"favicon.{ext}"))
        if not matches:
            continue
        favicon = matches[0]
        try:
            digest = hashlib.sha256(favicon.read_bytes()).hexdigest()
        except OSError as e:
            return CheckResult(status="warn",
                               message=f"favicon.{ext} unreadable: {type(e).__name__}")
        if digest in _KNOWN_DEFAULT_FAVICON_HASHES:
            scaffolder = _KNOWN_DEFAULT_FAVICON_HASHES[digest]
            return CheckResult(
                status="fail",
                message=f"favicon.{ext} is the default {scaffolder} scaffold favicon — replace before shipping",
            )
        return CheckResult(status="pass", message=f"favicon.{ext} present")
    return CheckResult(status="fail", message="public/favicon.* missing")
