"""Domain-suggest pipeline (v2.A → v3.D).

v2.A: Multi-strategy LLM brainstorm → SEO-weighted scoring → already-own intersect.
v3.D: Vocabulary-anchored brainstorm + registrar grid + cheap-first scoring +
      Porkbun auto-register on confirmation.

Hands off to availability.py for the per-name avail+price check and
domain registration.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

from .data import ROOT, load_domains

PORTFOLIO_ENV = ROOT / "portfolio.env"
STRATEGIES_JSON = ROOT / "data" / "strategies.json"
CACHE_DIR = ROOT / "data" / "cache" / "suggest"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-5-mini"
OPENAI_TIMEOUT = 90.0
DEFAULT_CANDIDATES_PER_STRATEGY = 12

# v3.D default ladder. .com .app .dev are the credible primaries; .xyz / .site / .co
# are the cheap-validation lane; .ai / .io kept for power-user `--tlds` overrides.
DEFAULT_TLDS = (".com", ".app", ".dev", ".xyz", ".site", ".co")

# Full ladder used when --tlds isn't given AND the user wants the wider scan.
# Validation-mode availability checks skip TLDs in BROKEN_RDAP_TLDS — they still
# render in the grid as `?` cells (manual verify at registrar).
FULL_LADDER = (".com", ".app", ".dev", ".co", ".ai", ".io", ".xyz", ".shop", ".life", ".info", ".pro")

# Historically: TLDs whose RDAP endpoints (rdap.radix.host) had a broken SSL
# chain. As of 2026-05-07 we route those calls with `verify=False` (see
# availability.RDAP_HOSTS_INSECURE), so checks succeed and these TLDs are no
# longer special-cased. The constant is kept empty to preserve backward-compat
# for any external callers; remove on the next major refactor.
BROKEN_RDAP_TLDS: frozenset[str] = frozenset()

# v3.D TLD tier reweighting based on validation-mode track record:
# .app and .dev are stable, low-renewal, modern — alongside .com.
# .ai / .io demoted (price-capped out for validation runs anyway).
# .xyz promoted to mid-tier (cheap + credible for MVP).
TLD_TIER = {
    ".com": 10,
    ".app": 9,
    ".dev": 9,
    ".ai": 7,
    ".io": 6,
    ".co": 7,
    ".xyz": 6,
    ".site": 5,
    ".online": 4,
    ".tech": 5,
    ".shop": 4,
    ".life": 4,
    ".info": 4,
    ".pro": 4,
    ".today": 3,
    ".live": 3,
    ".church": 4,
    ".tools": 4,
    ".org": 5,
    ".net": 5,
    ".us": 5,
    ".in": 4,
}

# v3.D defense bonuses. Applied in score_name when com_status is provided.
SCORE_BONUS_COM_AVAILABLE = 5     # .com is registerable → slice defendable
SCORE_PENALTY_COM_LIVE = -20      # .com is a live competing site → brand poisoned
SCORE_BONUS_PER_VOCAB_ANCHOR = 10 # +10 per vocab term that appears in the name
                                  # (concept density is the primary validity
                                  # signal; bumped from +5 in 2026-05-08 when
                                  # TLD-tier weight dropped from ×5 to ×1)

# Porkbun /domain/create endpoint (v3.D auto-register).
PORKBUN_DOMAIN_CREATE_URL = "https://api.porkbun.com/api/json/v3/domain/create"
PORKBUN_REGISTER_TIMEOUT = 60.0
PORKBUN_CHECKOUT_BASE = "https://porkbun.com/checkout/search?q="


PORTFOLIO_ENV_TEMPLATE = """\
# portfolio.env — secrets for portfolio CLI features.
# Loaded by python-dotenv at runtime. Do not commit this file (it's in .gitignore).

# Required for `portfolio domain suggest` brainstorm (v2.A)
OPENAI_API_KEY=

# Optional for `portfolio domain suggest` availability+price (v2.B).
# When unset, the CLI falls back to RDAP (free, no keys, availability only — no price).
PORKBUN_API_KEY=
PORKBUN_SECRET_API_KEY=

