"""Domain-suggest pipeline (v2.A).

Multi-strategy LLM brainstorm → SEO-weighted scoring → already-own intersect.
Hands off to availability.py for the per-name avail+price check.
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

DEFAULT_TLDS = (".com", ".ai", ".io", ".app", ".dev", ".tech", ".co", ".site", ".online")

TLD_TIER = {
    ".com": 10,
    ".ai": 9,
    ".io": 8,
    ".app": 7,
    ".dev": 7,
    ".co": 7,
    ".tech": 6,
    ".site": 4,
    ".online": 4,
    ".today": 3,
    ".live": 3,
    ".church": 4,
    ".tools": 4,
    ".org": 5,
    ".net": 5,
    ".us": 5,
    ".in": 4,
}


PORTFOLIO_ENV_TEMPLATE = """\
# portfolio.env — secrets for portfolio CLI features.
# Loaded by python-dotenv at runtime. Do not commit this file (it's in .gitignore).

# Required for `portfolio domain suggest` brainstorm (v2.A)
OPENAI_API_KEY=

# Optional for `portfolio domain suggest` availability+price (v2.B).
# When unset, the CLI falls back to RDAP (free, no keys, availability only — no price).
PORKBUN_API_KEY=
PORKBUN_SECRET_API_KEY=
"""


@dataclass
class Strategy:
    name: str
    label: str
    description: str


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
    p = path or STRATEGIES_JSON
    data = json.loads(p.read_text())
    return [Strategy(**s) for s in data.get("strategies", [])]


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


def cache_set(topic: str, strategies: list[Strategy], candidates_by_strategy: dict[str, list[Candidate]]) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _cache_path(topic, strategies)
    payload = {
        "cached_at": time.time(),
        "topic": topic,
        "strategy_names": [s.name for s in strategies],
        "candidates_by_strategy": {k: [asdict(c) for c in v] for k, v in candidates_by_strategy.items()},
    }
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


def score_name(name: str, topic: str, tld: str) -> tuple[int, list[str]]:
    """SEO-weighted score for a name+TLD pair given a topic. Returns (score, notes)."""
    notes: list[str] = []
    s = 0

    tier = TLD_TIER.get(tld.lower(), 2)
    s += tier * 5
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

    return s, notes


_BRAINSTORM_PROMPT = """\
Generate {n} product domain name candidates for this idea:

{idea}

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


def _brainstorm_prompt(idea: str, strategy: Strategy, history: list[str], n: int) -> str:
    return _BRAINSTORM_PROMPT.format(
        n=n,
        idea=idea.strip(),
        strategy_label=strategy.label,
        strategy_description=strategy.description,
        history=", ".join(sorted(set(history))) if history else "(none yet)",
    )


def _parse_openai_text(payload: dict) -> str:
    """Pull the model's text reply out of /v1/responses payload, robust to shape variants."""
    if "output_text" in payload:
        return payload["output_text"]
    output = payload.get("output", [])
    if output and isinstance(output, list):
        first = output[0]
        if isinstance(first, dict):
            content = first.get("content", [])
            if content and isinstance(content, list):
                first_block = content[0]
                if isinstance(first_block, dict):
                    return first_block.get("text", "") or first_block.get("output_text", "")
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


def brainstorm(idea: str, strategy: Strategy, history: list[str], api_key: str, n: int = DEFAULT_CANDIDATES_PER_STRATEGY) -> list[Candidate]:
    """Single brainstorm call. Returns Candidate objects (no scoring yet — that's per TLD)."""
    prompt = _brainstorm_prompt(idea, strategy, history, n)
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


def render_options(candidates: list[Candidate], topic: str, tlds: list[str], avail_check) -> list[ScoredOption]:
    """For each candidate, scan TLDs in order; stop at first **confirmed available** (True);
    otherwise track best `unknown` (None) result by score; only mark fully taken if every TLD
    came back False. `avail_check(domain) -> (available: bool|None, price: float|None)`.

    Surfaces unknowns to the caller so users can see and verify them at the registrar —
    RDAP has gaps (.io, .co, several radix TLDs); without this, those candidates would
    silently disappear.
    """
    out: list[ScoredOption] = []
    for c in candidates:
        attempts: list[tuple[bool | None, float | None, int, str, str]] = []
        for tld in tlds:
            domain = f"{c.name}{tld}"
            available, price = avail_check(domain)
            score, _notes = score_name(c.name, topic, tld)
            attempts.append((available, price, score, tld, domain))
            if available is True:
                break

        def _rank_priority(a):
            if a[0] is True:
                return 0
            if a[0] is None:
                return 1
            return 2

        attempts.sort(key=lambda a: (_rank_priority(a), -a[2]))
        best = attempts[0]
        out.append(ScoredOption(
            name=c.name,
            tld=best[3],
            domain=best[4],
            available=best[0],
            price=best[1],
            score=best[2],
            strategy=c.strategy,
        ))
    out.sort(key=lambda o: (
        0 if o.available is True else (1 if o.available is None else 2),
        -o.score,
    ))
    return out


def filter_by_max_price(options: list[ScoredOption], max_price: float | None) -> list[ScoredOption]:
    if max_price is None:
        return options
    return [o for o in options if (o.price is None or o.price <= max_price)]
