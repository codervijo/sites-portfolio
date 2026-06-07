"""v35.F — presentation helpers for `new validate` SERP-synthesis output.

Extracted from the `cli.py` monolith (H1 of the v35 register). These are
pure renderers: each takes the `rich` `console` as a parameter (no module
state) and reads a payload dict, so they have no dependency back on
`cli.py` — the import is one-directional (`cli` imports these), no cycle.

Synthesis output hallucinates domain names + invents competitive signals,
so these renderers hard-block the competitive verdict surface and keep only
ideation-safe sections. The companion real-SerpAPI renderer
(`_render_research_v2_full`) still lives in `cli.py` and is unaffected.
"""
from __future__ import annotations


_SYNTHESIS_PREFIX = "[red][SYNTHESIS ONLY — not real SERP data][/]"

_VERDICT_BLOCKED_BLOCK = (
    "\n  [red bold]⛔ VERDICT BLOCKED — source is AI synthesis, not real SERP data.[/]\n"
    "  [dim]Competitive verdicts (rankers, saturation, ship/mixed/wait) are\n"
    "  blocked because synthesis output hallucinates domain names and\n"
    "  invents competitive signals that look real but aren't.\n\n"
    "  Run again when SerpAPI quota resets, or keep using --synthesis-only\n"
    "  for ideation only (angles + content patterns + cluster queries are OK).[/]\n"
)


def _render_serp_full(payload: dict, console) -> None:
    """Default rendering for AI-synthesized SERP analysis.

    Synthesis outputs hallucinate domain names and invent competitive
    signals (saturation, rankers, ship/mixed/wait decisions) that read
    as real but aren't grounded in any SERP data. To prevent the
    operator from acting on those false signals, this renderer:

      - Hard-blocks the competitive verdict surface with a loud banner
      - Strips top_likely_rankers, competitive_signal (saturation/
        barrier/YMYL), per_query_summary (decision hints), final
        decision + decision-reasoning from the rendered output
      - Keeps only ideation-safe surfaces: cluster_queries,
        content_patterns, suggested_angles
      - Prefixes every kept section header with the
        "[SYNTHESIS ONLY — not real SERP data]" marker so a reader
        scanning the output can't mistake it for research data

    Real-SerpAPI payloads (v8.D `research-cluster-v2`) render via
    `_render_research_v2_full`, which is unaffected by this gate.
    """
    topic = payload.get("topic", "?")
    analysis = payload.get("analysis", {})
    caveat = payload.get("knowledge_caveat", "")
    from_cache = payload.get("from_cache", False)
    mode = payload.get("mode", "strict")

    mode_label = "cluster mode" if mode == "cluster" else "strict mode (literal topic)"
    src_line = f"source: AI synthesis ({payload.get('model', 'gpt-4o-mini')}) · {mode_label}"
    if from_cache:
        src_line += f" · cached {payload.get('cache_age_days', '?')}d ago"
    console.print(f"\n[bold]SERP research — \"{topic}\"[/]")
    console.print(f"  [dim]{src_line} · {caveat}[/]")

    # Verdict block — front-and-center so the reader sees it before any
    # ideation content. The block exits with a blank line so the
    # ideation sections render visibly separate.
    console.print(_VERDICT_BLOCKED_BLOCK)

    # ---------- Kept (ideation-safe) ----------

    # Topic on its own line just above the cluster grid — easy
    # reference while scanning the LLM's cluster expansion without
    # having to scroll back to the header (and past the verdict-
    # blocked block).
    console.print(f"  [bold]Topic:[/] [cyan]{topic}[/]")
    console.print()

    # Cluster queries — list of search strings. No domains, no scores,
    # no verdicts; just records what was queried.
    if mode == "cluster":
        cluster_queries = analysis.get("cluster_queries", [])
        if cluster_queries:
            console.print(
                f"  {_SYNTHESIS_PREFIX} [cyan]Topic cluster[/] "
                f"[dim]({len(cluster_queries)} queries):[/]"
            )
            for i, q in enumerate(cluster_queries, 1):
                marker = "[bold]→[/]" if q.lower() == topic.lower() else " "
                console.print(f"    {marker} {i}. {q}")
            console.print()

    # Content patterns — general patterns the LLM extracted (e.g.
    # "comparison tables dominate", "video-heavy"). General prose, not
    # domain claims.
    patterns = analysis.get("content_patterns", [])
    if patterns:
        console.print(f"  {_SYNTHESIS_PREFIX} [cyan]Content patterns:[/]")
        for p in patterns:
            console.print(f"    · {p}")

    # Suggested angles — ideation prompts. Not claims about competition.
    angles = analysis.get("suggested_angles", [])
    if angles:
        console.print(f"\n  {_SYNTHESIS_PREFIX} [cyan]Suggested angles:[/]")
        for i, a in enumerate(angles, 1):
            console.print(f"    {i}. {a}")

    # ---------- Intentionally NOT rendered (would be unsafe) ----------
    #
    #   analysis["top_likely_rankers"]      — hallucinated domain names
    #   analysis["competitive_signal"]      — saturation / barrier / YMYL
    #   analysis["per_query_summary"]       — ship/mixed/skip hints
    #   analysis["decision"] / reasoning    — final verdict
    #
    # See the verdict-blocked banner above for the operator-facing
    # explanation; see `_strip_unsafe_synthesis_fields` for the JSON
    # rendering's equivalent.

    console.print()


