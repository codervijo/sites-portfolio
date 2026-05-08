"""v4.B decide-from-shortlist module.

Houses the six decision-aid steps invoked by menu option 7:
  1. Brand-collision check (gpt-5-mini)
  2. USPTO TESS URL builders (manual click-through)
  3. Brand-extensibility (gpt-5-mini)
  4. 5-year cost projection (computed)
  5. Phone test (CLI-side; interactive)
  6. Memory test (CLI-side; interactive)

CLI orchestration lives in `cli._menu_decide`. This module is hermetic and
testable (no console output; all I/O is HTTP).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

import requests

from .data import ROOT
from .suggest import OPENAI_MODEL, OPENAI_RESPONSES_URL, OPENAI_TIMEOUT, _parse_openai_text

ASK_CACHE_DIR = ROOT / "data" / "cache" / "suggest" / "ask"


@dataclass
class CollisionResult:
    """Brand-collision verdict for one finalist."""
    name: str
    backend: str          # "ai" | "skipped"
    ai_verdict: str | None = None
    error: str | None = None


# ---------- Brand-collision check (gpt-5-mini) ----------
# Brave Search was previously the primary backend with AI as fallback. As of
# 2026-05-08 Brave's free tier is gone, so we go AI-only. The AI catches
# famous-brand collisions reliably; for niche brands, manual due-diligence
# (Step 2 USPTO + your own Google) remains the catch-all.


_AI_COLLISION_PROMPT = """\
Is "{name}" the name of any well-known company, product, brand, app, or
website? Answer in one short sentence:

- If YES, name what it is (e.g. "Yes — Stripe is a payments company").
- If NO, say "No notable brand match."
- If UNCERTAIN (small/regional/niche), say so plainly.

Be concise. The user is doing brand-collision due-diligence on a candidate
domain name — they want to know if registering this name would compete
with an existing recognized brand.

Name: {name}
"""


def assess_brand_collision_via_ai(name: str, api_key: str) -> str:
    """Single gpt-5-mini call asking whether `name` matches a known brand.
    Returns the model's one-sentence verdict. Raises on HTTP error.
    """
    prompt = _AI_COLLISION_PROMPT.format(name=name)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "input": prompt}
    r = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=OPENAI_TIMEOUT)
    r.raise_for_status()
    return _parse_openai_text(r.json()).strip() or "No verdict returned."


def check_brand_collision(name: str, openai_key: str) -> CollisionResult:
    """Step 1. AI-only brand-collision check via gpt-5-mini. Always returns
    a `CollisionResult` (never raises) so the decide flow keeps moving.
    Returns backend="skipped" if no API key or the call fails.
    """
    if not openai_key:
        return CollisionResult(name=name, backend="skipped",
                               error="no OPENAI_API_KEY")
    try:
        verdict = assess_brand_collision_via_ai(name, openai_key)
        return CollisionResult(name=name, backend="ai", ai_verdict=verdict)
    except Exception as e:
        return CollisionResult(name=name, backend="skipped",
                               error=f"AI call failed: {type(e).__name__}: {e}")


# ---------- Step 2: USPTO TESS URL builder ----------


def uspto_tess_url(name: str) -> str:
    """Build a search URL for the USPTO TESS quick-search interface.
    Manual click-through is the only realistic path — no clean free
    live-search API exists for trademark names.
    """
    return f"https://tmsearch.uspto.gov/search?queryString={quote_plus(name)}"


# ---------- Step 3: Brand-extensibility (AI) ----------


_EXTENSIBILITY_PROMPT = """\
Topic: {topic}
{anchor_block}
Candidate domain name: {name}

Question: Would this name survive a pivot from the topic above to a
broader scope (e.g. adjacent vertical, expanded use case, more general
audience) — or is it locked to the original framing?