# Required for `portfolio deploy <domain>` Cloudflare Pages step (v3.C).
# CF_API_TOKEN: create at https://dash.cloudflare.com/profile/api-tokens
#   with permission `Account / Cloudflare Pages: Edit` (scoped to your account).
# CF_ACCOUNT_ID: Cloudflare dashboard → right-side panel of any zone overview,
#   or `wrangler whoami` after `wrangler login`.
# `gh` CLI must also be authenticated (`gh auth login`).
CF_API_TOKEN=
CF_ACCOUNT_ID=
"""


@dataclass
class Strategy:
    name: str
    label: str
    description: str
    require_anchors: bool = True   # v3.D: must brainstormed names reference vocab terms?


@dataclass
class Candidate:
    """A name (without TLD) generated for one strategy."""
    name: str
    strategy: str
    score_base: int = 0
    score_notes: list[str] = field(default_factory=list)


@dataclass
class ScoredOption:
    """A name + TLD pair with availability + price + score, ready to present."""
    name: str
    tld: str
    domain: str
    available: bool | None
    price: float | None
    score: int
    strategy: str
    error: str | None = None  # set when availability check failed (vs None+no-err = RDAP gap)
    renewal: float | None = None  # v3.D: optional renewal price (Porkbun pricing dict)


@dataclass
class GridRow:
    """v3.D registrar-grid row: one candidate name with its per-TLD cells.

    `cells[tld]` is a CellState describing avail/price/classification. Pick is the
    recommended TLD for this row (or None if all options are skip-worthy). Why is
    a one-line rationale to render in the table.

    `anchors_matched`: vocab terms (from extract_vocab) that appear as substrings
    in `name`. Used both as a row differentiator column and as a tiebreaker
    in ranking (more anchors → ranks higher among same-pick rows).
    """
    name: str
    strategy: str
    cells: dict[str, "CellState"] = field(default_factory=dict)
    pick_tld: str | None = None
    pick_label: str = ""        # e.g. ".app +bundle" or "skip"
    why: str = ""
    score: int = 0
    anchors_matched: list[str] = field(default_factory=list)


@dataclass
class CellState:
    """One cell in the registrar grid (one (name, tld) pair).

    `available`:
      - True   → confirmed available
      - False  → confirmed taken
      - None   → unknown (RDAP gap or broken endpoint)

    `price` is first-year registration in USD (None if pricing missing or filtered).
    `over_max` is True when price > --max-price (cell shown but unselectable).
    `com_class` is set ONLY for the .com cell of a row, when the .com is taken
    and we ran a classification check (live-site / parked / for-sale / forwarder).
    `renewal` is the Porkbun renewal price (for --show-renewal sub-row).
    """
    domain: str
    available: bool | None
    price: float | None
    renewal: float | None = None
    error: str | None = None
    over_max: bool = False
    com_class: str | None = None     # only set for the .com cell when taken


def ensure_portfolio_env() -> Path:
    """Create portfolio.env from template if missing. Returns the path."""
    if not PORTFOLIO_ENV.exists():
        PORTFOLIO_ENV.write_text(PORTFOLIO_ENV_TEMPLATE)
    return PORTFOLIO_ENV


def load_env() -> dict[str, str]:
    """Load portfolio.env via python-dotenv. Returns merged env (file + os.environ)."""
    from dotenv import dotenv_values

    ensure_portfolio_env()
    file_env = dotenv_values(PORTFOLIO_ENV)
    merged = {k: v for k, v in os.environ.items()}
    for k, v in file_env.items():
        if v and not merged.get(k):
            merged[k] = v
    return merged


def load_strategies(path: Path | None = None) -> list[Strategy]:
    """Load the strategies config. Tolerates schema_version 1 (no `require_anchors`
    field — defaults to True) and schema_version 2 (with `require_anchors`)."""
    p = path or STRATEGIES_JSON
    data = json.loads(p.read_text())
    out: list[Strategy] = []
    for s in data.get("strategies", []):
        s = dict(s)
        # Drop fields the dataclass doesn't know about; tolerate missing require_anchors.
        kwargs = {
            "name": s["name"],
            "label": s["label"],
            "description": s["description"],
        }
        if "require_anchors" in s:
            kwargs["require_anchors"] = bool(s["require_anchors"])
        out.append(Strategy(**kwargs))
    return out


def filter_default_strategies(strategies: list[Strategy], with_abstract: bool = False) -> list[Strategy]:
    """v3.D: by default the abstract-brandable strategy is dropped from the run
    (gets re-added with --with-abstract). All other strategies always run."""
    if with_abstract:
        return list(strategies)
    return [s for s in strategies if s.name != "abstract-brandable"]


def _topic_hash(topic: str, strategy_names: list[str]) -> str:
    h = hashlib.sha256()
    h.update(topic.strip().lower().encode())
    h.update(b"|")
    h.update(",".join(sorted(strategy_names)).encode())
    return h.hexdigest()[:16]


def _cache_path(topic: str, strategies: list[Strategy]) -> Path:
    return CACHE_DIR / f"{_topic_hash(topic, [s.name for s in strategies])}.json"


def cache_get(topic: str, strategies: list[Strategy]) -> dict | None:
    p = _cache_path(topic, strategies)
    if not p.exists():
        return None
    try:
        payload = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if (time.time() - payload.get("cached_at", 0)) > CACHE_TTL_SECONDS:
        return None
    return payload


def cache_set(
    topic: str,
    strategies: list[Strategy],
    candidates_by_strategy: dict[str, list[Candidate]],
    vocab_terms: list[str] | None = None,
) -> Path:
    """v3.D: payload extends with `vocab_terms` so the vocabulary extraction is
    cached alongside the brainstorm under the same topic-hash key."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(topic, strategies)
    payload = {
        "cached_at": time.time(),
        "topic": topic,
        "strategy_names": [s.name for s in strategies],
        "candidates_by_strategy": {k: [asdict(c) for c in v] for k, v in candidates_by_strategy.items()},
    }
    if vocab_terms is not None:
        payload["vocab_terms"] = list(vocab_terms)
    p.write_text(json.dumps(payload, indent=2))
    return p


