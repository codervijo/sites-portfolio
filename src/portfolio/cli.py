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

app = typer.Typer(
    help=(
        "lamill — manage your domain fleet + sites/ workspace.\n"
        "Primary namespaces:\n"
        "  project  — per-project ops (check, fix, seo, diagnose, set-launched)\n"
        "  fleet    — cross-fleet ops (focus, live, seo, check, fix, drift, repos, dashboard, info)\n"
        "  new      — create new things (suggest, bootstrap, deploy, research)\n"
        "  settings — setup / debug (catalog, gsc, apikeys)"
    ),
    add_completion=False,
)
console = Console()

new_app = typer.Typer(
    help="Add new domains / projects (suggest, bootstrap, deploy, research).",
    no_args_is_help=True,
)
app.add_typer(new_app, name="new")

# v7.A — scope-first restructure. `project` for ops on one project,
# `fleet` for cross-portfolio ops, `settings` for setup/debug surfaces.
# Each new command is a thin wrapper that forwards to existing logic;
# old paths (`info status`, `check git --domain`, etc.) are kept as
# deprecation aliases that print a one-line nudge and forward.
fleet_app = typer.Typer(
    help="Cross-portfolio ops (focus, live, seo, check, fix, drift, repos, dashboard, info).",
    no_args_is_help=True,
)
fleet_info_app = typer.Typer(
    help="Read-only inventory views (summary, expiring, cleanup).",
    no_args_is_help=True,
)
settings_app = typer.Typer(
    help="Setup / debug surfaces (catalog, gsc, apikeys).",
    no_args_is_help=True,
)
settings_catalog_app = typer.Typer(
    help="Inspect the check catalog itself.",
    no_args_is_help=True,
)
settings_gsc_app = typer.Typer(
    help="Google Search Console integration.",
    no_args_is_help=True,
)
settings_apikeys_app = typer.Typer(
    help="Manage credentials in portfolio.env.",
    no_args_is_help=True,
)
app.add_typer(fleet_app, name="fleet")
fleet_app.add_typer(fleet_info_app, name="info")
app.add_typer(settings_app, name="settings")
settings_app.add_typer(settings_catalog_app, name="catalog")
settings_app.add_typer(settings_gsc_app, name="gsc")
settings_app.add_typer(settings_apikeys_app, name="apikeys")


@app.callback(invoke_without_command=True)
def _root_callback(ctx: typer.Context) -> None:
    """When `lamill` is invoked with no subcommand, drop into the grouped
    interactive menu. Explicit subcommands work unchanged."""
    if ctx.invoked_subcommand is None:
        from .menu import run_menu
        run_menu()


