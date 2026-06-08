"""v35.F incr 9 — `new validate` research-orchestration cluster, extracted
from cli.py (behavior-preserving, H1; approach A — sibling module).

The interpretive/audit/gates/synthesis passes + moat prompt + cost-summary
updater behind `new validate`. Pure orchestration (the SERP/verdict
*rendering* lives in research_render, imported here one-directionally).
cli.py re-exports every name; the `@new_app.command("validate")` callback
stays in cli.py.
"""
from __future__ import annotations

import typer

from .console import console
from .research_render import (
    _VERDICT_COLOR,
    _confidence_color,
    _render_serp_brief,
    _render_serp_full,
    _render_serp_json,
)


def _run_primary_interpretive_pass(topic: str, payload: dict, *, console) -> None:
    """Wire `run_primary_pass` into the research flow.

    Loads the operator profile from `sites/portfolio/lamill.toml`,
    runs the primary pass, persists the parsed verdict + metadata
    into the cluster snapshot. Mutates `payload` in place so the
    downstream renderer picks it up.

    Non-fatal on failure — `claude` CLI absent / timeout / quota
    exhausted / unparseable response all log a yellow warning and
    let the rest of the command continue. The mechanical v8.D
    verdict above is still valuable on its own.
    """
    from pathlib import Path
    from .interpretive_pass import (
        InterpretivePassError, run_primary_pass,
    )
    from .operator_profile import load_operator_profile
    from .research_v2 import save_cluster_snapshot

    profile = load_operator_profile()

    console.print(
        "[cyan]Running primary interpretive pass (Claude CLI subprocess)..."
        "[/] [dim](~5-15s, no API cost)[/]"
    )
    try:
        result = run_primary_pass(
            payload, operator_profile=profile, cwd=Path("."),
        )
    except InterpretivePassError as e:
        console.print(f"[yellow]  ✗ Interpretive pass skipped: {e}[/]")
        return

    # Persist the parsed verdict as a flat dict so JSON output +
    # downstream consumers don't need to import the dataclass.
    payload["primary_verdict"] = {
        "verdict": result.verdict.verdict,
        "confidence": result.verdict.confidence,
        "reasoning": result.verdict.reasoning,
        "moat_required": result.verdict.moat_required,
        "moat_prompt": result.verdict.moat_prompt,
        "reductions": result.verdict.reductions,
        "operator_fit_warnings": result.verdict.operator_fit_warnings,
        "blind_spot_self_report": result.verdict.blind_spot_self_report,
    }
    # Metadata kept under its own key — separates "what the LLM said"
    # from "how / how-much it cost" for the snapshot reader.
    payload["primary_pass_meta"] = {
        "prompt_version": result.prompt_version,
        "model_id": result.model_id,
        "rendered_prompt": result.rendered_prompt,
        "cost_usd": result.cost_usd,
        "duration_s": result.duration_s,
    }

    console.print(
        f"[green]  ✓ Interpretive verdict: {result.verdict.verdict} "
        f"([{_confidence_color(result.verdict.confidence)}]"
        f"{result.verdict.confidence}[/])[/] "
        f"[dim](cost=${result.cost_usd:.4f}, "
        f"duration={result.duration_s:.1f}s)[/]"
    )

    # v12.F — refresh the snapshot's `costs` block. Idempotent; audit
    # pass updates it again later if --verify ran.
    _update_cost_summary(payload)

    try:
        save_cluster_snapshot(topic, payload)
    except OSError as e:
        console.print(f"[dim]warn: could not persist interpretive verdict: {e}[/]")


