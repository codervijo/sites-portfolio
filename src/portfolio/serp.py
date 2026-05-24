"""v8.A + v8.B — SERP research for new projects (AI-only synthesis).

`lamill new validate <topic>` — analyzes the likely SERP landscape for a
topic using gpt-4o-mini from training data (NOT real-time SERP), surfaces
ranking patterns + content-type breakdown + decision aid (ship/mixed/skip).

Two modes:

  cluster (default, v8.B) — LLM expands the topic into 5 related queries
                            and produces a cluster-level analysis with
                            frequency-tagged rankers. Catches the "this
                            specific phrase looks open but the broader
                            territory is saturated" failure mode (and
                            vice-versa).
  strict (--strict, v8.A) — Analyzes the literal topic only. Faster, but
                            misses the topic territory.

Read-only by design. Cached to `data/serp/<hash>.json` with a 30-day TTL —
LLM knowledge doesn't move daily, so a generous cache keeps repeated runs
free and deterministic. Cache key includes the mode so cluster + strict
runs for the same topic have separate cache entries.

Future v8.A.1 may swap the AI-only synthesis for a real-SERP API (Brave
paid / SerpAPI / DataForSEO) without changing the response schema — the
analyzer is the same shape either way.

Determinism: OpenAI temperature=0 so repeat runs of the same topic always
produce the same analysis. Helps testing + makes the cache value-stable.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from .data import ROOT

SERP_DIR = ROOT / "data" / "serp"
SERP_INDEX = SERP_DIR / "_index.json"
CACHE_TTL_DAYS = 30
MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/responses"
OPENAI_TIMEOUT = 60.0

_ALLOWED_TYPES = frozenset({
    "institutional", "publisher-listicle", "vendor-published",
    "niche-vendor", "community", "tool", "q-and-a",
    "news", "documentation", "other",
})
_ALLOWED_INTENTS = frozenset({
    "informational", "commercial", "navigational", "transactional",
})
_ALLOWED_SATURATIONS = frozenset({"low", "medium", "medium-high", "high"})
_ALLOWED_DECISIONS = frozenset({"ship", "mixed", "skip", "unclear"})

# Placeholder / filler domain names the LLM will sometimes invent when it
# has no real knowledge of the topic's SERP. If any of these appear in the
# rankers list, the analysis is fabricated and gets coerced to "unclear".
# RFC 2606 / 6761 reserves .test, .example, .invalid, .localhost — treat
# any domain on those TLDs as a placeholder regardless of label.
_PLACEHOLDER_LABELS = frozenset({
    "example", "sample", "demo", "test", "placeholder",
    "mockup", "fake", "fakesite", "foo", "bar", "baz",
    "randomsite", "yoursite", "mysite", "anysite",
})
_PLACEHOLDER_TLDS = frozenset({"test", "example", "invalid", "localhost"})


class ResearchError(RuntimeError):
    """Raised for any failure in the research pipeline. Caller maps to exit codes."""


def _looks_like_placeholder_domain(domain: str) -> bool:
    """True if `domain` looks like LLM-invented filler (example.com, test.net,
    foo.io, etc.) rather than a real domain. The detector covers both the
    common label patterns (`example`, `sample`, `demo`, …) and RFC 6761
    reserved TLDs (`.test`, `.example`, `.invalid`, `.localhost`).

    Conservative: a real domain with one of these labels (e.g. a small
    business called "demo.io") would also be flagged. Acceptable false
    positive — those are rare; the false-negative cost (treating
    fabricated rankers as real) is much higher for our use case.
    """
    if not domain or "." not in domain:
        return True
    parts = domain.lower().split(".")
    label = parts[0]
    tld = parts[-1]
    if label in _PLACEHOLDER_LABELS:
        return True
    if tld in _PLACEHOLDER_TLDS:
        return True
    return False


def _placeholder_count(rankers: list[dict]) -> int:
    """How many entries in the rankers list look like LLM-invented filler."""
    return sum(1 for r in rankers if _looks_like_placeholder_domain(r.get("domain", "")))


@dataclass
class CacheHit:
    payload: dict
    age_days: float


# ---------- normalization + hashing ----------


def normalize_topic(topic: str) -> str:
    """Whitespace-collapse + lowercase. Same topic spelled different
    casings or padding hits the same cache."""
    return " ".join(topic.lower().split())


def topic_hash(topic: str, mode: str = "cluster") -> str:
    """12-char sha256 prefix of the normalized topic + mode. Short enough
    for filename use, long enough that collisions across one user's
    research history are vanishingly unlikely.

    Mode is part of the hash so cluster + strict runs for the same topic
    get distinct cache entries — they're materially different analyses.
    """
    key = f"{mode}:{normalize_topic(topic)}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return digest[:12]


def cache_path(topic: str, mode: str = "cluster") -> Path:
    suffix = "" if mode == "cluster" else f".{mode}"
    return SERP_DIR / f"{topic_hash(topic, mode)}{suffix}.json"


# ---------- cache IO ----------


def load_cached(topic: str, *, mode: str = "cluster",
                ttl_days: int = CACHE_TTL_DAYS) -> CacheHit | None:
    """Return cached analysis if present + not expired, else None.

    Corrupt cache files are silently treated as misses (caller re-fetches).
    """
    p = cache_path(topic, mode)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    fetched_at_iso = payload.get("fetched_at")
    if not fetched_at_iso:
        return None
    try:
        fetched_at = datetime.fromisoformat(fetched_at_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    age = datetime.now(timezone.utc) - fetched_at
    if age > timedelta(days=ttl_days):
        return None
    return CacheHit(payload=payload, age_days=age.total_seconds() / 86400)


def save_cache(topic: str, payload: dict, *, mode: str = "cluster") -> Path:
    """Write payload to cache + update the human-readable index file.

    Atomic write (tmp + rename) so concurrent reads never see a half-file.
    """
    SERP_DIR.mkdir(parents=True, exist_ok=True)
    p = cache_path(topic, mode)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(p)
    _update_index(topic, mode=mode)
    return p


def _update_index(topic: str, *, mode: str = "cluster") -> None:
    """Maintain `data/serp/_index.json` — a hash → "<mode>:<topic>" map
    so a human can recover the original query + mode from a cache file
    name."""
    index: dict[str, str] = {}
    if SERP_INDEX.exists():
        try:
            index = json.loads(SERP_INDEX.read_text())
        except (OSError, ValueError):
            index = {}
    index[topic_hash(topic, mode)] = f"{mode}:{normalize_topic(topic)}"
    tmp = SERP_INDEX.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n")
    tmp.replace(SERP_INDEX)


# ---------- prompt construction ----------


_SYSTEM_PROMPT = """You are a SERP-analysis assistant for a personal domain portfolio.
The user is deciding whether to build a new site on a topic. Analyze
the likely current search-result landscape for the topic and produce
a structured JSON response matching the schema below.