@app.command()
def focus(
    show_all: bool = typer.Option(False, "--all", help="Show the full ranked list, not just top 5"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-run live + SEO probes upstream before reading caches"),
    include_young: bool = typer.Option(
        False, "--include-young",
        help="Also flag SEO signals on sites <90d old (suppressed by default — those signals are normal in the Google freshness window)",
    ),
) -> None:
    """[v7.A — moved to `portfolio fleet focus`] Where to focus today.

    Reads from caches only — never blocks on a live fetch. If a cache
    is missing, that signal is silently skipped. Run `check live` /
    `check seo` first to populate them. `--refresh` does it for you.
    """
    from .check import latest_snapshot as live_latest
    from .check import load_snapshot as load_live
    from .dashboard import _site_age_days
    from .focus import build_focus_list, domains_with_expiry_from_portfolio
    from .seo_cache import latest_snapshot as seo_latest
    from .seo_cache import load_snapshot as load_seo

    if refresh:
        # Re-run live + seo upstream. Same shape as fleet dashboard --refresh.
        from .check import run_check
        from .seo_cache import save_snapshot as seo_save_snapshot
        from .seo_runtime import _live_domains_from_snapshot, run_seo
        from .suggest import load_env

        console.print("[cyan]Refreshing live snapshot (scope=wip)...[/]")
        snap_path, _ = run_check(only="wip", concurrency=20)
        console.print(f"[dim]Snapshot: {snap_path.name}[/]")
        domains = _live_domains_from_snapshot(load_live(snap_path))
        if domains:
            crux_key = load_env().get("CRUX_API_KEY", "").strip()
            console.print(f"[cyan]Refreshing SEO probes ({len(domains)} domains)...[/]")

            def progress(done: int, total: int, dom: str) -> None:
                console.print(f"[dim]  [{done}/{total}] {dom}[/]")
            seo_rows = run_seo(domains, days=28, crux_api_key=crux_key,
                               progress_callback=progress)
            cache_path = seo_save_snapshot(seo_rows, days=28)
            console.print(f"[dim]SEO cached: {cache_path.name}[/]")

    # Pull every signal source. None / empty means "skip that signal."
    live_path = live_latest()
    live_data = load_live(live_path) if live_path else None

    seo_path = seo_latest()
    seo_data = load_seo(seo_path) if seo_path else None

    all_domains = load_domains()
    domains_expiry = domains_with_expiry_from_portfolio(all_domains)
    # Build domain → category map so focus can skip "To be deleted immediately"
    # rows. Lowercase keys for case-insensitive matching.
    domain_categories = {d.name.lower(): (d.category or "") for d in all_domains}

    # Build domain → site-age map for the freshness-window suppression.
    # Reuses the dashboard's helper: prefers Domain.launched (manual via
    # `project set-launched`); falls back to first-commit-date inference
    # for projects without an explicit launched date.
    domain_site_age = {
        d.name.lower(): _site_age_days(d.name, d.launched)
        for d in all_domains
    }

    suppressed_young: list[str] = []
    items = build_focus_list(
        live_snapshot=live_data,
        seo_snapshot=seo_data,
        domains_with_expiry=domains_expiry,
        domain_categories=domain_categories,
        domain_site_age_days=domain_site_age,
        include_young=include_young,
        suppressed_young_out=suppressed_young,
    )

    # Header notes: which sources were available?
    notes = []
    if live_path:
        notes.append(f"live: {live_path.name}")
    else:
        notes.append("[yellow]live: missing (run `check live`)[/]")
    if seo_path:
        notes.append(f"seo: {seo_path.name}")
    else:
        notes.append("[yellow]seo: missing (run `check seo`)[/]")
    notes.append(f"expiry: {len(domains_expiry)} domains")
    console.print(f"[dim]Sources — {' · '.join(notes)}[/]\n")

    if not items and not suppressed_young:
        console.print("[green]Nothing to focus on — every signal is clean.[/]")
        return
    if not items:
        console.print(
            f"[green]Nothing to focus on[/] — "
            f"[dim]{len(suppressed_young)} young site(s) had SEO signals "
            f"suppressed (use --include-young to see).[/]"
        )
        return

    cap = len(items) if show_all else 5
    head = items[:cap]
    title = (
        f"[bold]All {len(items)} domains to focus on:[/]"
        if show_all
        else f"[bold]Top {len(head)} domains to focus on today:[/]"
    )
    console.print(title)
    for i, item in enumerate(head, 1):
        # Lead line: rank + domain + worst signal
        lead = item.signals[0]
        emoji, headline, action = lead
        console.print(f"  #{i}  [bold]{item.domain:<22}[/] {emoji} {headline}")
        console.print(f"      [dim]{action}[/]")
        # Additional signals on the same domain
        for emoji, headline, action in item.signals[1:]:
            console.print(f"      {emoji} {headline}  [dim]{action}[/]")
        console.print()

    if not show_all and len(items) > cap:
        console.print(
            f"[dim]+ {len(items) - cap} more — run "
            f"`portfolio fleet focus --all` for full list[/]"
        )

    if suppressed_young and not include_young:
        # Listing the sample names helps the reader confirm we suppressed
        # the right ones; full list with --include-young.
        sample = ", ".join(suppressed_young[:3])
        more = f" + {len(suppressed_young) - 3} more" if len(suppressed_young) > 3 else ""
        console.print(
            f"\n[dim]🌱 {len(suppressed_young)} young site(s) <90d "
            f"({sample}{more}) had SEO signals suppressed — "
            f"use --include-young to see them.[/]"
        )


# info_drift — kept as implementation for `fleet drift`.
def info_drift() -> None:
    """Cross-check the four sources of truth and surface inconsistencies.

    Read-only. Six signals:
      1. Registered but never bootstrapped (in portfolio.json, no sites/<dir>/)
      2. CSV-only domains (in registrar CSV, missing from portfolio.json)
      3. Expiry mismatches (CSV expires != portfolio.json expires)
      4. GSC orphans (verified GSC properties with no portfolio.json entry)
      5. Deployed-but-flagged-for-deletion (live-site classification on a
         domain in 'To be deleted immediately' category)
      6. Duplicate across registrars (same domain in two CSVs — transfer
         didn't clean up source)

    Domains in 'To be deleted immediately' category are excluded from
    signal 1 (they're already retired; no point flagging absence).
    """
    from .drift import compute_drift

    report = compute_drift()

    if report.is_clean() and not report.gsc_skipped and not report.snapshot_skipped:
        console.print("[green]No drift — all four sources agree.[/]")
        return

    console.print("[bold]Drift report[/]\n")

    # Signal 1: portfolio_no_dir
    console.print("[bold]1. Registered but never bootstrapped[/] "
                  f"[dim]({len(report.portfolio_no_dir)})[/]")
    if report.portfolio_no_dir:
        for d in report.portfolio_no_dir:
            console.print(f"   {d}")
    else:
        console.print("   [dim]—[/]")
    console.print()

    # Signal 2: csv_only
    console.print(f"[bold]2. CSV-only — registrar exports newer than portfolio.json[/] "
                  f"[dim]({len(report.csv_only)})[/]")
    if report.csv_only:
        for domain, registrar in report.csv_only:
            console.print(f"   {domain}  [dim]({registrar})[/]")
        console.print(f"   [dim]→ run 'portfolio fleet info cleanup' to consolidate[/]")
    else:
        console.print("   [dim]—[/]")
    console.print()

    # Signal 3: expiry_mismatches
    console.print(f"[bold]3. Expiry mismatches — CSV vs portfolio.json[/] "
                  f"[dim]({len(report.expiry_mismatches)})[/]")
    if report.expiry_mismatches:
        for ed in report.expiry_mismatches:
            console.print(
                f"   {ed.domain}  [dim]({ed.registrar})[/]  "
                f"csv={ed.csv_expires} json={ed.json_expires}"
            )
        console.print(f"   [dim]→ run 'portfolio fleet info cleanup' to refresh[/]")
    else:
        console.print("   [dim]—[/]")
    console.print()

    # Signal 4: gsc_orphans
    if report.gsc_skipped:
        console.print("[bold]4. GSC orphans[/] [yellow](skipped — GSC not authenticated)[/]")
    else:
        console.print(f"[bold]4. GSC orphans — verified in Search Console but not in portfolio.json[/] "
                      f"[dim]({len(report.gsc_orphans)})[/]")
        if report.gsc_orphans:
            for d in report.gsc_orphans:
                console.print(f"   {d}")
        else:
            console.print("   [dim]—[/]")
    console.print()

    # Signal 5: deployed_but_flagged
    if report.snapshot_skipped:
        console.print("[bold]5. Deployed but flagged for deletion[/] "
                      "[yellow](skipped — no check snapshot)[/]")
    else:
        console.print(f"[bold]5. Deployed but flagged for deletion[/] "
                      f"[dim]({len(report.deployed_but_flagged)})[/]")
        if report.deployed_but_flagged:
            for df in report.deployed_but_flagged:
                console.print(
                    f"   {df.domain}  [yellow]{df.classification}[/]  "
                    f"[dim](category: {df.category})[/]"
                )
        else:
            console.print("   [dim]—[/]")
    console.print()

    # Signal 6: duplicate_in_registrars
    console.print(f"[bold]6. Duplicate across registrars[/] "
                  f"[dim]({len(report.duplicate_in_registrars)})[/]")
    if report.duplicate_in_registrars:
        for dup in report.duplicate_in_registrars:
            console.print(
                f"   {dup.domain}  [dim]({', '.join(dup.registrars)})[/]"
            )
    else:
        console.print("   [dim]—[/]")


# info_cleanup — kept as implementation for `fleet info cleanup`.
def info_cleanup(refresh_rdap: bool = False) -> None:
    """Build canonical data/portfolio.json from registrar CSVs + plan.md classifications.

    With `refresh_rdap=True`, also fetches each domain's RDAP creation
    date (global registration age, distinct from registrar-account
    creation) and stores it as `domain_created`. ~0.5s per domain.
    """
    out_path, domains, uncategorized = run_cleanup()

    if refresh_rdap:
        from .availability import rdap_creation_date
        from .data import update_domain_field
        console.print(f"[cyan]Fetching RDAP creation dates ({len(domains)} domains)...[/]")
        hit = miss = 0
        for i, d in enumerate(domains, start=1):
            if d.domain_created is not None:
                # Already cached — RDAP creation_date doesn't change. Skip.
                hit += 1
                continue
            console.print(f"[dim]  [{i}/{len(domains)}] {d.name}[/]")
            cd = rdap_creation_date(d.name)
            if cd is not None:
                update_domain_field(d.name, "domain_created", cd)
                hit += 1
            else:
                miss += 1
        console.print(f"[dim]RDAP: {hit} resolved · {miss} unresolved[/]")

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


# info_summary — kept as implementation for `fleet info summary`.
def info_summary() -> None:
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


# info_expiring — kept as implementation for `fleet info expiring`.
def info_expiring(within: int = typer.Option(180, "--within", "-w", help="Days from today")) -> None:
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


# `info wip` was removed in v5.F.1 — covered by `info list --grouped`
# (the user picks the WIP-relevant categories visually). Deprecation
# shim lives at the bottom of the file with the other v5.F shims.

# `info category` was merged into `info list` in v5.F.1 — same single
# command supports flat (default), grouped, and category-filtered modes.
# Deprecation shim at the bottom of the file.


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


_SEVERITY_COLOR = {"error": "red", "warn": "yellow", "info": "cyan"}


# ---------- v5.F.2: check live / git / seo as real subcommands ----------
#
# Pre-v5.F.2 these were callback flags (`check --live`, `check --git`,
# `check --seo`). The callback form is preserved as a deprecation alias
# (see `check_callback` below) so existing scripts keep working through
# one transition window.


# check_live — kept as implementation for `fleet live`.
def check_live(
    only: str = typer.Option("wip", "--only", "-o", help="Scope: 'wip' or 'all' (ignored when --domain is set)"),
    concurrency: int = typer.Option(20, "--concurrency", "-c", help="Max parallel HTTP requests"),
    domain: str = typer.Option("", "--domain", help="One-shot probe of a single domain (does not overwrite the snapshot)"),
) -> None:
    """Live HTTP fetch + classify every domain → snapshot in data/checks/.

    With `--domain <one>`, probes just that domain (both bare + www
    variants) and renders the result inline. The shared snapshot file
    is NOT overwritten — a single-domain probe shouldn't shrink the
    cross-portfolio view that other commands (`focus`, `check seo`)
    depend on.
    """
    if domain:
        # One-shot: probe just this domain, don't touch data/checks/.
        import asyncio
        from dataclasses import asdict
        from .check import _run_all
        results = asyncio.run(_run_all([domain.lower()], concurrency))
        console.print(f"\n[bold]check live · {domain}[/]  [dim](one-shot — snapshot file untouched)[/]")
        for r in results:
            cls = r.classification
            cls_color = LIVE_CLS_COLORS.get(cls, "white")
            status = r.status if r.status is not None else "—"
            ms = f", {r.response_time_ms}ms" if r.response_time_ms is not None else ""
            url = f" → {r.final_url}" if r.final_url else ""
            console.print(
                f"  [bold]{r.variant:<6}[/] [{cls_color}]{cls}[/] (HTTP {status}{ms}){url}"
            )
            if r.error:
                console.print(f"          [red]error:[/] {r.error}")
        return
    if only not in ("wip", "all"):
        console.print(f"[red]--only must be 'wip' or 'all', got {only!r}.[/]")
        raise typer.Exit(2)
    console.print(f"[cyan]Checking {only} domains (concurrency={concurrency})...[/]")
    out, _ = run_check(only=only, concurrency=concurrency)
    console.print(f"[green]Snapshot:[/] {out}")
    _render_status(out)


# check_git — kept as implementation for `fleet check`.
def check_git(
    detail: bool = typer.Option(False, "--detail", help="Per-repo breakdown instead of summary"),
    check_id: str = typer.Option("", "--check", help="Run a single check ID across all repos"),
    domain: str = typer.Option("", "--domain", help="Filter to one project"),
    repo: str = typer.Option("", "--repo", help="[Deprecated — use --domain]"),
) -> None:
    """Scaffold + docs + git + stack + deploy catalog across all sites/* repos."""
    target = _resolve_domain_repo_synonyms(domain, repo)
    _run_check_git_mode(detail=detail, check_id=check_id, repo=target)


# check_seo — kept as implementation for `fleet seo` and `project seo`.
def check_seo(
    days: int = typer.Option(28, "--days", help="GSC lookback window in days"),
    domain: str = typer.Option("", "--domain", help="Filter to one project (always probes fresh)"),
    repo: str = typer.Option("", "--repo", help="[Deprecated — use --domain]"),
    only: str = typer.Option("wip", "--only", "-o", help="Scope: 'wip' or 'all' (used when refreshing snapshot)"),
    concurrency: int = typer.Option(20, "--concurrency", "-c", help="Max parallel HTTP requests when refreshing snapshot"),
    sort_by: str = typer.Option("impressions", "--sort",
                                help="Sort by: impressions | clicks | position | ctr"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Ignore cached SEO snapshot and re-probe (HTTP + GSC + CrUX)"),
) -> None:
    """Per-domain runtime SEO probe — HTTP + GSC + CrUX.

    Reads from `data/seo/<latest>.json` by default if it covers every
    domain in scope. `--refresh` forces a fresh probe and overwrites
    today's cache file. `--domain <one>` always probes fresh.
    """
    target = _resolve_domain_repo_synonyms(domain, repo)
    _run_check_seo_mode(days=days, only_domain=target, sort_by=sort_by,
                        only=only, concurrency=concurrency, refresh=refresh)


def _resolve_domain_repo_synonyms(domain: str, repo: str) -> str:
    """Collapse the --domain / --repo synonym pair into one target string.

    --repo is the deprecated form (kept since v5.F so existing scripts
    keep working). Conflict (different non-empty values) is an error."""
    if repo and not domain:
        console.print(
            "[yellow]Note:[/] [dim]--repo is deprecated; use --domain.[/]"
        )
        return repo
    if repo and domain and repo.lower() != domain.lower():
        console.print(
            f"[red]--repo={repo!r} and --domain={domain!r} disagree.[/] "
            "Pass only one (they're synonyms; --repo is deprecated)."
        )
        raise typer.Exit(2)
    return domain


# ---------- v5.B: --git cross-repo catalog runner ----------


# Categories included by --git: everything that doesn't need a live HTTP
# fetch or external API. SEO is the only excluded category (those checks
# need either deployed-URL fetch or are too project-specific for the
# cross-repo health view).
_GIT_FLAG_CATEGORIES = {
    "scaffold", "docs", "git", "ci", "stack", "deploy", "content",
}

# Render order for category-grouped output.
_CATEGORY_ORDER = (
    "scaffold", "docs", "git", "ci", "stack", "deploy", "seo", "content",
)
_CATEGORY_LABEL = {
    "scaffold": "Scaffold",
    "docs": "Docs",
    "git": "Git",
    "ci": "CI",
    "stack": "Stack",
    "deploy": "Deploy",
    "seo": "SEO",
    "content": "Content",
}


def _is_likely_repo(path) -> bool:
    """Heuristic: an immediate child of repos_dir counts as a repo if it's
    a directory and not a hidden/special name. We don't require .git to
    exist (a project can be missing its repo and we still want to report)."""
    from pathlib import Path
    p = Path(path)
    if not p.is_dir():
        return False
    name = p.name
    if name.startswith(".") or name in ("node_modules", "tarball", "__pycache__"):
        return False
    return True


def _iterate_repos(repos_dir, ignore: list[str] | None = None):
    """List immediate-child directories of `repos_dir` that look like repos.
    Sorted alphabetically for stable output. If `ignore` is given, drop
    repos whose name matches (case-insensitive) — the portfolio CLI repo
    itself is filtered by default via config (see `DEFAULT_IGNORE_REPOS`)."""
    from pathlib import Path
    base = Path(repos_dir)
    if not base.is_dir():
        return []
    skip_names = {n.lower() for n in (ignore or [])}
    return sorted(
        [p for p in base.iterdir()
         if _is_likely_repo(p) and p.name.lower() not in skip_names],
        key=lambda p: p.name.lower(),
    )


def _run_check_git_mode(*, detail: bool, check_id: str, repo: str) -> None:
    """Cross-repo catalog runner. Three render modes:
      - default summary: one row per repo with Score / Fails / Warns
      - --detail: full per-repo breakdown
      - --check CHECK_xxx: one column per repo for a single check
      - --repo <name>: full breakdown for one repo (== `check run <path>`)
    """
    from .checks import list_checks, load_config, run_checks

    cfg = load_config()
    repos_dir = cfg.repos_dir
    if not repos_dir.is_dir():
        console.print(f"[red]repos_dir not found: {repos_dir}[/]")
        console.print("[dim]Set [git] repos_dir in ~/.config/portfolio/config.toml.[/]")
        raise typer.Exit(2)

    # Filter the catalog: scaffold/git/stack/deploy categories.
    catalog_specs = [s for s in list_checks() if s.category in _GIT_FLAG_CATEGORIES]
    if check_id:
        catalog_specs = [s for s in catalog_specs if s.id == check_id]
        if not catalog_specs:
            console.print(f"[red]Unknown check ID: {check_id}[/]")
            raise typer.Exit(2)
    catalog_ids = [s.id for s in catalog_specs]

    repos = _iterate_repos(repos_dir, ignore=cfg.ignore_repos)

    # Single-repo mode short-circuit
    if repo:
        match = next((p for p in repos if p.name.lower() == repo.lower()), None)
        if match is None:
            console.print(f"[red]No repo named {repo!r} in {repos_dir}.[/]")
            raise typer.Exit(2)
        results = run_checks(str(match), ids=catalog_ids,
                             skip_checks=cfg.skip_checks)
        _render_per_repo_detail(match.name, results, catalog_specs)
        return

    if not repos:
        console.print(f"[yellow]No repos found in {repos_dir}.[/]")
        raise typer.Exit(1)

    # Run checks against every repo (sequential — speed isn't a concern).
    console.print(f"[dim]Running {len(catalog_ids)} check(s) against {len(repos)} repo(s) in {repos_dir}...[/]")
    per_repo: dict[str, dict] = {}
    for p in repos:
        per_repo[p.name] = run_checks(str(p), ids=catalog_ids,
                                      skip_checks=cfg.skip_checks)

    if check_id:
        _render_single_check_table(check_id, per_repo, catalog_specs[0])
        return
    if detail:
        for repo_name, results in per_repo.items():
            _render_per_repo_detail(repo_name, results, catalog_specs)
            console.print()
        return
    _render_summary_table(per_repo, catalog_specs)


def _render_summary_table(per_repo: dict[str, dict], catalog_specs: list) -> None:
    total = len(catalog_specs)
    spec_by_id = {s.id: s for s in catalog_specs}

    # Per-repo summary table — fails/warns ordered by category so related
    # gaps cluster visually instead of being interleaved by ID.
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]check --git — {len(per_repo)} repos · {total} checks[/]",
              title_justify="left")
    t.add_column("Repo")
    t.add_column("Score", justify="right")
    t.add_column("Fails")
    t.add_column("Warns")
    # Per-repo (name, passes, fails, warns, skipped_count). Skipped checks
    # are warns whose message contains "skipped" — they don't apply to this
    # project (e.g. astro-version-ok on a Vite project, or no-.git checks
    # on an unversioned dir). They get filtered from the Warns column and
    # excluded from the score denominator so it reflects only applicable
    # checks.
    rows: list[tuple[str, int, list[str], list[str], int]] = []
    for repo_name, results in per_repo.items():
        passed = [cid for cid, r in results.items() if r.status == "pass"]
        fails = _sort_ids_by_category(
            [cid for cid, r in results.items() if r.status == "fail"], spec_by_id)
        all_warns = [cid for cid, r in results.items() if r.status == "warn"]
        skipped = [cid for cid in all_warns
                   if "skipped" in results[cid].message.lower()]
        real_warns = _sort_ids_by_category(
            [cid for cid in all_warns if cid not in set(skipped)], spec_by_id)
        rows.append((repo_name, len(passed), fails, real_warns, len(skipped)))
    rows.sort(key=lambda r: (r[1], r[0]))  # worst score first
    for repo_name, score, fails, warns, skipped_n in rows:
        applicable = total - skipped_n
        score_color = ("red" if score < applicable * 0.5
                       else "yellow" if score < applicable * 0.8
                       else "green")
        score_cell = f"[{score_color}]{score}/{applicable}[/]"
        if skipped_n:
            score_cell += f" [dim]({skipped_n} n/a)[/]"
        t.add_row(
            repo_name,
            score_cell,
            ", ".join(fails) if fails else "[dim]—[/]",
            ", ".join(warns) if warns else "[dim]—[/]",
        )
    console.print(t)
    n_clean = sum(1 for r in rows if not r[2] and not r[3])
    # Average score now reflects applicable checks per repo, not catalog size.
    avg_applicable = (sum(r[1] for r in rows) /
                      sum((total - r[4]) for r in rows)
                      if rows else 0)
    total_skipped = sum(r[4] for r in rows)
    console.print(
        f"\n[dim]Totals: {len(rows)} repos · "
        f"avg {avg_applicable*100:.0f}% pass · "
        f"{n_clean} all-pass · "
        f"{total_skipped} skipped checks fleetwide (non-applicable)[/]"
    )

    # Aggregate "most common failures" view across all repos. Surfaces the
    # patterns worth fixing fleetwide rather than per-repo.
    _render_common_failures(per_repo, spec_by_id, n_repos=len(rows))