def _run_audit_pass_and_reconcile(topic: str, payload: dict, *,
                                  audit_model: str, console) -> None:
    """v12.E — wire the adversarial audit pass + reconciliation into
    the research flow.

    Runs after `_run_primary_interpretive_pass` when `--verify` is
    set. Loads the operator profile, calls `run_audit_pass` with the
    requested model, reconciles primary + audit into a final verdict
    via `reconcile()`, persists everything into the cluster snapshot.
    Mutates `payload` in place — the renderer + JSON output pick it
    up without a second pass.

    Non-fatal on failure: `AuditPassError` (OpenAI HTTP / transport /
    parse) logs a yellow warning and returns. The primary verdict
    above is still useful on its own — the audit's absence just
    means no second-opinion was added.
    """
    from .audit_pass import AuditPassError, run_audit_pass
    from .interpretive_pass import ParsedVerdict
    from .operator_profile import load_operator_profile
    from .reconciliation import reconcile
    from .research_v2 import save_cluster_snapshot

    profile = load_operator_profile()
    pv_dict = payload["primary_verdict"]

    console.print(
        f"[cyan]Running adversarial audit pass ({audit_model})...[/] "
        f"[dim](~10-30s, cost ~$0.01-0.02)[/]"
    )
    try:
        result = run_audit_pass(
            payload,
            primary_verdict=pv_dict,
            operator_profile=profile,
            model=audit_model,
        )
    except AuditPassError as e:
        console.print(f"[yellow]  ✗ Audit pass skipped: {e}[/]")
        return

    # Persist parsed audit as a flat dict — JSON output + downstream
    # consumers shouldn't need to import the ParsedAudit dataclass.
    payload["audit"] = {
        "agreement_level":        result.audit.agreement_level,
        "confidence":             result.audit.confidence,
        "specific_concerns":      list(result.audit.specific_concerns),
        "counter_verdict_token":  result.audit.counter_verdict_token,
        "counter_verdict_reasoning": result.audit.counter_verdict_reasoning,
        "audit_self_check":       result.audit.audit_self_check,
    }
    payload["audit_pass_meta"] = {
        "prompt_version": result.prompt_version,
        "model_id":       result.model_id,
        "rendered_prompt": result.rendered_prompt,
        "cost_usd":       result.cost_usd,
        "duration_s":     result.duration_s,
    }

    # Reconcile — rebuild ParsedVerdict from the persisted flat dict
    # so `reconcile()` does pure-logic work without knowing the
    # snapshot's serialization shape.
    parsed_primary = ParsedVerdict(
        verdict=pv_dict["verdict"],
        confidence=pv_dict["confidence"],
        reasoning=pv_dict.get("reasoning", ""),
        moat_required=pv_dict.get("moat_required"),
        moat_prompt=pv_dict.get("moat_prompt", ""),
        reductions=list(pv_dict.get("reductions") or []),
        operator_fit_warnings=list(pv_dict.get("operator_fit_warnings") or []),
        blind_spot_self_report=pv_dict.get("blind_spot_self_report", ""),
    )
    rec = reconcile(parsed_primary, result.audit)
    payload["reconciliation"] = {
        "final_verdict":     rec.final_verdict,
        "final_confidence":  rec.final_confidence,
        "caveats":           list(rec.caveats),
    }

    # Operator one-liner — yellow when REVIEW_REQUIRED (operator must
    # decide), green otherwise.
    line_color = "yellow" if rec.requires_review else "green"
    v_color = _VERDICT_COLOR.get(rec.final_verdict, "magenta")
    c_color = _confidence_color(rec.final_confidence)
    console.print(
        f"[{line_color}]  ✓ Audit:[/] [bold]{result.audit.agreement_level}[/] "
        f"→ final: [{v_color}]{rec.final_verdict}[/] "
        f"([{c_color}]{rec.final_confidence}[/]) "
        f"[dim](cost=${result.cost_usd:.4f}, "
        f"duration={result.duration_s:.1f}s)[/]"
    )

    # v12.F — refresh the snapshot's `costs` block to include the
    # audit pass. Primary's cost was added when the primary helper
    # ran; this call rolls them up together.
    _update_cost_summary(payload)

    try:
        save_cluster_snapshot(topic, payload)
    except OSError as e:
        console.print(
            f"[dim]warn: could not persist audit + reconciliation: {e}[/]"
        )


def _update_cost_summary(payload: dict) -> None:
    """v12.F — recompute the cluster-snapshot `costs` block from the
    individual pass metas. Idempotent; safe to call after either
    pass writes its meta. Aggregates only LLM costs — SerpAPI quota
    consumption is tracked separately in `data/serp/_quota.json`
    (a monthly ledger, not a per-run line item) so mixing them
    here would double-count.

    Block shape: `{primary_usd, audit_usd, total_usd, currency}`.
    Missing pass metas contribute 0.0. The `currency` field is
    fixed to USD today; surfaced for future-proofing (no current
    plan to charge in anything else, but pinning the unit is
    cheap insurance).
    """
    primary = (payload.get("primary_pass_meta") or {}).get("cost_usd", 0.0) or 0.0
    audit   = (payload.get("audit_pass_meta")   or {}).get("cost_usd", 0.0) or 0.0
    payload["costs"] = {
        "primary_usd": float(primary),
        "audit_usd":   float(audit),
        "total_usd":   float(primary + audit),
        "currency":    "USD",
    }


