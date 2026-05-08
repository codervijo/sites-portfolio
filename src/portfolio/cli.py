from __future__ import annotations

from collections import Counter
from datetime import date

import typer
from rich.console import Console
from rich.table import Table

from .check import (
    best_per_domain,
    latest_snapshot,
    list_snapshots,
    load_snapshot,
    previous_snapshot,
    run_check,
)
from .data import PORTFOLIO_JSON, cleanup as run_cleanup, load_domains, load_plan

app = typer.Typer(help="Manage your domain portfolio.", add_completion=False, no_args_is_help=True)
console = Console()


@app.command()
def cleanup() -> None:
    """Build canonical data/portfolio.json from registrar CSVs + plan.md classifications."""
    out_path, domains, uncategorized = run_cleanup()

    by_reg = Counter(d.registrar for d in domains)
    by_cat = Counter(d.category for d in domains if d.category)

    console.print(f"[green]Wrote[/] {out_path}  [dim]({len(domains)} domains)[/]")

    t = Table(title="By registrar", show_header=False, box=None, padding=(0, 1))
    t.add_column("Registrar")
    t.add_column("Count", justify="right")
    for reg, count in by_reg.most_common():
        t.add_row(reg, str(count))
    console.print(t)

    c = Table(title="By category", show_header=False, box=None, padding=(0, 1))
    c.add_column("Category")
    c.add_column("Count", justify="right")
    for cat, count in by_cat.most_common():
        c.add_row(cat, str(count))
    if uncategorized:
        c.add_row("[yellow](uncategorized)[/]", f"[yellow]{len(uncategorized)}[/]")
    console.print(c)

    if uncategorized:
        console.print(
            f"\n[yellow]Uncategorized GoDaddy domains ({len(uncategorized)}):[/] "
            + ", ".join(sorted(uncategorized))
        )
        console.print(
            "[dim]Edit data/portfolio.json to set their `category` by hand, "
            "or add them to plan.md (legacy) and re-run cleanup.[/]"
        )


@app.command()
def summary() -> None:
    """Print a portfolio overview."""
    domains = load_domains()
    plan = load_plan()

    n = len(domains)
    with_price = [d for d in domains if d.renewal_price is not None]
    missing_price_n = n - len(with_price)
    total_renewal = sum(d.renewal_price for d in with_price)

    valued = [d for d in domains if d.registrar != "porkbun" and d.estimated_value]
    porkbun_n = sum(1 for d in domains if d.registrar == "porkbun")
    missing_value_n = n - len(valued) - porkbun_n
    total_value = sum(d.estimated_value for d in valued)

    t = Table(title="Portfolio Summary", show_header=False)
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Total domains", str(n))
    t.add_row("Active", str(sum(1 for d in domains if d.status.lower() == "active")))
    t.add_row("On hold", str(sum(1 for d in domains if d.status.lower() == "hold")))
    t.add_row("Listed for sale", str(sum(1 for d in domains if "listed for sale" in d.listing_status.lower())))
    t.add_row("Auto-renew on", str(sum(1 for d in domains if d.auto_renew.lower() == "on")))
    renewal_note = f"  [dim]({len(with_price)}/{n}; {missing_price_n} missing price)[/]" if missing_price_n else ""
    t.add_row("Annual renewal cost", f"${total_renewal:,.2f}{renewal_note}")
    value_note_parts = []
    if porkbun_n:
        value_note_parts.append(f"{porkbun_n} Porkbun excluded")
    if missing_value_n:
        value_note_parts.append(f"{missing_value_n} missing")
    value_note = f"  [dim]({', '.join(value_note_parts)})[/]" if value_note_parts else ""
    t.add_row("Estimated value", f"${total_value:,.2f}{value_note}")
    console.print(t)

    by_reg = Counter(d.registrar for d in domains)
    if by_reg:
        r = Table(title="By registrar")
        r.add_column("Registrar")
        r.add_column("Count", justify="right")
        for reg, count in by_reg.most_common():
            r.add_row(reg, str(count))
        console.print(r)

    counts = Counter(plan.values())
    if counts:
        p = Table(title="By plan category")
        p.add_column("Category")
        p.add_column("Count", justify="right")
        for cat, count in counts.most_common():
            p.add_row(cat, str(count))
        console.print(p)

    csv_names = {d.name for d in domains}
    plan_names = set(plan)
    only_csv = sorted(csv_names - plan_names)
    only_plan = sorted(plan_names - csv_names)
    if only_csv:
        console.print(f"\n[yellow]In registrar data but not in plan ({len(only_csv)}):[/] " + ", ".join(only_csv))
    if only_plan:
        console.print(f"\n[yellow]In plan but not in registrar data ({len(only_plan)}):[/] " + ", ".join(only_plan))


@app.command()
def expiring(within: int = typer.Option(180, "--within", "-w", help="Days from today")) -> None:
    """List domains expiring within N days."""
    today = date.today()
    soon = [d for d in load_domains() if d.expires and (d.expires - today).days <= within]
    soon.sort(key=lambda d: d.expires)

    t = Table(title=f"Expiring within {within} days")
    t.add_column("Domain")
    t.add_column("Expires")
    t.add_column("Days", justify="right")
    t.add_column("Auto-renew")
    t.add_column("Status")
    for d in soon:
        t.add_row(d.name, str(d.expires), str(d.days_to_expire), d.auto_renew, d.status)
    console.print(t)


@app.command()
def category(name: str = typer.Argument(None, help="Category substring (omit for all)")) -> None:
    """List domains grouped by plan category."""
    plan = load_plan()
    by_name = {d.name: d for d in load_domains()}

    grouped: dict[str, list[str]] = {}
    for dom, cat in plan.items():
        grouped.setdefault(cat, []).append(dom)

    if name:
        grouped = {c: ds for c, ds in grouped.items() if name.lower() in c.lower()}
        if not grouped:
            console.print(f"[red]No category matches '{name}'.[/]")
            raise typer.Exit(1)

    for cat, doms in sorted(grouped.items()):
        t = Table(title=f"{cat} ({len(doms)})")
        t.add_column("Domain")
        t.add_column("Expires")
        t.add_column("Status")
        t.add_column("Value", justify="right")
        for dom in sorted(doms):
            d = by_name.get(dom)
            if d:
                value = f"${d.estimated_value:,.0f}" if d.estimated_value else "-"
                t.add_row(d.name, str(d.expires) if d.expires else "-", d.status, value)
            else:
                t.add_row(dom, "-", "[red]not in CSV[/]", "-")
        console.print(t)