def _sort_ids_by_category(ids: list[str], spec_by_id: dict) -> list[str]:
    """Order check IDs by (category render order, then ID) so the rendered
    fails/warns column reads as Scaffold → Docs → Git → CI → Stack → Deploy."""
    cat_index = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    def key(cid: str):
        spec = spec_by_id.get(cid)
        cat = spec.category if spec else ""
        return (cat_index.get(cat, len(_CATEGORY_ORDER)), cid)
    return sorted(ids, key=key)


def _render_common_failures(per_repo: dict[str, dict],
                            spec_by_id: dict,
                            *, n_repos: int,
                            top_n: int = 10) -> None:
    """Print "Most common failures across N repos" — top check IDs by repo
    count, where a repo "has" a failure if status is fail or warn (skips
    don't count). Grouped by category in render order."""
    if n_repos == 0:
        return
    counts: dict[str, int] = {}
    for results in per_repo.values():
        for cid, r in results.items():
            if r.status in ("fail", "warn") and "skipped" not in r.message:
                counts[cid] = counts.get(cid, 0) + 1
    if not counts:
        return
    # Filter to checks that hit ≥ 30% of repos to keep signal-noise high.
    threshold = max(2, int(n_repos * 0.3))
    common = [(cid, n) for cid, n in counts.items() if n >= threshold]
    if not common:
        return
    cat_index = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    common.sort(key=lambda t: (
        cat_index.get(spec_by_id.get(t[0]).category if t[0] in spec_by_id else "",
                      len(_CATEGORY_ORDER)),
        -t[1],
        t[0],
    ))
    common = common[:top_n]
    console.print(f"\n[bold]Most common failures across {n_repos} repos:[/]")
    last_cat = None
    for cid, n in common:
        spec = spec_by_id.get(cid)
        cat = spec.category if spec else "?"
        if cat != last_cat:
            console.print(f"  [bold cyan]{_CATEGORY_LABEL.get(cat, cat)}[/]")
            last_cat = cat
        name = spec.name if spec else "?"
        console.print(f"    {cid}  {name:<30}  [yellow]{n}/{n_repos}[/] repos")


def _render_per_repo_detail(repo_name: str, results: dict, catalog_specs: list) -> None:
    spec_by_id = {s.id: s for s in catalog_specs}
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]{repo_name}[/]",
              title_justify="left")
    t.add_column("ID")
    t.add_column("Status")
    t.add_column("Name")
    t.add_column("Message")
    for cid in _sort_ids_by_category(list(results), spec_by_id):
        r = results[cid]
        spec = spec_by_id.get(cid)
        # Skipped (warn whose message says "skipped") gets a softer icon
        # so the reader can tell at a glance "this didn't apply" vs
        # "this is an actionable warn."
        is_skipped = (r.status == "warn" and "skipped" in r.message.lower())
        if is_skipped:
            icon = "[dim]· n/a[/]"
        else:
            icon = {"pass": "[green]✓ pass[/]", "fail": "[red]✗ fail[/]",
                    "warn": "[yellow]~ warn[/]"}.get(r.status, r.status)
        t.add_row(cid, icon, spec.name if spec else "?", r.message)
    console.print(t)
    n_pass = sum(1 for r in results.values() if r.status == "pass")
    n_fail = sum(1 for r in results.values() if r.status == "fail")
    warns = [r for r in results.values() if r.status == "warn"]
    n_skipped = sum(1 for r in warns if "skipped" in r.message.lower())
    n_warn = len(warns) - n_skipped
    console.print(
        f"  [dim]{n_pass} pass · {n_fail} fail · {n_warn} warn · "
        f"{n_skipped} n/a[/]"
    )
    _render_action_plan(repo_name, results)


# v6.D.1 — manual-fix hints for checks without a registered fixer.
# Keyed by CHECK_ID. For checks not in this dict, we fall back to the
# check's `message` field as the hint (still useful, just less polished).
_MANUAL_HINTS = {
    "CHECK_010": "mkdir tests/ and add at least one .test.{js,ts,py}",
    "CHECK_022": "git status; commit or stash uncommitted changes",
    "CHECK_024": "add .github/workflows/ci.yml — copy from a bootstrapped project",
    "CHECK_029": 'add `"homepage": "https://<domain>/"` to package.json',
    "CHECK_035": "pnpm update vite@^6 && pnpm run build  (verify nothing breaks)",
    "CHECK_036": "pnpm update astro@^5",
    "CHECK_039": "tsc --init  (only if you want TypeScript)",
    "CHECK_071": "edit <head> meta description — keep it 120-160 chars",
    "CHECK_073": 'add <meta name="viewport" content="width=device-width, initial-scale=1">',
    "CHECK_074": 'add lang="en" (or appropriate code) to <html>',
    "CHECK_075": 'add <meta name="robots" content="index, follow">',
    "CHECK_076": "add the 5 og:* meta tags (title, description, url, type, image)",
    "CHECK_077": 'add <meta name="twitter:card" content="summary_large_image">',
    "CHECK_078": 'add <script type="application/ld+json"> with WebSite + Organization',
    "CHECK_079": "JSON-LD must include @type Organization or WebSite",
    "CHECK_080": "wire analytics (GA4 / Plausible / CF Web Analytics)",
    "CHECK_141": "git submodule deinit + rm -rf the gitlink (CF Pages won't clone)",
}


def _render_action_plan(repo_name: str, results: dict) -> None:
    """Print suggested fix commands per non-passing check.
    Categorizes into Tier 1 (templated), Tier 2 (--ai), manual,
    and design-skip. Manual hints come from `_MANUAL_HINTS` or fall
    back to the check's own message text.
    """
    from .fix_registry import fixable_check_ids

    tier_1 = fixable_check_ids(tier=1)
    tier_2 = fixable_check_ids(tier=2)

    actionable_t1: list[str] = []
    actionable_t2_only: list[str] = []
    manual: list[tuple[str, str]] = []
    design_skipped: list[str] = []

    for cid, r in results.items():
        if r.status == "pass":
            continue
        # Skip-by-design (auto-skipped by stack-aware checks). Identified
        # by "skipped" in the message text.
        if r.status == "warn" and "skipped" in r.message.lower():
            design_skipped.append(cid)
            continue
        if cid in tier_1:
            actionable_t1.append(cid)
        elif cid in tier_2:
            actionable_t2_only.append(cid)
        else:
            manual.append((cid, r.message))

    if not (actionable_t1 or actionable_t2_only or manual):
        return  # nothing to suggest

    console.print()
    console.print("[bold]Suggested fixes:[/]")

    if actionable_t1:
        console.print()
        console.print(f"  [cyan]• Tier 1[/] [dim](templated; ~5s):[/]")
        console.print(f"    [bold]portfolio project fix {repo_name} --apply --yes[/]")
        console.print(
            f"    [dim]Closes: {', '.join(sorted(actionable_t1))}[/]"
        )

    # Tier 2 fixers may share check IDs with Tier 1 (e.g. CHECK_026/027).
    # Only mention "Tier 2 only" for IDs WITHOUT a Tier 1 fixer.
    # Plus, mention --ai upgrades for the dual-tier ones.
    dual_tier = [c for c in actionable_t1 if c in tier_2]
    if actionable_t2_only or dual_tier:
        console.print()
        console.print(f"  [magenta]• Tier 2[/] [dim](Claude --ai; ~$0.05–0.10 per check):[/]")
        console.print(f"    [bold]portfolio project fix {repo_name} --apply --yes --ai[/]")
        if actionable_t2_only:
            console.print(
                f"    [dim]Closes (Tier 2 only): {', '.join(sorted(actionable_t2_only))}[/]"
            )
        if dual_tier:
            console.print(
                f"    [dim]Upgrades content (after Tier 1): {', '.join(sorted(dual_tier))}[/]"
            )

    if manual:
        console.print()
        console.print(f"  [yellow]• Manual ({len(manual)})[/] [dim](no auto-fix):[/]")
        for cid, msg in sorted(manual):
            hint = _MANUAL_HINTS.get(cid, msg)
            console.print(f"    [yellow]{cid}[/]  [dim]{hint}[/]")

    if design_skipped:
        console.print()
        console.print(
            f"  [dim]• Skipped ({len(design_skipped)}): "
            f"{', '.join(sorted(design_skipped))}  — design intent (no action)[/]"
        )


def _render_single_check_table(check_id: str, per_repo: dict, spec) -> None:
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]{check_id} — {spec.name}[/]",
              title_justify="left")
    t.add_column("Repo")
    t.add_column("Status")
    t.add_column("Message")
    rows = []
    for repo_name, results in per_repo.items():
        r = results.get(check_id)
        if r is None:
            continue
        rows.append((repo_name, r))
    # Sort: fails first, then warns, then passes
    order = {"fail": 0, "warn": 1, "pass": 2}
    rows.sort(key=lambda x: (order.get(x[1].status, 99), x[0]))
    for repo_name, r in rows:
        icon = {"pass": "[green]✓ pass[/]", "fail": "[red]✗ fail[/]",
                "warn": "[yellow]~ warn[/]"}.get(r.status, r.status)
        t.add_row(repo_name, icon, r.message)
    console.print(t)
    n_pass = sum(1 for _, r in rows if r.status == "pass")
    n_fail = sum(1 for _, r in rows if r.status == "fail")
    n_warn = sum(1 for _, r in rows if r.status == "warn")
    console.print(f"\n[dim]{n_pass} pass · {n_fail} fail · {n_warn} warn  "
                  f"({spec.severity} severity)[/]")


# ---------- v5.D: --seo per-domain runtime probe ----------


def _seo_snapshot_needs_refresh(snap_scope: str | None, only: str) -> bool:
    """Return True if the snapshot is missing or narrower than requested.

    Refresh rules:
      - no snapshot → refresh
      - only=all and snapshot=wip (or unknown) → refresh
      - only=wip → never force refresh (snapshot=wip is exact, snapshot=all is a superset)
    """
    if snap_scope is None:
        return True
    if only == "all" and snap_scope != "all":
        return True
    return False


def _run_check_seo_mode(*, days: int, only_domain: str, sort_by: str,
                        only: str, concurrency: int,
                        refresh: bool = False) -> None:
    """Driver for `portfolio check seo`. Picks domains from the latest
    classification snapshot (live-site + forwarder), reads cached SEO
    data when available (or runs HTTP/GSC/CrUX probes when `refresh` is
    set or no cache exists), renders one row per domain.

    Caching (v5.F.1): without `--refresh`, reads `data/seo/<latest>.json`
    if it exists and includes all needed domains. With `--refresh`, runs
    the full probe and overwrites today's cache file. `--domain <one>`
    always probes fresh (single-domain runs aren't cached).
    """
    from .check import latest_snapshot as live_latest_snapshot
    from .check import load_snapshot, run_check
    from .seo_cache import (
        latest_snapshot as seo_latest_snapshot,
        load_snapshot as seo_load_snapshot,
        rows_from_snapshot,
        save_snapshot as seo_save_snapshot,
    )
    from .seo_runtime import _live_domains_from_snapshot, run_seo, sort_rows
    from .suggest import load_env

    if sort_by not in ("impressions", "clicks", "position", "ctr"):
        console.print(f"[red]--sort must be impressions|clicks|position|ctr, got {sort_by!r}[/]")
        raise typer.Exit(2)
    if only not in ("wip", "all"):
        console.print(f"[red]--only must be 'wip' or 'all', got {only!r}.[/]")
        raise typer.Exit(2)

    if only_domain:
        # --domain bypasses both the live and seo caches — single-domain
        # runs aren't cached (they're cheap and one-off).
        domains = [only_domain.lower()]
        cache_eligible = False
    else:
        snap_path = live_latest_snapshot()
        snap_scope: str | None = None
        if snap_path is not None:
            try:
                snap_scope = load_snapshot(snap_path).get("scope")
            except (OSError, ValueError):
                snap_scope = None

        # Refresh the live snapshot when it's missing OR narrower than requested.
        if _seo_snapshot_needs_refresh(snap_scope, only):
            if snap_path is None:
                console.print("[dim]No check snapshot on disk — running live-site classification first.[/]")
            else:
                console.print(
                    f"[dim]Latest snapshot {snap_path.name} is scope={snap_scope!r}, "
                    f"but --only={only!r} requested. Running live-site classification first.[/]"
                )
            console.print(f"[cyan]Classifying {only} domains (concurrency={concurrency})...[/]")
            snap_path, _ = run_check(only=only, concurrency=concurrency)
            console.print(f"[green]Snapshot:[/] {snap_path}")

        domains = _live_domains_from_snapshot(load_snapshot(snap_path))
        if not domains:
            console.print(f"[yellow]No live-site/forwarder domains in {snap_path.name}.[/]")
            raise typer.Exit(1)
        console.print(f"[dim]Snapshot: {snap_path.name} · {len(domains)} live-site/forwarder domains[/]")
        cache_eligible = True

    # Cache hit path: read from data/seo/<latest>.json if it covers every
    # domain we need and `--refresh` wasn't set.
    if cache_eligible and not refresh:
        cache_path = seo_latest_snapshot()
        if cache_path is not None:
            cached = seo_load_snapshot(cache_path)
            cached_rows = rows_from_snapshot(cached)
            cached_domains = {r.domain for r in cached_rows}
            if cached_domains.issuperset(domains):
                console.print(
                    f"[dim]Reading cache: {cache_path.name} (use --refresh to re-fetch)[/]"
                )
                rows = [r for r in cached_rows if r.domain in set(domains)]
                rows = sort_rows(rows, sort_by)
                _render_seo_table(rows, days=cached.get("days", days), sort_by=sort_by)
                return

    env = load_env()
    crux_key = env.get("CRUX_API_KEY", "").strip()
    if not crux_key:
        console.print("[dim]CRUX_API_KEY not set in portfolio.env — Core Web Vitals columns will be empty.[/]")

    console.print(f"[cyan]Probing {len(domains)} domain(s) — HTTP + GSC ({days}d) + CrUX...[/]")

    def progress(done: int, total: int, dom: str) -> None:
        console.print(f"[dim]  [{done}/{total}] {dom}[/]")

    rows = run_seo(domains, days=days, crux_api_key=crux_key,
                   progress_callback=progress)

    if cache_eligible:
        cache_path = seo_save_snapshot(rows, days=days)
        console.print(f"[dim]Cached: {cache_path.name}[/]")

    rows = sort_rows(rows, sort_by)
    _render_seo_table(rows, days=days, sort_by=sort_by)


