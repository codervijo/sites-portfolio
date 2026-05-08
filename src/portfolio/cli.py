from __future__ import annotations

import re
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
    max_price: float = typer.Option(10.0, "--max-price", help="Filter out candidates priced above this USD/yr (default 10; pass a big number e.g. 999 to disable)"),
    strategies: int = typer.Option(0, "--strategies", help="Limit to first N strategies (0 = all)"),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Dump ranked candidates and exit; no prompts"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass the brainstorm + vocab cache"),
    browse: bool = typer.Option(False, "--browse", help="Use legacy per-strategy round-by-round flow (v2.A)"),
    show_renewal: bool = typer.Option(False, "--show-renewal", help="Show renewal price column alongside registration"),
    with_abstract: bool = typer.Option(False, "--with-abstract", help="Include the abstract-brandable strategy in the run"),
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
    )


def parse_pick_input(s: str, n_rows: int, columns: list[str]) -> tuple[int | None, str | None, str | None]:
    """Parse the picker's `N` or `N.tld` input.

    Returns `(row_idx_0based, override_tld_or_None, error_msg_or_None)`. Either
    a successful parse (idx + optional tld, no error) or `(None, None, err)`.
    The override TLD must be one of the displayed columns; out-of-range row
    indexes and unknown TLDs are surfaced as errors.
    """
    s = s.strip().lower()
    if not s:
        return None, None, "empty input"
    if "." in s:
        digit_part, tld_part = s.split(".", 1)
        tld = "." + tld_part
    else:
        digit_part, tld = s, None
    if not digit_part.isdigit():
        return None, None, f"'{s}': expected a row number (e.g. 5 or 5.app)"
    idx = int(digit_part) - 1
    if idx < 0 or idx >= n_rows:
        return None, None, f"row {digit_part} out of range (1-{n_rows})"
    if tld is not None and tld not in columns:
        return None, None, f"TLD {tld} not in displayed columns; choose from {' '.join(columns)}"
    return idx, tld, None


def parse_expand_input(s: str, rows) -> tuple[int | None, str | None]:
    """Parse the picker's expand command: `eN` or `e <name>`.

    Returns `(row_idx_0based, error_msg_or_None)`. Accepts:
      - `e5` / `e 5`  → row index lookup
      - `e codebeacon` / `e codebeacon.site` → name lookup (case-insensitive,
        prefix match acceptable; `.tld` suffix stripped)

    Returns `(None, "...")` on no-match or ambiguous-match (multiple prefix
    matches when rows differ).
    """
    s = s.strip().lower()
    if not s.startswith("e"):
        return None, "not an expand command"
    rest = s[1:].strip()
    if not rest:
        return None, "empty expand target — try 'e5' or 'e <name>'"
    if rest.isdigit():
        idx = int(rest) - 1
        if idx < 0 or idx >= len(rows):
            return None, f"row {rest} out of range (1-{len(rows)})"
        return idx, None
    # Strip optional `.tld` suffix
    name_part = rest.split(".", 1)[0] if "." in rest else rest
    if not re.match(r"^[a-z][a-z0-9]*$", name_part):
        return None, f"'{rest}' isn't a valid name or row number"
    matches = [(i, r) for i, r in enumerate(rows) if r.name.lower() == name_part]
    if not matches:
        # Try prefix match if no exact
        matches = [(i, r) for i, r in enumerate(rows) if r.name.lower().startswith(name_part)]
    if not matches:
        return None, f"no row matches '{name_part}'"
    if len(matches) > 1:
        names = ", ".join(r.name for _, r in matches[:5])
        return None, f"'{name_part}' is ambiguous: {names}"
    return matches[0][0], None


# v3.E 2026-05-08: post-grid menu. The menu replaces all the inline picker
# prompts (was N | N.tld | eN | "Add your own names?" auto-loop) with a
# numbered chooser. Re-shown after every non-terminating action; only
# successful registration or `q` exits.
# Menu items. (key, label, coming_soon). Slots 3 and 4 are reserved for
# v4.C (ask AI, widen) and not present yet. Slot 7 (decide from shortlist)
# is stubbed in v4.A as coming-soon for v4.B; slot 6 (mark/unmark shortlist)
# is active in v4.A. Stable numbering preserves muscle memory across phases.
MENU_ITEMS = [
    ("1", "Pick a row to register",                    False),
    ("2", "Expand a row (full-ladder detail)",         False),
    ("3", "Ask AI about a name",                       False),  # v4.C
    ("4", "Widen search — more candidates",            False),  # v4.C
    ("5", "Add my own names to the grid",              False),
    ("6", "Mark / unmark for shortlist",               False),
    ("7", "Decide from shortlist",                     False),
    ("8", "Show TLD reference (pricing, SEO, vibe)",   False),
]


# v4.B 2026-05-08: option 7 is now active. No coming-soon hints in v4.B;
# the constant is preserved (empty) for future stub use.
COMING_SOON_HINTS: dict[str, str] = {}