WIP_CATEGORIES = ("My brand", "SEO under way", "Next session")


@app.command()
def wip() -> None:
    """List work-in-progress domains: My brand + SEO under way + Next session."""
    plan = load_plan()
    by_name = {d.name: d for d in load_domains()}

    wip_domains = [(dom, cat) for dom, cat in plan.items() if cat in WIP_CATEGORIES]
    if not wip_domains:
        console.print("[yellow]No WIP domains found.[/]")
        raise typer.Exit(1)

    t = Table(title=f"WIP Domains ({len(wip_domains)})")
    t.add_column("Domain")
    t.add_column("Category")
    t.add_column("Expires")
    t.add_column("Status")
    t.add_column("Value", justify="right")
    for dom, cat in sorted(wip_domains, key=lambda x: (WIP_CATEGORIES.index(x[1]), x[0])):
        d = by_name.get(dom)
        if d:
            value = f"${d.estimated_value:,.0f}" if d.estimated_value else "-"
            t.add_row(d.name, cat, str(d.expires) if d.expires else "-", d.status, value)
        else:
            t.add_row(dom, cat, "-", "[red]not in CSV[/]", "-")
    console.print(t)


CLASSIFICATION_COLORS = {
    "live-site": "green",
    "forwarder": "cyan",
    "for-sale": "yellow",
    "parked": "yellow",
    "error": "red",
    "ssl-broken": "red",
    "dead": "red",
}


def _render_status(snapshot_path) -> None:
    snap = load_snapshot(snapshot_path)
    best = best_per_domain(snap)
    prev_path = previous_snapshot()
    prev_best = best_per_domain(load_snapshot(prev_path)) if (prev_path and prev_path != snapshot_path) else {}

    t = Table(title=f"Site status — {snapshot_path.name} (scope={snap.get('scope', '?')})")
    t.add_column("Domain")
    t.add_column("Var")
    t.add_column("HTTP", justify="right")
    t.add_column("Class")
    t.add_column("Final URL")
    t.add_column("ms", justify="right")
    t.add_column("Δ vs prev")

    for dom in sorted(best):
        r = best[dom]
        c = r["classification"]
        cls_str = f"[{CLASSIFICATION_COLORS.get(c, 'white')}]{c}[/]"
        prev_c = prev_best.get(dom, {}).get("classification")
        if prev_c and prev_c != c:
            delta = f"[bold yellow]{prev_c} → {c}[/]"
        elif prev_c:
            delta = ""
        else:
            delta = "[dim]new[/]" if prev_best else ""
        t.add_row(
            dom,
            r["variant"],
            str(r["status"]) if r["status"] is not None else "-",
            cls_str,
            (r["final_url"] or r.get("error") or "-")[:80],
            f"{r['response_time_ms']}" if r["response_time_ms"] is not None else "-",
            delta,
        )
    console.print(t)

    counts = Counter(r["classification"] for r in best.values())
    summary = "  ".join(f"[{CLASSIFICATION_COLORS.get(k, 'white')}]{k}[/]={v}" for k, v in counts.most_common())
    console.print(f"\nTotals ({len(best)} domains): {summary}")
    if prev_path and prev_path != snapshot_path:
        console.print(f"[dim]Compared against {prev_path.name}[/]")


@app.command()
def check(
    only: str = typer.Option("wip", "--only", "-o", help="Scope: 'wip' or 'all'"),
    concurrency: int = typer.Option(20, "--concurrency", "-c", help="Max parallel requests"),
) -> None:
    """Fetch each domain, classify, snapshot to data/checks/YYYY-MM-DD.json."""
    if only not in ("wip", "all"):
        console.print(f"[red]--only must be 'wip' or 'all', got {only!r}.[/]")
        raise typer.Exit(2)
    console.print(f"[cyan]Checking {only} domains (concurrency={concurrency})...[/]")
    out, _ = run_check(only=only, concurrency=concurrency)
    console.print(f"[green]Snapshot:[/] {out}")
    _render_status(out)


@app.command()
def status() -> None:
    """Show the latest snapshot, with diff vs. the previous one."""
    latest = latest_snapshot()
    if not latest:
        console.print("[red]No snapshots yet. Run `portfolio check` first.[/]")
        raise typer.Exit(1)
    _render_status(latest)


gsc_app = typer.Typer(help="Google Search Console integration.", no_args_is_help=True)
app.add_typer(gsc_app, name="gsc")


@gsc_app.command("auth")
def gsc_auth(
    force: bool = typer.Option(False, "--force", help="Force re-auth even if a valid token is cached"),
) -> None:
    """One-time interactive OAuth login. Caches refresh token locally."""
    from .gsc import TOKEN_PATH, MissingCredentialsError, authenticate

    try:
        console.print("[cyan]Opening a browser for Google sign-in. Approve access to Search Console (read-only).[/]")
        authenticate(force=force)
    except MissingCredentialsError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    console.print(f"[green]Authenticated.[/] Token cached at [dim]{TOKEN_PATH}[/]")


@gsc_app.command("list")
def gsc_list() -> None:
    """List GSC properties; cross-reference with WIP domains."""
    from .check import wip_domains as get_wip_domains
    from .gsc import MissingCredentialsError, list_properties, property_to_domain

    try:
        props = list_properties()
    except MissingCredentialsError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)

    wip_set = set(get_wip_domains())

    by_domain: dict[str, list[dict]] = {}
    for p in props:
        by_domain.setdefault(property_to_domain(p["siteUrl"]), []).append(p)

    t = Table(title=f"GSC Properties ({len(props)})")
    t.add_column("Property")
    t.add_column("Domain")
    t.add_column("Permission")
    t.add_column("WIP?")
    for p in sorted(props, key=lambda x: (property_to_domain(x["siteUrl"]), x["siteUrl"])):
        d = property_to_domain(p["siteUrl"])
        wip_flag = "[green]✓[/]" if d in wip_set else ""
        t.add_row(p["siteUrl"], d, p.get("permissionLevel", ""), wip_flag)
    console.print(t)

    not_in_gsc = sorted(wip_set - set(by_domain.keys()))
    if not_in_gsc:
        console.print(f"\n[yellow]WIP domains NOT verified in GSC ({len(not_in_gsc)}):[/]")
        for d in not_in_gsc:
            console.print(f"  • {d}")
    else:
        console.print("\n[green]All WIP domains are verified in GSC.[/]")