_EMOJI_TO_RICH_COLOR = {
    "🟢": "green",
    "🟡": "yellow",
    "🟠": "orange3",
    "🔴": "red",
    "⚪": "dim",
}


def _color_value(emoji: str, text: str) -> str:
    """Wrap `text` in a Rich color tag derived from a status emoji.
    Lets us put the color *into* the cell value (so right-justified
    numeric columns stay aligned) instead of prepending an emoji that
    eats horizontal space and breaks justification."""
    color = _EMOJI_TO_RICH_COLOR.get(emoji, "default")
    if color == "default":
        return text
    return f"[{color}]{text}[/]"


def _fmt_int(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "—"


def _fmt_pct(v: float | None, *, impressions: int | None) -> str:
    """CTR is meaningless when there are no impressions — show `—`, not `0.0%`."""
    if not isinstance(v, float):
        return "—"
    if not impressions:
        return "—"
    return f"{v * 100:.1f}%"


def _fmt_pos(v: float | None) -> str:
    return f"{v:.1f}" if isinstance(v, float) else "—"


def _fmt_ms(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.2f}s"
    return f"{int(v)}ms"


def _fmt_cls(v: float | None) -> str:
    return f"{v:.2f}" if isinstance(v, float) else "—"


def _render_seo_table(rows: list, *, days: int, sort_by: str) -> None:
    from .dashboard import _site_age_days
    from .data import load_domains
    from .seo_runtime import overall_status, row_statuses

    # P4 — build domain → site_age_days map for age-aware grading.
    # `overall_status` masks imp + pos cells for sites <90d old so the
    # grade reflects structural SEO (robots / sitemap / GSC presence),
    # not "no traffic yet" on a freshly-launched site.
    age_by_domain: dict[str, int | None] = {}
    try:
        for d in load_domains():
            age_by_domain[d.name.lower()] = _site_age_days(d.name, d.launched)
    except Exception:
        # If portfolio.json can't load (e.g., test environments), fall
        # back to no-mask behavior — matches pre-P4 grading.
        pass

    # Hide CrUX columns when nobody has CrUX data — saves three columns
    # of "⚪ —" noise. We still surface a one-line footer hint so the
    # user knows why those columns are gone.
    crux_uniformly_empty = bool(rows) and all(
        r.crux_status in ("no-key", "no-data", "unknown") for r in rows
    )

    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]check --seo · {len(rows)} domains · GSC {days}d · sort={sort_by}[/]",
              title_justify="left")
    t.add_column("SEO")
    t.add_column("Domain")
    t.add_column("HTTP")
    t.add_column("Robots", justify="center")
    t.add_column("Sitemap", justify="center")
    t.add_column("GSC", justify="center")
    t.add_column("Imp", justify="right")
    t.add_column("Clicks", justify="right")
    t.add_column("CTR", justify="right")
    t.add_column("Pos", justify="right")
    if not crux_uniformly_empty:
        t.add_column("LCP", justify="right")
        t.add_column("INP", justify="right")
        t.add_column("CLS", justify="right")

    for row in rows:
        s = row_statuses(row)
        http_cell = f"{s['http']} {row.http_status}" if row.http_status is not None else f"{s['http']} err"
        site_age = age_by_domain.get(row.domain.lower())
        cells = [
            overall_status(row, site_age_days=site_age),
            row.domain,
            http_cell,
            s["robots"],
            s["sitemap"],
            s["gsc"],
            _color_value(s["imp"], _fmt_int(row.gsc_impressions)),
            _fmt_int(row.gsc_clicks),
            _fmt_pct(row.gsc_ctr, impressions=row.gsc_impressions),
            _color_value(s["pos"], _fmt_pos(row.gsc_position)),
        ]
        if not crux_uniformly_empty:
            cells.extend([
                _color_value(s["lcp"], _fmt_ms(row.crux_lcp_p75)),
                _color_value(s["inp"], _fmt_ms(row.crux_inp_p75)),
                _color_value(s["cls"], _fmt_cls(row.crux_cls_p75)),
            ])
        t.add_row(*cells)
    console.print(t)

    # Footer counts: how many domains hit each tier of overall status.
    from collections import Counter
    counts = Counter(
        overall_status(r, site_age_days=age_by_domain.get(r.domain.lower()))
        for r in rows
    )
    summary_parts = []
    for emoji, label in (("🟢", "green"), ("🟡", "yellow"),
                         ("🟠", "orange"), ("🔴", "red"), ("⚪", "—")):
        if counts.get(emoji):
            summary_parts.append(f"{emoji} {counts[emoji]} {label}")
    if summary_parts:
        console.print("\n[dim]" + " · ".join(summary_parts) + "[/]")

    # P4 — note when young sites had imp/pos masked so the reader knows
    # the grade is age-aware (otherwise a 🟡 row with imp=0 looks wrong).
    young = [r.domain for r in rows
             if (age_by_domain.get(r.domain.lower()) is not None
                 and age_by_domain[r.domain.lower()] < 90)]
    if young:
        sample = ", ".join(young[:3])
        more = f" + {len(young) - 3} more" if len(young) > 3 else ""
        console.print(
            f"[dim]🌱 {len(young)} young site(s) <90d ({sample}{more}) — "
            f"imp + pos masked from grade (freshness window).[/]"
        )

    # Surface GSC + CrUX status when most rows are missing data.
    n = len(rows)
    if n:
        gsc_skipped = sum(1 for r in rows if r.gsc_status == "auth-skipped")
        if gsc_skipped == n:
            console.print("[dim]GSC: not authenticated — run `portfolio gsc auth` to enable GSC columns.[/]")
        if crux_uniformly_empty:
            crux_no_key = sum(1 for r in rows if r.crux_status == "no-key")
            crux_no_data = sum(1 for r in rows if r.crux_status == "no-data")
            if crux_no_key == n:
                console.print("[dim]CrUX columns hidden: CRUX_API_KEY missing — see portfolio.env.[/]")
            elif crux_no_data >= n - 1:  # tolerate a single error
                console.print(
                    "[dim]CrUX columns hidden: API key works, but Google has no field data "
                    "for these origins.\n"
                    "       CrUX only publishes p75 metrics for origins above a Chrome-traffic "
                    "threshold (~10k+ monthly visits with\n"
                    "       metrics-reporting enabled). Personal-portfolio-scale sites typically "
                    "fall below it.[/]"
                )
            else:
                console.print(
                    "[dim]CrUX columns hidden: mixed errors. Verify CRUX_API_KEY has the Chrome "
                    "UX Report API enabled at\n"
                    "       https://console.cloud.google.com/apis/library/chromeuxreport.googleapis.com[/]"
                )



# check_catalog — kept as implementation for `settings catalog list`.
def check_catalog(
    category: str = typer.Option("", "--category", "-c", help="Filter by category"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
) -> None:
    """List every check in the v5.A catalog (optionally filtered by category)."""
    from .checks import list_checks
    specs = list_checks(category=category or None)
    if json_out:
        import json as _json
        typer.echo(_json.dumps([{
            "id": s.id, "name": s.name, "category": s.category,
            "severity": s.severity, "description": s.description,
        } for s in specs], indent=2))
        return
    if not specs:
        console.print(f"[yellow]No checks match category={category!r}.[/]")
        raise typer.Exit(1)
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]Check catalog ({len(specs)} checks)[/]",
              title_justify="left")
    t.add_column("ID")
    t.add_column("Name")
    t.add_column("Cat")
    t.add_column("Severity")
    t.add_column("Description")
    for s in specs:
        sev_color = _SEVERITY_COLOR.get(s.severity, "white")
        t.add_row(s.id, s.name, s.category,
                  f"[{sev_color}]{s.severity}[/]", s.description)
    console.print(t)


# check_describe — kept as implementation for `settings catalog describe`.
def check_describe(
    check_id: str = typer.Argument(..., help="Check ID (e.g. CHECK_001)"),
) -> None:
    """Print full detail for one catalog check (id, name, category, severity,
    description, module path)."""
    from .checks import get_check
    try:
        spec = get_check(check_id)
    except KeyError:
        console.print(f"[red]Unknown check: {check_id}[/]")
        console.print("[dim]Run `portfolio check catalog` to see what's available.[/]")
        raise typer.Exit(1)
    sev_color = _SEVERITY_COLOR.get(spec.severity, "white")
    console.print(f"\n[bold]{spec.id}[/]  [dim]{spec.name}[/]")
    console.print(f"  category    {spec.category}")
    console.print(f"  severity    [{sev_color}]{spec.severity}[/]")
    console.print(f"  description {spec.description}")
    console.print(f"  module      [dim]{spec.module_name}[/]\n")


# check_run — kept as implementation for `settings catalog run`.
def check_run(
    repo_path: str = typer.Argument(..., help="Project / repo path to run checks against"),
    category: str = typer.Option("", "--category", "-c", help="Filter by category"),
    check_id: str = typer.Option("", "--check", help="Run a single check by ID"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
) -> None:
    """Run catalog checks against a single repo path. Convenience for one-off
    inspection; the canonical cross-repo orchestrator will be `check --git`
    (v5.B)."""
    from pathlib import Path

    from .checks import run_checks

    path = Path(repo_path).expanduser().resolve()
    if not path.exists():
        console.print(f"[red]Path not found: {path}[/]")
        raise typer.Exit(2)
    ids = [check_id] if check_id else None
    results = run_checks(str(path), category=category or None, ids=ids)
    if json_out:
        import json as _json
        typer.echo(_json.dumps({k: {"status": v.status, "message": v.message}
                                for k, v in results.items()}, indent=2))
        return
    if not results:
        console.print("[yellow]No checks ran (filter matched nothing).[/]")
        raise typer.Exit(1)
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]Checks against {path.name}[/]",
              title_justify="left")
    t.add_column("ID")
    t.add_column("Status")
    t.add_column("Message")
    for cid in sorted(results):
        r = results[cid]
        icon = {"pass": "[green]✓ pass[/]", "fail": "[red]✗ fail[/]",
                "warn": "[yellow]~ warn[/]"}.get(r.status, r.status)
        t.add_row(cid, icon, r.message)
    console.print(t)
    n_pass = sum(1 for r in results.values() if r.status == "pass")
    n_fail = sum(1 for r in results.values() if r.status == "fail")
    n_warn = sum(1 for r in results.values() if r.status == "warn")
    console.print(f"\n[dim]Totals: {n_pass} pass · {n_fail} fail · {n_warn} warn[/]")


# gsc_auth — kept as implementation for `settings gsc auth`.
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


# gsc_list — kept as implementation for `settings gsc status`.
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


# gsc_sync — kept as implementation for `settings gsc status --refresh`.
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


# gsc_compare — kept as implementation for `settings gsc status`.
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


