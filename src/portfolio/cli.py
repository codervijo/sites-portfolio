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
from .data import load_domains, load_plan

app = typer.Typer(help="Manage your domain portfolio.", add_completion=False, no_args_is_help=True)
console = Console()


@app.command()
def summary() -> None:
    """Print a portfolio overview."""
    domains = load_domains()
    plan = load_plan()

    total_renewal = sum(d.renewal_price for d in domains if d.renewal_price)
    total_value = sum(d.estimated_value for d in domains if d.estimated_value)

    t = Table(title="Portfolio Summary", show_header=False)
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    t.add_row("Total domains", str(len(domains)))
    t.add_row("Active", str(sum(1 for d in domains if d.status.lower() == "active")))
    t.add_row("On hold", str(sum(1 for d in domains if d.status.lower() == "hold")))
    t.add_row("Listed for sale", str(sum(1 for d in domains if "listed" in d.listing_status.lower())))
    t.add_row("Auto-renew on", str(sum(1 for d in domains if d.auto_renew.lower() == "on")))
    t.add_row("Annual renewal cost", f"${total_renewal:,.2f}")
    t.add_row("Estimated value", f"${total_value:,.2f}")
    console.print(t)

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
        console.print(f"\n[yellow]In CSV but not in plan ({len(only_csv)}):[/] " + ", ".join(only_csv))
    if only_plan:
        console.print(f"\n[yellow]In plan but not in CSV ({len(only_plan)}):[/] " + ", ".join(only_plan))


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


if __name__ == "__main__":
    app()
