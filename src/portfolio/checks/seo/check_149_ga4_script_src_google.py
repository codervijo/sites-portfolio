"""CHECK_149 — GA4 loader script src points to Google.

The standard GA4 install pattern is two `<script>` tags: one loads
the gtag library from Google (`https://www.googletagmanager.com/
gtag/js?id=G-XXX`), the next initializes it with inline `gtag(...)`
calls. If only the inline `gtag(` calls are present without the
loader, the gtag function is being called without the library →
silent breakage. CHECK_149 catches that gap.

Fires only on sites where CHECK_080 detected GA4 (the inline
`gtag(` marker). Skips cleanly on non-GA4 sites.
"""
from __future__ import annotations

import re

from ..result import CheckResult
from . import _is_web_project, _read_index_html

CHECK_ID = "CHECK_149"
CHECK_NAME = "ga4-script-src-google"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "GA4 install loads the gtag library from `www.googletagmanager.com`."

# CHECK_080's GA4-specific marker. We only check `gtag(` here (not
# `googletagmanager.com`) because if `googletagmanager.com` is
# already in the page, CHECK_149 would trivially pass on it. The
# breakage mode CHECK_149 actually catches is "inline gtag() calls
# without the loader script" — so we look for the inline marker
# first, then verify the loader is present too.
_GA4_INLINE_MARKER = re.compile(r"gtag\(")

# Valid loader src patterns. Both forms appear in Google's docs:
#   <script async src="https://www.googletagmanager.com/gtag/js?id=G-XXX"></script>
#   <script src="https://www.googletagmanager.com/gtag/js?id=G-XXX"></script>
# The src may be in single or double quotes; the param may be `?id=`
# or in some legacy installs the script just loads without `?id=`
# and the init script supplies the ID — we accept either.
_LOADER_SRC = re.compile(
    r"""<script\b[^>]*\bsrc=["']https://www\.googletagmanager\.com/gtag/js\b""",
    re.IGNORECASE,
)


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_index_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no index.html / index.astro — skipped")

    if not _GA4_INLINE_MARKER.search(html):
        return CheckResult(status="warn", message="no GA4 markers — skipped")

    if not _LOADER_SRC.search(html):
        return CheckResult(
            status="fail",
            message=("gtag() called inline but loader script "
                     "(`googletagmanager.com/gtag/js`) not found — "
                     "library never loads, gtag is undefined at runtime"),
        )

    return CheckResult(
        status="pass",
        message="GA4 loader src points to googletagmanager.com",
    )