# info_status — kept as implementation for `project check`.
def info_status(
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
        own = next((f for f in failed if f["rule"] == "CHECK_020"), {})
        reason = own.get("reason", "?")
        t.add_row("Repo", f"[red]{reason}[/]")
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
            rule = f["rule"]
            name = f.get("name")
            label = f"[bold]{rule}[/] {name}" if name else f"[bold]{rule}[/]"
            console.print(f"  ✗ {label} — {f.get('reason', '?')}")
            if f.get("fix"):
                console.print(f"    [dim]fix: {f['fix']}[/]")
    if conf["passed"]:
        console.print(
            f"[green]Passed ({len(conf['passed'])}):[/] [dim]"
            + ", ".join(conf["passed"])
            + "[/]"
        )
    if conf["skipped"]:
        console.print(
            f"[dim]Skipped ({len(conf['skipped'])}): "
            + ", ".join(s["rule"] for s in conf["skipped"])
            + "[/]"
        )


# info_list — kept as implementation for `fleet info summary --verbose`.
def info_list(
    grouped: bool = typer.Option(False, "--grouped", "-g",
                                 help="Group by plan category (subsumes the old `info category` command)"),
    category: str = typer.Option("", "--category", "-c",
                                 help="Filter to one category by substring match (implies --grouped)"),
) -> None:
    """List domains.

    Default: one flat table of every domain in the registrar CSVs.
    `--grouped`: separate sub-tables per plan category.
    `--category <substring>`: implies --grouped; filters to matching categories.

    Subsumes the v5.F `info category` command (now a deprecated alias).
    """
    if category:
        grouped = True

    if not grouped:
        t = Table(title="All Domains")
        t.add_column("Domain")
        t.add_column("Expires")
        t.add_column("Status")
        t.add_column("Auto-renew")
        t.add_column("Listed")
        t.add_column("Value", justify="right")
        for d in sorted(load_domains(), key=lambda x: x.name):
            value = f"${d.estimated_value:,.0f}" if d.estimated_value else "-"
            t.add_row(d.name, str(d.expires) if d.expires else "-",
                      d.status, d.auto_renew, d.listing_status, value)
        console.print(t)
        return

    # Grouped mode — categories from the plan.
    plan = load_plan()
    by_name = {d.name: d for d in load_domains()}

    cat_groups: dict[str, list[str]] = {}
    for dom, cat in plan.items():
        cat_groups.setdefault(cat, []).append(dom)

    if category:
        cat_groups = {c: ds for c, ds in cat_groups.items()
                      if category.lower() in c.lower()}
        if not cat_groups:
            console.print(f"[red]No category matches {category!r}.[/]")
            raise typer.Exit(1)

    for cat, doms in sorted(cat_groups.items()):
        t = Table(title=f"{cat} ({len(doms)})")
        t.add_column("Domain")
        t.add_column("Expires")
        t.add_column("Status")
        t.add_column("Value", justify="right")
        for dom in sorted(doms):
            d = by_name.get(dom)
            if d:
                value = f"${d.estimated_value:,.0f}" if d.estimated_value else "-"
                t.add_row(d.name, str(d.expires) if d.expires else "-",
                          d.status, value)
            else:
                t.add_row(dom, "-", "[red]not in CSV[/]", "-")
        console.print(t)


@new_app.command("suggest")
def new_suggest(
    topic: str = typer.Argument("", help="The product idea or topic to brainstorm domain names for (prompted if omitted)"),
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
    topic = _resolve_topic_arg(topic, non_interactive=non_interactive)
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


def _resolve_topic_arg(topic: str, *, non_interactive: bool) -> str:
    """Topic is now optional on the CLI surface — prompt interactively
    when missing. Non-interactive runs must still supply it explicitly
    (raise rather than silently prompt + block in a script context).
    """
    topic = (topic or "").strip()
    if topic:
        return topic
    if non_interactive:
        console.print(
            "[red]TOPIC is required in --non-interactive mode.[/]"
        )
        raise typer.Exit(2)
    console.print(
        "[dim]No topic provided. Examples:[/] "
        "[cyan]'AI vacuum diagnostics'[/], [cyan]'home pSEO'[/], [cyan]'cheap car repair'[/]"
    )
    topic = typer.prompt("Topic").strip()
    if not topic:
        console.print("[red]Topic cannot be empty.[/]")
        raise typer.Exit(2)
    return topic


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
    ("9", "Rerun fresh (bypass cache)",                False),  # v4.D polish
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


def _decide_step1_brand_collision(finalists, openai_key: str) -> None:
    from .decide import check_brand_collision
    console.print("\n[bold]Step 1/6 — Brand collision check[/]  [dim](gpt-5-mini)[/]")
    for row in finalists:
        result = check_brand_collision(row.name, openai_key)
        console.print(f"  [bold]{row.name}[/]")
        if result.backend == "ai":
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
                 openai_key: str):
    """Menu option 7 orchestrator. Returns (row, tld) pick or None."""
    finalists = [r for r in rows if r.name in shortlist]
    if not finalists:
        console.print("[yellow]Shortlist is empty — mark some candidates first (option 6).[/]")
        return None

    _render_decide_table(finalists, max_price=max_price)
    _decide_step1_brand_collision(finalists, openai_key)
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
            result = _menu_decide(
                rows, shortlist, tld_list, max_price,
                topic=topic, vocab_terms=vocab_terms,
                openai_key=openai_key,
            )
            if result is not None:
                selected_row, selected_tld = result
                break
            # b from decide → main menu (shortlist preserved)
            continue
        if choice == "8":
            _render_tld_reference()
            continue
        if choice == "9":
            from .suggest import clear_brainstorm_cache
            cleared = clear_brainstorm_cache(topic, all_strategies)
            if cleared:
                console.print("[dim]Brainstorm cache cleared.[/]")
            console.print("[dim]Re-running pipeline (fresh)...[/]")
            rows, vocab_terms = run_validation_pipeline(
                topic=topic, api_key=openai_key,
                strategies=all_strategies,
                columns=tld_list, avail_check=avail_fn,
                max_price=max_price, pricing_dict=pricing_dict,
                cache_payload=None,
                cache_save_fn=_save_cache,
                log_fn=_log,
            )
            rows = filter_pickable_rows(rows)
            if not rows:
                console.print("[yellow]No pickable candidates after rerun. Try refining the topic.[/]")
                continue
            _render_grid(rows, tld_list, show_renewal=show_renewal)
            if shortlist:
                missing = [n for n in shortlist if not any(r.name == n for r in rows)]
                if missing:
                    console.print(
                        f"[yellow]Note: shortlist has {len(missing)} name(s) not in the new grid: "
                        f"{', '.join(missing)}[/]"
                    )
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
    console.print(f'  portfolio new bootstrap {selected} --topic="{topic}"')
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


@new_app.command("bootstrap")
def new_bootstrap(
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

    _render_bootstrap_summary(result, domain)


def _render_bootstrap_summary(result, domain: str) -> None:
    """Post-bootstrap report: header, file inventory, tree view, conformance
    pass/fail, predicted live URL, grouped next-step commands."""
    console.print(
        f"[green]✓[/] Bootstrapped [bold]{result.project_dir}[/]  "
        f"[dim](path={result.path}, stack={result.stack})[/]"
    )

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

    # v4.D polish 2026-05-08: tree view of the actual scaffold.
    _render_project_tree(result.project_dir)

    if result.warnings:
        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/]")
        for w in result.warnings:
            console.print(f"  • {w}")

    # Conformance quick-check against the new project.
    _render_bootstrap_conformance(domain)

    # Predicted live URL.
    console.print(f"\n[bold]Live URL after deploy:[/]  [cyan]https://{domain}/[/]")

    # Grouped next steps with concrete commands.
    console.print("\n[bold]Next steps:[/]")
    console.print("  [bold cyan]Local dev[/]")
    console.print(f"    cd sites/{domain}")
    console.print("    make deps           [dim]# install dependencies via the central builder[/]")
    console.print("    make dev            [dim]# start the dev server[/]")
    console.print("  [bold cyan]Deploy[/]")
    console.print(f"    portfolio new deploy {domain}     [dim]# create GH repo + Cloudflare Pages project[/]")
    console.print("  [bold cyan]Verify after deploy[/]")
    console.print(f"    portfolio fleet live                         [dim]# refresh check snapshot[/]")
    console.print(f"    portfolio project check {domain}      [dim]# full conformance report[/]")


def _render_project_tree(project_dir) -> None:
    """Print a top-level tree of the bootstrapped project (one level deep,
    plus a count for any subdirectories that have entries). Skips .git and
    node_modules to avoid noise."""
    from pathlib import Path
    p = Path(project_dir)
    if not p.exists():
        return
    SKIP = {".git", "node_modules", "dist", ".venv", "__pycache__"}
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    console.print(f"\n[bold]Project tree:[/]  [dim]{p.name}/[/]")
    for entry in entries:
        if entry.name in SKIP:
            continue
        if entry.is_dir():
            children = [c for c in entry.iterdir() if c.name not in SKIP]
            count = len(children)
            console.print(f"  ├── [bold cyan]{entry.name}/[/]  [dim]({count} entries)[/]")
        else:
            console.print(f"  ├── {entry.name}")


def _render_bootstrap_conformance(domain: str) -> None:
    """Run the universal check catalog against the freshly-bootstrapped project
    (scaffold + stack + deploy + seo categories — git is skipped since the new
    project hasn't been pushed yet) and print pass/fail per check.

    v5.C: switched from the legacy `project.build_status` rule list to the
    registry-based runner so a single source of truth (the catalog) drives
    every conformance surface."""
    from pathlib import Path

    from .checks import list_checks, load_config, run_checks
    from .data import ROOT as DATA_ROOT

    project_dir = DATA_ROOT.parent / domain
    if not project_dir.is_dir():
        console.print(f"\n[yellow]Conformance check skipped:[/] {project_dir} not found")
        return

    cfg = load_config()
    bootstrap_categories = {"scaffold", "docs", "stack", "deploy", "seo"}
    catalog_specs = [s for s in list_checks() if s.category in bootstrap_categories]
    catalog_ids = [s.id for s in catalog_specs]

    try:
        results = run_checks(str(project_dir), ids=catalog_ids,
                             skip_checks=cfg.skip_checks)
    except Exception as e:
        console.print(f"\n[yellow]Conformance check skipped:[/] {type(e).__name__}: {e}")
        return

    by_id = {s.id: s for s in catalog_specs}
    passed = [cid for cid, r in results.items() if r.status == "pass"]
    failed = [(cid, r) for cid, r in results.items() if r.status == "fail"]
    warned = [(cid, r) for cid, r in results.items() if r.status == "warn"]

    console.print(
        f"\n[bold]Conformance ({len(passed)} pass · {len(failed)} fail · {len(warned)} warn):[/]"
    )
    for cid in sorted(passed):
        spec = by_id[cid]
        console.print(f"  [green]✓[/] {cid} {spec.name}")
    for cid, r in sorted(failed):
        spec = by_id[cid]
        console.print(f"  [red]✗[/] {cid} {spec.name}  [dim]— {r.message}[/]")
    if warned:
        # Most warns are stack-aware skips ("not a Vite project — skipped"); fold them.
        skipped = [(cid, r) for cid, r in warned if "skipped" in r.message]
        real_warns = [(cid, r) for cid, r in warned if "skipped" not in r.message]
        for cid, r in sorted(real_warns):
            spec = by_id[cid]
            console.print(f"  [yellow]![/] {cid} {spec.name}  [dim]— {r.message}[/]")
        if skipped:
            console.print(
                f"  [dim]skipped ({len(skipped)}): "
                + ", ".join(cid for cid, _ in sorted(skipped))
                + "[/]"
            )


@new_app.command("research")
def new_research(
    topic: str = typer.Argument("", help="Topic to research (prompted if omitted)"),
    synthesis_only: bool = typer.Option(
        False, "--synthesis-only",
        help="Skip SerpAPI; use LLM-only synthesis (heuristic verdicts; not "
             "real SERP data). Useful for fast ideation without burning quota.",
    ),
    no_cache: bool = typer.Option(False, "--no-cache",
                                  help="Bypass cache and re-fetch"),
    brief: bool = typer.Option(False, "--brief",
                               help="Compact output"),
    json_out: bool = typer.Option(False, "--json",
                                  help="Emit raw JSON"),
    non_interactive: bool = typer.Option(
        False, "--non-interactive",
        help="Skip the Gate 3 moat prompt (PENDING result; re-run "
             "interactively to fill in). Implied by --json.",
    ),
) -> None:
    """v8.D — multi-keyword cluster SERP research.

    Default: real SERP via SerpAPI for each cluster query (top-10
    organic + AI Overview + PAA + Reddit cards + SERP features).
    Requires `SERPAPI_KEY` in portfolio.env (free tier covers 250
    queries/month = ~50 research runs).

    `--synthesis-only`: skip SerpAPI; LLM synthesizes the analysis
    from training data. Use for ideation when you don't want to burn
    quota. Output is clearly labeled "NOT REAL SERP DATA".

    P1 scope: cluster + per-query SERP data only. Gates (Phase 2),
    operator-profile filtering (Phase 3), and interpretive verdict
    (Phase 4) land in subsequent commits.
    """
    from .apikeys import get_key

    topic = _resolve_topic_arg(topic, non_interactive=False)
    serpapi_key = get_key("SERPAPI_KEY") or ""

    if synthesis_only:
        _run_research_synthesis(topic, no_cache=no_cache,
                                brief=brief, json_out=json_out)
        return

    if not serpapi_key:
        # Refuse to silently fall back — that was a known bug in pre-v8.D.
        # The operator should either set the key or explicitly opt into
        # synthesis-only mode.
        console.print(
            "[red]SERPAPI_KEY not set.[/] Real SERP data requires a key.\n"
            "Two ways to proceed:\n"
            "  1. Set the key:  [cyan]lamill settings apikeys set SERPAPI_KEY <your-key>[/]\n"
            "     Free tier: https://serpapi.com/ (250 queries/month)\n"
            "  2. Skip SerpAPI: [cyan]lamill new research <topic> --synthesis-only[/]\n"
            "     (LLM-only synthesis; heuristic verdicts, not real SERP data)"
        )
        raise typer.Exit(2)

    # Pre-flight: soft-warn at 80% quota usage.
    from .serpapi_quota import quota_pct_used, read_quota, should_warn
    if should_warn():
        q = read_quota()
        console.print(
            f"[yellow]⚠  SerpAPI quota: {q['queries_used']}/{q['limit']} this UTC month "
            f"({int(quota_pct_used()*100)}%). Consider `--synthesis-only` for "
            f"ideation runs to stretch the cap.[/]"
        )

    # Real SerpAPI path.
    from .research_v2 import (
        ResearchV2Error, ResearchV2QuotaExhausted, run_research_v2,
    )
    try:
        payload = run_research_v2(topic, api_key=serpapi_key, no_cache=no_cache)
    except ResearchV2QuotaExhausted as e:
        # Auto-fallback to synthesis-only per §8.G.3 — quota's hit but
        # the user clearly wanted research data. Better to give them a
        # degraded answer than to refuse the run.
        console.print(
            f"[yellow]⚠  SerpAPI quota exhausted ({e})\n"
            f"   Falling back to GPT synthesis — NOT REAL SERP DATA.[/]"
        )
        _run_research_synthesis(topic, no_cache=no_cache,
                                brief=brief, json_out=json_out)
        return
    except ResearchV2Error as e:
        console.print(f"[red]Research failed:[/] {e}")
        raise typer.Exit(2)

    # v8.D Phase 2 — run gates + verdict on top of the cluster.
    # Optimization: if this is a cache hit AND the snapshot already
    # carries gates from a previous run, skip the recompute (Gate 1
    # burns an OpenAI volume call; classifiers are cheap but verdict
    # would be re-prompted needlessly).
    cache_has_gates = (
        payload.get("from_cache") and payload.get("gates")
        and payload.get("verdict")
    )
    if not cache_has_gates:
        gates = _run_gates_with_prompt(
            payload, console=console,
            non_interactive=non_interactive or json_out,
        )
        gates_dict = gates.to_dict()
        payload["gates"] = {
            "gate_1_market": gates_dict["gate_1_market"],
            "gate_2_serp": gates_dict["gate_2_serp"],
            "gate_3_moat": gates_dict["gate_3_moat"],
        }
        payload["operator_fit"] = gates_dict["operator_fit"]
        payload["verdict"] = gates.verdict
        payload["suggested_reductions"] = list(gates.suggested_reductions)
        payload["moat_required"] = gates.moat_required
        payload["moat_provided"] = gates.moat_provided

        # Persist gates back to the cluster snapshot so the next run
        # sees the verdict + moat without re-prompting / re-spending
        # the volume-estimator call.
        from .research_v2 import save_cluster_snapshot
        try:
            save_cluster_snapshot(topic, payload)
        except OSError as e:
            console.print(f"[dim]warn: could not persist gates: {e}[/]")

    if json_out:
        _render_serp_json(payload)
    else:
        _render_research_v2_full(payload, console)


def _run_gates_with_prompt(cluster: dict, *, console,
                           non_interactive: bool):
    """Run Gate 1 + Gate 2, prompt for moat if required, then Gate 3 +
    verdict + reductions. Returns a `GateResults`.

    Splitting the orchestration here (vs calling `evaluate_cluster()`
    directly) lets the prompt land between Gate 2 and Gate 3 without
    re-running Gate 1's LLM volume call.
    """
    from .research_gates import (
        OperatorFitResult, VERDICT_NICHE_DOWN, GateResults,
        evaluate_gate_1, evaluate_gate_2, evaluate_gate_3,
        is_moat_required, suggest_reductions, synthesize_verdict,
    )
    g1 = evaluate_gate_1(cluster)
    g2 = evaluate_gate_2(cluster)
    moat_sentence: str | None = None
    if not non_interactive and is_moat_required(g2):
        moat_sentence = _prompt_for_moat(g2, console)
    g3 = evaluate_gate_3(g2, moat_sentence, non_interactive=non_interactive)
    op_fit = OperatorFitResult()
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

    # Cluster
    console.print(f"  [cyan]Topic cluster:[/]")
    for i, q in enumerate(cluster_queries, 1):
        marker = "[bold]→[/]" if q.lower() == topic.lower() else " "
        console.print(f"    {marker} {i}. {q}")
    console.print()

    # Gates + verdict + reductions (Phase 2)
    if "gates" in payload:
        _render_gates_block(payload, console)

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


def _render_serp_full(payload: dict, console) -> None:
    """Default rendering — full analysis block + decision aid.

    Cluster-mode payloads (mode="cluster") get extra rendering for the
    cluster queries + frequency column + per-query summary. Strict-mode
    payloads (mode="strict") render the same shape minus those extras.
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
    console.print(f"  [dim]{src_line} · {caveat}[/]\n")

    # Cluster queries (v8.B)
    if mode == "cluster":
        cluster_queries = analysis.get("cluster_queries", [])
        if cluster_queries:
            console.print(f"  [cyan]Topic cluster[/] [dim]({len(cluster_queries)} queries):[/]")
            for i, q in enumerate(cluster_queries, 1):
                marker = "[bold]→[/]" if q.lower() == topic.lower() else " "
                console.print(f"    {marker} {i}. {q}")
            console.print()

    # Top rankers — with frequency column in cluster mode
    rankers = analysis.get("top_likely_rankers", [])
    n_queries = len(analysis.get("cluster_queries", [])) if mode == "cluster" else 1
    if rankers:
        if mode == "cluster":
            console.print(
                f"  [cyan]Cluster-level rankers[/] [dim](frequency / {n_queries} queries):[/]"
            )
        else:
            console.print("  [cyan]Likely top rankers[/] [dim](from training data, not live SERP):[/]")
        for i, r in enumerate(rankers, 1):
            domain = r.get("domain", "?")
            type_ = r.get("type", "?")
            intent = r.get("intent", "?")
            if mode == "cluster":
                freq = r.get("frequency", 1)
                # Color the frequency: 5/5 = red (dominates), 1/5 = green (niche)
                freq_color = ("red" if freq >= max(1, n_queries * 0.8)
                              else "yellow" if freq >= max(1, n_queries * 0.4)
                              else "green")
                freq_cell = f"[{freq_color}]{freq}/{n_queries}[/]"
                console.print(
                    f"    {i:>2}. [bold]{domain:<28}[/] {freq_cell}  "
                    f"[dim]{type_} · {intent}[/]"
                )
            else:
                console.print(f"    {i:>2}. [bold]{domain:<28}[/] [dim]{type_} · {intent}[/]")

    # Content patterns
    patterns = analysis.get("content_patterns", [])
    if patterns:
        console.print("\n  [cyan]Content patterns:[/]")
        for p in patterns:
            console.print(f"    · {p}")

    # Competitive signal
    comp = analysis.get("competitive_signal", {})
    sat = comp.get("saturation", "?")
    sat_color = {"low": "green", "medium": "yellow",
                 "medium-high": "orange3", "high": "red"}.get(sat, "white")
    ymyl = comp.get("ymyl_flag", False)
    barrier = comp.get("barrier", "")
    console.print("\n  [cyan]Competitive signal:[/]")
    console.print(f"    Saturation: [{sat_color}]{sat}[/]")
    if ymyl:
        console.print(f"    [red]⚠ YMYL[/] — portfolio policy excludes (medical/legal/financial)")
    if barrier:
        console.print(f"    Barrier: {barrier}")

    # Suggested angles
    angles = analysis.get("suggested_angles", [])
    if angles:
        console.print("\n  [cyan]Suggested angles:[/]")
        for i, a in enumerate(angles, 1):
            console.print(f"    {i}. {a}")

    # Per-query summary (cluster mode only)
    per_query = analysis.get("per_query_summary", [])
    if per_query and mode == "cluster":
        console.print("\n  [cyan]Per-query breakdown:[/]")
        for entry in per_query:
            q = entry.get("query", "?")
            hint = entry.get("decision_hint", "unclear")
            ymyl = entry.get("ymyl", False)
            hint_color = {"ship": "green", "mixed": "yellow",
                          "skip": "red", "unclear": "dim"}.get(hint, "white")
            ymyl_tag = " [red]YMYL[/]" if ymyl else ""
            console.print(
                f"    · {q:<40} [{hint_color}]{hint}[/]{ymyl_tag}"
            )

    # Decision
    decision = analysis.get("decision", "unclear")
    decision_emoji = {"ship": "✓", "mixed": "⚠", "skip": "✗", "unclear": "?"}.get(decision, "?")
    decision_color = {"ship": "green", "mixed": "yellow",
                      "skip": "red", "unclear": "dim"}.get(decision, "white")
    reasoning = analysis.get("reasoning", "")
    console.print(
        f"\n  [bold]Decision:[/] [{decision_color}]{decision_emoji} {decision.upper()}[/]"
    )
    if reasoning:
        # Wrap reasoning to 70 cols for readability
        from textwrap import fill
        wrapped = fill(reasoning, width=68, initial_indent="    ",
                       subsequent_indent="    ")
        console.print(f"[dim]{wrapped}[/]")

    console.print(
        "\n  [dim]Caveat: AI-only synthesis from training data. For real-time "
        "SERP, see roadmap v8.A.1.[/]\n"
    )


def _render_serp_brief(payload: dict, console) -> None:
    """Compact one-screen rendering — decision + top-3 bullets."""
    topic = payload.get("topic", "?")
    analysis = payload.get("analysis", {})
    decision = analysis.get("decision", "unclear")
    decision_emoji = {"ship": "✓", "mixed": "⚠", "skip": "✗", "unclear": "?"}.get(decision, "?")
    decision_color = {"ship": "green", "mixed": "yellow",
                      "skip": "red", "unclear": "dim"}.get(decision, "white")
    sat = analysis.get("competitive_signal", {}).get("saturation", "?")
    ymyl = analysis.get("competitive_signal", {}).get("ymyl_flag", False)

    console.print(f"\n[bold]{topic}[/]  "
                  f"[{decision_color}]{decision_emoji} {decision.upper()}[/]  "
                  f"[dim]({sat} saturation)[/]")
    if ymyl:
        console.print("  [red]⚠ YMYL — portfolio policy excludes[/]")

    angles = analysis.get("suggested_angles", [])[:3]
    if angles:
        for a in angles:
            console.print(f"  · {a}")

    reasoning = analysis.get("reasoning", "")
    if reasoning:
        from textwrap import shorten
        console.print(f"  [dim]{shorten(reasoning, width=200)}[/]")
    console.print()


def _render_serp_json(payload: dict) -> None:
    """Emit raw analysis JSON (suitable for piping / scripting)."""
    import json as _json
    print(_json.dumps(payload, indent=2))


@new_app.command("deploy")
def new_deploy(
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
        console.print("[dim]Run `portfolio new bootstrap <domain>` first, or check the domain spelling.[/]")
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


# `project` namespace — per-project ops (check, fix, seo, diagnose, set-launched).
project_app = typer.Typer(
    help="Per-project ops (check, fix, seo, diagnose, set-launched).",
    no_args_is_help=True,
)
app.add_typer(project_app, name="project")


@project_app.command("fix")
def project_fix(
    name: str = typer.Argument("", help="Project name (fuzzy-matched). Required unless --all."),
    fix_all: bool = typer.Option(False, "--all", help="Apply fixes across every eligible project (v6.D)"),
    apply_changes: bool = typer.Option(False, "--apply", help="Actually write the changes (default is dry-run)"),
    rule_filter: list[str] = typer.Option(None, "--rule", help="Run only this CHECK_ID (repeatable)"),
    assume_yes: bool = typer.Option(False, "--yes", help="Skip confirmations (lockfile deletes + fleetwide --apply)"),
    use_ai: bool = typer.Option(False, "--ai", help="Enable Tier 2 (Claude subprocess) — costs API budget"),
) -> None:
    """Auto-fix conformance issues for one project (or the whole fleet with --all).

    Default: dry-run plan (lists what would change; no writes).
    `--apply` performs the writes. `--rule CHECK_xxx` (repeatable)
    runs only specified fixers. `--yes` skips per-file confirmations
    on lockfile deletions (CHECK_032/033/034) and the fleetwide
    "apply N changes across M projects?" prompt.

    `--all` iterates every project in `repos_dir`, skipping projects
    in `ignore_repos` config + projects whose domain is in the
    "To be deleted immediately" category. Per-project output is
    compact in fleetwide mode; per-project errors are reported but
    don't stop the sweep.

    Tier 1 (templated) and Tier 2 (--ai) fixers — see v6.C / v6.C.1.
    """
    if fix_all and name:
        console.print("[red]Pass either <name> or --all, not both.[/]")
        raise typer.Exit(2)
    if fix_all:
        _run_project_fix_all(apply_changes=apply_changes,
                             rule_filter=rule_filter,
                             assume_yes=assume_yes,
                             use_ai=use_ai)
        return
    if not name:
        console.print("[red]'project fix' needs a <name> argument (or --all).[/]")
        raise typer.Exit(2)
    from .fix_registry import (
        fixable_check_ids, get_tier_1, get_tier_2, list_tier_2,
    )
    from .fix_helpers import claude_available
    from .project import resolve_project, build_status, SITES_ROOT

    plan = load_plan()
    res = resolve_project(name, plan=plan)
    if res.matched is None:
        if res.candidates:
            console.print(f"[yellow]'{name}' is ambiguous. Candidates:[/]")
            for c in res.candidates:
                console.print(f"  • {c}")
            raise typer.Exit(2)
        # No match. Diagnose: is there a sites/<name>/ dir despite the
        # missing portfolio.json entry? That's the "registered outside
        # tracked registrars" / "stale CSV" case — surface it explicitly.
        candidate_dir = SITES_ROOT / name
        sites_dir_exists = candidate_dir.is_dir()
        console.print(
            f"[red]No project matches[/] [bold]{name}[/] "
            f"[dim]in data/portfolio.json ({len(plan)}-domain inventory).[/]"
        )
        if sites_dir_exists:
            console.print()
            console.print(
                f"[yellow]But the directory exists:[/]  {candidate_dir}\n"
                f"[dim]This means {name} is registered somewhere not tracked by "
                "your registrar CSVs (or your CSV export is stale).[/]"
            )
            console.print("\n[bold]Fix one of these:[/]")
            console.print(
                "  • [cyan]Refresh CSVs[/] — re-export from Porkbun / Namecheap / "
                "GoDaddy into\n"
                f"    [dim]data/domains/<registrar>.csv[/], then run "
                f"[bold]portfolio info cleanup[/]"
            )
            console.print(
                "  • [cyan]Add manually[/] — append a row to "
                "[dim]data/domains/<registrar>.csv[/]\n"
                f"    with at least: domain, TLD, create date, expire date. "
                f"Then [bold]portfolio info cleanup[/]"
            )
            console.print(
                "  • [cyan]Use fleetwide mode[/] — "
                f"[bold]portfolio project fix --all --rule CHECK_xxx[/]\n"
                "    [dim](iterates dirs directly, no resolver lookup)[/]"
            )
        else:
            console.print(
                "\n[dim]No directory at "
                f"{candidate_dir} either. Check the spelling, or scaffold first:[/]\n"
                f"  [bold]portfolio new bootstrap {name}[/]"
            )
        raise typer.Exit(1)

    domain = res.matched
    project_dir = SITES_ROOT / domain
    if not project_dir.is_dir():
        console.print(f"[red]Project dir not found:[/] {project_dir}")
        raise typer.Exit(1)

    # Run conformance to find what's failing right now.
    result = build_status(name)
    failed_ids = [f["rule"] for f in result["conformance"]["failed"]
                  if f["rule"].startswith("CHECK_")]

    tier_1_fixable = fixable_check_ids(tier=1)
    tier_2_fixable = fixable_check_ids(tier=2) if use_ai else set()
    fixable = tier_1_fixable | tier_2_fixable
    requested = set(rule_filter) if rule_filter else None

    # Validate --rule arguments — error early on unknown IDs.
    if requested:
        for rid in requested:
            if rid not in fixable:
                tier_2_only = rid in fixable_check_ids(tier=2)
                if tier_2_only and not use_ai:
                    console.print(
                        f"[red]CHECK ID {rid!r} has only a Tier 2 fixer[/] "
                        "— pass --ai to enable Claude subprocess fixers."
                    )
                else:
                    console.print(
                        f"[red]CHECK ID {rid!r} has no fixer[/] "
                        "(unknown, or in the manual-only list)."
                    )
                raise typer.Exit(2)

    # Pick fixers. If --rule was given, run those; otherwise run every
    # fixable rule currently failing.
    if requested:
        to_fix_t1 = sorted(requested & tier_1_fixable)
        to_fix_t2 = sorted(requested & tier_2_fixable)
    else:
        to_fix_t1 = sorted(set(failed_ids) & tier_1_fixable)
        to_fix_t2 = sorted(set(failed_ids) & tier_2_fixable) if use_ai else []

    manual_failing = sorted(set(failed_ids) - fixable)

    console.print(f"[bold]{domain}[/]  [dim](resolved from {name!r})[/]")
    n_pass = len(result["conformance"]["passed"])
    n_fail = len(result["conformance"]["failed"])
    n_skip = result["conformance"].get("skipped", [])
    console.print(f"Conformance: {n_pass} pass · {n_fail} fail · {len(n_skip)} skip")
    console.print()

    if use_ai and not claude_available():
        console.print(
            "[yellow]--ai requested but `claude` CLI is not on PATH.[/] "
            "Tier 2 fixers will be skipped."
        )

    if not to_fix_t1 and not to_fix_t2 and not manual_failing:
        console.print("[green]Nothing to fix — all checks passing.[/]")
        return

    # Plan output.
    if to_fix_t1:
        verb = "Plan" if not apply_changes else "Applying"
        console.print(f"[bold]{verb}: {len(to_fix_t1)} fixable (Tier 1 — templated)[/]")
        for cid in to_fix_t1:
            spec = get_tier_1(cid)
            console.print(f"  + [cyan]{cid}[/]  {spec.summary}")
    if to_fix_t2:
        console.print(
            f"\n[bold]{len(to_fix_t2)} fixable (Tier 2 — Claude subprocess):[/]"
        )
        for cid in to_fix_t2:
            spec = get_tier_2(cid)
            console.print(f"  + [magenta]{cid}[/]  {spec.summary}")
    if manual_failing:
        console.print(
            f"\n[bold]Manual ({len(manual_failing)} not auto-fixable):[/]"
        )
        for cid in manual_failing:
            tier_2_only = cid in fixable_check_ids(tier=2)
            note = " [dim](pass --ai to enable Tier 2)[/]" if tier_2_only and not use_ai else "  needs human"
            console.print(f"  ! [yellow]{cid}[/] {note}")

    if not apply_changes:
        total = len(to_fix_t1) + len(to_fix_t2)
        console.print(
            f"\n[dim]Re-run with --apply to write the {total} change(s).[/]"
        )
        return

    # --apply path: Tier 1 first, then Tier 2 (if --ai).
    console.print()
    fixed_count = 0
    skipped_count = 0

    for cid in to_fix_t1:
        spec = get_tier_1(cid)
        # Lockfile deletions: per-file confirmation unless --yes.
        if cid in {"CHECK_032", "CHECK_033", "CHECK_034"} and not assume_yes:
            ok = typer.confirm(
                f"  Delete {spec.summary.split('delete ')[-1].split(' ')[0]}?",
                default=False,
            )
            if not ok:
                console.print(f"  [yellow]↷[/]  {cid}  skipped by user")
                skipped_count += 1
                continue
        result_obj = spec.apply(project_dir, dry_run=False, assume_yes=assume_yes)
        if result_obj.status == "fixed":
            console.print(f"  [green]✓[/]  {cid}  {result_obj.summary}")
            fixed_count += 1
        elif result_obj.status == "nothing-to-do":
            console.print(f"  [dim]·  {cid}  {result_obj.summary}[/]")
        elif result_obj.status == "manual":
            console.print(f"  [yellow]![/]  {cid}  {result_obj.summary}")
            skipped_count += 1
        else:
            console.print(f"  [red]✗[/]  {cid}  {result_obj.summary}")
            skipped_count += 1

    # Tier 2 (--ai): runs after Tier 1 so any file/section creation is
    # already in place when Claude tries to edit content.
    if to_fix_t2 and use_ai and claude_available():
        console.print(f"\n[magenta]Tier 2 — spawning {len(to_fix_t2)} claude subprocess(es)[/]")
        for cid in to_fix_t2:
            spec = get_tier_2(cid)
            console.print(f"  [magenta]→[/]  {cid}  {spec.summary}")
            result_obj = spec.apply(project_dir, dry_run=False, assume_yes=assume_yes)
            if result_obj.status == "fixed":
                console.print(f"  [green]✓[/]  {cid}  {result_obj.summary}")
                fixed_count += 1
            elif result_obj.status == "nothing-to-do":
                console.print(f"  [dim]·  {cid}  {result_obj.summary}[/]")
            elif result_obj.status == "manual":
                console.print(f"  [yellow]![/]  {cid}  {result_obj.summary}")
                skipped_count += 1
            else:
                console.print(f"  [red]✗[/]  {cid}  {result_obj.summary}")
                skipped_count += 1

    # Re-run conformance to confirm the changes landed.
    after = build_status(name)
    a_pass = len(after["conformance"]["passed"])
    a_fail = len(after["conformance"]["failed"])
    console.print(
        f"\n[bold]After fix:[/] {a_pass} pass · {a_fail} fail "
        f"[dim](was {n_pass} / {n_fail})[/]"
    )
    if manual_failing or skipped_count:
        console.print(
            f"[dim]{len(manual_failing)} manual + {skipped_count} skipped — "
            f"see plan above.[/]"
        )
        if a_fail > 0:
            raise typer.Exit(3)


# ===========================================================================
# v6.D — fleetwide `project fix --all` helper
# ===========================================================================


_DELETE_CATEGORY = "to be deleted immediately"
_TIER_2_COST_ESTIMATE_USD = 0.10  # rough per-call estimate for budget hint


def _list_fleet_eligible_projects():
    """Return [(domain, project_dir)] for every fleetwide-fix-eligible
    project: skip ignore_repos config + skip domains in 'To be deleted
    immediately' category. Sorted alphabetically."""
    from .checks.config import load_config
    cfg = load_config()
    repos = _iterate_repos(cfg.repos_dir, ignore=cfg.ignore_repos)
    domains_by_name = {d.name.lower(): d for d in load_domains()}
    out = []
    for repo_path in repos:
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


# ===========================================================================
# v7.A — new commands wired into project / fleet / settings namespaces.
# Each forwards to existing logic; old paths kept as deprecation aliases.
# ===========================================================================

# ---------- project namespace ----------


@project_app.command("check")
def project_check(
    name: str = typer.Argument(..., help="Project name (fuzzy-matched against domains)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of human table"),
    catalog_only: bool = typer.Option(
        False, "--catalog-only",
        help="Skip git/deploy/prompts; show only the per-rule catalog table",
    ),
) -> None:
    """v7.A — full per-project status: conformance + git + deploy + prompts.

    Replaces `info status` (deprecated alias still works). With
    `--catalog-only`, behaves like the per-rule view formerly at
    `check git --domain <name>`.
    """
    if catalog_only:
        # Map to the per-repo detail rendering used by `check git --domain`.
        from .checks import list_checks, run_checks
        from .checks.config import load_config
        from .project import resolve_project, SITES_ROOT

        plan = load_plan()
        res = resolve_project(name, plan=plan)
        if res.matched is None:
            console.print(f"[red]No project matches[/] [bold]{name}[/].")
            raise typer.Exit(1)
        project_dir = SITES_ROOT / res.matched
        if not project_dir.is_dir():
            console.print(f"[red]Project dir not found:[/] {project_dir}")
            raise typer.Exit(1)
        cfg = load_config()
        catalog_specs = [s for s in list_checks() if s.category in _GIT_FLAG_CATEGORIES]
        catalog_ids = [s.id for s in catalog_specs]
        results = run_checks(str(project_dir), ids=catalog_ids,
                             skip_checks=cfg.skip_checks)
        _render_per_repo_detail(res.matched, results, catalog_specs)
        return
    # Default: full status (the v5.E refactor body).
    info_status(name=name, json_out=json_out)


@project_app.command("seo")
def project_seo(
    name: str = typer.Argument(..., help="Domain (single-domain runtime SEO probe)"),
    days: int = typer.Option(28, "--days"),
    refresh: bool = typer.Option(False, "--refresh"),
    sort_by: str = typer.Option("impressions", "--sort"),
) -> None:
    """v7.A — runtime SEO probe (HTTP + GSC + CrUX) for one domain.
    Replaces `check seo --domain <name>` (deprecated alias works)."""
    _run_check_seo_mode(days=days, only_domain=name.lower(),
                        sort_by=sort_by, only="wip", concurrency=20,
                        refresh=refresh)


@project_app.command("diagnose")
def project_diagnose(
    domain: str = typer.Argument(..., help="Domain to investigate (e.g. lamill.us)"),
) -> None:
    """Auto-investigate a domain's deploy state — DNS / HTTP / TLS / repo
    / inventory — and surface a root cause + suggested fix.

    Read-only. Replaces the manual dig/curl/openssl flow when a dashboard
    row goes red and you need to know *why* before deciding what to do.
    """
    from .diagnose import diagnose, render
    d = diagnose(domain)
    render(d, console)


@project_app.command("set-launched")
def project_set_launched(
    name: str = typer.Argument(..., help="Project / domain name"),
    launched_date: str = typer.Argument(
        ..., metavar="YYYY-MM-DD",
        help="ISO date the site went live (e.g. 2026-04-18)",
    ),
) -> None:
    """Set the launch date for a site. Persisted in portfolio.json.

    `fleet dashboard` defaults to first-commit date as a proxy for
    site age; this command sets an explicit override for cases where
    that proxy is wrong (imported repo, long-running scaffold work
    before first deploy, etc.).
    """
    from datetime import date as _date
    from .data import update_domain_field
    try:
        d = _date.fromisoformat(launched_date)
    except ValueError:
        console.print(f"[red]Invalid date: {launched_date!r}[/] — expected YYYY-MM-DD.")
        raise typer.Exit(2)
    ok = update_domain_field(name, "launched", d)
    if not ok:
        console.print(f"[red]Domain not found in portfolio.json:[/] {name}")
        raise typer.Exit(1)
    console.print(f"[green]Set[/] {name}.launched = {d.isoformat()}")


# ---------- fleet namespace ----------


@fleet_app.command("focus")
def fleet_focus(
    show_all: bool = typer.Option(False, "--all"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-probe live + SEO before reading caches"),
    include_young: bool = typer.Option(
        False, "--include-young",
        help="Also flag SEO signals on sites <90d old",
    ),
) -> None:
    """v7.A — top priorities across the fleet (formerly top-level `focus`)."""
    focus(show_all=show_all, refresh=refresh, include_young=include_young)


@fleet_app.command("live")
def fleet_live(
    only: str = typer.Option("wip", "--only", "-o"),
    concurrency: int = typer.Option(20, "--concurrency", "-c"),
) -> None:
    """v7.A — fetch + classify each domain → snapshot. Was `check live`."""
    check_live(only=only, concurrency=concurrency, domain="")


@fleet_app.command("seo")
def fleet_seo(
    days: int = typer.Option(28, "--days"),
    only: str = typer.Option("wip", "--only", "-o"),
    concurrency: int = typer.Option(20, "--concurrency", "-c"),
    sort_by: str = typer.Option("impressions", "--sort"),
    refresh: bool = typer.Option(False, "--refresh"),
) -> None:
    """v7.A — runtime SEO probe across all live-site/forwarder domains.
    Was `check seo` (no `--domain`)."""
    check_seo(days=days, domain="", repo="", only=only,
              concurrency=concurrency, sort_by=sort_by, refresh=refresh)


@fleet_app.command("check")
def fleet_check(
    detail: bool = typer.Option(False, "--detail"),
    check_id: str = typer.Option("", "--check"),
) -> None:
    """v7.A — cross-repo catalog summary. Was `check git`."""
    check_git(detail=detail, check_id=check_id, domain="", repo="")


@fleet_app.command("fix")
def fleet_fix(
    apply_changes: bool = typer.Option(False, "--apply"),
    rule_filter: list[str] = typer.Option(None, "--rule"),
    assume_yes: bool = typer.Option(False, "--yes"),
    use_ai: bool = typer.Option(False, "--ai"),
) -> None:
    """v7.A — fleetwide remediation. Was `project fix --all`."""
    _run_project_fix_all(apply_changes=apply_changes,
                         rule_filter=rule_filter,
                         assume_yes=assume_yes,
                         use_ai=use_ai)


@fleet_app.command("drift")
def fleet_drift() -> None:
    """v7.A — cross-source inconsistencies. Was `info drift`."""
    info_drift()


@fleet_app.command("repos")
def fleet_repos(
    detail: bool = typer.Option(
        False, "--detail",
        help="Show per-site state + fix plan (verbose).",
    ),
    only: str = typer.Option(
        "", "--only",
        help="Filter to one site by name (implies --detail).",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Emit machine-readable JSON instead of a table.",
    ),
) -> None:
    """Audit each sites/<domain>/ for git-layer state (read-only).

    Classifies every site into one of: clean standalone, nested
    anti-pattern, standalone unpublished, monorepo-only, unversioned,
    or empty stub. Also flags any remote whose name truncates the
    domain (full-domain naming convention; CHECK_040 covers per-site).

    Write modes (`--fix`, `--remote`) are intentionally not implemented
    in this version — audit-only by design.
    """
    from .fleet_repos import (
        audit, render_detail, render_json, render_summary,
    )
    rows = audit()
    if only:
        rows = [r for r in rows if r.name == only]
        if not rows:
            console.print(f"[red]No site matches[/] [bold]{only}[/].")
            raise typer.Exit(1)
    if json_out:
        render_json(rows, console)
        return
    if only or detail:
        render_detail(rows, console)
        return
    render_summary(rows, console)


@fleet_app.command("dashboard")
def fleet_dashboard(
    scope: str = typer.Option("wip", "--only", "-o",
                              help="Scope: 'wip' or 'all'"),
    sort: str = typer.Option("attention", "--sort",
                             help="Sort: attention | name | imp | age"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-probe live + SEO before rendering"),
) -> None:
    """Unified per-domain view — joins live + SEO + git into one row.

    Read-only by default: just renders from the latest cached
    `data/checks/<date>.json` and `data/seo/<date>.json`. Git status
    is always live (local FS only). `--refresh` re-runs live + SEO
    probes (≈ same cost as `fleet live` + `fleet seo --refresh`).
    """
    if scope not in ("wip", "all"):
        console.print(f"[red]--only must be 'wip' or 'all', got {scope!r}.[/]")
        raise typer.Exit(2)
    if sort not in ("attention", "name", "imp", "age"):
        console.print(f"[red]--sort must be attention|name|imp|age, got {sort!r}.[/]")
        raise typer.Exit(2)
    from .dashboard import run_dashboard
    run_dashboard(scope=scope, sort=sort, refresh=refresh, console=console)


# fleet info subgroup


@fleet_info_app.command("summary")
def fleet_info_summary(
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Add the full domain list (replaces old `info list`)"),
) -> None:
    """v7.A — portfolio overview. `--verbose` adds the per-domain table."""
    info_summary()
    if verbose:
        console.print()
        info_list()


@fleet_info_app.command("expiring")
def fleet_info_expiring(
    within: int = typer.Option(180, "--within", "-w"),
) -> None:
    """v7.A — domains expiring within N days. Was `info expiring`."""
    info_expiring(within=within)


@fleet_info_app.command("cleanup")
def fleet_info_cleanup(
    refresh_rdap: bool = typer.Option(
        False, "--refresh-rdap",
        help="Also fetch RDAP creation_date per domain (~0.5s each, ~15s for full fleet)."
    ),
) -> None:
    """v7.A — rebuild data/portfolio.json from registrar CSVs.
    Was `info cleanup`. `--refresh-rdap` adds the domain-age fetch."""
    info_cleanup(refresh_rdap=refresh_rdap)


# ---------- settings namespace ----------


@settings_catalog_app.command("list")
def settings_catalog_list(
    category: str = typer.Option("", "--category", "-c"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """v7.A — list every check in the catalog. Was `check catalog`."""
    check_catalog(category=category, json_out=json_out)


@settings_catalog_app.command("describe")
def settings_catalog_describe(
    check_id: str = typer.Argument(..., help="Check ID (e.g. CHECK_001)"),
) -> None:
    """v7.A — show one check's metadata + source link.
    Was `check describe`."""
    check_describe(check_id=check_id)


@settings_catalog_app.command("run")
def settings_catalog_run(
    repo_path: str = typer.Argument(..., help="Project path"),
    check_id: str = typer.Option("", "--check"),
    category: str = typer.Option("", "--category", "-c"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of a table"),
) -> None:
    """Run one or many catalog checks against an arbitrary path."""
    check_run(repo_path=repo_path, check_id=check_id, category=category,
              json_out=json_out)


# settings gsc — auth + status (status folds in old list/sync/compare)


@settings_gsc_app.command("auth")
def settings_gsc_auth(
    force: bool = typer.Option(False, "--force"),
) -> None:
    """v7.A — set up / refresh GSC OAuth. Was `gsc auth`."""
    gsc_auth(force=force)


@settings_gsc_app.command("status")
def settings_gsc_status(
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Pull latest GSC totals + write a snapshot (was `gsc sync`)"),
    days: int = typer.Option(28, "--days", "-d",
                             help="Window size for --refresh"),
    lag_days: int = typer.Option(3, "--lag-days"),
    concurrency: int = typer.Option(5, "--concurrency", "-c"),
) -> None:
    """v7.A — GSC integration status. Without flags: lists verified
    properties + cross-references with WIP domains + shows latest
    snapshot diff (was `gsc list` + `gsc compare`). With `--refresh`:
    pulls fresh totals + writes a new snapshot (was `gsc sync`).
    """
    if refresh:
        gsc_sync(days=days, lag_days=lag_days, concurrency=concurrency)
        return
    gsc_list()
    console.print()
    try:
        gsc_compare()
    except typer.Exit:
        pass


# settings apikeys — list / set / delete


_TICK = {
    "valid": "[green]✓ valid[/]",
    "invalid": "[red]✗ invalid[/]",
    "not-testable": "[dim]— not testable[/]",
    "missing": "[dim]—[/]",
}


@settings_apikeys_app.command("list")
def settings_apikeys_list() -> None:
    """v7.A — list every known credential in portfolio.env, with a
    set/not-set marker AND a connectivity tick per provider.

    Probes hit each provider's API once (~5-10s total). Catches typos
    immediately ("did I paste the right key?") rather than discovering
    failures later when the actual feature uses the credential.
    """
    from .apikeys import KNOWN_KEYS, get_key, probe_all

    console.print("[cyan]Probing credentials (one network call per provider)...[/]")
    probes = probe_all()

    t = Table(box=None, padding=(0, 2), show_header=True,
              title="[bold]API keys in portfolio.env[/]",
              title_justify="left")
    t.add_column("Key")
    t.add_column("Status")
    t.add_column("Probe")
    for key in KNOWN_KEYS:
        is_set = "set" if get_key(key) else "[dim]not set[/]"
        probe = probes.get(key)
        if probe is None or probe.status == "missing":
            tick = "[dim]—[/]"
        else:
            tick = _TICK.get(probe.status, probe.status)
            if probe.detail and probe.status not in ("valid",):
                tick = f"{tick} [dim]({probe.detail})[/]"
        t.add_row(key, is_set, tick)
    console.print(t)


@settings_apikeys_app.command("set")
def settings_apikeys_set(
    key: str = typer.Argument(..., help="API key name (e.g. OPENAI_API_KEY)"),
    value: str = typer.Argument(..., help="Value to set"),
    force: bool = typer.Option(False, "--force",
                               help="Allow setting a key not in the known list"),
) -> None:
    """v7.A — set a credential in portfolio.env. Strict by default
    (only known keys); `--force` allows arbitrary key names.

    Atomic write — preserves comments, blank lines, and ordering of
    untouched keys. If the key already exists, the existing line is
    updated; new keys append at the end.
    """
    from .apikeys import KNOWN_KEYS, set_key
    if key not in KNOWN_KEYS and not force:
        console.print(
            f"[red]'{key}' isn't in the known list.[/] "
            f"[dim]Known: {', '.join(KNOWN_KEYS)}.[/]\n"
            "[dim]Use --force to set an arbitrary key name anyway.[/]"
        )
        raise typer.Exit(2)
    set_key(key, value)
    console.print(f"[green]✓[/] set [bold]{key}[/]")


@settings_apikeys_app.command("delete")
def settings_apikeys_delete(
    key: str = typer.Argument(..., help="API key name to remove"),
    assume_yes: bool = typer.Option(False, "--yes",
                                    help="Skip the confirmation prompt"),
) -> None:
    """v7.A — remove a credential from portfolio.env."""
    from .apikeys import delete_key, get_key
    if not get_key(key):
        console.print(f"[dim]{key} is already absent — nothing to do.[/]")
        return
    if not assume_yes:
        ok = typer.confirm(f"Delete {key} from portfolio.env?", default=False)
        if not ok:
            console.print("[yellow]Aborted.[/]")
            raise typer.Exit(0)
    if delete_key(key):
        console.print(f"[green]✓[/] removed [bold]{key}[/]")
    else:
        console.print(f"[dim]{key} was not present.[/]")


if __name__ == "__main__":
    app()