CRITICAL: Output ONLY valid JSON, no prose before or after.

You are analyzing from your training data — explicitly note this is
NOT real-time SERP data. Do NOT fabricate specific URLs (just domain
names + content-type categories).

Constrained vocabularies (use only these):
  type:       institutional | publisher-listicle | vendor-published |
              niche-vendor | community | tool | q-and-a | news |
              documentation | other
  intent:     informational | commercial | navigational | transactional
  saturation: low | medium | medium-high | high
  decision:   ship | mixed | skip | unclear

If the topic is YMYL (Your Money / Your Life — medical, legal,
financial, safety-critical), set `ymyl_flag: true` and lean toward
"skip" or "unclear" — portfolio policy excludes YMYL.

CRITICAL: If you don't have specific knowledge of real domains likely
to rank for this topic (e.g., the topic is too niche, brand-new, or
nonsensical), set `decision: unclear` and explain in reasoning. Do
NOT fill `top_likely_rankers` with placeholder domains like
example.com, test.net, sample.org, demo.edu, mockup.co, fakesite.biz,
foo.com, etc. — if you don't know real domains, the right answer
is "unclear" with an empty or near-empty rankers list.

If the topic is nonsensical or too vague to analyze, set
`decision: unclear` and explain in reasoning.
"""

_USER_PROMPT_TEMPLATE = """Topic: {topic}

Respond with the JSON object only. Schema:

{{
  "top_likely_rankers": [
    {{"domain": "...", "type": "...", "intent": "..."}}
  ],
  "content_patterns": ["...", "..."],
  "competitive_signal": {{
    "saturation": "...",
    "ymyl_flag": true,
    "barrier": "<one-sentence explanation>"
  }},
  "suggested_angles": ["...", "..."],
  "decision": "...",
  "reasoning": "<two-sentence justification>"
}}

Provide 8-12 entries in top_likely_rankers (approximate ranking order),
3-5 content_patterns, 3-5 suggested_angles."""


def build_prompt(topic: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) tuple for the OpenAI call."""
    return _SYSTEM_PROMPT, _USER_PROMPT_TEMPLATE.format(topic=topic)


# ---------- OpenAI call ----------


def _openai_api_key() -> str:
    """Read OPENAI_API_KEY from portfolio.env, environment, or fail loudly."""
    from .suggest import load_env
    env = load_env()
    key = env.get("OPENAI_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ResearchError(
            "OPENAI_API_KEY not set. Run: lamill settings apikeys set OPENAI_API_KEY <key>"
        )
    return key


# 2026-05-24 — retry-with-backoff for transient OpenAI errors. Operator
# hit a bare HTTP 500 mid-`lamill new validate` which surfaced as a hard
# failure (cluster expansion failed) instead of a self-recovering blip.
# Pattern mirrors the v25.B-era retry approach (sequential intervals,
# explicit budget). 5xx and 429 are transient; 4xx (other) is permanent.
_OPENAI_RETRY_INTERVALS_S: tuple[float, ...] = (1.0, 2.0, 4.0, 8.0)
_OPENAI_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