# v3.E 2026-05-08: per-TLD reference card. Surfaced via menu option 8 so the
# user can recall the operator / SEO / vibe / catch detail without leaving
# the tool. Card format mirrors the chat reference verbatim for the four
# TLDs the user emphasized (.app .dev .xyz .site) and matches that detail
# level for the rest of the default + full ladder.
TLD_REFERENCE = [
    {
        "tld": ".com",
        "grade": "A+",
        "operator": "Verisign",
        "reg": "$11",
        "renew": "$11",
        "vibe": "universal default; the global brand standard",
        "trust": "highest — recognized everywhere; what users type by default",
        "seo": "no penalty; baseline for everything else",
        "best_for": "any commercial site you intend to keep",
        "catch": "high collision risk; most short names already taken",
    },
    {
        "tld": ".app",
        "grade": "A",
        "operator": "Google Registry (2018)",
        "reg": "$11",
        "renew": "$15",
        "vibe": "modern app/SaaS, app-store adjacent",
        "trust": "high — Google-run, HSTS-preloaded (entire TLD forces HTTPS)",
        "seo": "no penalty",
        "best_for": "validation MVPs, mobile/web apps",
        "catch": "none meaningful",
    },
    {
        "tld": ".dev",
        "grade": "A",
        "operator": "Google Registry (2019)",
        "reg": "$11",
        "renew": "$13",
        "vibe": "developer tools, technical projects",
        "trust": "very high in tech audiences; HSTS-preloaded",
        "seo": "no penalty",
        "best_for": "dev tools, libraries, technical MVPs",
        "catch": "reads \"internal/staging\" to non-technical audiences",
    },
    {
        "tld": ".co",
        "grade": "B+",
        "operator": ".CO Internet S.A.S (2010)",
        "reg": "$10",
        "renew": "$27",
        "vibe": "Colombia ccTLD repurposed as a global .com alternative",
        "trust": "mid-high; mainstream-recognized after Twitter t.co et al.",
        "seo": "no penalty",
        "best_for": "fallback when .com is taken and you want a similar feel",
        "catch": "2.7× renewal cliff; users still type .com by reflex",
    },
    {
        "tld": ".xyz",
        "grade": "B+",
        "operator": "XYZ.com LLC (2014)",
        "reg": "$2",
        "renew": "$13",
        "vibe": "cheap-and-cheerful; legitimized by Alphabet (abc.xyz), Ethereum/ENS, web3 generally",
        "trust": "medium-high in tech, mixed in mainstream",
        "seo": "no penalty (one of the largest gTLDs by volume)",
        "best_for": "crypto-adjacent, experimental, Gen-Z-ish brands",
        "catch": "still reads \"scammy\" to some older/non-tech users",
    },
    {
        "tld": ".ai",
        "grade": "A-",
        "operator": "Government of Anguilla",
        "reg": "$83",
        "renew": "$83",
        "vibe": "AI startup signal; specialized but instantly read",
        "trust": "high in tech; carries clear positioning",
        "seo": "no penalty",
        "best_for": "AI/ML products you intend to keep long-term",
        "catch": "$83/yr — too steep for cheap validation",
    },
    {
        "tld": ".io",
        "grade": "B",
        "operator": "Internet Computer Bureau (British Indian Ocean Territory)",
        "reg": "$28",
        "renew": "$52",
        "vibe": "tech/startup default; reads developer-flavored",
        "trust": "high in tech; mainstream-aware",
        "seo": "no penalty",
        "best_for": "tech products willing to pay the premium",
        "catch": "$28 reg + ~2× renewal cliff; price-capped out for cheap validation",
    },
    {
        "tld": ".site",
        "grade": "C",
        "operator": "Radix Registry",
        "reg": "$2",
        "renew": "$30",
        "vibe": "generic, literal (\"this is a site\")",
        "trust": "low-mid; over-represented in parked-domain and spam datasets",
        "seo": "no penalty per Google, but signals \"low-effort\"",
        "best_for": "throwaway prototypes you'll let expire",
        "catch": "15× renewal cliff; weakest brand of the cheap tier",
    },
    {
        "tld": ".shop",
        "grade": "C",
        "operator": "GMO Registry",
        "reg": "$2",
        "renew": "$31",
        "vibe": "e-commerce-flavored; literally retail",
        "trust": "low-mid; locked to retail positioning",
        "seo": "no penalty per Google; reads narrow",
        "best_for": "e-commerce experiments / one-product stores",
        "catch": "15× renewal cliff; pigeonholes non-retail brands",
    },
    {
        "tld": ".life",
        "grade": "C",
        "operator": "Identity Digital (formerly Donuts)",
        "reg": "$2",
        "renew": "$29",
        "vibe": "generic lifestyle; vague",
        "trust": "low-mid; lacks definition",
        "seo": "no penalty; just unmemorable",
        "best_for": "lifestyle/wellness experiments; throwaways",
        "catch": "14× renewal cliff; brand is too soft to anchor anything",
    },
    {
        "tld": ".info",
        "grade": "C+",
        "operator": "Identity Digital",
        "reg": "$3",
        "renew": "$22",
        "vibe": "informational sites; reads dated (early-2000s)",
        "trust": "mid; recognized but unfashionable",
        "seo": "no penalty technically; \"info\" suffix can read SEO-bait",
        "best_for": "reference / informational properties; not products",
        "catch": "7× renewal cliff; dated feel limits brand growth",
    },
    {
        "tld": ".pro",
        "grade": "C+",
        "operator": "Identity Digital",
        "reg": "$3",
        "renew": "$22",
        "vibe": "professional services; was originally identity-verified",
        "trust": "mid; fine but narrow",
        "seo": "no penalty",
        "best_for": "individual practitioners, professional portfolios",
        "catch": "7× renewal cliff; \".pro\" reads niche, not product",
    },
]

# Closing summary the user asked for verbatim — anchors the trade-offs
# in the validation-pipeline context.
TLD_REFERENCE_SUMMARY = (
    "For your validation pipeline: .app and .dev are honest peers of .com "
    "(low renewal, dev-credible). .xyz is the cheap-grab that doesn't punish "
    "you on renewal. .site is fine for week-1 experiments but don't keep them."
)


def _render_tld_reference() -> None:
    """Print the per-TLD reference. One card per TLD with operator, reg/renew,
    vibe, trust, SEO, best-for, catch. Closes with a one-paragraph summary
    that frames the trade-offs in validation-pipeline terms."""
    grade_color = {
        "A+": "green", "A": "green", "A-": "green",
        "B+": "cyan",  "B": "cyan",
        "C+": "yellow", "C": "yellow",
    }
    console.print("\n[bold]TLD reference — pricing, SEO, vibe[/]\n")
    for entry in TLD_REFERENCE:
        color = grade_color.get(entry["grade"], "white")
        console.print(
            f"  [bold]{entry['tld']}[/]    Grade: [{color}]{entry['grade']}[/]"
        )
        console.print(f"    operator   {entry['operator']}")
        console.print(f"    reg/renew  {entry['reg']} / {entry['renew']}")
        console.print(f"    vibe       {entry['vibe']}")
        console.print(f"    trust      {entry['trust']}")
        console.print(f"    SEO        {entry['seo']}")
        console.print(f"    best for   {entry['best_for']}")
        console.print(f"    catch      {entry['catch']}")
        console.print()
    console.print(f"[dim]{TLD_REFERENCE_SUMMARY}[/]")


