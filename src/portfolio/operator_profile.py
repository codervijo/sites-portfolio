"""Operator profile loader for v8.D Phase 3.

Reads `[operator]` from `sites/portfolio/lamill.toml`. The full
`lamill.toml` schema lands in v9.A; this loader is intentionally
narrow — it only cares about the `[operator]` section and silently
ignores everything else.

Location decision (PRD §8.D P3, 2026-05-16): visible per-site path,
NOT `~/.lamill/operator.yaml`. The profile lives in the portfolio
repo itself; every other `sites/<domain>/` repo omits the section.

Three fields:
- `expertise: list[str]` — operator's strong areas (free-form labels)
- `workflow_preference: "builder" | "writer" | "mixed"` — how the
  operator likes to spend project time
- `motivation_cadence: "weekly" | "monthly" | "quarterly"` — how
  often the operator checks back on a niche

Missing file / missing section / unrecognized values all degrade to
defaults rather than raising. The tool runs without an operator
profile; the gates just skip the fit checks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .data import ROOT
from .research_gates import (
    OperatorFitResult,
    _tokenize_stems,
    load_media_publications,
)

LAMILL_TOML = ROOT / "lamill.toml"

WORKFLOW_VALUES = ("builder", "writer", "mixed")
CADENCE_VALUES = ("weekly", "monthly", "quarterly")

DEFAULT_WORKFLOW = "mixed"
DEFAULT_CADENCE = "monthly"


@dataclass
class OperatorProfile:
    expertise: list[str] = field(default_factory=list)
    workflow_preference: str = DEFAULT_WORKFLOW
    motivation_cadence: str = DEFAULT_CADENCE

    @property
    def configured(self) -> bool:
        """True if any non-default value is set — used by `show` to
        distinguish "no profile configured" from "all defaults"."""
        return bool(self.expertise) or (
            self.workflow_preference != DEFAULT_WORKFLOW
        ) or (
            self.motivation_cadence != DEFAULT_CADENCE
        )


def load_operator_profile(path: Path | None = None) -> OperatorProfile:
    """Load `[operator]` from `sites/portfolio/lamill.toml`.

    `path` overrides the default location (used by tests). Missing
    file, missing `[operator]` section, malformed TOML, or unknown
    enum values all return a default `OperatorProfile()` — the loader
    never raises on bad input.
    """
    import tomllib

    p = path if path is not None else LAMILL_TOML
    if not p.exists():
        return OperatorProfile()
    try:
        with p.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, ValueError):
        return OperatorProfile()

    section = doc.get("operator")
    if not isinstance(section, dict):
        return OperatorProfile()

    return OperatorProfile(
        expertise=_clean_str_list(section.get("expertise")),
        workflow_preference=_clean_enum(
            section.get("workflow_preference"),
            WORKFLOW_VALUES,
            DEFAULT_WORKFLOW,
        ),
        motivation_cadence=_clean_enum(
            section.get("motivation_cadence"),
            CADENCE_VALUES,
            DEFAULT_CADENCE,
        ),
    )


def _clean_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]


def _clean_enum(value: object, allowed: tuple[str, ...], default: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    return default


# ---------- Operator-fit logic (PRD §8.D P3.4) ----------
#
# Three checks layered on top of Gate 2:
#   1. Expertise   — auto-fails Gate 2 if intent is informational AND the
#                    SERP rewards authority AND topic terms don't overlap
#                    with declared expertise[].
#   2. Workflow    — warns if profile is "builder" but SERP rewards
#                    listicle content.
#   3. Cadence     — warns if profile is "weekly" but cluster looks like
#                    evergreen reference (slow-moving).
#
# Each check needs the operator to have declared the relevant field
# (non-default for workflow/cadence; non-empty for expertise). Otherwise
# the tool has nothing to judge against and the check no-ops.

_FINDING_EXPERTISE = "Operator lacks declared expertise; narrow to tool/data wedge."
_FINDING_WORKFLOW = "Builder profile + niche rewards content. Narrow to tool wedge."
_FINDING_CADENCE = "Cadence: weekly. Niche metrics move monthly+. Watch motivation."

# Informational query markers — checked as whole-word prefixes or as
# tokens anywhere in the query. Kept short; false positives degrade
# gracefully (just means more queries count as informational, which is
# the more permissive side of the auto-fail condition).
_INFORMATIONAL_MARKERS = (
    "how", "what", "why", "when", "where", "guide", "tutorial",
    "tips", "best", "top", "vs", "explained", "examples", "ideas",
)

# Listicle title pattern — opens with "Best", "Top", or a leading number
# of 1-3 digits ("10 best", "5 top", etc.). Case-insensitive.
_LISTICLE_TITLE = re.compile(
    r"^\s*(?:\d{1,3}\s+)?(?:best|top)\b|^\s*\d{1,3}\s+",
    re.IGNORECASE,
)

# Institutional TLD suffixes — used in the E-E-A-T heuristic.
_INSTITUTIONAL_SUFFIXES = (
    ".gov", ".edu", ".gov.uk", ".ac.uk", ".edu.au", ".gov.au",
    ".gc.ca", ".nhs.uk", ".int",
)

# Thresholds (5-query clusters per PRD §P1):
_INTENT_THRESHOLD = 3        # ≥3/5 queries → cluster intent applies
_EEAT_HITS_THRESHOLD = 3     # ≥3 institutional/media hits across top-10s → authority-rewarded
_LISTICLE_THRESHOLD = 3      # ≥3/5 queries with listicle-dominant top-10


def evaluate_operator_fit(cluster: dict, profile: OperatorProfile,
                          *, media_pubs: dict[str, list[str]] | None = None,
                          ) -> OperatorFitResult:
    """Apply operator-fit constraints to a cluster snapshot.

    Returns an `OperatorFitResult` with warnings + an `auto_fail_gate_2`
    flag. Empty profile (defaults across the board) → empty result.

    `media_pubs` is the publisher allow-list; defaults to the on-disk
    `data/research/media_publications.toml` allow-list. Injected by tests.
    """
    if media_pubs is None:
        media_pubs = load_media_publications()

    warnings: list[str] = []
    auto_fail = False

    queries = cluster.get("cluster_queries", []) or []
    topic = cluster.get("topic", "") or ""

    # Expertise check — auto-fail Gate 2 if all three conditions hit.
    if profile.expertise:
        if (
            _is_informational_intent(queries)
            and _is_eeat_rewarded(cluster, media_pubs=media_pubs)
            and not _expertise_overlaps_topic(profile.expertise, topic)
        ):
            warnings.append(_FINDING_EXPERTISE)
            auto_fail = True

    # Workflow check — warn if builder + listicle-dominant SERPs.
    if profile.workflow_preference == "builder":
        if _count_listicle_queries(cluster) >= _LISTICLE_THRESHOLD:
            warnings.append(_FINDING_WORKFLOW)

    # Cadence check — warn if weekly + cluster looks evergreen.
    if profile.motivation_cadence == "weekly":
        if _is_evergreen_cluster(cluster, queries):
            warnings.append(_FINDING_CADENCE)

    return OperatorFitResult(warnings=warnings, auto_fail_gate_2=auto_fail)


# ---------- helpers ----------


def _is_informational_intent(queries: list[str]) -> bool:
    """≥3/5 queries open with or contain an informational marker."""
    if not queries:
        return False
    hits = sum(1 for q in queries if _query_is_informational(q))
    return hits >= _INTENT_THRESHOLD


def _query_is_informational(query: str) -> bool:
    if not query:
        return False
    tokens = re.split(r"[^a-z0-9]+", query.lower())
    return any(t in _INFORMATIONAL_MARKERS for t in tokens if t)


def _is_eeat_rewarded(cluster: dict,
                      *, media_pubs: dict[str, list[str]]) -> bool:
    """≥3 institutional / curated-publisher domain hits across the
    cluster's top-10 results. Counts each (query, domain) once."""
    pub_domains: set[str] = set()
    for doms in media_pubs.values():
        pub_domains.update(d.lower() for d in doms)

    seen: set[tuple[str, str]] = set()
    hits = 0
    for p in cluster.get("per_query_results", []) or []:
        q = p.get("query", "")
        for r in (p.get("organic_results", []) or [])[:10]:
            d = (r.get("domain") or "").lower()
            if not d or (q, d) in seen:
                continue
            seen.add((q, d))
            if _is_institutional_domain(d) or d in pub_domains:
                hits += 1
                if hits >= _EEAT_HITS_THRESHOLD:
                    return True
    return False