@gsc_app.command("sync")
def gsc_sync(
    days: int = typer.Option(28, "--days", "-d", help="Window size in days (inclusive)"),
    lag_days: int = typer.Option(3, "--lag", help="End the window N days before today (GSC has ~2-3 day lag)"),
    concurrency: int = typer.Option(5, "--concurrency", "-c"),
) -> None:
    """Pull Search Analytics totals for each WIP domain; snapshot to data/gsc/."""
    from .check import wip_domains as get_wip_domains
    from .gsc import MissingCredentialsError, sync as run_sync

    wip = get_wip_domains()
    console.print(f"[cyan]Syncing {len(wip)} WIP domains: {days}d window ending {lag_days}d ago.[/]")
    try:
        out_path, snapshot = run_sync(wip, days=days, lag_days=lag_days, concurrency=concurrency)
    except MissingCredentialsError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)

    period = snapshot["period"]
    console.print(f"[green]Snapshot:[/] {out_path}  [dim]({period['start']} → {period['end']})[/]")
    _render_gsc_snapshot(snapshot)


def _render_gsc_snapshot(snapshot: dict) -> None:
    period = snapshot["period"]
    t = Table(title=f"GSC totals — {period['start']} → {period['end']}")
    t.add_column("Domain")
    t.add_column("Clicks", justify="right")
    t.add_column("Impressions", justify="right")
    t.add_column("CTR", justify="right")
    t.add_column("Position", justify="right")
    t.add_column("Notes")

    ok_rows = [r for r in snapshot["results"] if r.get("status") == "ok"]
    ok_rows.sort(key=lambda r: r["clicks"], reverse=True)

    for r in ok_rows:
        notes = ""
        if len(r.get("properties", [])) > 1:
            notes = f"[dim]merged {len(r['properties'])} properties[/]"
        ctr = f"{r['ctr'] * 100:.2f}%" if r["impressions"] else "-"
        pos = f"{r['position']:.1f}" if r.get("position") is not None else "-"
        t.add_row(
            r["domain"],
            f"{r['clicks']:,}",
            f"{r['impressions']:,}",
            ctr,
            pos,
            notes,
        )
    console.print(t)

    not_in_gsc = [r["domain"] for r in snapshot["results"] if r.get("status") == "not-in-gsc"]
    if not_in_gsc:
        console.print(f"\n[yellow]Skipped — not verified in GSC ({len(not_in_gsc)}):[/]")
        for d in sorted(not_in_gsc):
            console.print(f"  • {d}")

    total_clicks = sum(r.get("clicks", 0) for r in ok_rows)
    total_imp = sum(r.get("impressions", 0) for r in ok_rows)
    console.print(
        f"\n[bold]Portfolio total:[/] {total_clicks:,} clicks  /  {total_imp:,} impressions  "
        f"(across {len(ok_rows)} domains)"
    )


def _fmt_count_delta(cur: int, prev: int | None) -> str:
    if prev is None:
        return "[dim](new)[/]"
    delta = cur - prev
    if delta == 0:
        return "[dim]=[/]"
    sign = "+" if delta > 0 else ""
    color = "green" if delta > 0 else "red"
    if prev == 0:
        return f"[{color}]{sign}{delta:,}[/]"
    pct = delta / prev * 100
    return f"[{color}]{sign}{delta:,} ({sign}{pct:.0f}%)[/]"


def _fmt_position_delta(cur: float | None, prev: float | None) -> str:
    if cur is None and prev is None:
        return "-"
    if prev is None:
        return "[dim](new)[/]"
    if cur is None:
        return "[red](lost)[/]"
    delta = cur - prev
    if abs(delta) < 0.05:
        return "[dim]≈[/]"
    color = "green" if delta < 0 else "red"
    sign = "+" if delta > 0 else ""
    return f"[{color}]{sign}{delta:.1f}[/]"


@gsc_app.command("compare")
def gsc_compare() -> None:
    """Show latest GSC snapshot with deltas vs. the previous one."""
    from .gsc import latest_snapshot, load_snapshot, previous_snapshot

    latest_path = latest_snapshot()
    if not latest_path:
        console.print("[red]No GSC snapshots yet. Run `gsc sync` first.[/]")
        raise typer.Exit(1)

    latest = load_snapshot(latest_path)
    prev_path = previous_snapshot()
    prev = load_snapshot(prev_path) if prev_path else None

    period = latest["period"]
    title = f"GSC compare — {latest_path.name} ({period['start']} → {period['end']})"
    if prev:
        pp = prev["period"]
        title += f"  vs.  {prev_path.name} ({pp['start']} → {pp['end']})"
    console.print(f"[cyan]{title}[/]")
    if not prev:
        console.print("[dim]Only one snapshot exists — showing latest without deltas. Re-run `gsc sync` after a day for comparisons.[/]\n")
    elif latest["days"] != prev["days"]:
        console.print(
            f"[yellow]Warning:[/] snapshot windows differ "
            f"(latest={latest['days']}d, previous={prev['days']}d). Absolute deltas may mislead.\n"
        )

    cur_ok = {r["domain"]: r for r in latest["results"] if r.get("status") == "ok"}
    prev_ok = {r["domain"]: r for r in (prev["results"] if prev else []) if r.get("status") == "ok"}

    t = Table()
    t.add_column("Domain")
    t.add_column("Clicks", justify="right")
    t.add_column("Δ Clicks", justify="right")
    t.add_column("Impressions", justify="right")
    t.add_column("Δ Imp", justify="right")
    t.add_column("Position", justify="right")
    t.add_column("Δ Pos", justify="right")
    t.add_column("Notes")

    for d in sorted(cur_ok, key=lambda x: cur_ok[x]["clicks"], reverse=True):
        c = cur_ok[d]
        p = prev_ok.get(d)
        notes_parts = []
        if len(c.get("properties", [])) > 1:
            notes_parts.append(f"merged {len(c['properties'])} props")
        if prev and d not in prev_ok:
            notes_parts.append("new")
        notes = "[dim]" + ", ".join(notes_parts) + "[/]" if notes_parts else ""

        t.add_row(
            d,
            f"{c['clicks']:,}",
            _fmt_count_delta(c["clicks"], p["clicks"] if p else None) if prev else "-",
            f"{c['impressions']:,}",
            _fmt_count_delta(c["impressions"], p["impressions"] if p else None) if prev else "-",
            f"{c['position']:.1f}" if c["position"] is not None else "-",
            _fmt_position_delta(c["position"], p["position"] if p else None) if prev else "-",
            notes,
        )
    console.print(t)

    if prev:
        dropped = sorted(set(prev_ok) - set(cur_ok))
        if dropped:
            console.print(
                f"\n[yellow]In previous but missing from latest ({len(dropped)}):[/] " + ", ".join(dropped)
            )

    total_clicks = sum(r["clicks"] for r in cur_ok.values())
    total_imp = sum(r["impressions"] for r in cur_ok.values())
    if prev_ok:
        prev_clicks = sum(r["clicks"] for r in prev_ok.values())
        prev_imp = sum(r["impressions"] for r in prev_ok.values())
        dc = total_clicks - prev_clicks
        di = total_imp - prev_imp
        console.print(
            f"\n[bold]Portfolio total:[/] {total_clicks:,} clicks "
            f"([{'green' if dc >= 0 else 'red'}]{'+' if dc >= 0 else ''}{dc:,}[/])  "
            f"/  {total_imp:,} impressions "
            f"([{'green' if di >= 0 else 'red'}]{'+' if di >= 0 else ''}{di:,}[/])  "
            f"across {len(cur_ok)} domains"
        )
    else:
        console.print(f"\n[bold]Portfolio total:[/] {total_clicks:,} clicks  /  {total_imp:,} impressions  across {len(cur_ok)} domains")