def _render_menu(shortlist_count: int = 0) -> None:
    """Render the post-grid menu. When shortlist_count > 0, item 6's label
    gets a "(N marked)" suffix so the user can see at a glance how big their
    finalists list has grown."""
    console.print("\n[bold]What do you want to do next?[/]")
    for key, label, coming_soon in MENU_ITEMS:
        line = f"  {key}. {label}"
        if key == "6" and shortlist_count > 0:
            line += f" ({shortlist_count} marked)"
        if coming_soon:
            line += "  [dim](coming soon)[/]"
        console.print(line)
    console.print("  q. Quit")


def _menu_keys_hint() -> str:
    """Format the menu keys for the bad-input hint, e.g. '1, 2, 5, 6, 7, 8'."""
    return ", ".join(k for k, _, _ in MENU_ITEMS)


def _menu_pick(rows, tld_list):
    """Sub-prompt for menu option 1. Returns (row, tld) on success or None."""
    sub = typer.prompt("Which row? (N or N.tld)", default="", show_default=False).strip().lower()
    if not sub:
        return None
    idx, override_tld, err = parse_pick_input(sub, len(rows), tld_list)
    if err:
        console.print(f"[red]{err}[/]")
        return None
    row = rows[idx]
    if override_tld is not None:
        cell = row.cells.get(override_tld)
        if cell is None:
            console.print(f"[red]{override_tld} not in this row.[/]")
            return None
        if cell.available is False:
            console.print(f"[red]{row.name}{override_tld} is taken.[/]")
            return None
        if cell.over_max:
            console.print(f"[red]{row.name}{override_tld} is priced over --max-price (${cell.price:.2f}).[/]")
            return None
        return row, override_tld
    if row.pick_tld is None:
        console.print("[red]Row has no recommended TLD (.com poisoned). Use N.tld syntax to override.[/]")
        return None
    return row, row.pick_tld


def _menu_expand(rows, tld_list, max_price, show_renewal):
    """Sub-prompt for menu option 2. Reuses parse_expand_input by prefixing 'e '
    so user can type a bare row number or name. Returns (row, tld) if user
    picked from the expanded view, otherwise None."""
    sub = typer.prompt("Which row? (number or name)", default="", show_default=False).strip().lower()
    if not sub:
        return None
    cmd = "e " + sub
    idx, err = parse_expand_input(cmd, rows)
    if err:
        console.print(f"[red]{err}[/]")
        return None
    return _expand_and_pick(rows[idx], tld_list, max_price, show_renewal=show_renewal)


def parse_shortlist_input(s: str, rows) -> tuple[str | None, list[str], list[str]]:
    """Parse a shortlist sub-prompt input. Returns `(action, names, errors)`.

    Accepts (single OR multi-target; comma- and/or whitespace-separated):
      - `m N` / `m N1 N2 ...` / `m alpha beta` → ("mark", [...], [...])
      - `u N` / `u N1, N2`                      → ("unmark", [...], [...])
      - empty / `b` → ("back", [], [])
      - **bare targets without a verb** → implicit mark, e.g. `39 18`
        becomes `("mark", ["row39name", "row18name"], [])`.

    Per-target errors (out-of-range, unknown name) accumulate in the errors
    list while valid targets accumulate in names — partial successes succeed.
    A pure parse failure (missing targets after `m`/`u`) returns
    `(None, [], [error])`.

    Note: the `p` (print) action was removed in v4.A polish — the shortlist
    is auto-printed when the user enters the sub-prompt, so an explicit
    print verb is redundant.
    """
    s = s.strip().lower()
    if not s or s == "b":
        return "back", [], []
    parts = s.split(None, 1)
    first = parts[0]
    if first in ("m", "u"):
        if len(parts) < 2:
            return None, [], [f"missing target(s) after '{first}'"]
        verb = first
        rest = parts[1].strip()
    else:
        # Implicit mark — treat the entire input as targets.
        verb = "m"
        rest = s
    # Tokenize targets — accept comma OR whitespace separators.
    targets = [t for t in re.split(r"[,\s]+", rest) if t]
    if not targets:
        return None, [], [f"missing target(s) after '{verb}'"]
    resolved: list[str] = []
    errors: list[str] = []
    for target in targets:
        if target.isdigit():
            idx = int(target) - 1
            if idx < 0 or idx >= len(rows):
                errors.append(f"row {target} out of range (1-{len(rows)})")
                continue
            resolved.append(rows[idx].name)
        else:
            name_part = target.split(".", 1)[0] if "." in target else target
            match = next((r for r in rows if r.name.lower() == name_part), None)
            if match is None:
                errors.append(f"no row matches '{name_part}'")
                continue
            resolved.append(match.name)
    action = "mark" if verb == "m" else "unmark"
    return action, resolved, errors


def _print_shortlist(shortlist: list[str], rows) -> None:
    """Pretty-print the current shortlist with each finalist's pick TLD + price."""
    if not shortlist:
        console.print("[yellow]Shortlist is empty.[/]")
        return
    console.print(f"\n[bold]Shortlist ({len(shortlist)}):[/]")
    by_name = {r.name: r for r in rows}
    for i, name in enumerate(shortlist, 1):
        row = by_name.get(name)
        if row is None:
            console.print(f"  {i}. {name}  [dim](not in current grid)[/]")
            continue
        pick = row.pick_label or "-"
        # Surface the price of the picked TLD if known.
        price_s = ""
        if row.pick_tld:
            cell = row.cells.get(row.pick_tld)
            if cell and cell.price is not None:
                price_s = f"  ${cell.price:.0f}"
        console.print(f"  {i}. [bold]{name}[/]  Pick: [cyan]{pick}[/]{price_s}")


# v4.C 2026-05-08: ask-AI-about-a-name (option 3) orchestrator.


