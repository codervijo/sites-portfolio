"""v29.C — derive `lamill.toml [content]` field values from a site's
authored `AI_AGENTS.md` sections.

The operator already authors rich prose at `new bootstrap` time — Summary,
Audience, ICP, Goals, and especially Content strategy (which routinely
spells out the keyword targets and tone). v29 turns that authored brief
into the `[content]` block instead of asking the operator the same things
again:

  - `icp` is copied **verbatim** from the `## ICP` section (a direct
    paraphrase target, not an inference — decision (a)).
  - the other seven fields (`site_type`, `primary_keyword`,
    `secondary_keywords`, `urgency_trigger`, `penalty`, `tone`, `law`)
    are **derived** from the sections via one structured LLM call.

Derivation is best-effort and never load-bearing: no `OPENAI_API_KEY`, an
empty brief, an HTTP failure, or unparseable model output all degrade to
"return whatever we have" (at minimum the verbatim `icp`, possibly
nothing). Missing fields stay blank in the rendered block and re-seed the
"Fill in [content]" todo — `[content]`'s "empty is better than wrong"
rule. The result feeds `lamill_toml_edit.content_block(values)`.

See ADR-0019 (doc-derivation provenance) + `docs/prd.md § v29`.
"""
from __future__ import annotations

import json
import re

import requests

from .suggest import (
    OPENAI_MODEL,
    OPENAI_RESPONSES_URL,
    OPENAI_TIMEOUT,
    _parse_openai_text,
)

# The seven fields derived from the brief. `icp` is intentionally NOT here
# — it's copied verbatim, never sent through the model. Order/names mirror
# the `[content]` skeleton in `lamill_toml_edit._CONTENT_FIELDS`.
DERIVED_FIELDS: tuple[str, ...] = (
    "site_type",
    "primary_keyword",
    "secondary_keywords",
    "urgency_trigger",
    "penalty",
    "tone",
    "law",
)

# AI_AGENTS headings fed to the model as context, in reading order.
_BRIEF_SECTIONS: tuple[str, ...] = (
    "Summary",
    "Audience",
    "ICP",
    "Goals",
    "Content strategy",
)


def derive_content(
    sections: dict[str, str],
    *,
    api_key: str | None = None,
    log_fn=None,
) -> dict:
    """Derive `[content]` field values from authored `AI_AGENTS` sections.

    `sections` maps AI_AGENTS heading → content (the bootstrap
    `operator_inputs` dict: `Summary` / `Audience` / `ICP` / `Goals` /
    `Content strategy`).

    Returns a `{field: value}` dict ready for
    `lamill_toml_edit.content_block(values)`. Always includes `icp` when
    the `ICP` section is non-empty (verbatim). The other seven fields come
    from one LLM call when `api_key` is provided and the brief is
    non-empty; any failure (no key, HTTP error, bad JSON) yields just the
    fields gathered so far — never raises.
    """
    def _log(msg: str) -> None:
        if log_fn:
            log_fn(msg)

    values: dict = {}

    icp = (sections.get("ICP") or "").strip()
    if icp:
        values["icp"] = icp

    if not api_key:
        _log("↷ no OPENAI_API_KEY — [content] derivation skipped (icp reused if present)")
        return values

    brief = _format_brief(sections)
    if not brief.strip():
        _log("↷ empty AI_AGENTS brief — nothing to derive [content] from")
        return values

    try:
        raw_text = _call_openai(_derive_prompt(brief), api_key)
    except requests.RequestException as e:
        _log(f"↷ [content] derivation call failed ({e}) — fields left empty")
        return values

    derived = _coerce_fields(_parse_json_object(raw_text))
    if derived:
        values.update(derived)
        _log(f"✓ derived {len(derived)} [content] field(s): {', '.join(sorted(derived))}")
    else:
        _log("↷ [content] derivation returned nothing usable — fields left empty")
    return values


# ---- AI_AGENTS.md → sections (v29.E, for backfill) ------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_ITALIC_HINT_RE = re.compile(r"^\*.+\*$")


def parse_ai_agents_sections(text: str) -> dict[str, str]:
    """Parse the brief `## ` sections out of `AI_AGENTS.md` into the
    `{heading: body}` dict `derive_content` consumes — the inverse of
    bootstrap's renderer.

    Only the brief headings (`_BRIEF_SECTIONS`) are returned. A body is
    everything between its `## Heading` and the next heading of *any*
    level, so a trailing `### Post-deploy checklist` under Content
    strategy is excluded. The template's italic guidance line and the
    `(to be filled in)` placeholder are stripped; empty sections are
    dropped.
    """
    bodies: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            # H2 starts a brief body; any other heading level ends it.
            current = m.group(2).strip() if len(m.group(1)) == 2 else None
            if current is not None:
                bodies.setdefault(current, [])
        elif current is not None:
            bodies[current].append(line)

    out: dict[str, str] = {}
    for heading in _BRIEF_SECTIONS:
        body = _clean_section_body("\n".join(bodies.get(heading, [])))
        if body:
            out[heading] = body
    return out