project_app = typer.Typer(help="Per-project status and conformance.", no_args_is_help=True)
app.add_typer(project_app, name="project")


@project_app.command("status")
def project_status(
    name: str = typer.Argument(..., help="Project name (fuzzy-matched against plan.md domains)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a human table"),
) -> None:
    """Report the v1.1 status of a single project under sites/."""
    import json as _json

    from .project import build_status

    result = build_status(name)

    if json_out:
        typer.echo(_json.dumps(result, indent=2, default=str))
        if result.get("error") == "ambiguous":
            raise typer.Exit(2)
        if result.get("error") == "not-found":
            raise typer.Exit(1)
        return

    _render_project_status(result)


VERDICT_COLORS = {
    "Misconfigured": "red",
    "Active": "green",
    "Quiet": "yellow",
    "Stalled": "yellow",
    "Dormant": "red",
    "Fresh": "cyan",
}

LIVE_CLS_COLORS = {
    "live-site": "green",
    "forwarder": "cyan",
    "for-sale": "yellow",
    "parked": "yellow",
    "ssl-broken": "red",
    "dead": "red",
    "error": "red",
}


def _render_project_status(result: dict) -> None:
    if result.get("error") == "not-found":
        console.print(f"[red]No project matches '{result['input']}' in plan.md.[/]")
        raise typer.Exit(1)
    if result.get("error") == "ambiguous":
        console.print(f"[yellow]'{result['input']}' is ambiguous. Candidates:[/]")
        for c in result["candidates"]:
            console.print(f"  • {c}")
        raise typer.Exit(2)

    console.print(f"[bold]{result['resolved']}[/]  [dim](resolved from '{result['input']}')[/]")
    verdict = result["verdict"]
    color = VERDICT_COLORS.get(verdict, "white")
    console.print(f"Verdict: [{color}]{verdict}[/]")
    console.print(f"Plan:    {result.get('plan_category') or '[dim](no plan category)[/]'}")
    console.print(f"Dir:     {result['dir']}{'' if result['dir_exists'] else ' [red](missing)[/]'}")

    g = result["git"]
    t = Table(title="Git", show_header=False, box=None, padding=(0, 1))
    t.add_column("Field")
    t.add_column("Value")
    if g["own_repo_pass"]:
        t.add_row("Repo", "[green]own .git[/]")
        if g["branch"]:
            if g["clean"]:
                clean_str = "[green]clean[/]"
            else:
                clean_str = f"[yellow]{g['modified_count']} modified, {g['untracked_count']} untracked[/]"
            t.add_row("Branch", f"{g['branch']} ({clean_str})")
        last = g["last_commit"]
        if last:
            t.add_row(
                "Last commit",
                f'{last["short_sha"]} "{last["subject"]}" — {last["age_days"]}d ago, by {last["author"]}',
            )
        else:
            t.add_row("Last commit", "[yellow](no commits yet)[/]")
        if g["total_commits"] is not None:
            t.add_row(
                "Activity",
                f"{g['commits_7d']} in 7d · {g['commits_30d']} in 30d · {g['total_commits']} total",
            )
    else:
        failed = result["conformance"]["failed"]
        own = next((f for f in failed if f["rule"] == "own-git-repo"), {})
        reason = own.get("reason", "?")
        msg_map = {
            "dir-missing": "[red]directory does not exist[/]",
            "no-git": "[red]no .git found[/]",
            "tracked-by-parent": f"[red]tracked by parent ({own.get('toplevel', '?')})[/]",
        }
        t.add_row("Repo", msg_map.get(reason, f"[red]{reason}[/]"))
    console.print(t)

    p = result["prompts_md"]
    if p["exists"] and p["last_entry"]:
        le = p["last_entry"]
        title = f' — {le["title"]}' if le["title"] else ""
        warn = f" [yellow]({p['format_warning']})[/]" if p.get("format_warning") else ""
        console.print(f"\n[bold]Last AI prompt:[/]  {le['date']}{title}{warn}")
        console.print(f"  [dim]{le['summary']}[/]")
    elif p["exists"]:
        console.print("\n[bold]Last AI prompt:[/] [yellow](Prompts.md exists but is empty)[/]")
    else:
        console.print("\n[bold]Last AI prompt:[/] [dim]docs/Prompts.md not found[/]")

    d = result["deployment"]
    plat = d["platform"]
    plat_color = "green" if plat not in ("unknown", "n/a") else ("dim" if plat == "n/a" else "yellow")
    plat_extra = f" ({d['kind']})" if plat == "n/a" else ""
    plat_evidence = f"  [dim]via: {', '.join(d['evidence'])}[/]" if d["evidence"] else ""
    console.print(f"\n[bold]Deployment:[/]  [{plat_color}]{plat}[/]{plat_extra}{plat_evidence}")

    live = d.get("live")
    if live:
        cls = live["classification"]
        cls_color = LIVE_CLS_COLORS.get(cls, "white")
        ms = f", {live['response_time_ms']}ms" if live.get("response_time_ms") is not None else ""
        url = f"  → {live['final_url']}" if live.get("final_url") else ""
        http_status = live.get("http_status")
        console.print(
            f"  Live: [{cls_color}]{cls}[/] (HTTP {http_status if http_status is not None else '?'}{ms}){url}  [dim]{live['snapshot']}[/]"
        )
    elif plat != "n/a":
        console.print("  [dim]Live: no check snapshot covers this domain yet[/]")

    conf = result["conformance"]
    if conf["failed"]:
        console.print(f"\n[red]Conformance failures ({len(conf['failed'])}):[/]")
        for f in conf["failed"]:
            console.print(f"  ✗ [bold]{f['rule']}[/] — {f.get('reason', '?')}")
            if f.get("fix"):
                console.print(f"    [dim]fix: {f['fix']}[/]")
    if conf["passed"]:
        console.print(f"[green]Passed ({len(conf['passed'])}):[/] " + ", ".join(conf["passed"]))
    if conf["skipped"]:
        console.print(
            f"[dim]Skipped ({len(conf['skipped'])}): "
            + ", ".join(s["rule"] for s in conf["skipped"])
            + "[/]"
        )