def _menu_ask_ai(rows, topic: str, vocab_terms: list[str] | None,
                 openai_key: str) -> None:
    """Sub-prompt for menu option 3. Forgiving parser: scans the full input
    for any token that matches a row name (case-insensitive, .tld stripped).
    First match wins; the entire input becomes the question.

    Accepts:
      - `donready`                            → name=donready, default Q
      - `donready is this clinical?`          → name=donready, question=full input
      - `what is donready`                    → name=donready, question=full input
      - `compare donready vs scrubsync`       → name=donready (first match), Q=full input
    """
    from .decide import ask_ai_about_name
    if not openai_key:
        console.print("[red]OPENAI_API_KEY not set — Ask AI requires it.[/]")
        return
    sub = typer.prompt(
        "Which name to ask about? (e.g. 'donready' or 'what is donready')",
        default="", show_default=False,
    ).strip()
    if not sub:
        return
    # Token-scan for first matching row name.
    name_lookup = {r.name.lower(): r for r in rows}
    tokens = re.findall(r"[a-z][a-z0-9]*", sub.lower())
    match = next((name_lookup[t] for t in tokens if t in name_lookup), None)
    if match is None:
        sample = ", ".join(r.name for r in rows[:6])
        more = "..." if len(rows) > 6 else ""
        console.print(f"[red]No row name found in your input. Try one of:[/] {sample}{more}")
        return
    # Whether the user typed just the name (use default question) or wrote
    # a sentence (use the whole input as the question).
    only_name = sub.strip().lower() == match.name.lower()
    question = "" if only_name else sub
    console.print(f"[dim]asking gpt-5-mini about [bold]{match.name}[/]...[/]")
    try:
        answer = ask_ai_about_name(match.name, topic, vocab_terms, question, openai_key)
    except Exception as e:
        console.print(f"[red]Ask AI failed: {type(e).__name__}: {e}[/]")
        return
    console.print(f"\n[bold]{match.name}[/]")
    console.print(f"  {answer}\n")


# v4.C 2026-05-08: widen-search (option 4) orchestrator.


def _menu_widen(rows, *, topic: str, vocab_terms: list[str] | None,
                tld_list: list[str], max_price: float, pricing_dict: dict | None,
                avail_fn, show_renewal: bool, openai_key: str, log_fn):
    """Sub-prompt for menu option 4. Asks the user for optional guidance
    ("shorter", "foreign roots", etc.), calls widen_brainstorm, probes
    availability, merges into the grid. Returns the (possibly-merged)
    rows list."""
    from .suggest import (
        FULL_LADDER, build_grid, filter_pickable_rows, widen_brainstorm,
    )
    if not openai_key:
        console.print("[red]OPENAI_API_KEY not set — Widen requires it.[/]")
        return rows
    guidance = typer.prompt(
        "Guidance? (optional, e.g. 'shorter', 'foreign roots'; Enter for none)",
        default="", show_default=False,
    ).strip()
    history = [r.name for r in rows]
    console.print("[dim]asking gpt-5-mini for widened candidates...[/]")
    new_cands = widen_brainstorm(
        topic=topic, history=history, vocab_terms=vocab_terms,
        guidance=guidance, api_key=openai_key, log_fn=log_fn,
    )
    if not new_cands:
        console.print("[yellow]No new candidates returned. Try different guidance or run again.[/]")
        return rows
    console.print(f"[dim]+ {len(new_cands)} new name(s): {', '.join(c.name for c in new_cands)}[/]")
    new_rows = build_grid(
        new_cands, topic, tld_list, avail_fn,
        max_price=max_price, pricing_dict=pricing_dict,
        full_ladder=list(FULL_LADDER),
        vocab_terms=vocab_terms,
    )
    new_rows = filter_pickable_rows(new_rows)
    if not new_rows:
        console.print(f"[yellow]Widen produced names but none had a pickable cell under --max-price=${max_price:.2f}.[/]")
        return rows
    new_names = {r.name for r in new_rows}
    merged = new_rows + [r for r in rows if r.name not in new_names]
    merged.sort(key=lambda r: r.name.lower())
    _render_grid(merged, tld_list, show_renewal=show_renewal)
    return merged


# v4.B 2026-05-08: decide-from-shortlist orchestrator + helpers.


def _render_decide_table(finalists, max_price: float) -> None:
    """Focused comparison table for the decide phase. Columns:
    name · reg · renew (with cliff marker) · pick · anchors · defense.
    No per-TLD cell columns (cleaner than the full grid)."""
    t = Table(box=None, padding=(0, 1), show_header=True,
              title="[bold]Decide — finalists comparison[/]",
              title_justify="left")
    t.add_column("#", justify="right")
    t.add_column("Name", style="bold")
    t.add_column("Reg", justify="right")
    t.add_column("Renew", justify="right")
    t.add_column("Pick", style="cyan")
    t.add_column("Anchors", style="magenta")
    t.add_column("Defense")
    for i, row in enumerate(finalists, 1):
        pick_tld = row.pick_tld or "-"
        cell = row.cells.get(pick_tld) if row.pick_tld else None
        reg_s = f"${cell.price:.0f}" if (cell and cell.price is not None) else "-"
        renew_val = cell.renewal if cell else None
        renew_s = f"${renew_val:.0f}" if renew_val is not None else "-"
        cliff = _renewal_cliff_marker(cell.price if cell else None, renew_val)
        if cliff:
            renew_s += cliff
        anchors = " · ".join(row.anchors_matched) if row.anchors_matched else "-"
        # Defense one-liner.
        com_cell = row.cells.get(".com")
        if pick_tld == ".com":
            defense = "[dim]is the pick[/]"
        elif com_cell and com_cell.available is True and not com_cell.over_max:
            defense = "[green].com avail[/]"
        elif com_cell and com_cell.com_class == "live-site":
            defense = "[red].com is a live site[/]"
        elif com_cell and com_cell.available is False:
            defense = "[yellow].com taken[/]"
        else:
            defense = "[dim]?[/]"
        t.add_row(str(i), row.name, reg_s, renew_s,
                  row.pick_label or pick_tld, anchors, defense)
    console.print(t)