def already_owned_matches(topic: str) -> list[str]:
    """Find owned domains whose name (without TLD) overlaps the topic keywords."""
    topic_words = {w.strip() for w in re.split(r"\W+", topic.lower()) if len(w.strip()) >= 3}
    if not topic_words:
        return []
    matches: list[str] = []
    for d in load_domains():
        base = d.name.split(".")[0].lower()
        for w in topic_words:
            if w in base:
                matches.append(d.name)
                break
    return sorted(set(matches))


# v3.D 2026-05-08: TLD tier weight reduced from ×5 (max 50, dominated score) to
# ×1 (max 10, light nudge). Domain validity (anchor density, name shape) now
# drives ranking; TLD prestige is informational, not the primary signal.
SCORE_TLD_TIER_WEIGHT = 1


def score_name(
    name: str,
    topic: str,
    tld: str,
    com_status: str | None = None,
    vocab_terms: list[str] | None = None,
) -> tuple[int, list[str]]:
    """SEO-weighted score for a name+TLD pair given a topic. Returns (score, notes).

    v3.D: optional `com_status` shifts the score based on slice-defense status of
    the .com — `available` adds a small bonus (defendable), `live-site` poisons
    the row (the .com is a competing live brand). All other classes (parked,
    for-sale, forwarder, taken) are neutral.

    v3.D (2026-05-08): when `vocab_terms` is provided, each term that appears
    as a substring of `name` adds `SCORE_BONUS_PER_VOCAB_ANCHOR`. Acts as a row
    tiebreaker so multi-anchor names rank above single-anchor names when their
    .com (or other Pick-TLD) status is otherwise identical.
    """
    notes: list[str] = []
    s = 0

    tier = TLD_TIER.get(tld.lower(), 2)
    s += tier * SCORE_TLD_TIER_WEIGHT
    notes.append(f"tld:{tld}({tier})")

    base = name.lower()
    L = len(base)
    if L <= 6:
        s += 10
        notes.append("short")
    elif L <= 9:
        s += 6
    elif L <= 12:
        s += 2
    elif L > 16:
        s -= 6
        notes.append("long")

    if "-" in base:
        s -= 8
        notes.append("hyphen")
    if any(c.isdigit() for c in base):
        s -= 5
        notes.append("digit")

    topic_words = {w.strip() for w in re.split(r"\W+", topic.lower()) if len(w.strip()) >= 3}
    if any(w in base for w in topic_words):
        s += 12
        notes.append("keyword")

    if base.isalpha() and 5 <= L <= 10 and not any(w in base for w in topic_words):
        s += 4
        notes.append("brandable")

    # v3.D defense bonuses based on .com slice status.
    if com_status == "available":
        s += SCORE_BONUS_COM_AVAILABLE
        notes.append("com-defendable")
    elif com_status == "live-site":
        s += SCORE_PENALTY_COM_LIVE
        notes.append("com-poisoned")

    # v3.D vocab-anchor bonus: +5 per vocab term found in name. Differentiates
    # multi-anchor names from single-anchor ones when other fields are equal.
    if vocab_terms:
        n_anchors = sum(1 for v in vocab_terms if v and v in base)
        if n_anchors:
            s += SCORE_BONUS_PER_VOCAB_ANCHOR * n_anchors
            notes.append(f"anchors:{n_anchors}")

    return s, notes


