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
        # v36 — an empty `sitemaps` list here means "not in this GSC-detail
        # snapshot" (e.g. a cache written by the v16c inspection path), NOT a
        # definitive "none submitted" — which contradicted the authoritative
        # State-header Sitemap line (audit + `gsc_sitemap_count`). Defer to it.
        console.print(
            "    [dim]📋 Sitemaps  (none in this GSC-detail snapshot — see the "
            "Sitemap line above for the live audit)[/]"
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
        # v36 — the live coverage fetch came back empty, but the per-domain
        # cache often holds URL inspections (`v16c_inspections`). Surface
        # those instead of the misleading "no URLs inspected — unreachable"
        # (which contradicted the honest State header above).
        inspections = _get(diag, "v16c_inspections", []) or []
        if inspections:
            from .project_seo_diagnostics import _normalize_coverage_state
            console.print(
                f"    [bold]📊 Coverage[/] "
                f"[dim]({len(inspections)} cached URL inspection(s))[/]"
            )
            for insp in inspections:
                if not isinstance(insp, dict):
                    continue
                url = insp.get("url", "?")
                label = insp.get("coverage_state") or "unknown"
                token = (_normalize_coverage_state(label) or "").lower()
                glyph, color = _coverage_glyph(token)
                display_url = url if len(url) <= 38 else url[:18] + "…" + url[-19:]
                line = (f"      [{color}]{glyph}[/] [bold]{display_url:<38}[/] "
                        f"[dim]{label:<28}[/]")
                last_crawl = insp.get("last_crawl_time")
                if last_crawl:
                    line += f"  [dim]crawled {_human_age_from_iso(last_crawl)}[/]"
                console.print(line)
        else:
            console.print(
                "    [dim]📊 Coverage  (no cached URL inspections — "
                "run `--refresh`)[/]"
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


# ---- v35.F (incr 3) — real-SerpAPI + verdict/gates/reconciliation -----
# Moved from cli.py. Console-as-param, intra-module + textwrap only.
# `_confidence_color` / `_VERDICT_COLOR` are shared leaves also used by
# cli-staying code (re-exported from cli.py).


def _confidence_color(confidence: str) -> str:
    """HIGH → green, MEDIUM → yellow, LOW → red. Used by the
    interpretive-verdict header line + the rich render."""
    return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(
        confidence, "white",
    )


_VERDICT_COLOR = {
    "GO": "green",
    "NICHE-DOWN": "yellow",
    "NO-GO": "red",
    "REVIEW_REQUIRED": "magenta",   # v12.E — reconciliation's fourth verdict token
}


def _gate_marker(label: str) -> str:
    """Status glyph + color for a gate label."""
    if label == "PASS":
        return "[green]✓ PASS[/]"
    if label == "FAIL":
        return "[red]✗ FAIL[/]"
    if label == "WEAK-PASS":
        return "[yellow]~ WEAK PASS[/]"
    if label == "PENDING":
        return "[dim]… PENDING[/]"
    return f"[dim]{label}[/]"


def _verdict_marker(verdict: str) -> str:
    if verdict == "GO":
        return "[bold green]GO[/]"
    if verdict == "NICHE-DOWN":
        return "[bold yellow]NICHE-DOWN[/]"
    return "[bold red]NO-GO[/]"


def _render_gates_block(payload: dict, console) -> None:
    """v8.D Phase 2 — gate findings + verdict + suggested reductions."""
    gates = payload.get("gates", {})
    g1 = gates.get("gate_1_market", {})
    g2 = gates.get("gate_2_serp", {})
    g3 = gates.get("gate_3_moat", {})
    verdict = payload.get("verdict", "NO-GO")
    reductions = payload.get("suggested_reductions", []) or []

    def _render_gate(name: str, gate: dict) -> None:
        marker = _gate_marker(gate.get("label", "?"))
        findings = gate.get("findings", []) or []
        first = findings[0] if findings else ""
        console.print(f"  [bold]{name:<20}[/] {marker:<20}  [dim]· {first}[/]")
        for f in findings[1:]:
            console.print(f"  {'':<20} {'':<20}  [dim]· {f}[/]")

    _render_gate("Gate 1 (Market):", g1)
    _render_gate("Gate 2 (SERP):", g2)
    _render_gate("Gate 3 (Moat):", g3)
    console.print()

    console.print(f"  [bold]Verdict:[/] {_verdict_marker(verdict)}")

    if verdict == "NICHE-DOWN" and reductions:
        console.print()
        console.print(f"  [bold]Suggested reductions:[/]")
        for i, red in enumerate(reductions, 1):
            console.print(f"    {i}. {red}")
    console.print()


def _render_primary_verdict_block(payload: dict, console) -> None:
    """Render the v8.I primary interpretive verdict (Claude) block.

    Format intentionally mirrors the v8.D mechanical-gates block above
    it — same color palette for verdict / confidence, same indentation,
    same "Verdict: <token>" header structure — so the reader can scan
    both verdicts side-by-side without re-orienting. Disagreement
    between the two verdicts is the high-signal case v8.J's audit pass
    will dig into.

    Renders only the populated fields. `moat_required=False`, empty
    reductions list, empty operator_fit_warnings, etc. → those
    subsections are skipped (matches the prompt's "leave empty when
    X" convention).
    """
    pv = payload["primary_verdict"]
    meta = payload.get("primary_pass_meta", {})

    verdict = pv.get("verdict", "?")
    confidence = pv.get("confidence", "?")
    v_color = _VERDICT_COLOR.get(verdict, "white")
    c_color = _confidence_color(confidence)

    console.print()
    console.print("  [bold cyan]Interpretive verdict (Claude)[/]")
    cost = meta.get("cost_usd")
    duration = meta.get("duration_s")
    model = meta.get("model_id", "?")
    prompt_ver = meta.get("prompt_version", "?")
    if cost is not None and duration is not None:
        console.print(
            f"    [dim]source: {model} · prompt={prompt_ver} · "
            f"cost=${cost:.4f} · duration={duration:.1f}s[/]"
        )
    console.print(
        f"    [bold]Verdict:[/]    [{v_color}]{verdict}[/]"
    )
    console.print(
        f"    [bold]Confidence:[/] [{c_color}]{confidence}[/]"
    )

    reasoning = (pv.get("reasoning") or "").strip()
    if reasoning:
        from textwrap import fill
        wrapped = fill(reasoning, width=68, initial_indent="      ",
                       subsequent_indent="      ")
        console.print(f"    [bold]Reasoning:[/]")
        console.print(wrapped)

    moat_required = pv.get("moat_required")
    if moat_required:
        console.print(f"    [bold]Moat required:[/] [yellow]yes[/]")
        moat_prompt = (pv.get("moat_prompt") or "").strip()
        if moat_prompt:
            console.print(f"    [dim]    {moat_prompt}[/]")

    reductions = pv.get("reductions") or []
    if reductions:
        console.print(f"    [bold]Suggested reductions:[/]")
        for i, r in enumerate(reductions, 1):
            console.print(f"      {i}. {r}")

    warnings = pv.get("operator_fit_warnings") or []
    if warnings:
        console.print(f"    [bold]Operator-fit warnings:[/]")
        for w in warnings:
            console.print(f"      [yellow]·[/] {w}")

    blind_spot = (pv.get("blind_spot_self_report") or "").strip()
    if blind_spot:
        console.print(f"    [bold dim]Blind-spot self-report:[/]")
        from textwrap import fill
        wrapped = fill(blind_spot, width=68, initial_indent="      ",
                       subsequent_indent="      ")
        console.print(f"[dim]{wrapped}[/]")

    # Disagreement callout — when Claude's verdict differs from the
    # mechanical verdict above, the operator should look at both.
    # v8.J will formalize this with the GPT-4o audit pass; for now,
    # a one-line nudge keeps the disagreement visible.
    mechanical = payload.get("verdict")
    if mechanical and mechanical != verdict:
        console.print(
            f"    [yellow bold]⚠[/] [yellow]Disagreement with mechanical "
            f"verdict ([bold]{mechanical}[/] vs Claude's "
            f"[bold]{verdict}[/]). Both views above; read them carefully.[/]"
        )
    console.print()


def _render_reconciliation_block(payload: dict, console) -> None:
    """v12.E — render the reconciled audit + primary verdict.

    Three render shapes keyed on `audit.agreement_level`:
      - full     → terse one-line confirmation; no caveats block
      - partial  → caveats block populated from audit.specific_concerns
      - disagree → REVIEW_REQUIRED banner; both verdicts surfaced
                   side-by-side; audit's counter_verdict + self-check
                   shown so the operator has both sides to weigh

    Same indentation + color palette as the primary block above so
    the three verdicts (mechanical / primary / reconciled) read as a
    visually consistent cascade. REVIEW_REQUIRED renders in magenta
    to distinguish from NO-GO (red) — they mean very different
    things to the operator.
    """
    audit = payload["audit"]
    rec   = payload["reconciliation"]
    meta  = payload.get("audit_pass_meta", {})

    agreement = audit.get("agreement_level", "?")
    final_verdict     = rec.get("final_verdict", "?")
    final_confidence  = rec.get("final_confidence", "?")
    caveats           = rec.get("caveats") or []
    counter_token     = audit.get("counter_verdict_token", "")
    counter_reasoning = audit.get("counter_verdict_reasoning", "")
    self_check        = (audit.get("audit_self_check") or "").strip()

    v_color = _VERDICT_COLOR.get(final_verdict, "magenta")
    c_color = _confidence_color(final_confidence)

    console.print()
    console.print("  [bold cyan]Reconciliation (audit + primary)[/]")

    model     = meta.get("model_id", "?")
    prompt_ver = meta.get("prompt_version", "?")
    cost      = meta.get("cost_usd")
    duration  = meta.get("duration_s")
    if cost is not None and duration is not None:
        console.print(
            f"    [dim]source: {model} · prompt={prompt_ver} · "
            f"cost=${cost:.4f} · duration={duration:.1f}s[/]"
        )

    agreement_label = {
        "full":     "[green]full agreement[/]",
        "partial":  "[yellow]partial agreement[/]",
        "disagree": "[red bold]disagreement[/]",
    }.get(agreement, f"[dim]{agreement}[/]")
    console.print(f"    [bold]Audit agreement:[/] {agreement_label}")
    console.print(
        f"    [bold]Final verdict:[/]   [{v_color}]{final_verdict}[/]"
    )
    console.print(
        f"    [bold]Final confidence:[/] [{c_color}]{final_confidence}[/]"
    )

    if caveats:
        console.print(f"    [bold]Caveats from audit:[/]")
        for c in caveats:
            console.print(f"      [yellow]·[/] {c}")

    if agreement == "disagree":
        # Render the audit's counter-verdict + the primary's verdict
        # side-by-side. The operator needs both to break the tie.
        console.print(f"    [bold]REVIEW_REQUIRED — verdicts side-by-side:[/]")
        primary_verdict_token = payload.get("primary_verdict", {}).get("verdict", "?")
        p_color = _VERDICT_COLOR.get(primary_verdict_token, "white")
        console.print(
            f"      Primary (Claude): [{p_color}]{primary_verdict_token}[/]"
        )
        if counter_token:
            ct_color = _VERDICT_COLOR.get(counter_token, "white")
            console.print(
                f"      Audit ({model}):   [{ct_color}]{counter_token}[/] — "
                f"{counter_reasoning}"
            )

    if self_check:
        from textwrap import fill
        console.print(f"    [bold dim]Audit self-check:[/]")
        wrapped = fill(self_check, width=68, initial_indent="      ",
                       subsequent_indent="      ")
        console.print(f"[dim]{wrapped}[/]")

    console.print()


def _render_research_v2_full(payload: dict, console) -> None:
    """v8.D renderer for `research-cluster-v2` snapshots. Shows the
    cluster, gates + verdict + reductions (if present), and per-query
    SERP details. Gates section is omitted when `payload["gates"]` is
    absent — keeps the renderer compatible with older snapshots
    written before Phase 2 wired the gates in."""
    topic = payload.get("topic", "?")
    cluster_queries = payload.get("cluster_queries", [])
    per_query = payload.get("per_query_results", [])
    from_cache = payload.get("from_cache", False)
    fetch_errors = payload.get("fetch_errors", [])

    src_line = f"source: SerpAPI · {len(cluster_queries)} queries"
    if from_cache:
        src_line += " · from cluster cache"
    console.print(f"\n[bold]SERP research — \"{topic}\"[/]")
    console.print(f"  [dim]{src_line}[/]\n")

    # Topic on its own line just above the cluster grid — easy
    # reference while scanning the LLM's cluster expansion without
    # having to scroll back to the header.
    console.print(f"  [bold]Topic:[/] [cyan]{topic}[/]")
    console.print()

    # Cluster
    console.print(f"  [cyan]Topic cluster:[/]")
    for i, q in enumerate(cluster_queries, 1):
        marker = "[bold]→[/]" if q.lower() == topic.lower() else " "
        console.print(f"    {marker} {i}. {q}")
    console.print()

    # Gates + verdict + reductions (Phase 2)
    if "gates" in payload:
        _render_gates_block(payload, console)

    # v8.I — primary interpretive verdict (Claude). Lands right after
    # the mechanical gates so the operator reads both verdicts
    # back-to-back; disagreement between them is the high-signal case.
    if "primary_verdict" in payload:
        _render_primary_verdict_block(payload, console)

    # v12.E — reconciliation block (audit + primary). Renders only
    # when --verify was set on this or a prior cached run (i.e., the
    # snapshot has a `reconciliation` field). Sits below the primary
    # block so the operator scans mechanical → primary → audit/
    # reconciliation top-down, matching the verdict-formation order.
    if "reconciliation" in payload:
        _render_reconciliation_block(payload, console)

    # Per-query SERP summaries
    for pq in per_query:
        q = pq.get("query", "?")
        organic = pq.get("organic_results", [])
        features = pq.get("features", {})
        console.print(f"  [bold cyan]Query:[/] {q}")

        # Top 5 organic
        for r in organic[:5]:
            pos = r.get("position", "?")
            dom = r.get("domain", "?")
            console.print(f"    {pos:>2}. [bold]{dom:<28}[/] [dim]{r.get('title', '')[:55]}[/]")

        # Key SERP features (only present ones)
        f_tags = []
        if features.get("ai_overview", {}).get("present"):
            f_tags.append("[yellow]AI Overview[/]")
        if features.get("reddit_card", {}).get("present"):
            pos = features["reddit_card"].get("position", "?")
            f_tags.append(f"[yellow]Reddit #{pos}[/]")
        if features.get("featured_snippet", {}).get("present"):
            f_tags.append("[yellow]Featured snippet[/]")
        if features.get("local_pack", {}).get("present"):
            f_tags.append("[yellow]Local Pack[/]")
        if features.get("video_pack", {}).get("present"):
            f_tags.append("[yellow]Video Pack[/]")
        if f_tags:
            console.print(f"    [dim]Features:[/] " + " · ".join(f_tags))
        console.print()

    if fetch_errors:
        console.print(f"  [yellow]Fetch errors ({len(fetch_errors)}):[/]")
        for err in fetch_errors[:3]:
            console.print(f"    · {err}")

    # v12.F — cost-summary footer. Renders when at least one LLM pass
    # ran (primary or audit); skips on snapshots predating v12.F that
    # don't carry the `costs` block.
    costs = payload.get("costs")
    if costs and costs.get("total_usd", 0.0) > 0:
        primary_usd = costs.get("primary_usd", 0.0)
        audit_usd   = costs.get("audit_usd",   0.0)
        total_usd   = costs.get("total_usd",   0.0)
        # Show the breakdown only when both passes contributed; on a
        # primary-only run, the single number is enough.
        if audit_usd > 0:
            console.print(
                f"  [dim]LLM cost: ${total_usd:.4f} "
                f"(primary ${primary_usd:.4f}, audit ${audit_usd:.4f})[/]"
            )
        else:
            console.print(f"  [dim]LLM cost: ${total_usd:.4f}[/]")


# v35.F incr 5 — fleet-aggregated SEO detail renderers (the `fleet seo --detail`
# sections), extracted from cli.py. Converted to the console-as-param convention
# used throughout this module. The `fleet seo` command callback stays in cli.py
# and calls _render_fleet_seo_detail(only=..., console=console).
def _render_fleet_seo_detail(*, only: str, console) -> None:
    """v16.D — render fleet-aggregated top queries / top pages /
    page-2 opportunities. Reads `gsc_rollup` aggregations across
    every domain in scope."""
    from .data import load_domains, load_plan
    from .gsc_rollup import (
        fleet_aggregated_top_pages,
        fleet_aggregated_top_queries,
        fleet_page_2_opportunities,
    )

    fleet_doms = [d.name for d in load_domains()]
    # Honor the same scope as the upstream `check_seo` call.
    if only and only != "all":
        try:
            plan = load_plan()
            scope_doms = {
                d for d, cat in plan.items()
                if cat and cat.lower() == only.lower()
            }
            fleet_doms = [d for d in fleet_doms if d in scope_doms]
        except Exception:
            # Best-effort scope filter; fall through to full fleet.
            pass

    queries = fleet_aggregated_top_queries(fleet_doms, top_n=10)
    pages = fleet_aggregated_top_pages(fleet_doms, top_n=10)
    p2 = fleet_page_2_opportunities(fleet_doms, top_n=15)

    console.print()
    _render_top_queries_section(queries, console)
    console.print()
    _render_top_pages_section(pages, console)
    console.print()
    _render_page_2_opportunities_section(p2, console)
    console.print(
        "\n[dim]Source: per-domain GSC cache "
        "(`data/gsc/<domain>/<UTC-today>.json`). "
        "Populate via `lamill project seo <domain>`.[/]"
    )


def _render_top_queries_section(queries: list, console) -> None:
    tag = "" if queries else " [dim](empty — no cached query data)[/]"
    console.print(f"[bold]🔎 Top queries (fleet-aggregated, 28d){tag}[/]")
    if not queries:
        return
    t = Table(show_header=True, header_style="bold", box=None,
              padding=(0, 1))
    t.add_column("Query")
    t.add_column("Sites", justify="right")
    t.add_column("Imp", justify="right")
    t.add_column("Clicks", justify="right")
    for key, imp, clicks, sites in queries:
        t.add_row(key, str(sites), f"{imp:,}", f"{clicks:,}")
    console.print(t)


def _render_top_pages_section(pages: list, console) -> None:
    tag = "" if pages else " [dim](empty — no cached page data)[/]"
    console.print(f"[bold]📄 Top pages (fleet-aggregated, 28d){tag}[/]")
    if not pages:
        return
    t = Table(show_header=True, header_style="bold", box=None,
              padding=(0, 1))
    t.add_column("URL")
    t.add_column("Imp", justify="right")
    t.add_column("Clicks", justify="right")
    for url, imp, clicks in pages:
        short_url = url if len(url) <= 60 else url[:57] + "…"
        t.add_row(short_url, f"{imp:,}", f"{clicks:,}")
    console.print(t)


def _render_page_2_opportunities_section(p2: list, console) -> None:
    tag = "" if p2 else " [dim](empty — no qualifying pages, pos 11-20 / imp ≥50)[/]"
    console.print(f"[bold]💡 Page-2 opportunities (fleet-summed){tag}[/]")
    if not p2:
        return
    t = Table(show_header=True, header_style="bold", box=None,
              padding=(0, 1))
    t.add_column("Site")
    t.add_column("URL")
    t.add_column("Imp", justify="right")
    t.add_column("Pos", justify="right")
    for site, url, imp, pos in p2:
        short_url = url if len(url) <= 50 else url[:47] + "…"
        t.add_row(site, short_url, f"{imp:,}", f"{pos:.1f}")
    console.print(t)


# v35.F incr 6 — Google Trends payload renderer (the `new trends` output),
# extracted from cli.py. console-as-param convention. The `new trends`
# command callback stays in cli.py and calls _render_trends(payload, console).
def _render_trends(payload, console) -> None:
    """Render a `TrendsPayload` to the console — interest-over-time
    sparkline table + related queries (top + rising)."""
    from .gtrends import payload_age_hours, DEFAULT_TTL_HOURS

    # 2026-05-22 — stale-cache warning header. Payloads returned via
    # L1 fallback (rate-limit recovery) can be arbitrarily old; surface
    # the age so the operator knows the data is stale and can decide
    # whether to wait + retry with --refresh.
    age = payload_age_hours(payload)
    is_stale = age is not None and age > DEFAULT_TTL_HOURS
    if is_stale:
        # Format age compactly: 47h or 3d.
        if age < 48:
            age_str = f"{int(age)}h"
        else:
            age_str = f"{int(age / 24)}d"
        console.print(
            f"\n[yellow]⚠[/]  [yellow]Stale cache fallback[/] — "
            f"Google Trends rate-limited; serving last cached payload "
            f"([yellow]{age_str} old[/]). Wait 10-30 min and retry "
            f"with [cyan]--refresh[/] for fresh data."
        )

    console.print(
        f"\n[bold]Google Trends:[/] [cyan]{payload.topic}[/] "
        f"[dim]({payload.timeframe} · "
        f"{payload.region or 'worldwide'} · "
        f"fetched {payload.fetched_at[:19]})[/]"
    )

    if payload.interest_over_time:
        console.print("\n[bold]Interest over time[/]")
        values = [r["value"] for r in payload.interest_over_time]
        peak = max(values) if values else 0
        bar_width = 30

        # 12m timeframe = ~52 weekly rows; sample down so the output
        # fits on a screen. 5y = ~260 rows; same logic.
        n_rows = len(payload.interest_over_time)
        if n_rows <= 10:
            sample_rows = payload.interest_over_time
        else:
            step = max(1, n_rows // 7)
            indices = list(range(0, n_rows, step))
            if (n_rows - 1) not in indices:
                indices.append(n_rows - 1)
            sample_rows = [payload.interest_over_time[i] for i in indices]

        for row in sample_rows:
            value = row["value"]
            pct = value / peak if peak else 0
            bar_len = int(pct * bar_width)
            bar = "█" * bar_len + "·" * (bar_width - bar_len)
            console.print(
                f"  {row['date']}  [dim]{bar}[/]  [cyan]{value:>3}[/]"
            )

        # Trend-direction badge — last vs first.
        first_val = payload.interest_over_time[0]["value"]
        last_val = payload.interest_over_time[-1]["value"]
        if first_val > 0:
            change_pct = (last_val - first_val) / first_val * 100
            if change_pct > 10:
                arrow = "[green]rising[/]"
            elif change_pct < -10:
                arrow = "[red]declining[/]"
            else:
                arrow = "[yellow]flat[/]"
            console.print(
                f"  [dim]Direction over window:[/] {arrow} "
                f"[cyan]{change_pct:+.0f}%[/]"
            )
    else:
        console.print("\n[yellow]No interest-over-time data returned.[/]")

    if payload.related_top:
        console.print("\n[bold]Related queries — top[/]")
        for r in payload.related_top[:10]:
            console.print(f"  [cyan]{r['value']:>3}[/]  {r['query']}")

    if payload.related_rising:
        console.print("\n[bold]Related queries — rising[/]")
        for r in payload.related_rising[:10]:
            v = r["value"]
            v_str = "↑↑" if v is None else f"+{v}%"
            console.print(f"  [cyan]{v_str:>6}[/]  {r['query']}")

    if not (payload.related_top or payload.related_rising):
        console.print("\n[dim]No related-queries data returned.[/]")


# v36 — `project seo` problem-surfacing diagnostic (State header + Blockers).
# Project-scoped; the fleet table's emoji grade is unchanged.

_SEO_STATE_COLOR = {"healthy": "green", "unproven": "cyan", "blocked": "red"}


def render_seo_state_header(diag, console) -> None:
    """The honest headline above the table: State + the Index/Sitemap signals
    that drive it. `diag` is a `seo_diagnose.SeoDiagnosis`."""
    from .seo_diagnose import STATE_RENDER

    glyph, label = STATE_RENDER[diag.state]
    color = _SEO_STATE_COLOR.get(diag.state, "white")
    console.print()
    console.print(f"  [bold {color}]{glyph} SEO state: {label}[/]")

    # Index — surfaced from the cached GSC URL inspections (the headline the
    # old block hid behind "no URLs inspected").
    idx = diag.index_insights
    if idx:
        home = next((i for i in idx
                     if i.url.rstrip("/") == diag.origin.rstrip("/")), idx[0])
        istate = home.coverage_label or home.coverage_state or "?"
        icolor = "green" if home.is_indexed else "red"
        more = f"  [dim](+{len(idx) - 1} more URL(s))[/]" if len(idx) > 1 else ""
        console.print(f"    [bold]Index[/]   [{icolor}]{istate}[/]{more}")
    else:
        console.print("    [bold]Index[/]   [dim]no cached URL inspections "
                      "(run `--refresh`)[/]")

    # Sitemap — honest: URL count + submitted + reachable (replaces the
    # /sitemap.xml-returns-200 cell that contradicted this block).
    sm = diag.sitemap_audit
    if sm is None:
        console.print("    [bold]Sitemap[/] [dim]not probed[/]")
    elif not sm.reachable:
        console.print(f"    [bold]Sitemap[/] [red]unreachable[/] "
                      f"[dim]({sm.error or 'unknown'})[/]")
    else:
        bits = [f"{sm.url_count} URL{'' if sm.url_count == 1 else 's'}",
                "submitted" if sm.submitted_to_gsc else "not submitted",
                "reachable"]
        scolor = "green" if sm.healthy else "yellow"
        console.print(f"    [bold]Sitemap[/] [{scolor}]{' · '.join(bits)}[/]")


def render_seo_blockers(diag, console) -> None:
    """The Blockers section — the whole point. A prioritized ⛔/⚠ list with
    next actions, even when lamill can't fix the cause. Never silent when the
    state isn't healthy."""
    blockers = diag.blockers
    console.print()
    if not blockers:
        if diag.state == "healthy":
            console.print("  [green]✓ No blockers detected — site is earning "
                          "traffic.[/]")
        else:
            console.print("  [cyan]✓ No blockers detected yet — give the "
                          "freshness window time, then re-check.[/]")
        for n in diag.notes:
            console.print(f"    [dim]↷ {n}[/]")
        return

    console.print(f"  [bold red]⛔ Blockers[/] [dim]({len(blockers)} — why this "
                  f"site earns no traffic)[/]")
    for b in blockers:
        color = "red" if b.kind == "blocker" else "yellow"
        console.print(f"    [{color}]{b.glyph} {b.title}[/]")
        console.print(f"      [dim]{b.detail}[/]")
        console.print(f"      [dim]→ {b.next_action}[/]")
    for n in diag.notes:
        console.print(f"    [dim]↷ {n}[/]")