def _decide_step1_brand_collision(finalists, brave_key: str, openai_key: str) -> None:
    from .decide import check_brand_collision
    backend_label = "Brave Search" if brave_key else "AI fallback (gpt-5-mini)"
    console.print(f"\n[bold]Step 1/6 — Brand collision check[/]  [dim]({backend_label})[/]")
    for row in finalists:
        result = check_brand_collision(row.name, brave_key, openai_key)
        console.print(f"  [bold]{row.name}[/]")
        if result.backend == "brave":
            if not result.hits:
                console.print("    [dim](no notable results)[/]")
            for hit in result.hits:
                title = hit.title or "(no title)"
                console.print(f"    · [bold]{title}[/]")
                if hit.url:
                    console.print(f"      [dim]{hit.url}[/]")
        elif result.backend == "ai":
            console.print(f"    {result.ai_verdict}")
        else:
            err = result.error or "skipped"
            console.print(f"    [yellow](skipped: {err})[/]")


def _decide_step2_uspto(finalists) -> None:
    from .decide import uspto_tess_url
    console.print("\n[bold]Step 2/6 — USPTO TESS quick search[/]  [dim](manual click-through)[/]")
    for row in finalists:
        console.print(f"  [bold]{row.name}[/]  [dim]{uspto_tess_url(row.name)}[/]")


def _decide_step3_extensibility(finalists, topic: str,
                                vocab_terms: list[str] | None,
                                openai_key: str) -> None:
    from .decide import assess_extensibility_safe
    console.print("\n[bold]Step 3/6 — Brand-extensibility[/]  [dim](AI assessment)[/]")
    for row in finalists:
        verdict = assess_extensibility_safe(row.name, topic, vocab_terms, openai_key)
        console.print(f"  [bold]{row.name}[/]  {verdict}")


def _decide_step4_cost(finalists) -> None:
    from .decide import compute_five_year_cost
    console.print("\n[bold]Step 4/6 — 5-year cost projection[/]  [dim](reg + 4×renewal)[/]")
    for row in finalists:
        cell = row.cells.get(row.pick_tld) if row.pick_tld else None
        if cell is None:
            console.print(f"  [bold]{row.name}{row.pick_tld or ''}[/]  [dim](no pick)[/]")
            continue
        five_yr = compute_five_year_cost(cell.price, cell.renewal)
        if five_yr is None:
            console.print(f"  [bold]{row.name}{row.pick_tld}[/]  [dim](no pricing)[/]")
            continue
        reg_s = f"${cell.price:.0f}" if cell.price is not None else "—"
        renew_s = f"${cell.renewal:.0f}" if cell.renewal is not None else "—"
        console.print(
            f"  [bold]{row.name}{row.pick_tld}[/]  {reg_s} + 4×{renew_s} = "
            f"[cyan]${five_yr:.0f}[/]"
        )


def _decide_step5_phone_test(finalists) -> list[str]:
    from .decide import parse_test_response
    console.print("\n[bold]Step 5/6 — Phone test[/]  [dim](interactive)[/]")
    console.print("  Say \"the site is <name>\" out loud for each finalist:")
    for row in finalists:
        console.print(f"    · {row.name}")
    sub = typer.prompt(
        "  Names that tripped you (comma-sep), or Enter for none",
        default="", show_default=False,
    )
    matched, unrecognized = parse_test_response(sub, [r.name for r in finalists])
    for u in unrecognized:
        console.print(f"  [yellow]'{u}' not in the finalists — typo?[/]")
    return matched


def _decide_step6_memory_test(finalists) -> list[str]:
    from .decide import parse_test_response
    console.print("\n[bold]Step 6/6 — Memory test[/]  [dim](interactive)[/]")
    console.print("  Look away for 30 seconds, then list the finalists from memory.")
    sub = typer.prompt(
        "  Names you couldn't recall (comma-sep), or Enter for none",
        default="", show_default=False,
    )
    matched, unrecognized = parse_test_response(sub, [r.name for r in finalists])
    for u in unrecognized:
        console.print(f"  [yellow]'{u}' not in the finalists — typo?[/]")
    return matched


def _menu_decide(rows, shortlist: list[str], tld_list: list[str],
                 max_price: float, topic: str, vocab_terms: list[str] | None,
                 brave_key: str, openai_key: str):
    """Menu option 7 orchestrator. Returns (row, tld) pick or None."""
    finalists = [r for r in rows if r.name in shortlist]
    if not finalists:
        console.print("[yellow]Shortlist is empty — mark some candidates first (option 6).[/]")
        return None

    _render_decide_table(finalists, max_price=max_price)
    _decide_step1_brand_collision(finalists, brave_key, openai_key)
    _decide_step2_uspto(finalists)
    _decide_step3_extensibility(finalists, topic, vocab_terms, openai_key)
    _decide_step4_cost(finalists)
    phone_concerns = _decide_step5_phone_test(finalists)
    memory_concerns = _decide_step6_memory_test(finalists)

    console.print("\n[bold]Test concerns:[/]")
    console.print(f"  · Phone test:  {', '.join(phone_concerns) if phone_concerns else '[dim](none)[/]'}")
    console.print(f"  · Memory test: {', '.join(memory_concerns) if memory_concerns else '[dim](none)[/]'}")

    while True:
        choice = typer.prompt(
            f"\nPick row 1-{len(finalists)} to register, or b to back to menu",
            default="b", show_default=False,
        ).strip().lower()
        if choice == "b" or not choice:
            return None
        if not choice.isdigit():
            console.print(f"[red]Type 1-{len(finalists)} or b.[/]")
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(finalists):
            console.print(f"[red]Row {choice} out of range (1-{len(finalists)}).[/]")
            continue
        row = finalists[idx]
        if row.pick_tld is None:
            console.print(f"[red]{row.name} has no recommended TLD; remove from shortlist or fix.[/]")
            continue
        return row, row.pick_tld