@app.command(name="list")
def list_all() -> None:
    """List every domain in the CSV."""
    t = Table(title="All Domains")
    t.add_column("Domain")
    t.add_column("Expires")
    t.add_column("Status")
    t.add_column("Auto-renew")
    t.add_column("Listed")
    t.add_column("Value", justify="right")
    for d in sorted(load_domains(), key=lambda x: x.name):
        value = f"${d.estimated_value:,.0f}" if d.estimated_value else "-"
        t.add_row(d.name, str(d.expires) if d.expires else "-", d.status, d.auto_renew, d.listing_status, value)
    console.print(t)


domain_app = typer.Typer(help="Domain acquisition tooling (Power 1).", no_args_is_help=True)
app.add_typer(domain_app, name="domain")


@domain_app.command("suggest")
def domain_suggest(
    topic: str = typer.Argument(..., help="The product idea or topic to brainstorm domain names for"),
    tlds: str = typer.Option(
        "",
        "--tlds",
        help="Comma-separated TLDs to scan in priority order (default: .com,.app,.dev,.xyz,.site,.co)",
    ),
    max_price: float = typer.Option(20.0, "--max-price", help="Filter out candidates priced above this USD/yr (default 20; pass a big number e.g. 999 to disable)"),
    strategies: int = typer.Option(0, "--strategies", help="Limit to first N strategies (0 = all)"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Dump ranked candidates and exit; no prompts"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the brainstorm + vocab cache"),
    browse: bool = typer.Option(False, "--browse", help="Use legacy per-strategy round-by-round flow (v2.A)"),
    show_renewal: bool = typer.Option(False, "--show-renewal", help="Show renewal price column alongside registration"),
    with_abstract: bool = typer.Option(False, "--with-abstract", help="Include the abstract-brandable strategy in the run"),
    top_n: int = typer.Option(15, "--top-n", help="Validation-mode: max grid rows shown (default 15)"),
) -> None:
    """Brainstorm domain names for an idea, score them, check availability + price.

    Default flow (v3.D validation mode): vocab anchor → registrar grid → one pick → optional auto-register.
    Legacy flow (v2.A per-strategy rounds): pass --browse.
    """
    if browse:
        _domain_suggest_browse(topic, tlds, max_price, strategies, non_interactive, no_cache)
        return
    _domain_suggest_validation(
        topic=topic,
        tlds=tlds,
        max_price=max_price,
        non_interactive=non_interactive,
        no_cache=no_cache,
        show_renewal=show_renewal,
        with_abstract=with_abstract,
        top_n=top_n,
    )