def _is_institutional_domain(domain: str) -> bool:
    return any(domain.endswith(sfx) for sfx in _INSTITUTIONAL_SUFFIXES)


def _expertise_overlaps_topic(expertise: list[str], topic: str) -> bool:
    """Stem-tokenize topic + expertise items; return True if any stem
    intersects. Reuses `_tokenize_stems` from research_gates for parity
    with Gate 1's pollution check."""
    topic_stems = _tokenize_stems(topic)
    if not topic_stems:
        return False
    for item in expertise:
        if _tokenize_stems(item) & topic_stems:
            return True
    return False


def _count_listicle_queries(cluster: dict) -> int:
    """Number of cluster queries whose top-10 contains ≥2 listicle-style
    titles."""
    count = 0
    for p in cluster.get("per_query_results", []) or []:
        listicle_hits = sum(
            1 for r in (p.get("organic_results", []) or [])[:10]
            if _LISTICLE_TITLE.search(r.get("title", "") or "")
        )
        if listicle_hits >= 2:
            count += 1
    return count


def _is_evergreen_cluster(cluster: dict, queries: list[str]) -> bool:
    """Proxy for "evergreen reference" intent: ≥3/5 queries are
    informational AND ≥3/5 queries have an AI Overview in their SERP
    (signal that the answer is settled, not breaking).

    SERP snapshots don't carry per-result publication dates, so the
    PRD's "top results are >2 years old" proxy isn't computable from
    serp-query-v1 data. AI-Overview presence is the closest signal
    SerpAPI returns: Google only surfaces AI Overviews when the
    underlying answer is stable enough to summarize, which correlates
    with evergreen reference content.
    """
    if not _is_informational_intent(queries):
        return False
    ai_overview_hits = 0
    for p in cluster.get("per_query_results", []) or []:
        feats = p.get("features", {}) or {}
        if (feats.get("ai_overview") or {}).get("present"):
            ai_overview_hits += 1
    return ai_overview_hits >= _INTENT_THRESHOLD