def _render_serp_brief(payload: dict, console) -> None:
    """Compact one-screen rendering for synthesis output.

    Same guardrails as `_render_serp_full`: no decision, no saturation,
    no rankers. Just the topic + the top-3 angles + the verdict-
    blocked marker so brief mode can't be (mis)used as a "quick
    decision aid" on synthesis data.
    """
    topic = payload.get("topic", "?")
    analysis = payload.get("analysis", {})

    console.print(
        f"\n[bold]{topic}[/]  [red]⛔ VERDICT BLOCKED — AI synthesis[/]"
    )
    angles = analysis.get("suggested_angles", [])[:3]
    if angles:
        console.print(f"  {_SYNTHESIS_PREFIX} [cyan]Suggested angles:[/]")
        for a in angles:
            console.print(f"    · {a}")
    console.print(
        "  [dim]Run again with real SerpAPI for a competitive verdict.[/]"
    )
    console.print()


# Fields stripped from JSON payloads before emit when source is AI synthesis.
# Mirrors what the rich renderer hides — keeps `--json` output from carrying
# the same hallucinated competitive signals as the human-facing render.
_UNSAFE_SYNTHESIS_FIELDS: tuple[str, ...] = (
    "top_likely_rankers",
    "competitive_signal",
    "per_query_summary",
    "decision",
    "reasoning",
)


def _strip_unsafe_synthesis_fields(payload: dict) -> dict:
    """Return a copy of `payload` with verdict-related fields stripped
    from `payload["analysis"]`. Annotates with `verdict_blocked: true`
    plus a `verdict_blocked_reason` so downstream JSON consumers can
    detect the blocked state programmatically.

    Pure function — caller passes the original payload through, used
    by `_render_serp_json` before emit.
    """
    out = dict(payload)
    out["verdict_blocked"] = True
    out["verdict_blocked_reason"] = (
        "AI synthesis — competitive verdict suppressed to prevent acting "
        "on hallucinated domains / fabricated saturation signals. Use "
        "real SerpAPI data for verdicts."
    )
    analysis = dict(payload.get("analysis") or {})
    for f in _UNSAFE_SYNTHESIS_FIELDS:
        analysis.pop(f, None)
    out["analysis"] = analysis
    return out


def _render_serp_json(payload: dict) -> None:
    """Emit raw analysis JSON (suitable for piping / scripting).

    Synthesis payloads are sanitized first — `top_likely_rankers`,
    `competitive_signal`, `per_query_summary`, `decision`, and the
    decision-reasoning are stripped from `analysis`, and
    `verdict_blocked` + `verdict_blocked_reason` are added at the
    top level so downstream scripts can detect the blocked state.
    """
    import json as _json
    safe = _strip_unsafe_synthesis_fields(payload)
    print(_json.dumps(safe, indent=2))