def _menu_shortlist(rows, shortlist: list[str]) -> list[str]:
    """Sub-prompt for menu option 6. Multi-target per invocation
    (`m 5 7 12` or `m 5,7,12` marks three at once).

    v4.A polish 2026-05-08: stays in this sub-prompt loop until the user
    types `b` (back). Each iteration auto-prints the current shortlist so
    the user sees their state after every modification. Returns the
    (possibly-modified) shortlist when `b` is pressed.
    """
    current = list(shortlist)
    while True:
        _print_shortlist(current, rows)
        sub = typer.prompt(
            "Action? (just type N or names to mark, e.g. '39 18' or 'alpha beta'; "
            "u to unmark, b to back)",
            default="", show_default=False,
        )
        action, names, errors = parse_shortlist_input(sub, rows)
        for err in errors:
            console.print(f"[red]{err}[/]")
        if action == "back":
            return current
        if action is None:
            continue
        if action == "mark":
            for name in names:
                if name in current:
                    console.print(f"[yellow]{name} is already on the shortlist.[/]")
                    continue
                current.append(name)
                console.print(f"[green]✓[/] Marked [bold]{name}[/]")
        elif action == "unmark":
            for name in names:
                if name not in current:
                    console.print(f"[yellow]{name} is not on the shortlist.[/]")
                    continue
                current.remove(name)
                console.print(f"[green]✓[/] Unmarked [bold]{name}[/]")


def _menu_add_names(rows, *, topic, openai_key, vocab_terms, tld_list,
                    max_price, pricing_dict, avail_fn, show_renewal, log_fn):
    """Sub-prompt for menu option 5. Returns the (possibly-merged) rows list.
    Empty input or all-rejected names returns the rows unchanged.

    v4.A 2026-05-08: after collecting seeds, optionally invokes
    `expand_user_seeds` to ask gpt-5-mini for plurals / near-synonyms /
    prefix-suffix riffs / adjacent anchors. Default Y so the user doesn't
    have to type every variation; pass n to skip.
    """
    from .suggest import (
        Candidate, FULL_LADDER, build_grid, expand_user_seeds,
        filter_pickable_rows, screen_for_content_strict,
    )
    sub = typer.prompt(
        "Names to add (comma-separated, no TLDs)",
        default="", show_default=False,
    ).strip()
    if not sub:
        return rows
    valid_names, rejected = _parse_user_added_names(sub)
    for r in rejected:
        console.print(f"[yellow]skipping {r}[/]")
    if not valid_names:
        console.print("[yellow]No valid names parsed.[/]")
        return rows
    valid_names, screen_dropped = screen_for_content_strict(
        valid_names, openai_key, log_fn=log_fn,
    )
    if screen_dropped:
        console.print(f"[yellow]Filtered {len(screen_dropped)} of your name(s) (content policy)[/]")
    if not valid_names:
        return rows

    # Offer to expand via AI — default Y; n skips.
    if openai_key and typer.confirm(
        "Expand with AI to get plurals, near-synonyms, etc.?",
        default=True,
    ):
        console.print(f"[dim]Asking gpt-5-mini for variants of {len(valid_names)} seed(s)...[/]")
        variants = expand_user_seeds(
            valid_names, topic, vocab_terms, openai_key, log_fn=log_fn,
        )
        if variants:
            console.print(f"[dim]+ {len(variants)} variant(s): {', '.join(variants)}[/]")
            valid_names = valid_names + variants
        else:
            console.print("[dim](no variants returned; using your seeds as-is)[/]")

    console.print(f"[dim]Probing {len(valid_names)} name(s)...[/]")
    user_cands = [Candidate(name=n, strategy="user") for n in valid_names]
    user_rows = build_grid(
        user_cands, topic, tld_list, avail_fn,
        max_price=max_price, pricing_dict=pricing_dict,
        full_ladder=list(FULL_LADDER),
        vocab_terms=vocab_terms,
    )
    user_rows = filter_pickable_rows(user_rows)
    if not user_rows:
        console.print(f"[yellow]None of those names had a pickable cell under --max-price=${max_price:.2f}.[/]")
        return rows
    user_names = {r.name for r in user_rows}
    merged = user_rows + [r for r in rows if r.name not in user_names]
    # v4.A: alphabetical, matching build_grid.
    merged.sort(key=lambda r: r.name.lower())
    _render_grid(merged, tld_list, show_renewal=show_renewal)
    return merged


def _parse_user_added_names(raw: str) -> tuple[list[str], list[str]]:
    """Parse a comma-separated list of user-supplied names. Returns
    (valid_names, rejected_with_reason). Each name must be alphabetic, lowercase,
    and ≤14 chars (matching _extract_names rules)."""
    valid: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for piece in raw.replace("\n", ",").split(","):
        n = piece.strip().lower()
        if not n:
            continue
        # Strip optional .tld if user pasted full domains
        n = n.split(".", 1)[0]
        if not re.match(r"^[a-z][a-z0-9]*$", n):
            rejected.append(f"{piece.strip()} (invalid chars)")
            continue
        if len(n) > 14:
            rejected.append(f"{piece.strip()} (too long)")
            continue
        if n in seen:
            continue
        seen.add(n)
        valid.append(n)
    return valid, rejected


