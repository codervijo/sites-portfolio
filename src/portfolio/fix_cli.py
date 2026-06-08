"""v35.F incr 11 — `project fix` / `fleet fix` engine, extracted from cli.py
(behavior-preserving, H1; approach A — sibling module).

The remediation runner + fleet-eligible-project lister (and their cost/category
constants). Shared repo-walk lives in the neutral repo_walk module. cli.py
re-exports every name; the @command callbacks stay in cli.py.
"""
from __future__ import annotations

import typer

from .console import console
from .data import load_domains
from .repo_walk import _iterate_repos


_DELETE_CATEGORY = "to be deleted immediately"


_TIER_2_COST_ESTIMATE_USD = 0.10  # rough per-call estimate for budget hint


def _list_fleet_eligible_projects():
    """Return [(domain, project_dir)] for every fleetwide-fix-eligible
    project: skip ignore_repos config + skip domains in 'To be deleted
    immediately' category + skip dark_sites (2026-05-27 — internal sites
    that shouldn't receive auto-applied writes). Sorted alphabetically."""
    from .checks.config import load_config
    cfg = load_config()
    repos = _iterate_repos(cfg.repos_dir, ignore=cfg.ignore_repos)
    domains_by_name = {d.name.lower(): d for d in load_domains()}
    dark = set(cfg.dark_sites)
    out = []
    for repo_path in repos:
        if repo_path.name.lower() in dark:
            continue
        domain_obj = domains_by_name.get(repo_path.name.lower())
        if domain_obj and (domain_obj.category or "").lower() == _DELETE_CATEGORY:
            continue
        out.append((repo_path.name, repo_path))
    return out