def _domain_suggest_validation(
    *,
    topic: str,
    tlds: str,
    max_price: float,
    non_interactive: bool,
    no_cache: bool,
    show_renewal: bool,
    with_abstract: bool,
    top_n: int,
) -> None:
    """v3.D validation-mode flow."""
    from .availability import AvailabilityChecker, load_porkbun_pricing
    from .suggest import (
        DEFAULT_TLDS,
        FULL_LADDER,
        PORTFOLIO_ENV,
        already_owned_matches,
        cache_get,
        cache_set,
        filter_default_strategies,
        load_env,
        load_strategies,
        porkbun_cart_url,
        register_domain,
        run_validation_pipeline,
    )

    env = load_env()
    openai_key = env.get("OPENAI_API_KEY", "").strip()
    if not openai_key:
        console.print(f"[red]OPENAI_API_KEY is not set.[/]  Edit [dim]{PORTFOLIO_ENV}[/] and try again.")
        raise typer.Exit(2)

    tld_list = [t.strip() if t.strip().startswith(".") else f".{t.strip()}" for t in tlds.split(",") if t.strip()] if tlds else list(DEFAULT_TLDS)
    all_strategies = filter_default_strategies(load_strategies(), with_abstract=with_abstract)

    owned = already_owned_matches(topic)
    if owned:
        console.print(f"[cyan]Already own ({len(owned)} match{'es' if len(owned) > 1 else ''}):[/]")
        for o in owned:
            console.print(f"  • {o}")
        if not non_interactive:
            cont = typer.confirm("Continue with new candidate brainstorm?", default=True)
            if not cont:
                raise typer.Exit(0)

    cached = None if no_cache else cache_get(topic, all_strategies)

    def _log(msg: str) -> None:
        console.print(f"[dim]{msg}[/]")

    checker = AvailabilityChecker(log_fn=_log)
    avail_fn = checker.make_check_callable()
    pricing_dict = load_porkbun_pricing()

    # Config summary.
    cfg_t = Table(box=None, padding=(0, 1), show_header=False, title="[bold]Search config (v3.D validation mode)[/]", title_justify="left")
    cfg_t.add_column("key", style="dim")
    cfg_t.add_column("value")
    cfg_t.add_row("topic", topic)
    cfg_t.add_row("max price", f"${max_price:.2f}/yr (pass --max-price=999 to disable)")
    cfg_t.add_row("TLD columns", " ".join(tld_list))
    cfg_t.add_row("availability", "RDAP (auth-free); .tech/.site/.online → '?' (broken endpoint)")
    cfg_t.add_row("pricing", "Porkbun /pricing/get (public, cached 7d)")
    cfg_t.add_row("brainstorm", "OpenAI gpt-5-mini (vocab anchored)")
    cfg_t.add_row("strategies", f"{len(all_strategies)} ({', '.join(s.name for s in all_strategies)})")
    cfg_t.add_row("cache", "BYPASSED (--no-cache)" if no_cache else "7d topic-hash hit/miss")
    cfg_t.add_row("mode", "non-interactive" if non_interactive else "interactive (one merged grid)")
    console.print(cfg_t)
    console.print()

    cache_payload = cached if cached else None

    def _save_cache(cands_by_strat, vocab_terms):
        cache_set(topic, all_strategies, cands_by_strat, vocab_terms=vocab_terms)

    rows, vocab_terms = run_validation_pipeline(
        topic=topic,
        api_key=openai_key,
        strategies=all_strategies,
        columns=tld_list,
        avail_check=avail_fn,
        max_price=max_price,
        pricing_dict=pricing_dict,
        cache_payload=cache_payload,
        cache_save_fn=None if no_cache else _save_cache,
        log_fn=_log,
    )

    # Limit to top-N for the picker.
    rows = rows[:top_n]

    if not rows:
        console.print("[yellow]No candidate names produced. Try refining the topic or --no-cache.[/]")
        raise typer.Exit(0)

    _render_grid(rows, tld_list, show_renewal=show_renewal)

    if non_interactive:
        return

    pick_prompt = f"\nPick row 1-{len(rows)}, 'q' to quit"
    choice = typer.prompt(pick_prompt, default="q", show_default=False).strip().lower()
    if choice == "q" or not choice.isdigit():
        console.print("[yellow]No domain selected.[/]")
        return
    idx = int(choice) - 1
    if idx < 0 or idx >= len(rows):
        console.print("[red]Out of range.[/]")
        return

    row = rows[idx]
    if row.pick_tld is None:
        console.print("[red]Row has no recommended TLD (likely .com poisoned). Aborting.[/]")
        return

    selected = f"{row.name}{row.pick_tld}"
    console.print(f"\n[green]✅ Selected:[/] [bold]{selected}[/]")

    # Defense bundle: offer to grab .com and/or .app at standard price (manual cart).
    bundle: list[str] = []
    com_cell = row.cells.get(".com")
    app_cell = row.cells.get(".app")
    if row.pick_tld != ".com" and com_cell is not None and com_cell.available is True and not com_cell.over_max:
        bundle.append(".com")
    if row.pick_tld != ".app" and app_cell is not None and app_cell.available is True and not app_cell.over_max:
        bundle.append(".app")

    if bundle:
        bundle_doms = [f"{row.name}{t}" for t in bundle]
        bundle_str = " + ".join(bundle_doms)
        bundle_prompt = f"Defense bundle available: {bundle_str}. Open Porkbun cart with bundle? [y/N]"
        if typer.confirm(bundle_prompt, default=False):
            url = porkbun_cart_url([selected] + bundle_doms)
            console.print(f"[cyan]Bundle cart URL:[/] {url}")
            console.print("[dim](Bundle items are manual click-through; never auto-charged.)[/]")

    # Auto-register prompt for the primary domain only.
    if typer.confirm(f"Register {selected} now via Porkbun API?", default=False):
        pk_key = env.get("PORKBUN_API_KEY", "").strip()
        pk_secret = env.get("PORKBUN_SECRET_API_KEY", "").strip()
        result = register_domain(selected, pk_key, pk_secret)
        if result.ok:
            console.print(f"[green]✓ Registered {selected}[/]" + (f" (order {result.order_id})" if result.order_id else ""))
        else:
            console.print(f"[red]Auto-register failed:[/] {result.detail}")
            console.print(f"[cyan]Manual checkout:[/] {porkbun_cart_url([selected])}")
    else:
        console.print(f"[cyan]Register manually:[/] {porkbun_cart_url([selected])}")

    # Print next-step bootstrap command and vocab terms for paste.
    console.print("\n[bold]Next step:[/]")
    console.print(f'  portfolio bootstrap {selected} --topic="{topic}"')
    if vocab_terms:
        console.print(f"\n[bold]Vocab terms[/] (paste into docs/prd.md after bootstrap):")
        console.print("  " + ", ".join(vocab_terms))


def _cell_str(state, show_renewal: bool = False) -> str:
    """Format one grid cell: ✓ $N / ✗ live|park / ? / $N!"""
    if state.over_max:
        # Available but priced out; surface so user sees the option exists.
        if state.available is True and state.price is not None:
            return f"[dim]${state.price:.0f}![/]"
        if state.available is False:
            return "[red]✗[/]"
        return "[yellow]?[/]"
    if state.available is True:
        price_s = f"${state.price:.0f}" if state.price is not None else "-"
        if show_renewal and state.renewal is not None:
            return f"[green]✓[/] {price_s}\n[dim]r ${state.renewal:.0f}[/]"
        return f"[green]✓[/] {price_s}"
    if state.available is False:
        if state.com_class == "live-site":
            return "[red]✗ live[/]"
        if state.com_class == "parked":
            return "[yellow]✗ park[/]"
        if state.com_class == "for-sale":
            return "[yellow]✗ sale[/]"
        return "[red]✗[/]"
    if state.error:
        return "[red bold]✕[/]"
    return "[yellow]?[/]"


def _render_grid(rows, columns: list[str], show_renewal: bool = False) -> None:
    """Render the v3.D registrar grid (rows = names, cols = TLDs + Pick + Why)."""
    t = Table(box=None, padding=(0, 1))
    t.add_column("#", justify="right")
    t.add_column("Name", style="bold")
    for c in columns:
        t.add_column(c, justify="left")
    t.add_column("Pick", style="cyan")
    t.add_column("Why")
    for i, row in enumerate(rows, 1):
        cells_rendered = [_cell_str(row.cells.get(c), show_renewal=show_renewal) if row.cells.get(c) else "-" for c in columns]
        pick = row.pick_label or "-"
        t.add_row(str(i), row.name, *cells_rendered, pick, row.why)
    console.print(t)


