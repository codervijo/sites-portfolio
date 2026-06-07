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


# ---- v35.F (incr 2) — project SEO diagnostics renderer (v13.B) -------
# Moved from cli.py. Self-contained: console-as-param, stdlib-only
# (datetime / textwrap imported locally), no cli back-dependency.


_SITEMAP_STATUS_GLYPH = {
    "OK":      ("✓", "green"),
    "WARN":    ("⚠", "yellow"),
    "PENDING": ("…", "dim"),
    "ERROR":   ("✗", "red"),
}


def _coverage_glyph(state: str | None) -> tuple[str, str]:
    """Map URL Inspection coverage_state → (glyph, rich-color).
    `submitted_indexed` is the happy path; everything else is a
    failure mode the renderer should call out."""
    if not state:
        return ("?", "dim")
    if state == "submitted_indexed":
        return ("✓", "green")
    return ("✗", "red")


def _hint_severity_color(severity: str) -> str:
    return {"error": "red", "warn": "yellow", "info": "dim"}.get(
        severity, "default",
    )


def _human_age_from_iso(iso: str | None) -> str:
    """`2026-05-19T07:02:23+00:00` → `1d ago` etc. Returns `—` on
    parse failure or None. Same shape as the rest of the CLI's
    age renderers (1h / 1d / 12d / 4w / 8y)."""
    if not iso:
        return "—"
    try:
        from datetime import datetime, timezone
        ts = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc)
        delta = now - ts
        secs = int(delta.total_seconds())
        if secs < 3600:
            return f"{max(1, secs // 60)}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        if secs < 86400 * 14:
            return f"{secs // 86400}d ago"
        if secs < 86400 * 90:
            return f"{secs // (86400 * 7)}w ago"
        # 2026-05-28 — months branch. Without it, any delta in the
        # 90-364 day range fell through to the years branch and rendered
        # "0y ago" (secs // (86400*365) == 0). Surface "Nmo ago" instead.
        if secs < 86400 * 365:
            return f"{secs // (86400 * 30)}mo ago"
        return f"{secs // (86400 * 365)}y ago"
    except (ValueError, TypeError):
        return "—"


def _render_project_seo_diagnostics(diag, console) -> None:
    """v13.B — render the diagnostics block (sitemaps + coverage +
    hints) for one domain. Accepts a `ProjectSeoDiagnostics`
    dataclass instance OR a dict reconstructed from the cache;
    duck-typed access (`getattr`/`.get`) keeps both shapes
    supported."""
    # Normalize access — works for both dataclass and dict.
    def _get(obj, key, default=None):
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    not_registered = _get(diag, "not_registered", False)
    property_url   = _get(diag, "property_url", "")
    sitemaps       = _get(diag, "sitemaps", []) or []
    coverage       = _get(diag, "coverage", []) or []
    hints          = _get(diag, "hints", []) or []

    console.print()
    if not_registered:
        # Single-line "not in GSC" + the registration hint. No
        # sitemap / coverage block — nothing to show.
        console.print(
            "  [yellow]Property:[/] [dim]not registered in GSC[/]"
        )
        for h in hints:
            text = _get(h, "text", "")
            console.print(f"  [dim]💡 {text}[/]")
        console.print()
        return

    console.print(f"  [bold cyan]GSC diagnostics[/]")
    if property_url:
        console.print(f"    [dim]Property: {property_url}[/]")

    # 📋 Sitemaps
    if sitemaps:
        console.print(f"    [bold]📋 Sitemaps[/] [dim]({len(sitemaps)} submitted)[/]")
        for sm in sitemaps:
            status = _get(sm, "status", "OK")
            path   = _get(sm, "path", "?")
            errs   = _get(sm, "errors", 0)
            warns  = _get(sm, "warnings", 0)
            last_dl = _get(sm, "last_downloaded")
            summary = _get(sm, "error_summary", "")
            glyph, color = _SITEMAP_STATUS_GLYPH.get(status, ("·", "white"))
            line = (
                f"      [{color}]{glyph} {status:<8}[/] [bold]{path:<32}[/] "
            )
            tail_bits: list[str] = []
            if warns:
                tail_bits.append(f"{warns} warning(s)")
            if last_dl:
                tail_bits.append(f"fetched {_human_age_from_iso(last_dl)}")
            if summary:
                # 2026-05-28 — when GSC is mid-refetch (PENDING), the
                # error count is from the prior fetch and may clear on
                # the next download. Annotate so the operator doesn't
                # chase a stale error.
                if status == "PENDING":
                    tail_bits.append(
                        f"{summary} from prior fetch (clears on next download)"
                    )
                else:
                    tail_bits.append(summary)
            if tail_bits:
                line += "[dim]" + "  ·  ".join(tail_bits) + "[/]"
            console.print(line)
    else:
        console.print(
            "    [yellow]📋 Sitemaps[/] [dim]none submitted[/]"
        )

    # 📊 Coverage
    if coverage:
        # Headline: how many indexed of how many inspected.
        indexed_count = sum(
            1 for c in coverage
            if (_get(c, "coverage_state") or "").lower() == "submitted_indexed"
        )
        total = len(coverage)
        pct = (indexed_count * 100 // total) if total else 0
        console.print(
            f"    [bold]📊 Coverage[/] "
            f"[dim](top {total} inspected — {indexed_count}/{total} indexed, {pct}%)[/]"
        )
        for cv in coverage:
            state = (_get(cv, "coverage_state") or "").lower()
            url   = _get(cv, "url", "?")
            verdict = _get(cv, "verdict")
            last_crawl = _get(cv, "last_crawl_at")
            err = _get(cv, "error")
            glyph, color = _coverage_glyph(state)
            # Truncate long URLs from the middle so the prefix +
            # path leaf both stay visible.
            display_url = url if len(url) <= 38 else url[:18] + "…" + url[-19:]
            state_display = state or ("error" if err else "unknown")
            line = (
                f"      [{color}]{glyph}[/] "
                f"[bold]{display_url:<38}[/] "
                f"[dim]{state_display:<24}[/]"
            )
            tail_bits: list[str] = []
            if verdict and verdict != "PASS":
                tail_bits.append(f"verdict={verdict}")
            if last_crawl:
                tail_bits.append(f"crawled {_human_age_from_iso(last_crawl)}")
            if err:
                tail_bits.append(err[:40])
            if tail_bits:
                line += "  [dim]" + " · ".join(tail_bits) + "[/]"
            console.print(line)
    else:
        console.print(
            "    [dim]📊 Coverage  (no URLs inspected — sitemap unreachable)[/]"
        )

    # 💡 Hints
    if hints:
        console.print(f"    [bold]💡 Hints[/]")
        for h in hints:
            severity = _get(h, "severity", "info")
            text = _get(h, "text", "")
            color = _hint_severity_color(severity)
            # Soft-wrap long hints at 70 chars with 6-space indent.
            from textwrap import fill as _fill
            wrapped = _fill(
                text, width=72, initial_indent="", subsequent_indent="        ",
            )
            console.print(f"      [{color}]·[/] {wrapped}")

    console.print()