def _run_project_fix_all(*, apply_changes: bool, rule_filter, assume_yes: bool,
                        use_ai: bool) -> None:
    """Fleetwide fix: dry-run plan or --apply across all eligible projects.

    Skips: ignore_repos + 'To be deleted immediately' category. Continues
    on per-project error (errors reported in summary). Single confirm
    prompt before fleetwide writes (unless --yes).
    """
    from .checks import run_checks
    from .fix_registry import fixable_check_ids, get_tier_1, get_tier_2
    from .fix_helpers import claude_available

    projects = _list_fleet_eligible_projects()
    if not projects:
        console.print("[yellow]No fleetwide-eligible projects in repos_dir.[/]")
        return

    tier_1_fixable = fixable_check_ids(tier=1)
    tier_2_fixable = fixable_check_ids(tier=2) if use_ai else set()
    requested = set(rule_filter) if rule_filter else None

    # Phase 1 — compute the plan (always run, to show fleetwide totals).
    # Note: we run the catalog directly against the project dir rather
    # than going through `build_status` — the resolver requires a
    # portfolio.json match, and dirs like `harmonia` / `levents` that
    # don't naturally resolve still need fixing. The catalog operates
    # on filesystem state alone, no resolver needed.
    plans: list[dict] = []
    total_t1 = 0
    total_t2 = 0
    for domain, project_dir in projects:
        try:
            results = run_checks(str(project_dir))
            failed_ids = [
                cid for cid, r in results.items()
                if r.status == "fail"
            ]
        except Exception as e:
            plans.append({
                "domain": domain, "dir": project_dir,
                "t1": [], "t2": [], "error": f"catalog run: {e}",
            })
            continue

        if requested:
            t1 = sorted(requested & tier_1_fixable & set(failed_ids))
            t2 = sorted(requested & tier_2_fixable & set(failed_ids))
        else:
            t1 = sorted(set(failed_ids) & tier_1_fixable)
            t2 = sorted(set(failed_ids) & tier_2_fixable)
        plans.append({
            "domain": domain, "dir": project_dir,
            "t1": t1, "t2": t2, "error": None,
        })
        total_t1 += len(t1)
        total_t2 += len(t2)

    # Phase 2 — render the plan.
    rule_label = (
        f" [dim](filtered to {', '.join(sorted(requested))})[/]"
        if requested else ""
    )
    console.print(
        f"\n[bold]Fleetwide fix plan: {len(projects)} eligible project(s)[/]"
        f"{rule_label}"
    )
    # 2026-05-27 — surface dark-site exclusions so operator sees what was
    # filtered (and edits [fleet] dark_sites in config.toml if they
    # disagree). Silent exclusion hides the wrong-default risk.
    from .checks.config import load_config as _load_cfg
    _dark = _load_cfg().dark_sites
    if _dark:
        console.print(
            f"  [dim]↷ skipping {len(_dark)} dark site(s): "
            f"{', '.join(sorted(_dark))} "
            f"(edit [cyan][fleet] dark_sites[/] in config.toml to change)[/]"
        )
    console.print(f"  Tier 1 templated:    {total_t1} fix(es) across the fleet")
    if use_ai:
        cost = total_t2 * _TIER_2_COST_ESTIMATE_USD
        console.print(
            f"  Tier 2 (--ai):       {total_t2} Claude subprocess(es)  "
            f"[dim](est. ~${cost:.2f})[/]"
        )
    if use_ai and not claude_available():
        console.print(
            "  [yellow]warning:[/] [dim]--ai requested but `claude` CLI not on PATH; "
            "Tier 2 will skip[/]"
        )
    console.print()

    # Per-project compact lines.
    for p in plans:
        if p["error"]:
            console.print(f"  [red]✗[/]  {p['domain']:<24}  {p['error']}")
            continue
        n_t1, n_t2 = len(p["t1"]), len(p["t2"])
        if n_t1 == 0 and n_t2 == 0:
            console.print(f"  [dim]·  {p['domain']:<24}  nothing to fix[/]")
            continue
        tags = []
        if n_t1: tags.append(f"{n_t1}×T1")
        if n_t2: tags.append(f"{n_t2}×T2")
        console.print(f"  +  {p['domain']:<24}  {', '.join(tags)}")

    if not apply_changes:
        console.print("\n[dim]Re-run with --apply to write across the fleet.[/]")
        return

    # Phase 3 — confirm before fleetwide writes.
    total_changes = total_t1 + total_t2
    if total_changes == 0:
        console.print("\n[green]Nothing to apply — every project is clean.[/]")
        return
    if not assume_yes:
        ok = typer.confirm(
            f"\nApply {total_changes} change(s) across {len(projects)} project(s)?",
            default=False,
        )
        if not ok:
            console.print("[yellow]Aborted.[/]")
            raise typer.Exit(0)

    # Phase 4 — execute. Continue-on-error.
    console.print()
    fixed = 0
    errored = 0
    for i, p in enumerate(plans, 1):
        prefix = f"[{i}/{len(plans)}]"
        if p["error"]:
            console.print(f"{prefix} [red]✗[/] {p['domain']}  {p['error']}")
            errored += 1
            continue
        if not p["t1"] and not p["t2"]:
            console.print(f"{prefix} [dim]·[/] {p['domain']}  nothing to fix")
            continue
        per_project_fixed = 0
        try:
            for cid in p["t1"]:
                spec = get_tier_1(cid)
                # Lockfile deletions: in --all mode, --yes is required to skip
                # the per-file prompt across N repos. Without --yes we skip
                # those checks and surface them at end.
                if cid in {"CHECK_032", "CHECK_033", "CHECK_034"} and not assume_yes:
                    continue
                r = spec.apply(p["dir"], dry_run=False, assume_yes=assume_yes)
                if r.status == "fixed":
                    per_project_fixed += 1
            if use_ai and claude_available():
                for cid in p["t2"]:
                    spec = get_tier_2(cid)
                    r = spec.apply(p["dir"], dry_run=False, assume_yes=assume_yes)
                    if r.status == "fixed":
                        per_project_fixed += 1
            console.print(
                f"{prefix} [green]✓[/] {p['domain']:<24}  {per_project_fixed} fix(es)"
            )
            fixed += per_project_fixed
        except Exception as e:
            console.print(f"{prefix} [red]✗[/] {p['domain']}  runtime error: {e}")
            errored += 1

    # Phase 5 — fleetwide summary.
    console.print(
        f"\n[bold]Done:[/] {fixed} fix(es) applied across {len(plans) - errored} project(s)"
    )
    if errored:
        console.print(f"  [red]{errored} project(s) errored — see above[/]")