def call_openai(system: str, user: str, *, api_key: str,
                _sleep: Callable[[float], None] = time.sleep) -> str:
    """Single API call with temperature=0 for determinism. Returns raw
    response text (expected to be a JSON object). Caller validates.

    2026-05-24 — retries transient failures (HTTP 429 / 5xx, network
    errors) with exponential backoff (~15s total budget). Permanent
    failures (HTTP 4xx other than 429) raise immediately.

    `_sleep` is injectable for tests so the backoff loop runs instantly.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": MODEL,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
    }

    last_error: str | None = None
    attempts = len(_OPENAI_RETRY_INTERVALS_S) + 1
    for attempt_idx in range(attempts):
        try:
            r = requests.post(OPENAI_URL, headers=headers, json=body,
                              timeout=OPENAI_TIMEOUT)
        except requests.RequestException as e:
            last_error = f"network error: {type(e).__name__}: {e}"
            if attempt_idx == attempts - 1:
                raise ResearchError(
                    f"OpenAI request failed after {attempts} attempts: "
                    f"{last_error}"
                ) from e
            _sleep(_OPENAI_RETRY_INTERVALS_S[attempt_idx])
            continue

        if r.status_code == 200:
            break
        if r.status_code in _OPENAI_RETRYABLE_STATUSES:
            last_error = f"HTTP {r.status_code}: {r.text[:200]}"
            if attempt_idx == attempts - 1:
                raise ResearchError(
                    f"OpenAI transient failure after {attempts} attempts: "
                    f"{last_error}"
                )
            _sleep(_OPENAI_RETRY_INTERVALS_S[attempt_idx])
            continue
        # Permanent error (4xx other than 429) — don't retry.
        raise ResearchError(
            f"OpenAI HTTP {r.status_code}: {r.text[:200]}"
        )
    try:
        data = r.json()
    except ValueError as e:
        raise ResearchError(f"OpenAI returned non-JSON: {e}") from e
    # Responses API surfaces output as `output_text` (convenience field)
    # OR as a structured `output[].content[].text` tree.
    if "output_text" in data:
        return data["output_text"]
    out = data.get("output", [])
    if out and isinstance(out, list):
        # First message → first text-typed content
        for item in out:
            content = item.get("content", [])
            for c in content:
                if c.get("type") == "output_text" or c.get("type") == "text":
                    return c.get("text", "")
    raise ResearchError(f"unexpected OpenAI response shape: {list(data.keys())}")


# ---------- response parsing + schema validation ----------


def parse_response(raw: str) -> dict:
    """Parse LLM response into a validated analysis dict. Coerces unknown
    enum values to safe defaults so a slightly-off LLM answer doesn't crash.
    Raises ResearchError on structural failures (no top_likely_rankers,
    malformed JSON, etc.).
    """
    raw = raw.strip()
    # Some models wrap JSON in ```json ... ``` fences despite the prompt.
    if raw.startswith("```"):
        lines = raw.splitlines()
        # Drop fence opener + closer
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        analysis = json.loads(raw)
    except ValueError as e:
        raise ResearchError(f"model returned malformed JSON: {e}") from e

    if not isinstance(analysis, dict):
        raise ResearchError("model returned non-object JSON")

    # `top_likely_rankers` is required as a list, but may legitimately be
    # empty when the LLM has no real data for the topic (post-prompt-fix
    # behavior for nonsense / very-niche topics). Empty rankers + decision
    # "unclear" is the correct shape, not an error.
    rankers = analysis.get("top_likely_rankers")
    if not isinstance(rankers, list):
        raise ResearchError("response missing `top_likely_rankers` list")

    # Coerce per-entry enums.
    cleaned_rankers = []
    for entry in rankers:
        if not isinstance(entry, dict):
            continue
        domain = entry.get("domain", "").strip().lower()
        if not domain:
            continue
        type_ = entry.get("type", "other")
        if type_ not in _ALLOWED_TYPES:
            type_ = "other"
        intent = entry.get("intent", "informational")
        if intent not in _ALLOWED_INTENTS:
            intent = "informational"
        cleaned_rankers.append({"domain": domain, "type": type_, "intent": intent})

    competitive = analysis.get("competitive_signal") or {}
    saturation = competitive.get("saturation", "medium")
    if saturation not in _ALLOWED_SATURATIONS:
        saturation = "medium"
    ymyl = bool(competitive.get("ymyl_flag", False))
    barrier = competitive.get("barrier", "")

    decision = analysis.get("decision", "unclear")
    if decision not in _ALLOWED_DECISIONS:
        decision = "unclear"

    reasoning = str(analysis.get("reasoning", ""))

    # Defense-in-depth: if the LLM ignored the prompt and filled the rankers
    # list with placeholder filler (example.com, test.net, etc.), the
    # analysis is fabricated. Coerce the decision to "unclear" and tag the
    # reasoning so the renderer (and the user) can see the LLM had no real
    # data. We require a majority of rankers to be placeholders — a single
    # accidental "demo.io" doesn't poison an otherwise-real analysis.
    #
    # Empty rankers list also triggers — that's the LLM correctly signaling
    # "I have no data for this topic" per the post-prompt-fix behavior.
    if not cleaned_rankers:
        decision = "unclear"
        prefix = ("[No real SERP data — LLM had no knowledge of this topic "
                  "and returned an empty rankers list.] ")
        reasoning = prefix + reasoning
    else:
        n_placeholders = _placeholder_count(cleaned_rankers)
        if n_placeholders >= max(2, len(cleaned_rankers) // 2):
            decision = "unclear"
            prefix = ("[No real SERP data — LLM had no specific knowledge "
                      "of this topic and returned placeholder filler "
                      "domains.] ")
            reasoning = prefix + reasoning

    return {
        "top_likely_rankers": cleaned_rankers,
        "content_patterns": [
            str(p) for p in analysis.get("content_patterns", []) if p
        ],
        "competitive_signal": {
            "saturation": saturation,
            "ymyl_flag": ymyl,
            "barrier": str(barrier),
        },
        "suggested_angles": [
            str(a) for a in analysis.get("suggested_angles", []) if a
        ],
        "decision": decision,
        "reasoning": reasoning,
    }


# ---------- cluster mode (v8.B) ----------


_CLUSTER_SYSTEM_PROMPT = """You are a SERP-analysis assistant for a personal domain portfolio.
The user is deciding whether to build a new site on a topic. Instead of
analyzing only the literal phrase, expand the topic into a CLUSTER of
3-5 related searches a real visitor interested in the topic would do,
then produce a cluster-level analysis that thinks across all of them.

