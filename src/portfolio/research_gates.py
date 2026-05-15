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


def evaluate_gate_2(cluster: dict) -> GateResult:
    """Gate 2 (SERP) — seven classifiers + pass/fail/weak-pass.

    Stub: returns PENDING. P2.C replaces this with the real logic.
    """
    return GateResult(
        passed=None, label=LABEL_PENDING,
        findings=["Gate 2 not yet implemented (P2.C)"],
        raw={"stub": True},
    )


def evaluate_gate_3(gate_2: GateResult, moat_sentence: str | None,
                    *, non_interactive: bool = False) -> GateResult:
    """Gate 3 (Moat) — required only when Gate 2 detected a specialty
    or programmatic incumbent.

    The moat-required check inspects `gate_2.raw["classifications"]`
    for the kill-tier classifier flags. When required:
      - `moat_sentence` non-empty → PASS, sentence stored on `.raw`
      - `moat_sentence` empty/None AND `non_interactive` → PENDING
      - `moat_sentence` empty/None AND interactive → FAIL

    When not required, returns PASS with an explanatory finding.

    Stub returns PENDING for now. P2.D fills it in.
    """
    return GateResult(
        passed=None, label=LABEL_PENDING,
        findings=["Gate 3 not yet implemented (P2.D)"],
        raw={"stub": True},
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
    invoking `evaluate_gate_3`.
    """
    cls = gate_2.raw.get("classifications", {}) if gate_2.raw else {}
    if cls.get("specialty_incumbent"):
        return True
    if cls.get("programmatic_at_scale"):
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