_BRAINSTORM_PROMPT = """\
Generate {n} product domain name candidates for this idea:

{idea}
{anchor_block}
Strategy:
{strategy_label} — {strategy_description}

Avoid these previously-suggested names:
{history}

Strict rules:
- under 12 characters per name (excluding TLD)
- no hyphens, no digits
- pronounceable / brandable / easy to say
- return ONLY names, lowercase, one per line, NO TLDs, NO commentary, NO numbering
"""

# v3.D: vocab-anchor sub-prompts. Two variants — must-reference vs inspiration.
_ANCHOR_BLOCK_REQUIRED = """
Concept anchors — each name must reference at least one (literal substring,
a close root, or a clear morphological riff):
{vocab_terms}
"""
_ANCHOR_BLOCK_INSPIRATION = """
Concept anchors (use as thematic inspiration only — names do NOT need to
literally reference these):
{vocab_terms}
"""


def _brainstorm_prompt(
    idea: str,
    strategy: Strategy,
    history: list[str],
    n: int,
    vocab_terms: list[str] | None = None,
) -> str:
    """Build the brainstorm prompt. v3.D: when vocab_terms is non-empty, inject
    a must-reference or inspiration anchor block based on `strategy.require_anchors`.
    """
    if vocab_terms:
        terms_str = ", ".join(vocab_terms)
        if strategy.require_anchors:
            anchor_block = _ANCHOR_BLOCK_REQUIRED.format(vocab_terms=terms_str)
        else:
            anchor_block = _ANCHOR_BLOCK_INSPIRATION.format(vocab_terms=terms_str)
    else:
        anchor_block = ""

    return _BRAINSTORM_PROMPT.format(
        n=n,
        idea=idea.strip(),
        anchor_block=anchor_block,
        strategy_label=strategy.label,
        strategy_description=strategy.description,
        history=", ".join(sorted(set(history))) if history else "(none yet)",
    )


# v3.D: vocabulary extraction prompt. One-shot LLM call before the brainstorm.
_VOCAB_EXTRACTION_PROMPT = """\
Extract 12-15 concrete, domain-specific terms for the topic below. These will
anchor a domain-name brainstorm — surface words a practitioner in this field
would say in a daily standup, not words a marketer would put on a homepage.

Topic:
{topic}

Rules:
- Practitioner register, not marketing register. Prefer concrete nouns and
  workflow verbs (objects, tools, materials, actions, roles, artifacts) over
  abstractions like `solution, platform, sync, flow, smart, unified, intelligent`.
- Specific over generic. Prefer `scrubs, gown, badge, shift` over `apparel,
  schedule, identity, garment`.
- Single words only. No phrases, no hyphens. Each term <= 9 characters.
- Lowercase, alphabetic (a-z) only.
- Avoid surface echoes of the topic. Decompose the idea into its components
  and adjacent vocabulary, don't just lift words from the prompt.
- 12-15 terms total.

Worked example - for topic "an Uber for dog walking", good terms:
  leash, paw, walk, fetch, kennel, sniff, treat, bark, route, drop, pickup
Bad terms (do not produce these): pet, service, app, mobile, schedule, smart

Return ONLY the terms, one per line, no numbering, no commentary.
"""


def _vocab_prompt(topic: str) -> str:
    return _VOCAB_EXTRACTION_PROMPT.format(topic=topic.strip())


