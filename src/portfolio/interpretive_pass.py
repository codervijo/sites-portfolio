"""v8.E — interpretive verdict layer on top of v8.D's mechanical gates.

Reads the same cluster snapshot the v8.D pipeline emits (SerpAPI top-10
+ AI Overview / Reddit / PAA / features + Market/SERP/Moat gates +
operator-fit findings + GO/NICHE-DOWN/NO-GO verdict) and produces a
qualitative read of the same data via the Claude CLI subprocess.

This module currently exposes one piece: `build_payload(cluster,
operator_profile) -> dict`. That's the structured user-message body the
primary-pass prompt will receive — the LLM-call substrate is
`fix_helpers.run_claude_text` (already shipped); the parser, runner,
and orchestrator wiring land in subsequent commits.

Payload shape contract — keep it stable. The standing prompt at
`prompts/niche_evaluation_v1.md` references these keys; renaming
breaks reproducibility on cached snapshots.

  {
    "topic":                       str,
    "cluster_queries":             list[str],
    "gates":                       dict — passes through cluster's
                                          gate_1_market / gate_2_serp /
                                          gate_3_moat dicts verbatim
    "operator_fit":                dict — warnings + auto_fail_gate_2
                                          from research_gates
    "operator_profile_summary":    str — rendered for the LLM (not raw
                                          YAML/TOML dump)
    "raw_top_10_per_query":        list — title/URL/domain only
                                          per PRD §4 — drops snippet
                                          + displayed_link to keep
                                          prompt token cost bounded
    "serp_features_per_query":     list — only the features that fired
                                          per query (suppresses the
                                          empty {present: false} dicts
                                          that pad the cluster snapshot)
  }
"""
from __future__ import annotations

import json
from typing import Any

from .operator_profile import OperatorProfile
from .prompt_loader import load_prompt, render_prompt

PRIMARY_PROMPT_NAME = "niche_evaluation_v1"


def _summarize_operator_profile(profile: OperatorProfile | None) -> str:
    """Render the operator profile as a one-paragraph human-readable
    summary the LLM can consume. Different shape from the YAML/TOML
    on disk — the LLM doesn't need the schema, it needs the operator
    constraints.

    Returns "no operator profile configured" when `profile` is None or
    is the default (no declared expertise, default workflow + cadence)
    — same convention as `settings operator show`.
    """
    if profile is None or not _profile_has_content(profile):
        return "no operator profile configured"
    parts: list[str] = []
    if profile.expertise:
        parts.append("Expertise: " + ", ".join(profile.expertise))
    parts.append(f"Workflow preference: {profile.workflow_preference}")
    parts.append(f"Motivation cadence: {profile.motivation_cadence}")
    return ". ".join(parts) + "."


def _profile_has_content(profile: OperatorProfile) -> bool:
    """True iff the profile carries operator-supplied content (any
    expertise entry, OR a non-default workflow / cadence). Matches the
    "no profile configured" check in `settings operator show`."""
    from .operator_profile import DEFAULT_WORKFLOW, DEFAULT_CADENCE
    if profile.expertise:
        return True
    if profile.workflow_preference != DEFAULT_WORKFLOW:
        return True
    if profile.motivation_cadence != DEFAULT_CADENCE:
        return True
    return False


def _trim_organic_result(r: dict) -> dict:
    """Strip a SerpAPI organic-result dict to the fields the LLM needs
    for context (position, domain, URL, title). Drops snippet (~100-300
    chars each — would balloon prompt cost across 5 queries × 10
    results) and displayed_link (redundant with URL)."""
    return {
        "position": r.get("position"),
        "domain": r.get("domain"),
        "url": r.get("url"),
        "title": r.get("title"),
    }


def _present_features_only(features: dict) -> dict:
    """Filter a per-query features dict to entries where `present` is
    truthy. The cluster snapshot pads with `{present: false}` for every
    feature absent on a given query — the LLM doesn't need the
    negative space, only the SERP features that actually fired.

    Values are passed through verbatim so feature-specific subfields
    (Reddit card position, AI Overview cited domains, PAA question
    count, etc.) reach the prompt.
    """
    out: dict[str, dict] = {}
    for name, body in (features or {}).items():
        if isinstance(body, dict) and body.get("present"):
            out[name] = body
    return out