def _domain_suggest_validation(
    *,
    topic: str,
    tlds: str,
    max_price: float,
    non_interactive: bool,
    no_cache: bool,
    show_renewal: bool,
    with_abstract: bool,
) -> None:
    """v3.D validation-mode flow."""
    from .availability import AvailabilityChecker, load_porkbun_pricing
    from .suggest import (
        Candidate,
        DEFAULT_TLDS,
        FULL_LADDER,
        PORTFOLIO_ENV,
        already_owned_matches,
        build_grid,
        cache_get,
        cache_set,
        filter_default_strategies,
        filter_pickable_rows,
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
    cfg_t.add_row("max price", f"${max_price:.2f}/yr (pass --max-price=N to override; 999 disables)")
    cfg_t.add_row("TLD columns", " ".join(tld_list))
    cfg_t.add_row("availability", "RDAP + DoH fallback (Google then Cloudflare)")
    cfg_t.add_row("pricing", "Porkbun /pricing/get (public, cached 7d)")
    cfg_t.add_row("brainstorm", "OpenAI gpt-5-mini (vocab anchored)")
    cfg_t.add_row("strategies", f"{len(all_strategies)} ({', '.join(s.name for s in all_strategies)})")
    cfg_t.add_row("cache", "BYPASSED (--no-cache)" if no_cache else "7d topic-hash hit/miss")
    cfg_t.add_row("mode", "non-interactive" if non_interactive else "interactive")
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

    # v3.D 2026-05-08: filter rows to those with at least one pickable cell
    # (available + under price cap). Drop the rest — nothing to do with them.
    rows = filter_pickable_rows(rows)

    if not rows:
        console.print("[yellow]No pickable candidates — every name was either taken or priced over --max-price. Try refining the topic, raising --max-price, or --no-cache.[/]")
        raise typer.Exit(0)

    _render_grid(rows, tld_list, show_renewal=show_renewal)

    if non_interactive:
        return

    # v3.E 2026-05-08: post-grid menu. Replaces the inline pick + add-names
    # loops. Re-shown after every non-terminating action; terminates only on
    # successful pick (→ post_pick_flow) or `q`.
    # v4.A 2026-05-08: shortlist persists across menu iterations (list of
    # names, so it survives grid mutations from add-names / future widen).
    selected_row = None
    selected_tld = None
    shortlist: list[str] = []
    while selected_row is None:
        _render_menu(shortlist_count=len(shortlist))
        choice = typer.prompt(">", default="", show_default=False).strip().lower()
        if choice == "q":
            console.print("[yellow]No domain selected.[/]")
            return
        if choice == "1":
            result = _menu_pick(rows, tld_list)
            if result is not None:
                selected_row, selected_tld = result
                break
            # else: error printed by _menu_pick; re-show menu
            continue
        if choice == "2":
            result = _menu_expand(rows, tld_list, max_price, show_renewal)
            if result is not None:
                selected_row, selected_tld = result
                break
            # back from expand → re-render grid then re-show menu
            _render_grid(rows, tld_list, show_renewal=show_renewal)
            continue
        if choice == "3":
            _menu_ask_ai(rows, topic=topic, vocab_terms=vocab_terms,
                         openai_key=openai_key)
            continue
        if choice == "4":
            rows = _menu_widen(
                rows, topic=topic, vocab_terms=vocab_terms,
                tld_list=tld_list, max_price=max_price,
                pricing_dict=pricing_dict, avail_fn=avail_fn,
                show_renewal=show_renewal, openai_key=openai_key, log_fn=_log,
            )
            continue
        if choice == "5":
            rows = _menu_add_names(
                rows, topic=topic, openai_key=openai_key,
                vocab_terms=vocab_terms, tld_list=tld_list,
                max_price=max_price, pricing_dict=pricing_dict,
                avail_fn=avail_fn, show_renewal=show_renewal, log_fn=_log,
            )
            continue
        if choice == "6":
            shortlist = _menu_shortlist(rows, shortlist)
            continue
        if choice == "7":
            brave_key = env.get("BRAVE_SEARCH_API_KEY", "").strip()
            result = _menu_decide(
                rows, shortlist, tld_list, max_price,
                topic=topic, vocab_terms=vocab_terms,
                brave_key=brave_key, openai_key=openai_key,
            )
            if result is not None:
                selected_row, selected_tld = result
                break
            # b from decide → main menu (shortlist preserved)
            continue
        if choice == "8":
            _render_tld_reference()
            continue
        if choice in COMING_SOON_HINTS:
            console.print(f"[dim]{COMING_SOON_HINTS[choice]}[/]")
            continue
        console.print(f"[red]Type {_menu_keys_hint()} or q.[/]")

    _post_pick_flow(
        row=selected_row,
        pick_tld=selected_tld,
        topic=topic,
        env=env,
        vocab_terms=vocab_terms,
        register_domain=register_domain,
        porkbun_cart_url=porkbun_cart_url,
    )


def _post_pick_flow(*, row, pick_tld, topic, env, vocab_terms,
                    register_domain, porkbun_cart_url) -> None:
    """Defense bundle, auto-register, next-step output. Shared between the
    main picker and the expand-view picker."""
    selected = f"{row.name}{pick_tld}"
    selected_cell = row.cells.get(pick_tld)
    is_unverified = selected_cell is not None and selected_cell.available is None
    console.print(f"\n[green]✅ Selected:[/] [bold]{selected}[/]")
    if is_unverified:
        console.print("[dim](RDAP/DoH gap on this TLD — final availability check happens at registrar checkout.)[/]")

    bundle: list[str] = []
    com_cell = row.cells.get(".com")
    app_cell = row.cells.get(".app")
    if pick_tld != ".com" and com_cell is not None and com_cell.available is True and not com_cell.over_max:
        bundle.append(".com")
    if pick_tld != ".app" and app_cell is not None and app_cell.available is True and not app_cell.over_max:
        bundle.append(".app")

    if bundle:
        bundle_doms = [f"{row.name}{t}" for t in bundle]
        bundle_str = " + ".join(bundle_doms)
        bundle_prompt = f"Defense bundle available: {bundle_str}. Open Porkbun cart with bundle? [y/N]"
        if typer.confirm(bundle_prompt, default=False):
            url = porkbun_cart_url([selected] + bundle_doms)
            console.print(f"[cyan]Bundle cart URL:[/] {url}")
            console.print("[dim](Bundle items are manual click-through; never auto-charged.)[/]")

    if is_unverified:
        console.print(f"[cyan]Register manually (verify availability first):[/] {porkbun_cart_url([selected])}")
    elif typer.confirm(f"Register {selected} now via Porkbun API?", default=False):
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

    console.print("\n[bold]Next step:[/]")
    console.print(f'  portfolio bootstrap {selected} --topic="{topic}"')
    if vocab_terms:
        console.print("\n[bold]Vocab terms[/] (paste into docs/prd.md after bootstrap):")
        console.print("  " + ", ".join(vocab_terms))


def _expand_and_pick(row, visible_columns: list[str], max_price: float,
                     show_renewal: bool = False):
    """Render an expanded full-ladder view for one row, then prompt for a
    scoped pick. Returns `(row, tld)` if user picks, `None` if user typed `b`
    (back to grid) or `q` (quit propagates as None too)."""
    _render_expanded_row(row, max_price=max_price, show_renewal=show_renewal)
    while True:
        prompt = "[N | N.tld] pick · [b] back to grid · [q] quit"
        choice = typer.prompt(f"\n{prompt}", default="b", show_default=False).strip().lower()
        if choice == "q":
            console.print("[yellow]No domain selected.[/]")
            raise typer.Exit(0)
        if choice == "b" or not choice:
            return None
        # Pick is "N" or "N.tld" but here N is irrelevant — single-row context.
        # Accept ".tld" or "tld" or full "N.tld" (any digit).
        if choice.startswith("."):
            tld = choice
        elif "." in choice:
            tld = "." + choice.split(".", 1)[1]
        else:
            # Treat as bare TLD without dot, e.g. "app" → ".app"
            tld = "." + choice
        cell = row.cells.get(tld)
        if cell is None:
            console.print(f"[red]{tld} wasn't probed for this row.[/]")
            continue
        if cell.available is False:
            console.print(f"[red]{row.name}{tld} is taken.[/]")
            continue
        if cell.over_max:
            console.print(f"[red]{row.name}{tld} is priced over --max-price (${cell.price:.2f}).[/]")
            continue
        return row, tld


def _render_expanded_row(row, max_price: float, show_renewal: bool = False) -> None:
    """Render the expanded full-ladder view for one row."""
    console.print(f"\n─── [bold]{row.name}[/] ───────────────────")
    if row.anchors_matched:
        console.print(f"  [magenta]Anchors:[/] {' · '.join(row.anchors_matched)}")
    else:
        console.print("  [magenta]Anchors:[/] [dim](none)[/]")
    console.print(f"  [cyan]Strategy:[/] {row.strategy}")
    pick_label = row.pick_label or "-"
    console.print(f"  [cyan]Pick:[/] {pick_label}  [dim]{row.why}[/]")
    console.print()

    t = Table(box=None, padding=(0, 2))
    t.add_column("TLD")
    t.add_column("Avail")
    t.add_column("Reg", justify="right")
    t.add_column("Renew", justify="right")
    t.add_column("Notes")
    # Sort cells by TLD tier desc so good options appear first.
    from .suggest import TLD_TIER
    sorted_tlds = sorted(row.cells.keys(), key=lambda t: -TLD_TIER.get(t.lower(), 0))
    for tld in sorted_tlds:
        c = row.cells[tld]
        if c.available is True:
            avail = "[green]✓[/]"
        elif c.available is False:
            if c.com_class == "live-site":
                avail = "[red]✗ live[/]"
            elif c.com_class == "parked":
                avail = "[yellow]✗ park[/]"
            elif c.com_class == "for-sale":
                avail = "[yellow]✗ sale[/]"
            else:
                avail = "[red]✗[/]"
        elif c.error:
            avail = "[red bold]✕[/]"
        else:
            avail = "[yellow]?[/]"
        reg = f"${c.price:.2f}" if c.price is not None else "-"
        renew = f"${c.renewal:.2f}" if c.renewal is not None else "-"
        notes = []
        if c.over_max:
            notes.append("over --max-price")
        cliff = _renewal_cliff_marker(c.price, c.renewal)
        if cliff:
            # cliff includes leading space + rich tag; strip the space for column form
            notes.append(cliff.strip())
        notes_s = " · ".join(notes) if notes else ""
        t.add_row(tld, avail, reg, renew, notes_s)
    console.print(t)


def _renewal_cliff_marker(price: float | None, renewal: float | None) -> str:
    """Inline cell marker showing the renewal-cliff multiplier when significant.

    Returns ` ↑Nx` when renewal/registration > 2.0 (so the bait-and-switch
    TLDs get visual flagging without a separate column). Returns "" when
    either price is missing or the cliff is mild (≤ 2x).
    """
    if price is None or renewal is None or price <= 0:
        return ""
    ratio = renewal / price
    if ratio <= 2.0:
        return ""
    return f" [yellow]↑{ratio:.0f}x[/]"


def _cell_str(state, show_renewal: bool = False) -> str:
    """Format one grid cell: ✓ $N [↑Nx] / ✗ live|park / ? / $N!"""
    if state.over_max:
        # Available but priced out; surface so user sees the option exists.
        if state.available is True and state.price is not None:
            return f"[dim]${state.price:.0f}![/]"
        if state.available is False:
            return "[red]✗[/]"
        return "[yellow]?[/]"
    if state.available is True:
        price_s = f"${state.price:.0f}" if state.price is not None else "-"
        cliff = _renewal_cliff_marker(state.price, state.renewal)
        if show_renewal and state.renewal is not None:
            return f"[green]✓[/] {price_s}{cliff}\n[dim]r ${state.renewal:.0f}[/]"
        return f"[green]✓[/] {price_s}{cliff}"
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
    """Render the v3.D registrar grid: rows = names, cols = TLD cells + Anchors
    + Pick + Why. Anchors column shows vocab terms found in the name (the row
    differentiator); cliff markers (↑Nx) on cells flag renewal bait-and-switch
    (the column differentiator)."""
    t = Table(box=None, padding=(0, 1))
    t.add_column("#", justify="right")
    t.add_column("Name", style="bold")
    for c in columns:
        t.add_column(c, justify="left")
    t.add_column("Anchors", style="magenta")
    t.add_column("Pick", style="cyan")
    t.add_column("Why")
    for i, row in enumerate(rows, 1):
        cells_rendered = [_cell_str(row.cells.get(c), show_renewal=show_renewal) if row.cells.get(c) else "-" for c in columns]
        anchors = " · ".join(row.anchors_matched) if row.anchors_matched else "-"
        pick = row.pick_label or "-"
        t.add_row(str(i), row.name, *cells_rendered, anchors, pick, row.why)
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