Answer in one short sentence. Be concrete: name what the candidate
generalizes well to (or what it doesn't). Do not hedge.
"""


def assess_brand_extensibility(name: str, topic: str,
                               vocab_terms: list[str] | None,
                               api_key: str) -> str:
    """Step 3. Single gpt-5-mini call returning a 1-sentence pivot
    assessment for `name` in the context of `topic` + vocab anchors."""
    if vocab_terms:
        anchor_block = f"\nConcept anchors: {', '.join(vocab_terms)}\n"
    else:
        anchor_block = ""
    prompt = _EXTENSIBILITY_PROMPT.format(
        topic=topic.strip(), anchor_block=anchor_block, name=name,
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "input": prompt}
    r = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=OPENAI_TIMEOUT)
    r.raise_for_status()
    return _parse_openai_text(r.json()).strip() or "No assessment returned."


def assess_extensibility_safe(name: str, topic: str,
                              vocab_terms: list[str] | None,
                              api_key: str) -> str:
    """Wrapper that swallows API failures so the decide flow keeps moving."""
    if not api_key:
        return "(no OPENAI_API_KEY — extensibility assessment skipped)"
    try:
        return assess_brand_extensibility(name, topic, vocab_terms, api_key)
    except Exception as e:
        return f"(extensibility check failed: {type(e).__name__})"


# ---------- Step 4: 5-year cost projection ----------


def compute_five_year_cost(reg_price: float | None,
                           renewal_price: float | None) -> float | None:
    """Return reg + 4×renewal for a 5-year hold. Falls back to 4×reg if
    renewal is missing (some TLDs don't surface renewal in the cache).
    Returns None when neither is known."""
    if reg_price is None and renewal_price is None:
        return None
    reg = reg_price if reg_price is not None else 0.0
    renew = renewal_price if renewal_price is not None else (reg_price or 0.0)
    return reg + 4 * renew


# ---------- Step 5/6: phone & memory test parsers ----------


# ---------- v4.C Ask AI about a name ----------


_ASK_DEFAULT_QUESTION = (
    "Why was this name chosen and how does it relate to the topic?"
)

_ASK_AI_PROMPT = """\
The user is evaluating a candidate domain name and wants a short
explanation. Answer in 1-3 sentences. Be concrete and specific to the
candidate; don't restate the topic verbatim.

Topic:
{topic}
{anchor_block}
Candidate name: {name}

User question: {question}
"""


def _topic_hash_for_ask(topic: str) -> str:
    return hashlib.sha256(topic.strip().lower().encode()).hexdigest()[:16]


def _question_hash(question: str) -> str:
    return hashlib.sha256(question.strip().lower().encode()).hexdigest()[:12]


def _ask_cache_path(topic: str) -> Path:
    return ASK_CACHE_DIR / f"{_topic_hash_for_ask(topic)}.json"


def _load_ask_cache(topic: str) -> dict[str, str]:
    p = _ask_cache_path(topic)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_ask_cache(topic: str, payload: dict[str, str]) -> None:
    p = _ask_cache_path(topic)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2))


def _ask_cache_key(name: str, question: str) -> str:
    return f"{name.lower()}|{_question_hash(question)}"


def ask_ai_about_name(
    name: str,
    topic: str,
    vocab_terms: list[str] | None,
    question: str,
    api_key: str,
    no_cache: bool = False,
) -> str:
    """v4.C: gpt-5-mini call answering `question` about candidate `name`
    in the context of `topic` + vocab anchors. Cached on disk by
    (topic-hash, name, question-hash) so repeat asks are free across
    sessions. Returns the model's 1-3 sentence answer; raises on HTTP
    error so callers can fall back gracefully.
    """
    q = (question or _ASK_DEFAULT_QUESTION).strip()
    cache_key = _ask_cache_key(name, q)
    if not no_cache:
        cached = _load_ask_cache(topic).get(cache_key)
        if cached:
            return cached
    if vocab_terms:
        anchor_block = f"\nConcept anchors: {', '.join(vocab_terms)}\n"
    else:
        anchor_block = ""
    prompt = _ASK_AI_PROMPT.format(
        topic=topic.strip(), anchor_block=anchor_block, name=name, question=q,
    )
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "input": prompt}
    r = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=OPENAI_TIMEOUT)
    r.raise_for_status()
    answer = _parse_openai_text(r.json()).strip() or "(no answer returned)"
    if not no_cache:
        cache = _load_ask_cache(topic)
        cache[cache_key] = answer
        _save_ask_cache(topic, cache)
    return answer


def parse_test_response(s: str, finalist_names: list[str]) -> tuple[list[str], list[str]]:
    """Parse a comma-separated list of names the user reports as flagged.

    Returns (matched_finalist_names, unrecognized_input_tokens). Empty input
    means "no concerns" — both lists empty. Names match case-insensitively
    against `finalist_names`; tokens that don't match are returned for the
    caller to surface as warnings (typo / not-a-finalist).
    """
    s = s.strip()
    if not s:
        return [], []
    finalists_lower = {n.lower(): n for n in finalist_names}
    matched: list[str] = []
    unrecognized: list[str] = []
    seen: set[str] = set()
    for piece in s.replace("\n", ",").split(","):
        token = piece.strip().lower()
        if not token:
            continue
        # Strip optional .tld suffix
        token = token.split(".", 1)[0]
        if token in seen:
            continue
        seen.add(token)
        if token in finalists_lower:
            matched.append(finalists_lower[token])
        else:
            unrecognized.append(piece.strip())
    return matched, unrecognized