def build_payload(cluster: dict, *,
                  operator_profile: OperatorProfile | None = None) -> dict:
    """Assemble the structured user-message payload for the primary
    interpretive pass.

    `cluster` is the parsed `research-cluster-v2` snapshot (v8.D output)
    — typically read from `data/serp/<date>/clusters/<hash>.json` OR
    passed directly from `run_research_v2`. Required keys: `topic`,
    `cluster_queries`, `gates`, `per_query_results`. Other keys are
    tolerated (forward-compat for v8.D snapshot evolution).

    `operator_profile` is the loaded `OperatorProfile` dataclass.
    Defaults to None (renders as "no operator profile configured" in
    the summary) so callers that don't have one yet still get a usable
    payload — same convention as the v8.D Phase 3 fallback when the
    operator hasn't run `settings operator` setup.
    """
    per_query = cluster.get("per_query_results") or []
    raw_top_10 = [
        {
            "query": q.get("query"),
            "results": [_trim_organic_result(r)
                        for r in (q.get("organic_results") or [])][:10],
        }
        for q in per_query
    ]
    serp_features = [
        {
            "query": q.get("query"),
            "features": _present_features_only(q.get("features") or {}),
        }
        for q in per_query
    ]
    return {
        "topic": cluster.get("topic"),
        "cluster_queries": cluster.get("cluster_queries") or [],
        "gates": cluster.get("gates") or {},
        "operator_fit": cluster.get("operator_fit") or {},
        "operator_profile_summary": _summarize_operator_profile(operator_profile),
        "raw_top_10_per_query": raw_top_10,
        "serp_features_per_query": serp_features,
    }


# ---------- prompt rendering ----------


def _operator_var_values(profile: OperatorProfile | None) -> dict[str, str]:
    """Return the three operator-related `{{var}}` substitutions for
    the standing prompt.

    No-profile / default-profile maps every var to `"(not configured)"`
    rather than inheriting the OperatorProfile dataclass defaults
    (`mixed` / `monthly`). The LLM should know honestly when operator
    constraints aren't set — dataclass defaults would falsely imply
    the operator chose `mixed` and `monthly` deliberately.

    Set profile renders the actual values; an operator-set profile
    with empty expertise gets `"(none declared)"` for that field so
    the prompt's bullet doesn't render with a trailing colon.
    """
    if profile is None or not _profile_has_content(profile):
        return {
            "operator_expertise": "(not configured)",
            "operator_workflow_preference": "(not configured)",
            "operator_motivation_cadence": "(not configured)",
        }
    expertise = ", ".join(profile.expertise) if profile.expertise else "(none declared)"
    return {
        "operator_expertise": expertise,
        "operator_workflow_preference": profile.workflow_preference,
        "operator_motivation_cadence": profile.motivation_cadence,
    }


def render_primary_prompt(payload: dict, *,
                          operator_profile: OperatorProfile | None = None,
                          prompt_name: str = PRIMARY_PROMPT_NAME) -> str:
    """Assemble the final prompt string for `run_claude_text`.

    Combines:
      1. `prompts/<prompt_name>.md` with the three operator
         `{{var}}` placeholders substituted (or `"(not configured)"`
         when the profile isn't set).
      2. A clear `---` delimiter line.
      3. The structured payload from `build_payload(cluster, ...)`
         JSON-encoded inside a ```json``` fence so it reads cleanly
         in both the prompt itself and any debug snapshot.

    Raises `UnfilledPlaceholderError` (from `prompt_loader.render_prompt`)
    if the prompt file references a placeholder we don't substitute —
    catches drift between the prompt template and the operator-var
    substitution list at the rendering boundary, before the LLM call
    burns a subscription quota slot.

    The Claude CLI subprocess (`run_claude_text`) doesn't currently
    support a separate `--system-prompt` flag, so the system message
    + user message are concatenated into one prompt body. The prompt
    template's own internal structure ("You are evaluating for this
    operator: ... The user message will carry a structured payload:")
    makes that single-string composition read naturally.
    """
    template = load_prompt(prompt_name)
    var_values = _operator_var_values(operator_profile)
    system_part = render_prompt(template, **var_values)
    payload_json = json.dumps(payload, indent=2, default=str)
    return (
        f"{system_part}\n\n"
        f"---\n\n"
        f"INPUT PAYLOAD (JSON):\n\n"
        f"```json\n{payload_json}\n```"
    )
