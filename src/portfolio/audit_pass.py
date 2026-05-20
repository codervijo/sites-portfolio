"""v8.J + v12.A onward — adversarial audit pass primitives.

Mirrors `interpretive_pass.py`'s shape but for the audit-pass leg of
the research-module interpretive layer. The audit pass reads the
same cluster snapshot the primary pass saw plus the primary's
response, then steel-mans the opposite verdict — surfacing risks
the primary missed.

This module currently exposes:
  - `build_audit_payload(cluster, *, primary_verdict,
    operator_profile) -> dict` — the structured user-message body
    the audit prompt consumes. (v8.J)
  - `render_audit_prompt(payload, *, prompt_name) -> str` —
    assembles the final prompt string to send to the audit-model
    LLM. (v12.A)
  - `parse_audit(markdown_text) -> ParsedAudit` + `AuditParseError`
    — parses the audit LLM's markdown response. Different schema
    than primary: agreement_level / confidence / specific_concerns /
    counter_verdict / audit_self_check. Reuses interpretive_pass's
    section + bullet primitives. (v12.B)
  - `run_audit_pass(cluster, *, primary_verdict, ...) -> AuditPassResult`
    + `AuditPassError` — end-to-end orchestrator: build_audit_payload
    → render_audit_prompt → OpenAI Responses-API call → parse_audit
    → cost computation. Default model `gpt-4o`, override via
    `model=`. Test seam: `openai_caller=`. (v12.C)

Subsequent commits add:
  - reconciliation + REVIEW_REQUIRED first-class verdict — v12.D
  - CLI `--verify` wiring + render integration in `new validate` —
    v12.E

Why a separate module from `interpretive_pass.py`: the prompts are
different (niche_evaluation vs adversarial_audit), the response
schemas are different (verdict tokens differ — `full / partial /
disagree` vs `GO / NICHE-DOWN / NO-GO`), and the LLM providers are
different (Claude CLI subprocess for the primary; OpenAI HTTP for
the audit — different model families are the point per the PRD).
Sharing the module would force the implementations to stay
artificially aligned.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .interpretive_pass import (
    _VALID_VERDICTS,
    _normalize_verdict_token,
    _parse_bullets,
    _split_sections,
    build_payload,
)
from .operator_profile import OperatorProfile
from .prompt_loader import load_prompt, render_prompt

AUDIT_PROMPT_NAME = "adversarial_audit_v1"
AUDIT_PROMPT_VERSION = "v1"   # matches the suffix on the prompt filename

DEFAULT_AUDIT_MODEL = "gpt-4o"
DEFAULT_AUDIT_TIMEOUT_S = 180

# OpenAI Responses API endpoint. Same URL the v8.D primary research
# uses in `serp.call_openai`; replicated here rather than importing
# because v12.C needs token usage (for cost) which `serp.call_openai`
# discards. Two callers, two return shapes — duplicating 20 lines
# is cheaper than refactoring serp.py and re-validating its 5 callers.
_OPENAI_URL = "https://api.openai.com/v1/responses"

# gpt-4o pricing as of 2026-05 (USD per 1M tokens). Treated as a
# starting table; v12.F's cost-ledger polish refines this (config
# file or pulled from OpenAI's pricing API). Unknown models fall
# through to zero cost — the duration is still recorded so the
# snapshot has *something* useful even without USD.
_OPENAI_PRICING_USD_PER_1M = {
    "gpt-4o":          {"input": 2.50,  "output": 10.00},
    "gpt-4o-mini":     {"input": 0.15,  "output":  0.60},
    "gpt-4-turbo":     {"input": 10.00, "output": 30.00},
    "gpt-4.1":         {"input": 2.00,  "output":  8.00},
}


def _reconstruct_primary_markdown(verdict: dict, *,
                                  strip_blind_spot: bool = True) -> str:
    """Rebuild the primary's markdown response from the parsed
    `primary_verdict` dict that v8.I persists into the cluster
    snapshot.

    The cluster snapshot persists the PARSED verdict (a flat dict of
    ParsedVerdict fields), not the LLM's raw markdown — so the audit
    needs reconstruction. The result is lossy in whitespace /
    ordering (a different shape than what the LLM emitted), but
    semantically equivalent: every field the audit reads is present
    under the same `### <header>` it was originally written under.

    `strip_blind_spot=True` (the prompt-required default) omits the
    primary's `blind_spot_self_report` section per the audit prompt's
    instruction — visibility into the primary's stated blind spots
    would anchor the audit on the same concerns, defeating the
    point. Set `False` for the rare diagnostic case where the full
    primary response is needed verbatim.
    """
    if not verdict:
        return ""
    parts: list[str] = []
    parts.append(f"### verdict\n{verdict.get('verdict', '')}")
    parts.append(f"### confidence\n{verdict.get('confidence', '')}")
    parts.append(f"### reasoning\n{(verdict.get('reasoning') or '').strip()}")

    moat_required = verdict.get("moat_required")
    if moat_required is not None:
        # Render `true` / `false` lowercase to match the prompt's
        # specified shape (matches what parse_verdict accepts).
        parts.append(f"### moat_required\n{'true' if moat_required else 'false'}")

    moat_prompt = (verdict.get("moat_prompt") or "").strip()
    if moat_prompt:
        parts.append(f"### moat_prompt\n{moat_prompt}")

    reductions = verdict.get("reductions") or []
    if reductions:
        body = "\n".join(f"- {r}" for r in reductions)
        parts.append(f"### reductions\n{body}")

    warnings = verdict.get("operator_fit_warnings") or []
    if warnings:
        body = "\n".join(f"- {w}" for w in warnings)
        parts.append(f"### operator_fit_warnings\n{body}")

    if not strip_blind_spot:
        blind_spot = (verdict.get("blind_spot_self_report") or "").strip()
        if blind_spot:
            parts.append(f"### blind_spot_self_report\n{blind_spot}")

    return "\n\n".join(parts) + "\n"


def build_audit_payload(cluster: dict, *,
                        primary_verdict: dict,
                        operator_profile: OperatorProfile | None = None) -> dict:
    """Assemble the structured user-message payload for the
    adversarial audit pass.

    Builds on `interpretive_pass.build_payload` (same cluster +
    profile shape) and adds:

      `primary_response_markdown`: str — the primary's response
        reconstructed from the persisted parsed verdict, with the
        `blind_spot_self_report` section stripped per the audit
        prompt's anti-anchoring instruction.

    The audit prompt teaches the LLM to read the JSON payload AND
    the primary's markdown verbatim — same data the primary saw
    plus the primary's reasoning — then steel-man the opposite
    verdict.

    Why we reconstruct the markdown rather than persist the raw
    response: v8.I's cluster-snapshot schema stores the PARSED
    primary_verdict (dict of ParsedVerdict fields) but not the
    LLM's raw markdown. Reconstruction is lossy in formatting but
    preserves all the semantic content the audit reads. Storing the
    raw response too would double the snapshot size for negligible
    audit benefit.

    Required keys in `primary_verdict`:
      verdict, confidence, reasoning  — required (raises KeyError
      otherwise via the underlying dict access).
    Optional keys:
      moat_required, moat_prompt, reductions,
      operator_fit_warnings, blind_spot_self_report.
    """
    base = build_payload(cluster, operator_profile=operator_profile)
    base["primary_response_markdown"] = _reconstruct_primary_markdown(
        primary_verdict, strip_blind_spot=True,
    )
    return base


# ---------- prompt rendering ----------


def render_audit_prompt(payload: dict, *,
                        prompt_name: str = AUDIT_PROMPT_NAME) -> str:
    """Assemble the final audit-pass prompt string.

    Parallel to `interpretive_pass.render_primary_prompt`:

      1. Load `prompts/<prompt_name>.md` (H1 stripped by load_prompt).
      2. Run it through `render_prompt(template)` with **no
         substitutions**. The audit prompt today carries no `{{var}}`
         placeholders (operator context flows through the payload's
         `operator_profile_summary` and `operator_fit` fields rather
         than via prompt-level template vars — the audit doesn't tailor
         instructions to operator type, just reasons about the data).
         The render-call is defensive: if a future prompt edit adds a
         `{{var}}`, `render_prompt` raises `UnfilledPlaceholderError`
         at the rendering boundary BEFORE the LLM call burns a token
         budget. Better to fail loud at prompt assembly than to ship
         `{{operator_expertise}}` text to the model.
      3. Append a clear `---` delimiter line.
      4. Append the structured payload (from `build_audit_payload`)
         JSON-encoded inside a ```json``` fence — same shape the
         primary uses, so debug snapshots between the two passes are
         visually consistent.

    The payload's `primary_response_markdown` field carries the
    primary's verdict reconstructed (with `blind_spot_self_report`
    stripped — anti-anchoring per the audit prompt's instruction); the
    audit prompt reads it from the JSON, not from a separate section.

    Raises `UnfilledPlaceholderError` if the prompt template
    introduces unsubstituted placeholders (see step 2 above for the
    drift-detection rationale).
    """
    template = load_prompt(prompt_name)
    system_part = render_prompt(template)  # no substitutions — drift guard
    payload_json = json.dumps(payload, indent=2, default=str)
    return (
        f"{system_part}\n\n"
        f"---\n\n"
        f"INPUT PAYLOAD (JSON):\n\n"
        f"```json\n{payload_json}\n```"
    )


# ---------- response parsing ----------


# Canonical tokens per `prompts/adversarial_audit_v1.md`'s response-
# format spec. Distinct from interpretive_pass's verdict set:
# agreement_level captures the audit's relationship to the primary,
# not its own GO/NICHE-DOWN/NO-GO call. The counter_verdict (used
# only on `disagree`) reuses interpretive_pass._VALID_VERDICTS.
_VALID_AGREEMENT = {"full", "partial", "disagree"}
_VALID_AUDIT_CONFIDENCE = {"HIGH", "MEDIUM", "LOW"}


@dataclass
class ParsedAudit:
    """Structured representation of the audit-pass LLM's markdown
    response. Required fields (agreement_level / confidence /
    specific_concerns) are validated at parse time; optional fields
    default to empty when the LLM omits them per the prompt spec
    (e.g., counter_verdict is required only on `disagree`)."""
    agreement_level: str          # full | partial | disagree
    confidence: str               # HIGH | MEDIUM | LOW (audit's own)
    specific_concerns: list[str]  # ≥1 bullet — validated
    counter_verdict_token: str = ""        # GO | NICHE-DOWN | NO-GO
    counter_verdict_reasoning: str = ""    # 1-2 sentence explanation
    audit_self_check: str = ""             # honest self-assessment


class AuditParseError(ValueError):
    """Raised when the audit LLM's response can't be parsed into a
    ParsedAudit. The runner (v12.C) catches and surfaces — failing
    loud beats shipping a half-parsed audit into reconciliation."""


def _parse_counter_verdict(body: str) -> tuple[str, str]:
    """Parse the counter_verdict section body into
    (canonical_token, reasoning). Expected shape per the audit prompt:

        <TOKEN>: <1-2 sentences why>

    where TOKEN ∈ {GO, NICHE-DOWN, NO-GO}. The reasoning may span
    multiple lines — everything after the first `:` is the reasoning.

    Raises `AuditParseError` when the body is empty, lacks a colon,
    or the token isn't in the canonical set (after the same
    normalization `_normalize_verdict_token` applies to the primary).
    """
    text = body.strip()
    if not text:
        raise AuditParseError(
            "counter_verdict section is empty — required when "
            "agreement_level=disagree"
        )
    head, sep, rest = text.partition(":")
    if not sep:
        raise AuditParseError(
            f"counter_verdict must follow `<TOKEN>: <reasoning>` shape "
            f"(got: {text[:60]!r})"
        )
    token = _normalize_verdict_token(head)
    if token not in _VALID_VERDICTS:
        raise AuditParseError(
            f"counter_verdict token {head!r} not in canonical set "
            f"{sorted(_VALID_VERDICTS)} (normalized: {token!r})"
        )
    return token, rest.strip()


def parse_audit(markdown_text: str) -> ParsedAudit:
    """Parse the audit-pass LLM's markdown response into a `ParsedAudit`.

    Raises `AuditParseError` when:
      - Any of the three required sections is missing
        (agreement_level / confidence / specific_concerns)
      - The agreement_level token isn't in {full, partial, disagree}
      - The confidence token isn't in {HIGH, MEDIUM, LOW}
      - `specific_concerns` has no bullets (vague-concerns rejection
        per the prompt's "concrete or omitted" instruction)
      - `agreement_level=disagree` but `counter_verdict` is missing
        or empty
      - `counter_verdict` is present but malformed (no colon, or token
        not in {GO, NICHE-DOWN, NO-GO}) — strict only when the
        agreement_level requires it; permissive otherwise (see below)

    Permissive on:
      - Optional sections: absent → empty defaults
      - Bullet marker style in specific_concerns (`-`, `*`, `+`, `N.`)
      - Header case (`### Agreement_Level` and `### agreement_level`
        both work)
      - Trailing punctuation on tokens (`partial.`, `HIGH,`)
      - Pre-section preamble chatter (discarded)
      - `counter_verdict` present when agreement_level != disagree:
        parsed if well-formed (stored), tolerated if malformed
        (stored raw in `counter_verdict_reasoning`). Reconciliation
        (v12.D) decides whether to surface it in non-disagree cases.
    """
    sections = _split_sections(markdown_text)

    for required in ("agreement_level", "confidence", "specific_concerns"):
        if required not in sections:
            raise AuditParseError(
                f"required section `### {required}` missing from response. "
                f"Sections found: {sorted(sections.keys())}"
            )

    agreement = sections["agreement_level"].strip().lower().rstrip(".!,;:")
    if agreement not in _VALID_AGREEMENT:
        raise AuditParseError(
            f"agreement_level {sections['agreement_level']!r} not in canonical "
            f"set {sorted(_VALID_AGREEMENT)}"
        )

    confidence = sections["confidence"].strip().upper().rstrip(".!,;:")
    if confidence not in _VALID_AUDIT_CONFIDENCE:
        raise AuditParseError(
            f"confidence {sections['confidence']!r} not in canonical set "
            f"{sorted(_VALID_AUDIT_CONFIDENCE)}"
        )

    concerns = _parse_bullets(sections["specific_concerns"])
    if not concerns:
        raise AuditParseError(
            "specific_concerns must contain at least one bullet — "
            "the audit prompt rejects vague or empty concerns "
            "(\"concrete or omitted\")"
        )

    counter_token = ""
    counter_reasoning = ""
    counter_body = sections.get("counter_verdict", "").strip()
    if agreement == "disagree":
        if not counter_body:
            raise AuditParseError(
                "agreement_level=disagree requires a non-empty "
                "`### counter_verdict` section per the audit prompt"
            )
        counter_token, counter_reasoning = _parse_counter_verdict(counter_body)
    elif counter_body:
        # Permissive: LLM emitted a counter on full/partial against
        # the prompt's instructions. Parse if well-formed so
        # reconciliation can see it; otherwise store the raw body
        # under reasoning and leave the token empty rather than
        # raising — the audit's signal lives in the concerns list,
        # not in an off-spec counter on a non-disagree audit.
        try:
            counter_token, counter_reasoning = _parse_counter_verdict(counter_body)
        except AuditParseError:
            counter_token = ""
            counter_reasoning = counter_body

    return ParsedAudit(
        agreement_level=agreement,
        confidence=confidence,
        specific_concerns=concerns,
        counter_verdict_token=counter_token,
        counter_verdict_reasoning=counter_reasoning,
        audit_self_check=sections.get("audit_self_check", "").strip(),
    )


# ---------- runner ----------


@dataclass
class OpenAIChatResult:
    """Minimal OpenAI Responses-API result tuple. Carries the raw
    text plus token usage so the audit pass can compute cost without
    a second API roundtrip. Returned by the default `openai_caller`
    in `run_audit_pass`; tests inject stubs of the same shape."""
    text: str
    input_tokens: int
    output_tokens: int


class AuditPassError(RuntimeError):
    """Raised when the audit pass fails end-to-end: OpenAI HTTP call
    errored, response was empty, or markdown couldn't be parsed into
    a `ParsedAudit`. The orchestrator (v12.E `new validate --verify`)
    catches and surfaces the underlying cause."""


@dataclass
class AuditPassResult:
    """Outcome of one full audit-pass run. Mirrors
    `InterpretivePassResult`'s shape so v8.I's snapshot persistence
    can fold both into the cluster snapshot symmetrically.

    `model_id` is the OpenAI model string the caller resolved to
    (not the API's echoed model, which can be a dated alias like
    `gpt-4o-2024-08-06`). Snapshot persistence depends on these field
    names — keep them stable across v12.* commits.
    """
    audit: ParsedAudit
    rendered_prompt: str        # full text sent to OpenAI (for snapshot)
    prompt_version: str         # "v1" — matches adversarial_audit_v1.md
    model_id: str               # e.g. "gpt-4o"
    cost_usd: float
    duration_s: float


def _openai_pricing_for(model: str) -> dict[str, float]:
    """Return the {input, output} per-1M-token USD rates for `model`.

    Unknown models return zeros — better to record cost=0 than to
    crash the audit on a model not yet in the table. v12.F's polish
    fills out the table (and may pull from a config file or
    OpenAI's pricing API).

    Matches OpenAI's dated-alias convention: `gpt-4o-2024-08-06`
    falls through to `gpt-4o` via prefix match. Avoids the
    fail-on-rename foot-gun where pricing breaks the day OpenAI
    promotes a new snapshot.
    """
    if model in _OPENAI_PRICING_USD_PER_1M:
        return _OPENAI_PRICING_USD_PER_1M[model]
    # Prefix match for dated aliases (gpt-4o-2024-08-06 → gpt-4o).
    for base, rates in _OPENAI_PRICING_USD_PER_1M.items():
        if model.startswith(base + "-"):
            return rates
    return {"input": 0.0, "output": 0.0}


def _compute_cost_usd(model: str, *,
                      input_tokens: int, output_tokens: int) -> float:
    """Convert token counts to USD using `_openai_pricing_for(model)`.
    Returns 0.0 for unknown models so the audit still completes."""
    rates = _openai_pricing_for(model)
    return (
        (input_tokens  / 1_000_000.0) * rates["input"] +
        (output_tokens / 1_000_000.0) * rates["output"]
    )


def _call_openai_chat(system: str, user: str, *,
                       model: str, api_key: str,
                       timeout_s: float) -> OpenAIChatResult:
    """Default OpenAI Responses-API caller. Single request, no
    retries — the audit pass is operator-triggered and a transient
    failure should surface as `AuditPassError`, not be silently
    retried while burning quota.

    Same endpoint shape as `serp.call_openai` but returns token
    usage alongside text. Doesn't reuse `serp.call_openai` because
    that one discards usage; v12.F will likely consolidate when
    cost-ledger work needs the same shape everywhere.

    Raises `AuditPassError` on HTTP/transport failure or unexpected
    response shape — caller catches and wraps in the higher-level
    pass error.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    body = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": 0,
    }
    try:
        r = requests.post(_OPENAI_URL, headers=headers, json=body,
                          timeout=timeout_s)
    except requests.RequestException as e:
        raise AuditPassError(
            f"OpenAI request failed: {type(e).__name__}: {e}"
        ) from e
    if r.status_code != 200:
        raise AuditPassError(
            f"OpenAI HTTP {r.status_code}: {r.text[:200]}"
        )
    try:
        data = r.json()
    except ValueError as e:
        raise AuditPassError(f"OpenAI returned non-JSON: {e}") from e

    text = data.get("output_text", "")
    if not text:
        # Responses API can also surface text under `output[].content[]`.
        for item in data.get("output") or []:
            for c in item.get("content") or []:
                if c.get("type") in ("output_text", "text"):
                    text = c.get("text", "")
                    if text:
                        break
            if text:
                break
    if not text:
        raise AuditPassError(
            f"unexpected OpenAI response shape: {list(data.keys())}"
        )

    usage = data.get("usage") or {}
    return OpenAIChatResult(
        text=text,
        input_tokens=int(usage.get("input_tokens", 0)),
        output_tokens=int(usage.get("output_tokens", 0)),
    )


def _read_openai_api_key() -> str:
    """Read OPENAI_API_KEY via the existing v8.D pathway in
    `serp.py`. Re-imported here so the audit pass has its own
    error message hinting at `lamill settings apikeys set
    OPENAI_API_KEY <key>`.

    Imported lazy to avoid a circular import at module load —
    serp.py is heavy (loads requests, all the cluster schema).
    """
    from .serp import _openai_api_key
    return _openai_api_key()


def run_audit_pass(
    cluster: dict,
    *,
    primary_verdict: dict,
    operator_profile: OperatorProfile | None = None,
    model: str = DEFAULT_AUDIT_MODEL,
    timeout_s: int = DEFAULT_AUDIT_TIMEOUT_S,
    openai_caller: Callable[..., OpenAIChatResult] | None = None,
    api_key: str | None = None,
) -> AuditPassResult:
    """End-to-end orchestration of the adversarial audit pass.

    Sequence:
      1. `build_audit_payload(cluster, primary_verdict, operator_profile)`
      2. `render_audit_prompt(payload)` → str
      3. `openai_caller(system, user, model, ...)` → OpenAIChatResult
         The rendered prompt is split on the audit prompt's `---`
         delimiter into (system, user). Single-message senders that
         can't split fall back to sending everything as `user`.
      4. `parse_audit(result.text)` → ParsedAudit
      5. Compute cost from token usage + model pricing table.

    Returns `AuditPassResult` carrying the parsed audit plus
    rendered_prompt (for snapshot), prompt_version, model_id, cost,
    duration.

    Raises `AuditPassError` when:
      - OpenAI HTTP call fails (network, non-200, malformed JSON,
        unexpected shape)
      - Response is empty
      - `parse_audit` rejects the response (the underlying
        `AuditParseError` is wrapped)

    `model` defaults to gpt-4o per PRD §6 v12 (different family from
    the Claude-CLI primary by design — the audit's value is in model
    disagreement, not in being a second opinion from the same family).

    `openai_caller` is the test seam — production callers leave None
    and get `_call_openai_chat`. Tests inject stubs returning canned
    OpenAIChatResult values without touching the network.

    `api_key` defaults to reading via the v8.D pathway (`portfolio.env`
    → `OPENAI_API_KEY` env var). Tests pass a placeholder so the
    real key isn't required.
    """
    payload = build_audit_payload(
        cluster,
        primary_verdict=primary_verdict,
        operator_profile=operator_profile,
    )
    rendered_prompt = render_audit_prompt(payload)

    # Split the rendered prompt on the `---` delimiter the renderer
    # inserts between the system prompt and the payload section.
    # The OpenAI Responses API takes separate system + user fields
    # (improves model adherence vs concatenating into one blob), so
    # we split rather than send the whole rendered string as one
    # message. Fallback: if the delimiter isn't present (e.g.,
    # someone edited the renderer and forgot it), send the entire
    # rendered prompt as `user` and an empty system — graceful
    # degradation beats a hard failure here.
    if "\n---\n" in rendered_prompt:
        system_part, _, user_part = rendered_prompt.partition("\n---\n")
        system_part = system_part.strip()
        user_part = user_part.strip()
    else:
        system_part = ""
        user_part = rendered_prompt

    caller = openai_caller if openai_caller is not None else _call_openai_chat
    resolved_api_key = api_key if api_key is not None else _read_openai_api_key()

    t0 = time.monotonic()
    chat_result = caller(
        system_part, user_part,
        model=model, api_key=resolved_api_key, timeout_s=timeout_s,
    )
    duration_s = time.monotonic() - t0

    try:
        audit = parse_audit(chat_result.text)
    except AuditParseError as e:
        raise AuditPassError(
            f"could not parse audit response: {e}"
        ) from e

    cost_usd = _compute_cost_usd(
        model,
        input_tokens=chat_result.input_tokens,
        output_tokens=chat_result.output_tokens,
    )
    return AuditPassResult(
        audit=audit,
        rendered_prompt=rendered_prompt,
        prompt_version=AUDIT_PROMPT_VERSION,
        model_id=model,
        cost_usd=cost_usd,
        duration_s=duration_s,
    )
