"""v8.J onward — adversarial audit pass primitives.

Mirrors `interpretive_pass.py`'s shape but for the audit-pass leg of
v8.E-series. The audit pass reads the same cluster snapshot the
primary pass saw plus the primary's response, then steel-mans the
opposite verdict — surfacing risks the primary missed.

This module currently exposes:
  - `build_audit_payload(cluster, *, primary_verdict,
    operator_profile) -> dict` — the structured user-message body
    the audit prompt consumes.

Subsequent commits add:
  - audit prompt rendering (load adversarial_audit_v1.md +
    substitute, parallel to render_primary_prompt)
  - audit response parser (different schema than primary —
    agreement_level / confidence / specific_concerns /
    counter_verdict / audit_self_check)
  - audit-pass runner (orchestrates payload → render → OpenAI →
    parse; uses the existing OPENAI_API_KEY pathway in serp.py)
  - CLI `--verify` wiring + render integration in `new research`

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

import re
from typing import Any

from .interpretive_pass import build_payload
from .operator_profile import OperatorProfile


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