def sections_from_repo(repo_path) -> dict[str, str]:
    """Read `<repo>/AI_AGENTS.md` and parse its brief sections; `{}` when
    the file is absent."""
    from pathlib import Path

    p = Path(repo_path) / "AI_AGENTS.md"
    if not p.is_file():
        return {}
    return parse_ai_agents_sections(p.read_text(encoding="utf-8"))


def _clean_section_body(raw: str) -> str:
    """Drop the template's leading italic guidance line and the
    `(to be filled in)` placeholder from a section body, returning the
    operator's prose (or `""` when the section is just the placeholder)."""
    lines = raw.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and _ITALIC_HINT_RE.match(lines[i].strip()):
        i += 1
    body = "\n".join(lines[i:]).strip()
    return "" if body == "(to be filled in)" else body


# ---- internals ------------------------------------------------------


def _format_brief(sections: dict[str, str]) -> str:
    """Render the authored sections as a `## Heading` + body block, in
    reading order, skipping empties."""
    parts: list[str] = []
    for heading in _BRIEF_SECTIONS:
        body = (sections.get(heading) or "").strip()
        if body:
            parts.append(f"## {heading}\n{body}")
    return "\n\n".join(parts)


def _derive_prompt(brief: str) -> str:
    """The extraction prompt. Constrains the model to the field schema and
    to deriving only from the brief (empty when unsupported)."""
    return (
        "You extract a structured content-config from a website's authored "
        "brief. Return ONLY a JSON object with EXACTLY these keys:\n"
        '- "site_type": a short category for the site — one of "tool", "b2c", '
        '"b2b", "directory", "blog", "legal-compliance".\n'
        '- "primary_keyword": the single search phrase this site should rank '
        "for (prefer one stated in the Content strategy).\n"
        '- "secondary_keywords": an array of 3-8 supporting search phrases '
        "(use the Content strategy's listed targets when present).\n"
        '- "urgency_trigger": what makes the reader act now.\n'
        '- "penalty": the cost of inaction, in the reader\'s terms.\n'
        '- "tone": the writing voice (use the Content strategy if it states '
        'one), e.g. "direct, technical, no fluff".\n'
        '- "law": a statute, regulation, or compliance framework if the site '
        'is compliance-related, else "".\n\n'
        "Rules:\n"
        "- Derive ONLY from the provided brief. Do NOT invent facts the brief "
        "does not support.\n"
        '- If a field is not supported by the brief, return "" (or [] for '
        "secondary_keywords).\n"
        "- Do NOT include an icp field; it is handled separately.\n"
        "- Output the JSON object and nothing else.\n\n"
        f"BRIEF:\n{brief}"
    )


def _call_openai(prompt: str, api_key: str) -> str:
    """One `/v1/responses` call → the model's raw text reply. Mirrors the
    `suggest.py` call shape (same endpoint/model/parser). Isolated so tests
    can monkeypatch it without touching HTTP."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": OPENAI_MODEL, "input": prompt}
    r = requests.post(OPENAI_RESPONSES_URL, headers=headers, json=body, timeout=OPENAI_TIMEOUT)
    r.raise_for_status()
    return _parse_openai_text(r.json())


def _parse_json_object(text: str) -> dict:
    """Tolerantly pull the first JSON object out of `text` (the model may
    wrap it in prose or a ```json fence). Returns {} on any failure."""
    if not text:
        return {}
    # Fast path: the whole reply is JSON.
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: grab the outermost {...} span and try that.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


def _coerce_fields(raw: dict) -> dict:
    """Coerce the model's object to the field schema: keep only
    `DERIVED_FIELDS`, force `secondary_keywords` to a list[str], everything
    else to a non-empty trimmed string. Empty / missing fields are dropped
    so the renderer leaves them at their skeleton default."""
    out: dict = {}
    for field in DERIVED_FIELDS:
        v = raw.get(field)
        if field == "secondary_keywords":
            kws = _coerce_keyword_list(v)
            if kws:
                out[field] = kws
        else:
            s = _coerce_str(v)
            if s:
                out[field] = s
    return out


def _coerce_str(v) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, dict)) or v is None:
        return ""
    return str(v).strip()


def _coerce_keyword_list(v) -> list[str]:
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # Tolerate a comma-separated string instead of an array.
        return [s.strip() for s in re.split(r"[,\n]", v) if s.strip()]
    return []