CRITICAL: Output ONLY valid JSON, no prose before or after.

You are analyzing from your training data — explicitly NOT real-time
SERP data. Do NOT fabricate specific URLs (just domain names + content-
type categories). Do NOT fill rankers with placeholder domains
(example.com, test.net, sample.org, demo.edu, foo.com, mockup.co, etc.)
— if you don't know real domains, return an empty rankers list and set
`decision: unclear`.

Constrained vocabularies (use only these):
  type:       institutional | publisher-listicle | vendor-published |
              niche-vendor | community | tool | q-and-a | news |
              documentation | other
  intent:     informational | commercial | navigational | transactional
  saturation: low | medium | medium-high | high
  decision:   ship | mixed | skip | unclear

For each ranker, include a `frequency` field: the number of queries
in the cluster (out of N) where this domain likely appears in the top
10. A domain ranking on 5/5 queries is much stronger competition than
one ranking on 1/5.

YMYL handling: flag the cluster-level `ymyl_flag` true ONLY if the
MAJORITY of the cluster queries are YMYL (medical/legal/financial/
safety-critical). Individual YMYL queries within an otherwise non-
YMYL cluster are surfaced in the `per_query_summary` instead.

Decision is cluster-level — base it on the merged signal, not any
single query. The whole point of cluster mode is to catch cases
where the literal topic looks one way but the territory looks another.
"""

_CLUSTER_USER_PROMPT_TEMPLATE = """Topic: {topic}

Step 1: expand the topic into 3-5 related search queries a real
visitor would actually type. Include the literal topic as one of them.

Step 2: for each query, mentally consider its likely top-10 SERP.

Step 3: emit cluster-level analysis in this JSON shape:

{{
  "cluster_queries": ["literal topic", "related query 1", ...],
  "top_likely_rankers": [
    {{"domain": "...", "type": "...", "intent": "...", "frequency": 5}}
  ],
  "content_patterns": ["...", "..."],
  "competitive_signal": {{
    "saturation": "...",
    "ymyl_flag": true,
    "barrier": "<one-sentence>"
  }},
  "suggested_angles": ["...", "..."],
  "per_query_summary": [
    {{"query": "...", "decision_hint": "ship|mixed|skip|unclear", "ymyl": true}}
  ],
  "decision": "...",
  "reasoning": "<two-sentence cluster-level justification>"
}}

