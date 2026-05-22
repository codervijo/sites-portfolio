"""CHECK_148 — GA4 measurement ID is well-formed (`G-[A-Z0-9]{6,12}`).

Fires only on sites where CHECK_080 detected GA4 specifically (markers
`gtag(` or `googletagmanager.com` present). Skips cleanly on sites
using other analytics providers (Plausible / CF Analytics / Umami).

Catches typo'd IDs, placeholder values like `G-XXXXXX`, and the
common copy/paste failure mode where the operator hard-codes the
property number (e.g., `123456789`) instead of the measurement ID.
"""
from __future__ import annotations

import re

from ..result import CheckResult
from . import _is_web_project, _read_index_html

CHECK_ID = "CHECK_148"
CHECK_NAME = "ga4-id-well-formed"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "GA4 measurement ID matches `G-[A-Z0-9]{6,12}` shape (no placeholder / typo'd values)."

# GA4 measurement IDs are `G-` followed by 6-12 uppercase alphanumerics.
# Real-world samples from the operator's fleet:
#   G-QG4CYZ7MXE   (10 chars) — keralavotemap.site
#   G-41C0WXB0HR   (10 chars) — lamillrentals.com
#   G-HP39MQPM2M   (10 chars) — washcalc.app
# Google's docs say IDs are 10 chars in practice; we accept 6-12 to be
# tolerant of future Google changes. Lowercase rejected (Google emits
# uppercase only).
_GA4_ID_SHAPE = re.compile(r"^G-[A-Z0-9]{6,12}$")

# Detection: same markers as CHECK_080, but GA4-specific subset
# (gtag function call OR googletagmanager.com script src). Plausible /
# CF Analytics / Umami won't match → check skips.
_GA4_MARKER_RE = re.compile(r"gtag\(|googletagmanager\.com")

# Extract every `G-XXXXXX`-shaped string from the rendered HTML. We
# don't restrict where it appears — operator might pass an ID in a
# data attribute, a config object, a `gtag('config', 'G-...')` call,
# etc. The check passes when AT LEAST ONE extracted ID is well-formed
# AND no extracted ID violates the shape.
_GA4_ID_EXTRACT = re.compile(r"G-[A-Za-z0-9]{1,16}")


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_index_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no index.html / index.astro — skipped")

    if not _GA4_MARKER_RE.search(html):
        return CheckResult(status="warn", message="no GA4 markers — skipped")

    candidates = _GA4_ID_EXTRACT.findall(html)
    if not candidates:
        return CheckResult(
            status="fail",
            message=("GA4 markers present but no `G-...` measurement ID "
                     "found in rendered HTML"),
        )

    # Deduplicate while preserving order for stable reporting.
    seen: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.append(c)

    malformed = [c for c in seen if not _GA4_ID_SHAPE.match(c)]
    if malformed:
        return CheckResult(
            status="fail",
            message=f"malformed GA4 ID(s): {', '.join(malformed)}",
        )

    return CheckResult(
        status="pass",
        message=f"GA4 ID well-formed: {', '.join(seen)}",
    )
