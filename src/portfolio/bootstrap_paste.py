"""Multi-section paste detection + parsing for `new bootstrap`.

Bug-fix 2026-05-20 — when the operator pastes a multi-section response
from ChatGPT / claude.ai at the Summary prompt, the entire blob landed
in the Summary field and the remaining prompts fired empty. This module
detects the pattern, extracts each section, and returns a canonical
mapping the bootstrap orchestrator uses to auto-fill the rest of the
prompts.

Detection pattern: numbered section headers like ``2. Summary`` /
``3. Audience`` / ``9. Growth hypothesis`` separating content blocks.
Detection threshold: ≥3 matched canonical sections (fewer → treated as
single-section input; current behavior preserved).
"""
from __future__ import annotations

import re


# Canonical section keys map directly to orchestrator state slots.
# Multiple header spellings map to the same key (fuzzy matching).
#
# Header text is normalized via `_normalize_header()` before matching:
#   - lowercased
#   - punctuation stripped (`?`, `.`, `:`, `!`, `,`)
#   - collapsed whitespace
#
# Order matters only insofar as longest-prefix-first wins when two
# patterns share a prefix (e.g. "ideal customer profile" before "icp").
_HEADER_ALIASES: dict[str, str] = {
    "summary": "summary",
    "audience": "audience",
    "icp": "icp",
    "ideal customer profile": "icp",
    "ideal customer": "icp",
    "goal": "goals",
    "goals": "goals",
    "content strategy": "content_strategy",
    "content": "content_strategy",
    "domain registered": "domain_registered",
    "registered": "domain_registered",
    "registrar": "registrar",
    "growth hypothesis": "growth_hypothesis",
    "growth": "growth_hypothesis",
    "lovable github repo url": "lovable_repo",
    "lovable github repo": "lovable_repo",
    "lovable repo url": "lovable_repo",
    "lovable repo": "lovable_repo",
    "github repo url": "lovable_repo",
    "github repo": "lovable_repo",
    "repo url": "lovable_repo",
}


# Canonical key → human-facing label used in the preview banner.
CANONICAL_LABELS: dict[str, str] = {
    "summary": "Summary",
    "audience": "Audience",
    "icp": "ICP",
    "goals": "Goals",
    "content_strategy": "Content strategy",
    "domain_registered": "Domain registered?",
    "registrar": "Registrar",
    "growth_hypothesis": "Growth hypothesis",
    "lovable_repo": "Lovable GitHub repo URL",
}


# Match a numbered section header line, e.g. `2. Summary` or
# `9. Growth hypothesis`. Captures (number, header_text).
# Allows trailing punctuation on the header (e.g. `7. Domain registered?`).
_HEADER_RE = re.compile(
    r"^[ \t]*(\d+)\.[ \t]+(.+?)[ \t]*$",
    re.MULTILINE,
)


def _normalize_header(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = text.lower()
    # Drop common trailing/embedded punctuation.
    lowered = re.sub(r"[?!.,:;]", " ", lowered)
    # Collapse whitespace runs to a single space; strip ends.
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _match_header(normalized: str) -> str | None:
    """Map a normalized header to a canonical key, or return None.

    Tries longest alias first so `ideal customer profile` beats
    `icp` when both might match a header that contains both.
    """
    # Exact match first (most aliases).
    if normalized in _HEADER_ALIASES:
        return _HEADER_ALIASES[normalized]
    # Suffix/prefix permissive match: try each alias as a "starts with"
    # or "equals after trimming a leading number-like prefix".
    for alias in sorted(_HEADER_ALIASES, key=len, reverse=True):
        if normalized == alias:
            return _HEADER_ALIASES[alias]
    return None


def parse_multisection_paste(text: str) -> dict[str, str] | None:
    """Parse a multi-section paste into a canonical-key → content dict.

    Detection: scans `text` for numbered section headers
    (``^\\d+\\. <HeaderText>``). Each match becomes a section
    boundary; the lines between matches are the previous section's
    content (whitespace-stripped).

    Each header is normalized (lowercase, punctuation stripped) and
    mapped to a canonical key via `_HEADER_ALIASES`. Headers that
    don't match any known canonical section are skipped (they don't
    count toward the threshold and they don't contribute content).

    Threshold: at least 3 canonical sections must be present for the
    paste to be treated as multi-section. Fewer → return None.

    Returns:
      - dict[canonical_key → content_str] when ≥3 canonical sections
        matched. Content has leading/trailing whitespace stripped;
        internal newlines preserved.
      - None when the input isn't a multi-section paste (or is empty).
    """
    if not text or not text.strip():
        return None

    # Find all numbered headers and their byte spans.
    matches = list(_HEADER_RE.finditer(text))
    if len(matches) < 3:
        # Not enough numbered headers to even potentially be multi-section.
        return None

    # Walk pairs of (current_header, next_header_or_EOF) and capture
    # the slice of `text` between them as that section's content.
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        header_text = m.group(2)
        normalized = _normalize_header(header_text)
        key = _match_header(normalized)
        if key is None:
            # Unknown header (e.g. "1. Topic" if the operator's prompt
            # template added an extra section we don't track). Skip
            # without consuming content boundary; the next known
            # section will absorb the following content. To keep the
            # algorithm simple + predictable, we still treat unknown
            # headers as boundaries (their content is discarded) — the
            # alternative (merge unknown content into the prior known
            # section) would silently corrupt sections.
            continue

        content_start = m.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[content_start:content_end].strip()
        # If we've already captured this key (operator pasted two
        # `Summary` sections), prefer the first non-empty one — drop
        # the duplicate silently.
        if key in sections and sections[key]:
            continue
        sections[key] = content

    # Threshold: ≥3 canonical sections must have content (or at least
    # be recognized as headers). Count keys that landed in the dict.
    if len(sections) < 3:
        return None

    return sections


def normalize_yes_no(text: str) -> bool | None:
    """Parse a single-line Y/N answer (case-insensitive).

    Returns True for {y, yes, true, 1}, False for {n, no, false, 0},
    None for anything else (including empty)."""
    cleaned = text.strip().lower()
    if cleaned in ("y", "yes", "true", "1"):
        return True
    if cleaned in ("n", "no", "false", "0"):
        return False
    return None


def normalize_registrar(text: str, valid: tuple[str, ...]) -> str:
    """Normalize a registrar value against the canonical set.

    Whitespace-stripped + lowercased. If the result isn't in `valid`,
    returns ``"other"`` (the safe fallback used elsewhere in the
    bootstrap flow when a registrar can't be matched)."""
    candidate = text.strip().lower()
    if candidate in valid:
        return candidate
    return "other"


def first_nonblank_line(text: str) -> str:
    """Return the first non-blank line of `text`, stripped.

    Used for single-line section slots (Audience, Goals) that may
    arrive as paragraphs in a multi-section paste — collapse to one
    line rather than overflow into AI_AGENTS.md."""
    for line in text.splitlines():
        s = line.strip()
        if s:
            return s
    return ""


def looks_like_repo_url(text: str) -> bool:
    """Cheap URL-shape validator matching `_resolve_git_url`."""
    s = text.strip()
    if not s:
        return False
    return bool(re.match(r"^https?://", s) or re.match(r"^git@", s))


def preview_snippet(content: str, limit: int = 80) -> str:
    """Shorten `content` to a single-line preview (≤ `limit` chars).

    Collapses internal newlines to spaces, then truncates with an
    ellipsis."""
    one_line = re.sub(r"\s+", " ", content).strip()
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1].rstrip() + "…"