8-12 entries in top_likely_rankers (merged across the cluster),
3-5 content_patterns, 3-5 suggested_angles, one per_query_summary
entry per cluster query."""


def build_cluster_prompt(topic: str) -> tuple[str, str]:
    """Return (system, user) for the cluster-mode OpenAI call."""
    return _CLUSTER_SYSTEM_PROMPT, _CLUSTER_USER_PROMPT_TEMPLATE.format(topic=topic)


def parse_cluster_response(raw: str) -> dict:
    """Parse + validate the cluster-mode LLM response. Returns a dict
    that fits the existing v8.A `analysis` shape with added cluster
    fields (`cluster_queries`, per-ranker `frequency`, `per_query_summary`).
    """
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)

    try:
        analysis = json.loads(raw)
    except ValueError as e:
        raise ResearchError(f"model returned malformed JSON: {e}") from e
    if not isinstance(analysis, dict):
        raise ResearchError("model returned non-object JSON")

    cluster_queries = analysis.get("cluster_queries")
    if not isinstance(cluster_queries, list) or not cluster_queries:
        raise ResearchError("cluster response missing or empty `cluster_queries`")
    cluster_queries = [str(q).strip() for q in cluster_queries if q]
    n_queries = len(cluster_queries)

    rankers = analysis.get("top_likely_rankers")
    if not isinstance(rankers, list):
        raise ResearchError("cluster response missing `top_likely_rankers`")

    cleaned_rankers = []
    for entry in rankers:
        if not isinstance(entry, dict):
            continue
        domain = entry.get("domain", "").strip().lower()
        if not domain:
            continue
        type_ = entry.get("type", "other")
        if type_ not in _ALLOWED_TYPES:
            type_ = "other"
        intent = entry.get("intent", "informational")
        if intent not in _ALLOWED_INTENTS:
            intent = "informational"
        # Coerce frequency to int in [1, n_queries].
        freq_raw = entry.get("frequency", 1)
        try:
            freq = int(freq_raw)
        except (TypeError, ValueError):
            freq = 1
        freq = max(1, min(freq, n_queries))
        cleaned_rankers.append({
            "domain": domain, "type": type_, "intent": intent,
            "frequency": freq,
        })

    competitive = analysis.get("competitive_signal") or {}
    saturation = competitive.get("saturation", "medium")
    if saturation not in _ALLOWED_SATURATIONS:
        saturation = "medium"
    ymyl = bool(competitive.get("ymyl_flag", False))
    barrier = str(competitive.get("barrier", ""))

    # per_query_summary — one entry per cluster query, with decision_hint + ymyl flag
    per_query = []
    for entry in analysis.get("per_query_summary", []):
        if not isinstance(entry, dict):
            continue
        query = str(entry.get("query", "")).strip()
        if not query:
            continue
        hint = entry.get("decision_hint", "unclear")
        if hint not in _ALLOWED_DECISIONS:
            hint = "unclear"
        per_query.append({
            "query": query,
            "decision_hint": hint,
            "ymyl": bool(entry.get("ymyl", False)),
        })

    decision = analysis.get("decision", "unclear")
    if decision not in _ALLOWED_DECISIONS:
        decision = "unclear"
    reasoning = str(analysis.get("reasoning", ""))

    # Same fabrication-detector as strict mode.
    if not cleaned_rankers:
        decision = "unclear"
        reasoning = ("[No real SERP data — LLM had no knowledge of this "
                     "cluster and returned an empty rankers list.] " + reasoning)
    else:
        n_placeholders = _placeholder_count(cleaned_rankers)
        if n_placeholders >= max(2, len(cleaned_rankers) // 2):
            decision = "unclear"
            reasoning = ("[No real SERP data — LLM returned placeholder "
                         "filler domains across the cluster.] " + reasoning)

    return {
        "cluster_queries": cluster_queries,
        "top_likely_rankers": cleaned_rankers,
        "content_patterns": [
            str(p) for p in analysis.get("content_patterns", []) if p
        ],
        "competitive_signal": {
            "saturation": saturation,
            "ymyl_flag": ymyl,
            "barrier": barrier,
        },
        "suggested_angles": [
            str(a) for a in analysis.get("suggested_angles", []) if a
        ],
        "per_query_summary": per_query,
        "decision": decision,
        "reasoning": reasoning,
    }


# ---------- orchestrator ----------


def research(topic: str, *, no_cache: bool = False, strict: bool = False,
             ttl_days: int = CACHE_TTL_DAYS) -> dict:
    """Run the full research pipeline. Returns a payload dict matching
    the cache schema. Hits cache by default (within TTL); always writes
    cache on a fresh fetch.

    `strict=True` runs v8.A literal-topic mode. Default (False) runs
    v8.B cluster mode — LLM expands topic into a related-query cluster
    and produces a merged frequency-tagged analysis.

    Raises ResearchError on any unrecoverable failure.
    """
    if not topic or not topic.strip():
        raise ResearchError("topic cannot be empty")
    topic = topic.strip()
    mode = "strict" if strict else "cluster"

    if not no_cache:
        hit = load_cached(topic, mode=mode, ttl_days=ttl_days)
        if hit is not None:
            hit.payload["from_cache"] = True
            hit.payload["cache_age_days"] = round(hit.age_days, 1)
            return hit.payload

    api_key = _openai_api_key()
    if strict:
        system, user = build_prompt(topic)
        raw = call_openai(system, user, api_key=api_key)
        analysis = parse_response(raw)
    else:
        system, user = build_cluster_prompt(topic)
        raw = call_openai(system, user, api_key=api_key)
        analysis = parse_cluster_response(raw)

    payload = {
        "topic": topic,
        "topic_normalized": normalize_topic(topic),
        "topic_hash": topic_hash(topic, mode),
        "mode": mode,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "knowledge_caveat": "AI synthesis from training data, not real-time SERP",
        "analysis": analysis,
        "from_cache": False,
    }
    save_cache(topic, payload, mode=mode)
    return payload