def _extract_vocab_terms(text: str) -> list[str]:
    """Parse LLM vocab-extraction output. Same shape rules as _extract_names but
    capped at <= 9 characters per term (instead of <= 14)."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip().strip("-•*").strip()
        if not line:
            continue
        line = re.sub(r"^\d+[.)]\s*", "", line)
        line = line.strip("`'\"").strip().lower()
        if not line:
            continue
        if not re.match(r"^[a-z]+$", line):  # alphabetic only, no digits in vocab
            continue
        if len(line) > 9:
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def extract_vocab(topic: str, api_key: str) -> list[str]:
    """v3.D: one-shot vocabulary-extraction LLM call. Returns 12-15 practitioner
    terms (no guarantee on count; caller may cache and re-use). Raises on HTTP
    failure so callers can fall back to no-anchors brainstorm.
    """
    prompt = _vocab_prompt(topic)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "input": prompt}
    r = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=OPENAI_TIMEOUT)
    r.raise_for_status()
    text = _parse_openai_text(r.json())
    return _extract_vocab_terms(text)


def _parse_openai_text(payload: dict) -> str:
    """Pull the model's text reply out of /v1/responses payload.

    Reasoning models (gpt-5-mini, o-series) return `output` as a list where
    `output[0]` is a `{"type": "reasoning"}` block with no text, and the actual
    assistant message is later in the list. Naive `output[0].content[0].text`
    misses it entirely. We walk the list and pick the first `type == "message"`
    item with an `output_text` content block.
    """
    if isinstance(payload.get("output_text"), str) and payload["output_text"]:
        return payload["output_text"]
    output = payload.get("output", [])
    if not isinstance(output, list):
        return ""
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("output_text", None):
                text = block.get("text") or block.get("output_text") or ""
                if text:
                    return text
    return ""


def _extract_names(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().strip("-•*").strip()
        if not line:
            continue
        line = re.sub(r"^\d+[.)]\s*", "", line)
        line = line.strip("`'\"").strip().lower()
        if not line:
            continue
        if not re.match(r"^[a-z][a-z0-9]*$", line):
            continue
        if len(line) > 14:
            continue
        out.append(line)
    return out


def brainstorm(
    idea: str,
    strategy: Strategy,
    history: list[str],
    api_key: str,
    n: int = DEFAULT_CANDIDATES_PER_STRATEGY,
    vocab_terms: list[str] | None = None,
) -> list[Candidate]:
    """Single brainstorm call. Returns Candidate objects (no scoring yet — that's per TLD).

    v3.D: when `vocab_terms` is non-empty, the prompt receives a must-reference
    (or inspiration-only) anchor block depending on `strategy.require_anchors`.
    """
    prompt = _brainstorm_prompt(idea, strategy, history, n, vocab_terms=vocab_terms)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "input": prompt}
    r = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=OPENAI_TIMEOUT)
    r.raise_for_status()
    text = _parse_openai_text(r.json())
    names = _extract_names(text)
    seen = set(history)
    out: list[Candidate] = []
    for n_ in names:
        if n_ in seen:
            continue
        seen.add(n_)
        out.append(Candidate(name=n_, strategy=strategy.name))
    return out


def _normalize_avail_check(avail_check):
    """Adapter so render_options accepts both the new 3-tuple
    `(avail, price, error)` callables (post-2026-05-06) and any old
    2-tuple `(avail, price)` callables that may exist in tests."""
    def _wrapped(domain: str):
        result = avail_check(domain)
        if not isinstance(result, tuple):
            return None, None, None
        if len(result) == 3:
            return result
        if len(result) == 2:
            return result[0], result[1], None
        return None, None, None
    return _wrapped


def render_options(candidates: list[Candidate], topic: str, tlds: list[str], avail_check) -> list[ScoredOption]:
    """For each candidate, scan TLDs in order; stop at first **confirmed available** (True);
    otherwise pick the best result by priority (True > unknown-no-err > unknown-error > False),
    score-tiebreak. Surfaces both unknowns AND errors to the caller so checks aren't silently
    swallowed.
    """
    check = _normalize_avail_check(avail_check)
    out: list[ScoredOption] = []
    for c in candidates:
        attempts: list[tuple] = []  # (avail, price, error, score, tld, domain)
        for tld in tlds:
            domain = f"{c.name}{tld}"
            available, price, error = check(domain)
            score, _notes = score_name(c.name, topic, tld)
            attempts.append((available, price, error, score, tld, domain))
            if available is True:
                break

        def _rank_priority(a):
            avail, _, err, _, _, _ = a
            if avail is True:
                return 0
            if avail is None and err is None:
                return 1   # genuine RDAP gap (worth showing)
            if avail is None and err is not None:
                return 2   # call failed (worth showing distinctly)
            return 3       # confirmed taken

        attempts.sort(key=lambda a: (_rank_priority(a), -a[3]))
        best = attempts[0]
        out.append(ScoredOption(
            name=c.name,
            tld=best[4],
            domain=best[5],
            available=best[0],
            price=best[1],
            score=best[3],
            strategy=c.strategy,
            error=best[2],
        ))

    def _final_priority(o):
        if o.available is True:
            return 0
        if o.available is None and o.error is None:
            return 1
        if o.available is None and o.error is not None:
            return 2
        return 3

    out.sort(key=lambda o: (_final_priority(o), -o.score))
    return out


def filter_by_max_price(options: list[ScoredOption], max_price: float | None) -> list[ScoredOption]:
    if max_price is None:
        return options
    return [o for o in options if (o.price is None or o.price <= max_price)]


# ---------- v3.D registrar grid ----------


def _is_broken_rdap(tld: str) -> bool:
    return tld.lower() in BROKEN_RDAP_TLDS


def _classify_com(domain: str, classifier_fn=None) -> str | None:
    """Look up the .com's check.py classification (live-site / parked / for-sale /
    forwarder / dead). Returns None if no snapshot covers this domain.

    `classifier_fn` is injected for testing; default reads from data/checks/.
    """
    if classifier_fn is not None:
        return classifier_fn(domain)
    # Read from latest check snapshot if available.
    try:
        from .check import best_per_domain, latest_snapshot, load_snapshot
        latest = latest_snapshot()
        if not latest:
            return None
        snap = load_snapshot(latest)
        best = best_per_domain(snap)
        rec = best.get(domain)
        if rec:
            return rec.get("classification")
    except Exception:
        return None
    return None


def filter_pickable_rows(rows: list[GridRow]) -> list[GridRow]:
    """Drop rows that have nothing the user can buy. Keeps a row if any of its
    cells is `available=True` AND not over `--max-price`. Rows where every TLD
    is taken or every available TLD is over the price cap are eliminated — the
    user has no action on them.

    `?` cells (RDAP/DoH gaps) and `over_max` cells don't count as pickable.
    """
    out: list[GridRow] = []
    for r in rows:
        if any(cell.available is True and not cell.over_max for cell in r.cells.values()):
            out.append(r)
    return out


def _anchors_in(name: str, vocab_terms: list[str] | None) -> list[str]:
    """Return the subset of vocab_terms (in order, deduped) that appear as
    substrings of `name`. Empty list if vocab_terms is empty or None."""
    if not vocab_terms:
        return []
    base = name.lower()
    seen: set[str] = set()
    out: list[str] = []
    for v in vocab_terms:
        if v and v not in seen and v in base:
            seen.add(v)
            out.append(v)
    return out


def build_grid(
    candidates: list[Candidate],
    topic: str,
    columns: list[str],
    avail_check,
    max_price: float,
    pricing_dict: dict | None = None,
    com_classifier=None,
    full_ladder: list[str] | None = None,
    vocab_terms: list[str] | None = None,
) -> list[GridRow]:
    """Build a registrar-grid row per candidate name.

    For each name we run the availability check across all `columns`, plus
    `.com` (always, so we can compute the defense column even when .com isn't a
    selected column). For TLDs in BROKEN_RDAP_TLDS we skip the check and return
    `?` cells.

    Pick + Why are derived from the cell pattern:
      - if any premium TLD is available and .com is also available → "{tld} +bundle"
      - if .com is a live-site → "skip" (poisoned)
      - else first-available premium → "{tld}"
      - all `?` → "?, verify" with the highest-tier option

    `full_ladder` (optional) extends the per-row availability scan beyond the
    visible columns; it's used for the merged top-N picker so we can include
    options that aren't in the default column set.
    """
    check = _normalize_avail_check(avail_check)
    pricing_dict = pricing_dict or {}
    rows: list[GridRow] = []

    # Ensure .com is always probed even if not in `columns` (defense logic needs it).
    probed = list(dict.fromkeys(list(columns) + (list(full_ladder) if full_ladder else []) + [".com"]))

    for c in candidates:
        cells: dict[str, CellState] = {}
        com_class: str | None = None

        for tld in probed:
            domain = f"{c.name}{tld}"
            if _is_broken_rdap(tld):
                # Skip availability check; surface as `?` cell.
                price = _money_from_pricing(pricing_dict, tld)
                renewal = _money_from_pricing(pricing_dict, tld, key="renewal")
                cells[tld] = CellState(
                    domain=domain, available=None, price=price, renewal=renewal,
                    error=None, over_max=(price is not None and price > max_price),
                )
                continue

            available, price, error = check(domain)
            renewal = _money_from_pricing(pricing_dict, tld, key="renewal")
            over_max = (price is not None and price > max_price)
            cells[tld] = CellState(
                domain=domain, available=available, price=price, renewal=renewal,
                error=error, over_max=over_max,
            )

            # If this is the .com and it's confirmed taken, ask the classifier.
            if tld == ".com" and available is False:
                com_class = _classify_com(domain, classifier_fn=com_classifier)
                cells[tld].com_class = com_class

        # Defense status for scoring.
        com_cell = cells.get(".com")
        com_status: str | None = None
        if com_cell is not None:
            if com_cell.available is True:
                com_status = "available"
            elif com_cell.com_class == "live-site":
                com_status = "live-site"

        # Compute pick + why.
        pick_tld, pick_label, why = _decide_pick(c.name, cells, columns, com_status, max_price)

        anchors = _anchors_in(c.name, vocab_terms)

        # Score = best score among available TLDs the user might pick (bias
        # toward the recommended tld). Vocab-anchor bonus differentiates names
        # with the same Pick-TLD status.
        if pick_tld:
            score, _ = score_name(c.name, topic, pick_tld,
                                  com_status=com_status, vocab_terms=vocab_terms)
        else:
            # No clear pick — use .com tier as the placeholder so poisoned rows sort last.
            score, _ = score_name(c.name, topic, ".com",
                                  com_status=com_status, vocab_terms=vocab_terms)

        rows.append(GridRow(
            name=c.name,
            strategy=c.strategy,
            cells={k: cells[k] for k in probed if k in cells},
            pick_tld=pick_tld,
            pick_label=pick_label,
            why=why,
            score=score,
            anchors_matched=anchors,
        ))

    # Sort: score desc, anchor count desc, length asc (shorter wins ties).
    rows.sort(key=lambda r: (-r.score, -len(r.anchors_matched), len(r.name)))
    return rows


def _money_from_pricing(pricing: dict, tld: str, key: str = "registration") -> float | None:
    """Look up a specific price field (registration / renewal / transfer) for a TLD."""
    if not pricing:
        return None
    bare = tld.lstrip(".").lower()
    entry = pricing.get(bare)
    if not isinstance(entry, dict):
        return None
    val = entry.get(key)
    if val is None:
        return None
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _decide_pick(
    name: str,
    cells: dict[str, CellState],
    visible_columns: list[str],
    com_status: str | None,
    max_price: float,
) -> tuple[str | None, str, str]:
    """Pick a recommended TLD for a row plus a label and why-string.

    Logic, in order:
      1. .com is a live competing site → skip (poisoned)
      2. There's an available premium TLD (.com / .app / .dev) under max-price → pick it.
         If .com is ALSO available, label `+bundle` (defense pickup).
      3. There's an available cheap TLD under max-price → pick it.
      4. No confirmed-available picks but `?` cells exist → pick the highest-tier `?`.
      5. Else → no pick.
    """
    if com_status == "live-site":
        return None, "skip", ".com is an active competing site"

    com_avail = (cells.get(".com") and cells[".com"].available is True
                 and not cells[".com"].over_max)

    def is_pickable(state: CellState) -> bool:
        return state.available is True and not state.over_max

    # Premium ladder
    premium = [".com", ".app", ".dev"]
    for tld in premium:
        if tld in visible_columns and tld in cells and is_pickable(cells[tld]):
            label = f"{tld} +bundle" if (com_avail and tld != ".com") else tld
            why = "premium TLD available"
            if tld != ".com" and com_avail:
                why = "premium open + .com defendable"
            elif tld == ".com":
                why = ".com available"
            return tld, label, why

    # Cheap ladder
    cheap = [".xyz", ".co", ".life", ".info", ".pro", ".shop"]
    for tld in cheap:
        if tld in visible_columns and tld in cells and is_pickable(cells[tld]):
            why = "cheap TLD available"
            if com_avail:
                why = "cheap pick + .com defendable"
            label = f"{tld} +bundle" if com_avail else tld
            return tld, label, why

    # `?` cells (RDAP-broken or genuine gap) — pick the highest-tier one.
    ranked = sorted(visible_columns, key=lambda t: -TLD_TIER.get(t.lower(), 0))
    for tld in ranked:
        st = cells.get(tld)
        if st and st.available is None and not st.over_max:
            return tld, f"{tld} (verify)", "RDAP gap — verify at registrar"

    return None, "skip", "no available picks under price cap"


# ---------- v3.D Porkbun auto-register ----------


@dataclass
class RegisterResult:
    ok: bool
    detail: str
    order_id: str | None = None


def register_domain(
    domain: str,
    api_key: str,
    secret_key: str,
    years: int = 1,
) -> RegisterResult:
    """v3.D: call Porkbun /domain/create to register one domain.

    Charges the card on file at Porkbun. Caller is expected to have prompted
    the user for confirmation BEFORE invoking this. Returns RegisterResult
    with `ok=False` on any failure (HTTP error, non-SUCCESS status, or missing
    keys) so the caller can fall back to the manual checkout URL.
    """
    if not api_key or not secret_key:
        return RegisterResult(ok=False, detail="Porkbun API keys not set in portfolio.env")

    body = {
        "apikey": api_key,
        "secretapikey": secret_key,
        "domain": domain,
        "years": years,
    }
    try:
        r = requests.post(PORKBUN_DOMAIN_CREATE_URL, json=body, timeout=PORKBUN_REGISTER_TIMEOUT)
    except Exception as e:
        return RegisterResult(ok=False, detail=f"Porkbun API call failed: {type(e).__name__}: {e}")

    if r.status_code != 200:
        try:
            err_body = r.json()
        except Exception:
            err_body = {}
        msg = err_body.get("message") or f"HTTP {r.status_code}"
        return RegisterResult(ok=False, detail=f"Porkbun /domain/create returned {msg}")

    try:
        body_json = r.json()
    except Exception:
        return RegisterResult(ok=False, detail="Porkbun returned non-JSON body")

    if body_json.get("status") != "SUCCESS":
        msg = body_json.get("message") or "no message"
        return RegisterResult(ok=False, detail=f"Porkbun /domain/create error: {msg}")

    order_id = body_json.get("orderId") or body_json.get("order_id") or body_json.get("transactionId")
    return RegisterResult(
        ok=True,
        detail=f"Registered {domain}",
        order_id=str(order_id) if order_id else None,
    )


def porkbun_cart_url(domains: list[str]) -> str:
    """Build a Porkbun checkout URL with one or more domains pre-loaded."""
    qs = "+".join(domains)
    return f"{PORKBUN_CHECKOUT_BASE}{qs}"


# ---------- v3.D validation-mode pipeline ----------


def run_validation_pipeline(
    topic: str,
    api_key: str,
    strategies: list[Strategy],
    columns: list[str],
    avail_check,
    max_price: float,
    pricing_dict: dict | None = None,
    com_classifier=None,
    cache_payload: dict | None = None,
    cache_save_fn=None,
    n_per_strategy: int = DEFAULT_CANDIDATES_PER_STRATEGY,
    log_fn=None,
) -> tuple[list[GridRow], list[str]]:
    """v3.D one-pass orchestration.

    Steps:
      1. Vocab extraction (or load from cache_payload).
      2. For each strategy, brainstorm with vocab anchors (cached entries skipped).
      3. Build registrar grid for the unioned candidates.
      4. Return (rows, vocab_terms).

    `cache_payload` is the existing brainstorm-cache dict (or None for cold).
    `cache_save_fn(candidates_by_strategy, vocab_terms)` is invoked after each
    successful step so partial work survives an interrupt.
    """
    def log(msg: str):
        if log_fn is not None:
            log_fn(msg)

    # 1. Vocab.
    vocab_terms: list[str] = []
    if cache_payload and cache_payload.get("vocab_terms"):
        vocab_terms = list(cache_payload["vocab_terms"])
        log(f"vocab: cached ({len(vocab_terms)} terms)")
    else:
        try:
            log("vocab: extracting via OpenAI gpt-5-mini...")
            vocab_terms = extract_vocab(topic, api_key)
            log(f"vocab: {len(vocab_terms)} terms — {', '.join(vocab_terms)}")
        except Exception as e:
            log(f"vocab: extraction failed ({e}); proceeding without anchors")
            vocab_terms = []

    # 2. Brainstorm per strategy.
    candidates_by_strategy: dict[str, list[Candidate]] = {}
    if cache_payload:
        for k, v in (cache_payload.get("candidates_by_strategy") or {}).items():
            candidates_by_strategy[k] = [Candidate(**c) for c in v]

    history: list[str] = []
    for s in strategies:
        if s.name in candidates_by_strategy and candidates_by_strategy[s.name]:
            log(f"strategy '{s.name}': {len(candidates_by_strategy[s.name])} cached candidates")
            history.extend(c.name for c in candidates_by_strategy[s.name])
            continue
        log(f"strategy '{s.name}': brainstorming...")
        try:
            cands = brainstorm(topic, s, history, api_key, n=n_per_strategy, vocab_terms=vocab_terms)
        except Exception as e:
            log(f"strategy '{s.name}': failed ({e})")
            continue
        candidates_by_strategy[s.name] = cands
        history.extend(c.name for c in cands)
        if cache_save_fn:
            cache_save_fn(candidates_by_strategy, vocab_terms)

    # 3. Build grid (one row per unique candidate; dedup across strategies).
    seen: set[str] = set()
    flat: list[Candidate] = []
    for s in strategies:
        for c in candidates_by_strategy.get(s.name, []):
            if c.name in seen:
                continue
            seen.add(c.name)
            flat.append(c)

    rows = build_grid(
        flat, topic, columns, avail_check,
        max_price=max_price,
        pricing_dict=pricing_dict,
        com_classifier=com_classifier,
        full_ladder=list(FULL_LADDER),
        vocab_terms=vocab_terms,
    )
    return rows, vocab_terms