def _domain_suggest_browse(
    topic: str,
    tlds: str,
    max_price: float,
    strategies: int,
    non_interactive: bool,
    no_cache: bool,
) -> None:
    """v2.A legacy per-strategy round-by-round flow (preserved behind --browse)."""
    from .availability import AvailabilityChecker
    from .suggest import (
        DEFAULT_TLDS,
        Candidate,
        already_owned_matches,
        brainstorm,
        cache_get,
        cache_set,
        filter_by_max_price,
        load_env,
        load_strategies,
        render_options,
        PORTFOLIO_ENV,
    )

    env = load_env()
    openai_key = env.get("OPENAI_API_KEY", "").strip()
    if not openai_key:
        console.print(f"[red]OPENAI_API_KEY is not set.[/]  Edit [dim]{PORTFOLIO_ENV}[/] and try again.")
        raise typer.Exit(2)

    tld_list = [t.strip() if t.strip().startswith(".") else f".{t.strip()}" for t in tlds.split(",") if t.strip()] if tlds else list(DEFAULT_TLDS)
    all_strategies = load_strategies()
    if strategies > 0:
        all_strategies = all_strategies[:strategies]

    owned = already_owned_matches(topic)
    if owned:
        console.print(f"[cyan]Already own ({len(owned)} match{'es' if len(owned) > 1 else ''}):[/]")
        for o in owned:
            console.print(f"  • {o}")
        if not non_interactive:
            cont = typer.confirm("Continue with new candidate brainstorm?", default=True)
            if not cont:
                raise typer.Exit(0)

    cached = None if no_cache else cache_get(topic, all_strategies)
    if cached:
        console.print(f"[dim](using cached brainstorm; {len(cached.get('candidates_by_strategy', {}))} strategies)[/]")
        candidates_by_strategy = {k: [Candidate(**c) for c in v] for k, v in cached["candidates_by_strategy"].items()}
    else:
        candidates_by_strategy = {}

    def _log_check(msg: str) -> None:
        console.print(f"[dim]{msg}[/]")

    checker = AvailabilityChecker(log_fn=_log_check)
    avail_fn = checker.make_check_callable()

    cfg_t = Table(box=None, padding=(0, 1), show_header=False, title="[bold]Search config (browse mode / v2.A)[/]", title_justify="left")
    cfg_t.add_column("key", style="dim"); cfg_t.add_column("value")
    cfg_t.add_row("topic", topic)
    cfg_t.add_row("max price", f"${max_price:.2f}/yr")
    cfg_t.add_row("TLD ladder", " ".join(tld_list))
    cfg_t.add_row("strategies", f"{len(all_strategies)} ({', '.join(s.name for s in all_strategies)})")
    console.print(cfg_t); console.print()

    history: list[str] = []
    selected: str | None = None
    for idx, strategy in enumerate(all_strategies, 1):
        if selected:
            break
        console.print(f"\n[bold cyan]--- Strategy {idx}/{len(all_strategies)}: {strategy.label} ---[/]")
        console.print(f"[dim]{strategy.description}[/]")

        cached_cands = candidates_by_strategy.get(strategy.name)
        if cached_cands:
            cands = cached_cands
            console.print(f"[dim](cached: {len(cands)} candidates)[/]")
        else:
            console.print("[dim]Brainstorming via OpenAI gpt-5-mini...[/]")
            try:
                cands = brainstorm(topic, strategy, history, openai_key)
            except Exception as e:
                console.print(f"[red]brainstorm failed:[/] {e}")
                continue
            if not cands:
                continue
            candidates_by_strategy[strategy.name] = cands
            cache_set(topic, all_strategies, candidates_by_strategy)

        history.extend(c.name for c in cands)

        options = render_options(cands, topic, tld_list, avail_fn)
        options = filter_by_max_price(options, max_price)
        showable = [o for o in options if o.available is not False]
        if not showable:
            console.print("[yellow]No available or candidate domains in this round.[/]")
            continue

        top = showable[:5]
        t = Table(box=None, padding=(0, 1))
        t.add_column("#", justify="right"); t.add_column("Name"); t.add_column("TLD")
        t.add_column("Avail", justify="center"); t.add_column("Price", justify="right"); t.add_column("Score", justify="right")
        for i, o in enumerate(top, 1):
            price_s = f"${o.price:,.2f}" if o.price is not None else "-"
            avail_s = "[green]✓[/]" if o.available is True else ("[red]✗[/]" if o.available is False else ("[red bold]✕[/]" if o.error else "[yellow]?[/]"))
            t.add_row(str(i), o.name, o.tld, avail_s, price_s, str(o.score))
        console.print(t)

        if non_interactive:
            continue

        choice = typer.prompt(f"\nPick (1-{len(top)}), 'n' next, 'q' quit", default="n", show_default=False).strip().lower()
        if choice == "q":
            console.print("[yellow]Aborted.[/]"); raise typer.Exit(0)
        if choice in ("n", ""):
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(top):
            selected = top[int(choice) - 1].domain

    if selected:
        console.print(f"\n[green]✅ Selected:[/] [bold]{selected}[/]")
        console.print(f"[cyan]Register at:[/] https://porkbun.com/checkout/search?q={selected}")
    elif not non_interactive:
        console.print("\n[yellow]No domain selected.[/]")


@app.command()
def bootstrap(
    domain: str = typer.Argument(..., help="Domain name to scaffold under sites/ (e.g. kwizicle.com)"),
    stack: str = typer.Option("astro", "--stack", help="astro or vite (ignored if --from-genai or --git-url)"),
    from_genai: bool = typer.Option(False, "--from-genai", help="Copy contents of sites/<domain>/genai/ up to project root + apply CF safety fixes"),
    git_url: str = typer.Option("", "--git-url", help="git clone URL into sites/<domain>/genai/, then proceed as --from-genai"),
    with_ingester: bool = typer.Option(False, "--with-ingester", help="Add scripts/ dir with an ingester template"),
    topic: str = typer.Option("", "--topic", help="One-line topic; written into AI_AGENTS.md and docs/prd.md"),
) -> None:
    """Scaffold a new sites/<domain>/ project to ship-ready conformance (v3.A)."""
    from .bootstrap import BootstrapError, bootstrap as run_bootstrap

    try:
        result = run_bootstrap(
            domain=domain,
            stack=stack,
            from_genai=from_genai,
            git_url=git_url or None,
            with_ingester=with_ingester,
            topic=topic,
        )
    except BootstrapError as e:
        console.print(f"[red]bootstrap failed:[/] {e}")
        raise typer.Exit(2)

    console.print(f"[green]✓[/] Bootstrapped [bold]{result.project_dir}[/]  [dim](path={result.path}, stack={result.stack})[/]")

    if result.files_copied:
        console.print(f"\n[bold]Copied from genai/ ({len(result.files_copied)}):[/]")
        for f in result.files_copied:
            console.print(f"  • {f}")

    if result.cf_fixes:
        console.print(f"\n[bold]Cloudflare Pages safety fixes ({len(result.cf_fixes)}):[/]")
        for fix in result.cf_fixes:
            console.print(f"  • {fix}")

    if result.files_written:
        console.print(f"\n[bold]Files written ({len(result.files_written)}):[/]")
        for f in sorted(result.files_written):
            console.print(f"  • {f}")

    if result.git_initialized:
        sha = result.initial_commit_sha[:7] if result.initial_commit_sha else "?"
        console.print(f"\n[green]✓[/] git initialized; initial commit [dim]{sha}[/]")
    else:
        console.print("\n[yellow]✗[/] git init failed — initialize manually")

    if result.warnings:
        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/]")
        for w in result.warnings:
            console.print(f"  • {w}")

    if result.next_steps:
        console.print("\n[bold]Next steps:[/]")
        for step in result.next_steps:
            console.print(f"  {step}")


