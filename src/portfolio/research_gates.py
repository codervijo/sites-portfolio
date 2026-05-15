"""v8.D Phase 2 — three-gate decision logic.

Pure logic + one optional LLM call. No CLI. Takes a `research-cluster-v2`
snapshot (produced by `research_v2.py` in Phase 1) and returns gate
results + overall verdict.

The three gates:

  1. **Market** (`evaluate_gate_1`) — pollution-adjusted search-volume
     estimate. PASS when the cluster has ≥5K SV/month after polluted
     queries are zeroed out. The volume proxy itself is LLM-estimated
     and flagged low-confidence (PRD §8.A option 1).

  2. **SERP** (`evaluate_gate_2`) — seven classifiers run over the
     merged top-10 across cluster queries. Kill-tier classifiers
     (specialty incumbent / programmatic-at-scale / locked intents)
     force FAIL; sufficient `POTENTIALLY_BEATABLE` results force PASS;
     anything between is WEAK PASS with a niche-down finding.

  3. **Moat** (`evaluate_gate_3`) — interactive. Required only when
     Gate 2 detected a specialty incumbent / programmatic incumbent.
     Caller passes the user's typed sentence (or None for FAIL).

Verdict synthesis lives in `synthesize_verdict()` per PRD §P2.5.

The functions in this module accept dicts (the cluster snapshot shape)
and return dicts so they're trivially serializable into the
`research-cluster-v2` schema's `gates` / `verdict` slots without
adapter code in the CLI layer.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

# Labels for the gate-result `label` field. Kept as constants so callers
# can pattern-match without remembering capitalization.
LABEL_PASS = "PASS"
LABEL_FAIL = "FAIL"
LABEL_WEAK_PASS = "WEAK-PASS"
LABEL_PENDING = "PENDING"

# Verdicts emitted by synthesize_verdict().
VERDICT_GO = "GO"
VERDICT_NICHE_DOWN = "NICHE-DOWN"
VERDICT_NO_GO = "NO-GO"

# Gate 1 threshold (PRD §P2.2). Pollution-adjusted volume below this
# fails the market gate.
GATE_1_VOLUME_THRESHOLD = 5000

# Gate 2 PASS threshold (PRD §P2.3). Number of beatable results required
# across the merged cluster top-10s.
GATE_2_BEATABLE_THRESHOLD = 3


# ---------- dataclasses ----------


@dataclass
class GateResult:
    """One gate's outcome.

    `passed=None` is reserved for Gate 3 in `--non-interactive` / `--json`
    mode where the user hasn't been prompted yet. In that case `label`
    is `PENDING` and the verdict treats it as if it had failed.
    """
    passed: bool | None
    label: str
    findings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OperatorFitResult:
    """Operator-profile findings layered on top of the gates.

    Empty in Phase 2 — populated by Phase 3 when operator.toml exists.
    Carrying the dataclass through Phase 2 keeps the snapshot schema
    forward-compatible.
    """
    warnings: list[str] = field(default_factory=list)
    auto_fail_gate_2: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResults:
    """All gates + operator fit + final verdict for one cluster."""
    gate_1_market: GateResult
    gate_2_serp: GateResult
    gate_3_moat: GateResult
    operator_fit: OperatorFitResult
    verdict: str
    suggested_reductions: list[str] = field(default_factory=list)
    moat_required: bool = False
    moat_provided: str | None = None

    def to_dict(self) -> dict:
        return {
            "gate_1_market": self.gate_1_market.to_dict(),
            "gate_2_serp": self.gate_2_serp.to_dict(),
            "gate_3_moat": self.gate_3_moat.to_dict(),
            "operator_fit": self.operator_fit.to_dict(),
            "verdict": self.verdict,
            "suggested_reductions": list(self.suggested_reductions),
            "moat_required": self.moat_required,
            "moat_provided": self.moat_provided,
        }


# ---------- Gate 1 (Market) — P2.B ----------

# Short stopword list — keeps the stem-match honest without dragging in
# nltk. These are the words that appear in cluster queries and would
# stem-match anything (and / the / for / a / etc.).
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at",
    "by", "from", "with", "is", "are", "was", "were", "be", "been",
    "do", "does", "did", "how", "what", "when", "where", "why", "which",
    "this", "that", "these", "those", "best", "top",
})

# Light Porter-equivalent suffix stripping. Order matters: strip the
# longest match first so "operations" → "operat" not "operation".
_STEM_SUFFIXES = (
    "tions", "tional", "sional", "ation", "ations",
    "ings", "ing", "ies", "ied", "ied",
    "ers", "er", "ly", "ed", "es", "s",
)


def _stem(token: str) -> str:
    """Lowercase + light suffix strip. Tokens shorter than 4 chars after
    stripping are returned unchanged (avoids "ev" → "" on "evs")."""
    token = token.lower()
    for suffix in _STEM_SUFFIXES:
        if len(token) - len(suffix) >= 3 and token.endswith(suffix):
            return token[:-len(suffix)]
    return token


_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")


def _tokenize_stems(text: str) -> set[str]:
    """Lowercase, split on non-alphanum, drop stopwords, stem.
    Returns a set so callers can do membership/intersection tests."""
    if not text:
        return set()
    tokens = _TOKEN_SPLIT.split(text.lower())
    return {
        _stem(t) for t in tokens
        if t and len(t) >= 2 and t not in _STOPWORDS
    }


def _query_is_polluted(query_payload: dict, topic_stems: set[str]) -> bool:
    """A query is polluted if 0/3 of its top-3 organic results' titles
    contain any stem from the topic (PRD §P2.2).

    Pollution is compared against the ORIGINAL topic's stems, not the
    LLM-expanded query's own stems — otherwise a drifted cluster query
    would pollute-protect itself (titles about the drift's subject
    would match the drifted-query's stems and look on-topic).

    `query_payload` is one entry from `cluster["per_query_results"]`
    — a `serp-query-v1` snapshot dict.
    """
    organic = query_payload.get("organic_results", [])[:3]
    if not organic:
        return True   # no data → treat as polluted (PRD §8.J option 1)
    for r in organic:
        title_stems = _tokenize_stems(r.get("title", ""))
        if title_stems & topic_stems:
            return False
    return True


# Sentinel used by tests + callers to inject a fake volume estimator
# without dragging in the LLM machinery.
VolumeEstimator = Callable[[list[str]], dict[str, int]]


def _llm_volume_estimator(queries: list[str]) -> dict[str, int]:
    """Default volume estimator — single OpenAI call returning a
    rough monthly-volume estimate per query.

    Returns `{query: estimated_monthly_volume}`. Treats the output as
    a low-confidence proxy; the finding text always tags it as such.

    Local import of `.serp` keeps the module import-cheap for tests
    that inject a fake estimator.
    """
    from .serp import _openai_api_key, call_openai

    if not queries:
        return {}

    system = (
        "You are a search-volume estimator for a personal domain portfolio. "
        "Given a list of search queries, return your best estimate of US "
        "monthly Google search volume for each query as a plain integer. "
        "Be honest about uncertainty — these are rough estimates, not "
        "Keyword Planner data. Reply with JSON ONLY in the shape: "
        '{"estimates": [{"query": "...", "monthly_volume": 1500}, ...]}.'
    )
    user = "Estimate monthly volume for:\n" + "\n".join(f"- {q}" for q in queries)
    raw = call_openai(system, user, api_key=_openai_api_key())

    # Tolerant parse — strip markdown fences if the model added them.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        # Soft-fail rather than blowing up the whole research run.
        # Treat every query as 0-volume — Gate 1 fails but the user can
        # re-run with --synthesis-only or override.
        return {q: 0 for q in queries}

    out: dict[str, int] = {}
    for item in parsed.get("estimates", []):
        q = item.get("query", "").strip()
        v = item.get("monthly_volume")
        if q and isinstance(v, (int, float)) and v >= 0:
            out[q] = int(v)
    # Fill missing queries with 0 (honest behavior per PRD §8.J).
    for q in queries:
        out.setdefault(q, 0)
    return out


def evaluate_gate_1(cluster: dict, *,
                    volume_estimator: VolumeEstimator | None = None,
                    ) -> GateResult:
    """Gate 1 (Market) — pollution-adjusted search-volume check.

    Steps:
      1. Tokenize the topic + every cluster query → union of stems.
      2. For each per-query SerpAPI result, check top-3 organic titles
         against the cluster-stem set. 0 matches → polluted.
      3. Get LLM volume estimates for all queries.
      4. Pollution-adjusted volume = sum of unpolluted queries' volumes.
      5. PASS if ≥ GATE_1_VOLUME_THRESHOLD (5000), FAIL else.

    The LLM proxy is honest about its weakness — the finding string
    always carries a `low-confidence` tag (PRD §8.A option 1).
    Inject `volume_estimator` for tests / synthesis-only mode.
    """
    cluster_queries = cluster.get("cluster_queries", []) or []
    per_query = cluster.get("per_query_results", []) or []
    source = cluster.get("source", "serpapi")
    synthesis_only = source != "serpapi"

    # 1 — topic stems (used for pollution detection).
    topic_stems = _tokenize_stems(cluster.get("topic", ""))

    # 2 — pollution detection per query. Skip in synthesis-only mode
    # (no real top-3 titles to inspect — PRD §8.F option 1: run anyway
    # but tag findings).
    polluted: list[str] = []
    unpolluted: list[str] = []
    if synthesis_only:
        unpolluted = list(cluster_queries)
    else:
        # Build a lookup of query → payload so we tolerate any ordering.
        by_query = {p.get("query"): p for p in per_query if p.get("query")}
        for q in cluster_queries:
            payload = by_query.get(q)
            if payload is None or _query_is_polluted(payload, topic_stems):
                polluted.append(q)
            else:
                unpolluted.append(q)

    # 3 — volume estimates for all cluster queries.
    estimator = volume_estimator or _llm_volume_estimator
    try:
        volumes = estimator(cluster_queries)
    except Exception as e:    # noqa: BLE001
        # Honest fallback: estimator died → treat every query as 0 SV.
        # Gate 1 will likely FAIL; finding explains why.
        volumes = {q: 0 for q in cluster_queries}
        estimator_error = f"{type(e).__name__}: {e}"
    else:
        estimator_error = None

    # 4 — pollution-adjusted volume.
    adjusted = sum(int(volumes.get(q, 0)) for q in unpolluted)
    total = sum(int(volumes.get(q, 0)) for q in cluster_queries)

    # 5 — PASS / FAIL.
    passed = adjusted >= GATE_1_VOLUME_THRESHOLD
    label = LABEL_PASS if passed else LABEL_FAIL

    findings: list[str] = []
    findings.append(
        f"{adjusted:,} SV/month after pollution adjustment "
        f"(LLM estimate, low-confidence)"
    )
    if synthesis_only:
        findings.append("[from LLM guess] — synthesis-only mode, no real SERP")
    if polluted:
        findings.append(
            f"{len(polluted)} of {len(cluster_queries)} queries polluted "
            f"(top-3 titles don't match cluster topic)"
        )
    if estimator_error:
        findings.append(f"volume estimator failed: {estimator_error}")

    return GateResult(
        passed=passed, label=label, findings=findings,
        raw={
            "pollution_adjusted_volume": adjusted,
            "total_volume": total,
            "polluted_queries": polluted,
            "unpolluted_queries": unpolluted,
            "per_query_volumes": dict(volumes),
            "topic_stems": sorted(topic_stems),
            "threshold": GATE_1_VOLUME_THRESHOLD,
            "synthesis_only": synthesis_only,
        },
    )


# ---------- Gate 2 (SERP) — P2.C ----------

# Programmatic-URL patterns (PRD §P2.3 SPECIALTY_INCUMBENT classifier).
# A URL matching any of these is a signal that the page belongs to a
# template-generated programmatic cluster.
_PROGRAMMATIC_URL_PATTERNS = [
    re.compile(r"/(?:19|20)\d{2}/"),                       # year segment
    re.compile(r"/v\d+\b"),                                # version segment
    re.compile(r"/[a-z]{2}/(?:state|states)/"),            # state-code/state
    re.compile(r"/[a-z\-]+(?:city|town)\b"),               # geo
    re.compile(r"/(?:model|models|version)/[a-z0-9\-]+"),  # model identifier
]

# Threshold for PROGRAMMATIC_AT_SCALE — domain in N+ cluster queries' top-10.
_PROGRAMMATIC_SCALE_THRESHOLD = 3

# Threshold for MEDIA_LOCKED + AI_OVERVIEW_DOMINANT — ≥N cluster queries
# carry the signal.
_MEDIA_LOCKED_THRESHOLD = 2
_AI_OVERVIEW_DOMINANT_THRESHOLD = 2


def load_media_publications() -> dict[str, list[str]]:
    """Load the media-pub allow-list from
    `data/research/media_publications.toml`. Returns
    `{vertical: [domains]}`. Returns `{}` if the file is missing — the
    MEDIA_LOCKED classifier will silently no-op rather than crash."""
    import tomllib
    from .data import ROOT
    p = ROOT / "data" / "research" / "media_publications.toml"
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    for vert, section in doc.items():
        if isinstance(section, dict):
            domains = section.get("domains", [])
            if isinstance(domains, list):
                out[vert] = [str(d).lower().strip() for d in domains if d]
    return out


def _all_organic(cluster: dict) -> list[tuple[str, dict]]:
    """Yield (query, organic_result) pairs across the cluster's top-10s."""
    out: list[tuple[str, dict]] = []
    for p in cluster.get("per_query_results", []) or []:
        q = p.get("query", "")
        for r in (p.get("organic_results", []) or [])[:10]:
            out.append((q, r))
    return out


def _detect_reddit_present(cluster: dict) -> dict:
    """REDDIT_PRESENT — `reddit.com` in any cluster query's top-10."""
    hits: list[str] = []
    for q, r in _all_organic(cluster):
        d = (r.get("domain") or "").lower()
        if d == "reddit.com" or d.endswith(".reddit.com"):
            if q not in hits:
                hits.append(q)
    return {"present": bool(hits), "queries": hits}


def _detect_ai_overview_dominant(cluster: dict) -> dict:
    """AI_OVERVIEW_DOMINANT — `ai_overview.present == True` on ≥2 queries."""
    hits: list[str] = []
    for p in cluster.get("per_query_results", []) or []:
        feats = p.get("features", {}) or {}
        ai = feats.get("ai_overview") or {}
        if ai.get("present"):
            hits.append(p.get("query", ""))
    return {
        "dominant": len(hits) >= _AI_OVERVIEW_DOMINANT_THRESHOLD,
        "queries": hits,
        "count": len(hits),
    }


def _detect_programmatic_at_scale(cluster: dict) -> dict:
    """PROGRAMMATIC_AT_SCALE — same domain in ≥3 cluster queries' top-10."""
    from collections import defaultdict
    by_domain: defaultdict[str, set] = defaultdict(set)
    for q, r in _all_organic(cluster):
        d = (r.get("domain") or "").lower()
        if d:
            by_domain[d].add(q)
    incumbents = {
        d: sorted(qs) for d, qs in by_domain.items()
        if len(qs) >= _PROGRAMMATIC_SCALE_THRESHOLD
    }
    return {"present": bool(incumbents), "incumbents": incumbents}


def _detect_specialty_incumbent(cluster: dict, *,
                                excluded_domains: set[str]) -> dict:
    """SPECIALTY_INCUMBENT — domain ranks ≥1 query with a URL matching the
    programmatic-pattern regex AND is not in the excluded set
    (media/Reddit/wiki/etc.)."""
    hits: dict[str, list[str]] = {}
    for q, r in _all_organic(cluster):
        d = (r.get("domain") or "").lower()
        url = (r.get("url") or "").lower()
        if not d or not url:
            continue
        if d in excluded_domains:
            continue
        for pat in _PROGRAMMATIC_URL_PATTERNS:
            if pat.search(url):
                if d not in hits:
                    hits[d] = []
                if q not in hits[d]:
                    hits[d].append(q)
                break
    return {"present": bool(hits), "incumbents": hits}


def _detect_media_locked(cluster: dict, *,
                         media_pubs: dict[str, list[str]]) -> dict:
    """MEDIA_LOCKED — ≥2 cluster queries return a media-pub domain in top-10."""
    all_media: set[str] = set()
    domain_to_vertical: dict[str, str] = {}
    for vert, doms in media_pubs.items():
        for d in doms:
            all_media.add(d)
            domain_to_vertical[d] = vert
    if not all_media:
        return {"locked": False, "queries": {}, "count": 0, "verticals": []}

    by_query: dict[str, list[str]] = {}
    for q, r in _all_organic(cluster):
        d = (r.get("domain") or "").lower()
        if d in all_media:
            by_query.setdefault(q, []).append(d)

    verticals = sorted({
        domain_to_vertical[d]
        for doms in by_query.values() for d in doms
    })
    return {
        "locked": len(by_query) >= _MEDIA_LOCKED_THRESHOLD,
        "queries": by_query,
        "count": len(by_query),
        "verticals": verticals,
    }


def _detect_potentially_beatable(cluster: dict, *,
                                 classified_domains: set[str]) -> dict:
    """POTENTIALLY_BEATABLE — domains not claimed by a kill-tier classifier.
    Weak signal: counts unique domains that look generic (no programmatic
    URL, not in media list, not Reddit / Wikipedia)."""
    seen: set[str] = set()
    beatable: list[dict] = []
    for q, r in _all_organic(cluster):
        d = (r.get("domain") or "").lower()
        if not d or d in seen:
            continue
        if d in classified_domains:
            continue
        if d == "wikipedia.org" or d.endswith(".wikipedia.org"):
            continue
        seen.add(d)
        beatable.append({
            "domain": d,
            "query": q,
            "title": r.get("title", ""),
        })
    return {"count": len(beatable), "domains": beatable}


def evaluate_gate_2(cluster: dict, *,
                    media_pubs: dict[str, list[str]] | None = None,
                    ) -> GateResult:
    """Gate 2 (SERP) — six classifiers + pass/fail/weak-pass.

    Classifiers (PRD §P2.3):
      - REDDIT_PRESENT
      - AI_OVERVIEW_DOMINANT
      - PROGRAMMATIC_AT_SCALE
      - SPECIALTY_INCUMBENT
      - MEDIA_LOCKED
      - POTENTIALLY_BEATABLE

    BRANDED_LOCKED is deferred — it's not in the PASS/FAIL decision per
    PRD §P2.3, and a robust brand-detection mechanism is out of scope.

    Fail conditions (PRD §P2.3):
      - SPECIALTY_INCUMBENT or PROGRAMMATIC_AT_SCALE → FAIL (moat required)
      - REDDIT_PRESENT AND MEDIA_LOCKED → FAIL (both intents locked)
      - AI_OVERVIEW_DOMINANT alone → FAIL

    Pass: ≥3 POTENTIALLY_BEATABLE AND no kill-tier classifier fires.
    Else: WEAK PASS (findings flag what would force a niche-down).

    `media_pubs` defaults to the on-disk allow-list (load_media_publications).
    Inject a dict for tests.
    """
    cluster_queries = cluster.get("cluster_queries", []) or []
    source = cluster.get("source", "serpapi")
    synthesis_only = source != "serpapi"

    if media_pubs is None:
        media_pubs = load_media_publications()

    reddit = _detect_reddit_present(cluster)
    ai_ov = _detect_ai_overview_dominant(cluster)
    prog = _detect_programmatic_at_scale(cluster)

    # SPECIALTY_INCUMBENT excludes Reddit + every media-list domain.
    excluded = {"reddit.com"}
    for doms in media_pubs.values():
        excluded.update(doms)
    spec = _detect_specialty_incumbent(cluster, excluded_domains=excluded)

    media = _detect_media_locked(cluster, media_pubs=media_pubs)

    # Build the set of domains already classified by a non-beatable
    # classifier — these are excluded from POTENTIALLY_BEATABLE.
    classified_domains: set[str] = set()
    classified_domains.update(prog["incumbents"].keys())
    classified_domains.update(spec["incumbents"].keys())
    if reddit["present"]:
        classified_domains.add("reddit.com")
    for doms in media["queries"].values():
        classified_domains.update(doms)

    beatable = _detect_potentially_beatable(
        cluster, classified_domains=classified_domains,
    )

    classifications = {
        "specialty_incumbent": spec,
        "programmatic_at_scale": prog,
        "ai_overview_dominant": ai_ov,
        "media_locked": media,
        "reddit_present": reddit,
        "potentially_beatable": beatable,
    }

    # Decide pass/fail per PRD §P2.3.
    kill_tier_reasons: list[str] = []
    if spec["present"]:
        kill_tier_reasons.append("specialty_incumbent")
    if prog["present"]:
        kill_tier_reasons.append("programmatic_at_scale")
    if reddit["present"] and media["locked"]:
        kill_tier_reasons.append("reddit_and_media_locked")
    if ai_ov["dominant"] and not kill_tier_reasons:
        kill_tier_reasons.append("ai_overview_dominant")

    findings: list[str] = []

    if spec["present"]:
        for d, qs in spec["incumbents"].items():
            findings.append(
                f"specialty incumbent: {d} ({len(qs)} queries, programmatic URLs)"
            )
    if prog["present"]:
        for d, qs in prog["incumbents"].items():
            findings.append(
                f"programmatic at scale: {d} ({len(qs)}/{len(cluster_queries)} queries)"
            )
    if ai_ov["dominant"]:
        findings.append(
            f"AI Overview dominant: {ai_ov['count']}/{len(cluster_queries)} queries"
        )
    if reddit["present"] and media["locked"]:
        findings.append(
            f"locked intent: Reddit ({len(reddit['queries'])} queries) "
            f"+ major media ({media['count']} queries)"
        )
    elif reddit["present"]:
        findings.append(
            f"Reddit present: {len(reddit['queries'])}/{len(cluster_queries)} queries "
            "(discussion intent locked)"
        )
    elif media["locked"]:
        verticals = ", ".join(media["verticals"]) if media["verticals"] else ""
        verticals_str = f" ({verticals})" if verticals else ""
        findings.append(
            f"media-locked: {media['count']}/{len(cluster_queries)} queries{verticals_str}"
        )

    findings.append(
        f"{beatable['count']} potentially beatable results"
    )

    if synthesis_only:
        findings.append("[from LLM guess] — synthesis-only mode, classifiers degraded")

    if kill_tier_reasons:
        passed = False
        label = LABEL_FAIL
    elif beatable["count"] >= GATE_2_BEATABLE_THRESHOLD:
        passed = True
        label = LABEL_PASS
    else:
        passed = True
        label = LABEL_WEAK_PASS

    return GateResult(
        passed=passed, label=label, findings=findings,
        raw={
            "classifications": classifications,
            "kill_tier_reasons": kill_tier_reasons,
            "synthesis_only": synthesis_only,
        },
    )


# ---------- Gate 3 (Moat) — P2.D ----------

# Reason strings — surfaced both in findings text and in raw for the
# renderer. Keep these as constants so callers and tests can pattern-match.
_MOAT_NOT_REQUIRED = "not required (no specialty/programmatic incumbent)"
_MOAT_PROVIDED = "moat acknowledged"
_MOAT_DECLINED = "no moat provided"
_MOAT_PENDING = "pending operator input (non-interactive mode)"


def evaluate_gate_3(gate_2: GateResult, moat_sentence: str | None,
                    *, non_interactive: bool = False) -> GateResult:
    """Gate 3 (Moat) — required only when Gate 2 detected a specialty
    or programmatic incumbent (PRD §P2.4).

    Resolution table (`required` from `is_moat_required(gate_2)`):

      | required | moat_sentence | non_interactive | label   | passed |
      |----------|---------------|-----------------|---------|--------|
      | False    | anything      | anything        | PASS    | True   |
      | True     | non-empty     | anything        | PASS    | True   |
      | True     | empty/None    | False           | FAIL    | False  |
      | True     | empty/None    | True            | PENDING | None   |

    The moat sentence is stored on `.raw["moat_sentence"]` when provided
    — the cluster snapshot caches it for re-runs / `--json` consumers.
    """
    required = is_moat_required(gate_2)
    if not required:
        return GateResult(
            passed=True, label=LABEL_PASS,
            findings=[_MOAT_NOT_REQUIRED],
            raw={"required": False, "moat_sentence": None},
        )

    sentence = (moat_sentence or "").strip()
    if sentence:
        return GateResult(
            passed=True, label=LABEL_PASS,
            findings=[_MOAT_PROVIDED, f'"{sentence}"'],
            raw={"required": True, "moat_sentence": sentence},
        )

    if non_interactive:
        return GateResult(
            passed=None, label=LABEL_PENDING,
            findings=[_MOAT_PENDING],
            raw={"required": True, "moat_sentence": None},
        )

    return GateResult(
        passed=False, label=LABEL_FAIL,
        findings=[_MOAT_DECLINED],
        raw={"required": True, "moat_sentence": None},
    )


# ---------- verdict synthesis (filled in by P2.E) ----------


def synthesize_verdict(g1: GateResult, g2: GateResult, g3: GateResult,
                       *, op_fit: OperatorFitResult | None = None) -> str:
    """Compose final verdict per PRD §P2.5.

    The table:
      | Gates                                          | Verdict       |
      |------------------------------------------------|---------------|
      | Gate 1 FAIL                                    | NO-GO         |
      | Gate 2 FAIL AND Gate 3 PROVIDED                | NICHE-DOWN    |
      | Gate 2 FAIL AND no moat                        | NO-GO         |
      | G1 PASS + G2 WEAK-PASS + Gate 3 not required   | NICHE-DOWN    |
      | All gates PASS                                 | GO            |

    Operator-fit's `auto_fail_gate_2` flag (Phase 3) is honored by
    treating Gate 2 as FAIL even if its label is PASS / WEAK-PASS.

    Stub returns NO-GO until P2.E fills it in.
    """
    return VERDICT_NO_GO


# ---------- helpers (shared across gates) ----------


def is_moat_required(gate_2: GateResult) -> bool:
    """True when Gate 2's findings include a SPECIALTY_INCUMBENT or
    PROGRAMMATIC_AT_SCALE classifier hit.

    Used by callers to decide whether to prompt the user before
    invoking `evaluate_gate_3`. Tolerant of two shapes for
    `classifications.<name>`:
      - dict with `"present": bool` (real P2.C output)
      - truthy list/value (legacy test fixtures)
    """
    cls = gate_2.raw.get("classifications", {}) if gate_2.raw else {}
    for key in ("specialty_incumbent", "programmatic_at_scale"):
        v = cls.get(key)
        if isinstance(v, dict):
            if v.get("present"):
                return True
        elif v:
            return True
    return False


def evaluate_cluster(cluster: dict, *, moat_sentence: str | None = None,
                     non_interactive: bool = False,
                     operator_fit: OperatorFitResult | None = None,
                     volume_estimator: VolumeEstimator | None = None,
                     ) -> GateResults:
    """Run all three gates against a cluster snapshot and return the
    composed `GateResults`. The orchestrator entry point used by the CLI.

    `volume_estimator` is forwarded to Gate 1 (P2.B). Tests inject a
    fake; the CLI lets it default to the LLM-backed estimator.
    """
    g1 = evaluate_gate_1(cluster, volume_estimator=volume_estimator)
    g2 = evaluate_gate_2(cluster)
    g3 = evaluate_gate_3(g2, moat_sentence, non_interactive=non_interactive)
    op_fit = operator_fit or OperatorFitResult()
    verdict = synthesize_verdict(g1, g2, g3, op_fit=op_fit)
    return GateResults(
        gate_1_market=g1,
        gate_2_serp=g2,
        gate_3_moat=g3,
        operator_fit=op_fit,
        verdict=verdict,
        suggested_reductions=[],
        moat_required=is_moat_required(g2),
        moat_provided=moat_sentence,
    )