def _run_gates_with_prompt(cluster: dict, *, console,
                           non_interactive: bool):
    """Run Gate 1 + Gate 2, prompt for moat if required, then Gate 3 +
    verdict + reductions. Returns a `GateResults`.

    Splitting the orchestration here (vs calling `evaluate_cluster()`
    directly) lets the prompt land between Gate 2 and Gate 3 without
    re-running Gate 1's LLM volume call.
    """
    from .operator_profile import (
        evaluate_operator_fit, load_operator_profile,
    )
    from .research_gates import (
        VERDICT_NICHE_DOWN, GateResults,
        evaluate_gate_1, evaluate_gate_2, evaluate_gate_3,
        is_moat_required, suggest_reductions, synthesize_verdict,
    )
    g1 = evaluate_gate_1(cluster)
    g2 = evaluate_gate_2(cluster)
    moat_sentence: str | None = None
    if not non_interactive and is_moat_required(g2):
        moat_sentence = _prompt_for_moat(g2, console)
    g3 = evaluate_gate_3(g2, moat_sentence, non_interactive=non_interactive)
    op_fit = evaluate_operator_fit(cluster, load_operator_profile())
    verdict = synthesize_verdict(g1, g2, g3, op_fit=op_fit)
    reductions: list[str] = []
    if verdict == VERDICT_NICHE_DOWN:
        reductions = suggest_reductions(cluster.get("topic", ""), g1, g2, g3)
    return GateResults(
        gate_1_market=g1, gate_2_serp=g2, gate_3_moat=g3,
        operator_fit=op_fit, verdict=verdict,
        suggested_reductions=reductions,
        moat_required=is_moat_required(g2),
        moat_provided=moat_sentence,
    )


def _prompt_for_moat(g2, console) -> str | None:
    """Interactive prompt for Gate 3 — shown only when Gate 2 detected
    a specialty/programmatic incumbent."""
    cls = g2.raw.get("classifications", {})
    triggers = []
    spec = cls.get("specialty_incumbent", {})
    if isinstance(spec, dict) and spec.get("present"):
        triggers.append("a specialty incumbent")
    prog = cls.get("programmatic_at_scale", {})
    if isinstance(prog, dict) and prog.get("present"):
        triggers.append("a programmatic incumbent")
    trigger_str = " + ".join(triggers) or "an incumbent"

    console.print()
    console.print(f"  [bold yellow]Gate 3 (Moat):[/] Required because Gate 2 detected {trigger_str}.")
    console.print('  Format: [dim]"I will win on [query pattern] because [incumbent gap],')
    console.print('           and the incumbent cannot close this gap in 6 months because')
    console.print('           [structural reason]."[/]')
    console.print()
    console.print("  Enter your moat sentence (or press Enter to skip and accept NO-GO):")
    try:
        line = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None
    return line or None


def _run_research_synthesis(topic: str, *, no_cache: bool,
                            brief: bool, json_out: bool) -> None:
    """Synthesis-only path — explicit opt-in via `--synthesis-only`.
    Prints the loud "NOT REAL SERP DATA" banner before running."""
    from .serp import ResearchError, research

    console.print(
        "[yellow]⚠  source: GPT synthesis (--synthesis-only) — NOT REAL SERP DATA[/]\n"
        "[dim]   knowledge cutoff applies; verdicts are heuristic only.[/]"
    )
    try:
        payload = research(topic, no_cache=no_cache, strict=False)
    except ResearchError as e:
        console.print(f"[red]Research failed:[/] {e}")
        raise typer.Exit(2)

    if json_out:
        _render_serp_json(payload)
    elif brief:
        _render_serp_brief(payload, console)
    else:
        _render_serp_full(payload, console)