@app.command()
def deploy(
    domain: str = typer.Argument(..., help="Domain whose sites/<domain>/ project to deploy (e.g. kwizicle.com)"),
    gh_owner: str = typer.Option("", "--gh-owner", help="GitHub username/org for the new repo (auto-detected via `gh api user` if empty)"),
    private: bool = typer.Option(False, "--private", help="Create the GitHub repo as private (default: public)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen; don't actually call APIs or create resources"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip the local-config sanity check"),
    skip_repo: bool = typer.Option(False, "--skip-repo", help="Skip GitHub repo creation (use if repo already exists)"),
    skip_pages: bool = typer.Option(False, "--skip-pages", help="Skip Cloudflare Pages project creation"),
) -> None:
    """Set up the GitHub repo + Cloudflare Pages project for a sites/<domain>/ project (v3.C)."""
    from .bootstrap import _project_name
    from .deploy import CloudflarePagesDeploy, detect_gh_owner
    from .suggest import PORTFOLIO_ENV, load_env

    from .data import ROOT as DATA_ROOT

    env = load_env()
    project_dir = DATA_ROOT.parent / domain
    if not project_dir.exists():
        console.print(f"[red]Project dir not found:[/] {project_dir}")
        console.print("[dim]Run `portfolio bootstrap <domain>` first, or check the domain spelling.[/]")
        raise typer.Exit(1)

    cf_token = env.get("CF_API_TOKEN", "").strip()
    cf_account = env.get("CF_ACCOUNT_ID", "").strip()
    if not cf_token or not cf_account:
        console.print(f"[red]CF_API_TOKEN and CF_ACCOUNT_ID required.[/]  Edit [dim]{PORTFOLIO_ENV}[/] and try again.")
        raise typer.Exit(2)

    if not gh_owner:
        gh_owner = detect_gh_owner() or ""
    if not gh_owner:
        console.print("[red]GitHub owner not provided and `gh api user` failed.[/]")
        console.print("[dim]Either pass --gh-owner=<your-login>, or run `gh auth login` first.[/]")
        raise typer.Exit(2)

    slug = f"{gh_owner}/{_project_name(domain)}"
    target = CloudflarePagesDeploy(api_token=cf_token, account_id=cf_account, dry_run=dry_run)

    console.print(f"[bold]Deploy plan for[/] [cyan]{domain}[/]")
    console.print(f"  project dir:  {project_dir}")
    console.print(f"  gh slug:      {slug}")
    console.print(f"  cf project:   {_project_name(domain)}  [dim](from wrangler.jsonc, falling back to domain base)[/]")
    console.print(f"  visibility:   {'private' if private else 'public'}")
    console.print(f"  dry-run:      {dry_run}")

    # 1. verify
    if not skip_verify:
        console.print("\n[bold]1. Verify local config[/]")
        v = target.verify_local_config(project_dir)
        if v.notes:
            for n in v.notes:
                console.print(f"  [dim]·[/] {n}")
        if not v.ok:
            console.print("[red]Local config issues:[/]")
            for m in v.missing:
                console.print(f"  ✗ {m}")
            console.print("[yellow]Fix the above, then re-run. Use --skip-verify to override at your own risk.[/]")
            raise typer.Exit(3)
        console.print("[green]✓ local config looks deployable[/]")

    # 2. github
    if not skip_repo:
        console.print(f"\n[bold]2. Create + push GitHub repo[/] ({slug})")
        if not dry_run:
            confirm = typer.confirm("  Proceed?", default=True)
            if not confirm:
                console.print("[yellow]Aborted at GitHub step.[/]")
                raise typer.Exit(0)
        r1 = target.create_github_repo(project_dir, slug, private=private)
        if r1.skipped:
            console.print(f"  [yellow]↷[/] {r1.detail}")
        elif r1.ok:
            console.print(f"  [green]✓[/] {r1.detail}")
        else:
            console.print(f"  [red]✗[/] {r1.detail}")
            raise typer.Exit(4)

    # 3. cf pages project
    if not skip_pages:
        cf_project = _project_name(domain)
        console.print(f"\n[bold]3. Create Cloudflare Pages project[/] ({cf_project} → github.com/{slug})")
        if not dry_run:
            confirm = typer.confirm("  Proceed?", default=True)
            if not confirm:
                console.print("[yellow]Aborted at CF Pages step.[/]")
                raise typer.Exit(0)
        r2 = target.create_project(project_dir, domain, gh_owner=gh_owner, gh_repo=_project_name(domain))
        if r2.skipped:
            console.print(f"  [yellow]↷[/] {r2.detail}")
        elif r2.ok:
            console.print(f"  [green]✓[/] {r2.detail}")
        else:
            console.print(f"  [red]✗[/] {r2.detail}")
            raise typer.Exit(5)

    console.print("\n[green]Deploy plumbing complete.[/]")
    console.print("[dim]Next: CF auto-builds on each push to main. Watch the dashboard for the first build.[/]")
    console.print(f"[dim]To add the custom domain, do it in the CF Pages dashboard for now (deferred from v3.C).[/]")


if __name__ == "__main__":
    app()
