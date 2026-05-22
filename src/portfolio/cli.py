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
    help="lamill — manage your domain fleet + sites/ workspace.",
    add_completion=False,
)
console = Console()

new_app = typer.Typer(help="Add new domains / projects.", no_args_is_help=True)
app.add_typer(new_app, name="new")

# v7.A — scope-first restructure. `project` for ops on one project,
# `fleet` for cross-portfolio ops, `settings` for setup/debug surfaces.
# Each new command is a thin wrapper that forwards to existing logic;
# old paths (`info status`, `check git --domain`, etc.) are kept as
# deprecation aliases that print a one-line nudge and forward.
fleet_app = typer.Typer(help="Cross-portfolio ops.", no_args_is_help=True)
settings_app = typer.Typer(help="Setup / debug.", no_args_is_help=True)
settings_catalog_app = typer.Typer(help="Inspect the check catalog.",
                                   no_args_is_help=True)
settings_gsc_app = typer.Typer(help="Google Search Console integration.",
                               no_args_is_help=True)
settings_ga4_app = typer.Typer(help="Google Analytics 4 Admin API integration.",
                               no_args_is_help=True)
settings_apikeys_app = typer.Typer(help="Manage credentials in portfolio.env.",
                                   no_args_is_help=True)
settings_operator_app = typer.Typer(
    help="Operator profile (used by `new validate` fit-checks).",
    no_args_is_help=True,
)
settings_cloudflare_app = typer.Typer(
    help="Cloudflare API token (used by CHECK_057 cache-purge fix).",
    no_args_is_help=True,
)
settings_serpapi_app = typer.Typer(
    help="SerpAPI quota ledger — show local state + sync with SerpAPI's records.",
    no_args_is_help=True,
)
settings_deploy_app = typer.Typer(
    help="Per-project deploy declaration — `set`, `show`, `set-launched`.",
    no_args_is_help=True,
)
app.add_typer(fleet_app, name="fleet")
app.add_typer(settings_app, name="settings")
settings_app.add_typer(settings_catalog_app, name="catalog")
settings_app.add_typer(settings_gsc_app, name="gsc")
settings_app.add_typer(settings_ga4_app, name="ga4")
settings_app.add_typer(settings_apikeys_app, name="apikeys")
settings_app.add_typer(settings_operator_app, name="operator")
settings_app.add_typer(settings_cloudflare_app, name="cloudflare")
settings_app.add_typer(settings_serpapi_app, name="serpapi-quota")
settings_app.add_typer(settings_deploy_app, name="deploy")


@app.callback(invoke_without_command=True)
def _root_callback(ctx: typer.Context) -> None:
    """When `lamill` is invoked with no subcommand, drop into the grouped
    interactive menu. Explicit subcommands work unchanged."""
    if ctx.invoked_subcommand is None:
        from .menu import run_menu
        run_menu()


# focus — kept as implementation for `fleet focus`.
def focus(
    show_all: bool = typer.Option(False, "--all", help="Show the full ranked list, not just top 5"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-run live + SEO probes upstream before reading caches"),
    include_young: bool = typer.Option(
        False, "--include-young",
        help="Also flag SEO signals on sites <90d old (suppressed by default — those signals are normal in the Google freshness window)",
    ),
) -> None:
    """Where to focus today — top priorities across the fleet.

    Reads from caches only — never blocks on a live fetch. If a cache
    is missing, that signal is silently skipped. Run `fleet domains` /
    `fleet seo` first to populate them. `--refresh` does it for you.
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
    # `settings deploy set-launched`); falls back to first-commit-date inference
    # for projects without an explicit launched date.
    domain_site_age = {
        d.name.lower(): _site_age_days(d.name, d.launched)
        for d in all_domains
    }

    # CHECK_057 (stale CF edge cache) — run directly per CF Pages site
    # rather than waiting for a full `build_status` pass per domain.
    # Bounded cost: 5 HTTP probes × N CF sites, parallelized. Skips
    # non-CF projects cheaply via filesystem stat.
    from concurrent.futures import ThreadPoolExecutor
    from .project import SITES_ROOT
    from .checks.deploy.check_057_cf_edge_cache_fresh import (
        run as _run_cf_cache_check,
    )

    def _cf_failure_for(name: str) -> tuple[str, str] | None:
        project_dir = SITES_ROOT / name
        if not project_dir.is_dir():
            return None
        if not (project_dir / "wrangler.jsonc").is_file() and \
           not (project_dir / "wrangler.toml").is_file():
            return None
        try:
            result = _run_cf_cache_check(str(project_dir))
        except Exception:
            return None
        if result.status != "fail":
            return None
        return (name.lower(), result.message)

    domain_check_failures: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(_cf_failure_for, [d.name for d in all_domains]):
            if r is None:
                continue
            dom, msg = r
            domain_check_failures[dom] = {"CHECK_057": msg}

    suppressed_young: list[str] = []
    items = build_focus_list(
        live_snapshot=live_data,
        seo_snapshot=seo_data,
        domains_with_expiry=domains_expiry,
        domain_categories=domain_categories,
        domain_site_age_days=domain_site_age,
        domain_check_failures=domain_check_failures,
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
        console.print(f"   [dim]→ run 'lamill fleet sync' to consolidate[/]")
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
        console.print(f"   [dim]→ run 'lamill fleet sync' to refresh[/]")
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


# info_cleanup — kept as implementation for `fleet sync`.
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


# info_summary — kept as implementation for `fleet domains --summary`.
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


# info_expiring — kept as implementation for `fleet domains --expiring`.
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


# check_live — kept as implementation for `fleet domains`.
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
    "CHECK_148": "fix GA4 measurement ID (must match `G-[A-Z0-9]{6,12}`)",
    "CHECK_149": 'add `<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXX">` loader before the inline gtag() calls',
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
    from .seo_runtime import gsc_sitemap_cell, overall_status, row_statuses

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
    # GSC sitemap cell — merges presence (submitted or not) with per-sitemap
    # processing health (errors / warnings from GSC's Sitemaps API). 🔴 = GSC
    # reported errors on a submitted sitemap ("Sitemap could not be read"),
    # 🟡 = warnings, 🟢 = submitted and clean, ❌ = none submitted, ⚪ = no data.
    t.add_column("GSC sm", justify="center")
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
            gsc_sitemap_cell(row),
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

    # Call out sites that are in GSC but have no sitemap submitted —
    # easy fix, but invisible without this surface.
    missing_sm = [r.domain for r in rows
                  if r.gsc_status == "ok"
                  and r.gsc_sitemap_count == 0]
    if missing_sm:
        sample = ", ".join(missing_sm[:3])
        more = f" + {len(missing_sm) - 3} more" if len(missing_sm) > 3 else ""
        console.print(
            f"[dim]❌ {len(missing_sm)} site(s) in GSC with no sitemap submitted "
            f"({sample}{more}) — submit at search.google.com/search-console "
            f"→ Sitemaps.[/]"
        )

    # Call out sites where GSC reported errors on a SUBMITTED sitemap —
    # "Sitemap could not be read" lives here. Different fix from missing
    # submission: the sitemap exists in GSC but Google can't process it.
    broken_sm = [r for r in rows
                 if r.gsc_status == "ok"
                 and (r.gsc_sitemap_errors or 0) > 0]
    if broken_sm:
        sample = ", ".join(r.domain for r in broken_sm[:3])
        more = f" + {len(broken_sm) - 3} more" if len(broken_sm) > 3 else ""
        console.print(
            f"[dim]🔴 {len(broken_sm)} site(s) with sitemap errors in GSC "
            f"({sample}{more}) — open Search Console → Sitemaps and "
            f"inspect the failing entry; common causes: stale edge cache, "
            f"sitemap URL not in current build, malformed XML.[/]"
        )

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


# info_list — kept as implementation for `fleet domains --summary --verbose`.
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


@new_app.command("domain")
def new_domain(
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
    # 2026-05-21: dropped letter-keyed `s` in favor of pure numeric
    # menu. Was `s` (between 7 and 8) — broke the eye's left-column
    # numeric scan. Now `8` keeps the affordance next to its 6/7
    # shortlist siblings; `9` and `10` follow.
    ("8", "Show marked names as full grid",            False),
    ("9", "Show TLD reference (pricing, SEO, vibe)",   False),
    ("10", "Rerun fresh (bypass cache)",               False),  # v4.D polish
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
    """Render the post-grid menu. When shortlist_count > 0, items 6
    (Mark / unmark) and 8 (Show marked as grid) both get a
    "(N marked)" suffix so the user can see at a glance how big their
    shortlist has grown."""
    console.print("\n[bold]What do you want to do next?[/]")
    for key, label, coming_soon in MENU_ITEMS:
        line = f"  {key}. {label}"
        if key in ("6", "8") and shortlist_count > 0:
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
    _render_grid(merged, tld_list, show_renewal=show_renewal, topic=topic)
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


def _menu_show_marked(rows, shortlist: list[str], tld_list: list[str], *,
                     show_renewal: bool, topic: str = "") -> None:
    """Render the shortlist as a full registrar grid (same columns as
    the main grid) so the operator can compare marked names side-by-
    side with per-TLD cells, anchors, picks, and rationale visible.

    Distinct from the brief shortlist printed inside `_menu_shortlist`
    after each mark (that one is just name + pick + price). This is the
    full grid scoped to the marked set. Handy after marking 10+ names
    when the brief form loses the "why" / per-TLD detail.

    No-op cases handled explicitly:
      - empty shortlist → tells the operator to mark first
      - shortlist exists but none of the names appear in the current
        rows (can happen after `widen` filtered them out) → tells the
        operator to re-mark from the current grid
    """
    if not shortlist:
        console.print(
            "[yellow]Shortlist is empty. Mark some rows first (option 6).[/]"
        )
        return
    name_to_row = {r.name: r for r in rows}
    marked_rows = [name_to_row[n] for n in shortlist if n in name_to_row]
    missing = [n for n in shortlist if n not in name_to_row]

    if not marked_rows:
        console.print(
            f"[yellow]None of the {len(shortlist)} marked names are in the "
            f"current grid (e.g., after a widen pass that filtered them "
            f"out). Re-mark from the current grid (option 6).[/]"
        )
        return

    _render_grid(marked_rows, tld_list, show_renewal=show_renewal, topic=topic)
    if missing:
        sample = ", ".join(missing[:5])
        more = f" + {len(missing) - 5} more" if len(missing) > 5 else ""
        console.print(
            f"[dim]Note: {len(missing)} marked name(s) not in current grid: "
            f"{sample}{more}[/]"
        )


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
    _render_grid(merged, tld_list, show_renewal=show_renewal, topic=topic)
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

    _render_grid(rows, tld_list, show_renewal=show_renewal, topic=topic)

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
            _render_grid(rows, tld_list, show_renewal=show_renewal, topic=topic)
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
            _menu_show_marked(
                rows, shortlist, tld_list,
                show_renewal=show_renewal, topic=topic,
            )
            continue
        if choice == "9":
            _render_tld_reference()
            continue
        if choice == "10":
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
            _render_grid(rows, tld_list, show_renewal=show_renewal, topic=topic)
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


def _render_grid(rows, columns: list[str], show_renewal: bool = False,
                 *, topic: str | None = None) -> None:
    """Render the v3.D registrar grid: rows = names, cols = TLD cells + Anchors
    + Pick + Why. Anchors column shows vocab terms found in the name (the row
    differentiator); cliff markers (↑Nx) on cells flag renewal bait-and-switch
    (the column differentiator).

    When `topic` is provided, renders a one-line title above the table
    so the operator can scan the grid with the original topic in
    eyeshot — same affordance as `new validate`'s Topic line. Optional
    for backward compatibility with any caller that doesn't have the
    topic in scope.
    """
    if topic:
        console.print(f"\n[bold]Topic:[/] [cyan]{topic}[/]\n")
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
    # v9.B — operator-input AI_AGENTS sections. Each flag overrides
    # the interactive prompt; missing flags get prompted unless
    # --non-interactive is set.
    summary: str = typer.Option("", "--summary",
                                help="AI_AGENTS.md Summary section content (skips the prompt)"),
    audience: str = typer.Option("", "--audience",
                                 help="AI_AGENTS.md Audience section content (skips the prompt)"),
    icp: str = typer.Option("", "--icp",
                            help="AI_AGENTS.md ICP section content (skips the prompt)"),
    goal: str = typer.Option("", "--goal",
                             help="AI_AGENTS.md Goals section content (skips the prompt)"),
    content_strategy: str = typer.Option("", "--content-strategy",
                                         help="AI_AGENTS.md Content strategy section content (skips the prompt)"),
    non_interactive: bool = typer.Option(
        False, "--non-interactive",
        help="Skip all v9.B / v9.C prompts — operator-input sections "
             "without --flag values get (to be filled in) placeholders; "
             "domain inventory isn't updated unless --registered is set.",
    ),
    # v9.C — domain-registration prompt + portfolio.json auto-update.
    registered: bool | None = typer.Option(
        None, "--registered/--not-registered",
        help="Domain registration status. --registered appends an Active "
             "row to portfolio.json; --not-registered appends a Pending "
             "row (reminder to come back). Omit to be prompted interactively.",
    ),
    registrar: str = typer.Option(
        "", "--registrar",
        help="porkbun | godaddy | namecheap | other  (skips the prompt)",
    ),
    # v9.D — growth-hypothesis prompt that seeds docs/growth.md.
    growth_hypothesis: str = typer.Option(
        "", "--growth-hypothesis",
        help="One paragraph: what's your bet for how this site reaches "
             "its audience? Written into docs/growth.md as the first "
             "dated H2 entry. (skips the prompt)",
    ),
    # v10.C — `lamill.toml` written as part of scaffolding.
    platform: str = typer.Option(
        "", "--platform",
        help="Override the lamill.toml [deploy].platform written by "
             "bootstrap. Default: cf-pages (or inferred from existing "
             "platform-config markers if --from-genai brought any). "
             "Values: cf-pages | cf-workers | vercel | netlify | "
             "github-pages | hostgator | custom | none.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Skip the owned-domains validation — use when "
             "bootstrapping a domain you haven't registered yet (rare).",
    ),
    budget_usd: float = typer.Option(
        0.0, "--budget",
        help="v15.K — Claude translation budget cap (USD). Default 0.0 "
             "uses the stack_translate module default ($2.00; was $0.50 "
             "pre-v15.K — bumped after operator's TanStack→Astro hit the "
             "old cap). Pass a higher value (e.g. `--budget 5.0`) for "
             "very complex Lovable exports. Only consulted when "
             "`--translate-now` is set; the deferred path uses the "
             "`project translate` verb's own budget flag.",
    ),
    translate_now: bool = typer.Option(
        False, "--translate-now",
        help="v15.M — translate non-Astro `--git-url` cloned source "
             "synchronously during bootstrap (the pre-v15.M behavior). "
             "Default skips translation, scaffolds blank Astro, and "
             "leaves `genai/` for `lamill project translate <domain>` "
             "to port later.",
    ),
) -> None:
    """Scaffold a new sites/<domain>/ project to ship-ready conformance (v3.A).

    v9.B — bootstrap prompts for the 5 operator-input AI_AGENTS
    sections (Summary / Audience / ICP / Goals / Content strategy)
    unless overridden by per-section flags or `--non-interactive`.
    Sections left blank render as `(to be filled in)` placeholders
    that CHECK_014's tier-1 fix can also populate later.

    v9.C — bootstrap also asks whether the domain is registered and
    appends a row to data/portfolio.json so `project check <domain>`
    resolves immediately. Bypass with `--registered` / `--not-registered`
    + `--registrar <name>` flags, or `--non-interactive`.

    v9.D — bootstrap also prompts for an initial growth hypothesis
    (one paragraph: "what's your bet for how this site reaches its
    audience?") and writes it as the first dated H2 entry in
    `docs/growth.md`. Skip with `--growth-hypothesis "X"` flag or
    `--non-interactive`.

    Cross-checks the requested domain against the owned-domains
    inventory (`data/portfolio.json` + `data/domains/*.csv`) before
    writing anything. Typo'd or unregistered domains exit 2 with a
    "Did you mean: …?" hint unless `--force` is passed.
    """
    from .bootstrap import (
        BootstrapError,
        bootstrap as run_bootstrap,
        validate_owned_domain,
    )
    from .stack_translate import StackTranslationError

    # Owned-domains pre-flight. Runs BEFORE prompts / file writes so a
    # typo'd domain (e.g. `ageskd.dev` for `agesdk.dev`) exits cleanly
    # without scaffolding the wrong directory or polluting
    # portfolio.json. Bypass with `--force`.
    if not force:
        owned = validate_owned_domain(domain)
        if not owned.found:
            if owned.close_matches:
                hint = (
                    f"Did you mean: {', '.join(owned.close_matches)}? "
                    "Run `lamill fleet sync --refresh` to pull the "
                    "latest Porkbun list, or pass --force to bootstrap "
                    "anyway."
                )
            else:
                hint = (
                    "Verify the spelling, or pass --force to bootstrap "
                    "anyway."
                )
            console.print(
                f"[yellow]⚠[/] '{domain}' is not in your owned-domains "
                f"inventory. {hint}"
            )
            raise typer.Exit(2)

    # Bug-fix 2026-05-20 — pre-flight banner: when running fully
    # interactively, print all 9 prompts the operator is about to be
    # asked so they can prep paragraph-length answers or hit Enter to
    # skip. Skipped when `--non-interactive` or when all per-section
    # flag values are supplied (no prompts would fire anyway).
    _render_bootstrap_preflight(
        domain=domain,
        non_interactive=non_interactive,
        git_url=git_url,
        summary=summary, audience=audience, icp=icp, goal=goal,
        content_strategy=content_strategy,
        growth_hypothesis=growth_hypothesis,
        registered=registered, registrar=registrar,
    )

    # Bug-fix 2026-05-20 — Lovable repo URL prompt. Asked FIRST so the
    # operator's UI is in place before the AI_AGENTS docs are filled
    # in (those docs should be able to reference the actual code).
    # Skipped when `--git-url` is already supplied or `--non-interactive`.
    git_url = _resolve_git_url(
        flag_value=git_url, non_interactive=non_interactive,
    )

    # Bug-fix 2026-05-20 — smart multi-section paste. When the operator
    # pastes an LLM-staged 9-section response at the Summary prompt,
    # the parsed payload can override downstream resolvers' flag
    # values (git_url, registered, registrar, growth_hypothesis). The
    # extras dict collects those overrides; the orchestrator applies
    # them below before the corresponding resolver runs.
    paste_extras: dict = {}
    operator_inputs = _collect_operator_inputs(
        summary=summary, audience=audience, icp=icp,
        goal=goal, content_strategy=content_strategy,
        non_interactive=non_interactive,
        extras_out=paste_extras,
    )
    # If smart-paste captured a Lovable repo URL, override the empty
    # value `_resolve_git_url` returned earlier (operator likely hit
    # Enter to skip because they were planning to paste it as part of
    # the multi-section response).
    if not git_url and paste_extras.get("git_url"):
        git_url = paste_extras["git_url"]
    if paste_extras.get("registered") is not None and registered is None:
        registered = paste_extras["registered"]
    if paste_extras.get("registrar") and not registrar:
        registrar = paste_extras["registrar"]
    if paste_extras.get("growth_hypothesis") and not growth_hypothesis:
        growth_hypothesis = paste_extras["growth_hypothesis"]
    # Resolve v9.C inputs BEFORE running bootstrap so a failed scaffold
    # doesn't waste the operator's prompt answers. (The inventory write
    # itself happens AFTER bootstrap succeeds.)
    inventory_decision = _resolve_inventory_inputs(
        domain=domain, registered=registered, registrar=registrar,
        non_interactive=non_interactive,
    )
    # v9.D — growth hypothesis. Same flag-or-prompt pattern; empty
    # value renders the pre-v9.D "site scaffolded; growth log started"
    # docs/growth.md.
    growth_hypothesis_resolved = _resolve_growth_hypothesis(
        flag_value=growth_hypothesis, non_interactive=non_interactive,
    )

    try:
        result = run_bootstrap(
            domain=domain,
            stack=stack,
            from_genai=from_genai,
            git_url=git_url or None,
            with_ingester=with_ingester,
            topic=topic,
            operator_inputs=operator_inputs,
            growth_hypothesis=growth_hypothesis_resolved,
            platform=platform or None,
            translation_budget_usd=budget_usd if budget_usd > 0.0 else None,
            translate_now=translate_now,
        )
    except BootstrapError as e:
        console.print(f"[red]bootstrap failed:[/] {e}")
        console.print(
            "[dim]Project dir cleaned up (v15.K rollback). Re-run when "
            "ready.[/]"
        )
        raise typer.Exit(2)
    except StackTranslationError as e:
        console.print(f"[red]bootstrap failed — stack translation:[/] {e}")
        console.print(
            "[dim]Project dir cleaned up (v15.K rollback). Try a higher "
            "budget with `--budget 5.0`, or fix the source repo.[/]"
        )
        raise typer.Exit(3)

    # v9.C — append portfolio.json row when applicable.
    _apply_inventory_decision(domain, inventory_decision)

    _render_bootstrap_summary(result, domain, topic=topic)

    # v15.M — surface translation-pending hint if the deferred-translation
    # marker is present (bootstrap ran with --git-url + non-Astro stack
    # but didn't translate synchronously).
    from .data import ROOT as _DATA_ROOT
    marker = _DATA_ROOT.parent / domain / ".lamill-translation-pending"
    if marker.exists():
        console.print()
        console.print(
            "[yellow]Translation deferred (v15.M).[/] "
            f"[dim]Run [bold]lamill project translate {domain}[/bold] when "
            "ready to port the Lovable UI from `genai/` into the Astro "
            "scaffold (default budget $5.00, timeout 30min — both "
            "configurable via flags).[/]"
        )


# v9.B — bootstrap interactive prompts for the 5 operator-input
# AI_AGENTS sections. The canonical schema (see
# portfolio.canonical_sections) is the source of truth for which
# sections are operator-input; this helper iterates that list so
# adding a new operator section in v9.E doesn't require touching
# CLI code.


# Bug-fix 2026-05-20 — multi-line prompt helper. `typer.prompt` (via
# Click) reads to the first newline only, so multi-paragraph pastes
# overflow into the shell and try to run as commands. This helper
# reads stdin until two consecutive blank lines (Enter twice) OR an
# EOF (Ctrl-D). Used for paragraph-style operator-input prompts in
# `new bootstrap`: Summary, ICP, Content strategy, Growth hypothesis.

def _prompt_multiline(label: str, *, hint: str | None = None) -> str:
    """Read multi-line input until two blank lines or EOF.

    Behavior:
      - Prints `label` (rich markup OK) and the optional `hint`.
      - Reads `sys.stdin` line-by-line until either:
          * Two consecutive blank lines (operator hit Enter twice), OR
          * EOF (Ctrl-D / closed stream)
      - Strips trailing blank lines; returns the joined text. Empty
        input (immediate Enter-Enter or EOF) → "".

    Single-line answers still work: type the line, hit Enter, hit
    Enter again to terminate.
    """
    import sys

    if label:
        console.print(label)
    if hint:
        console.print(f"  [dim]{hint}[/]")

    lines: list[str] = []
    blank_run = 0
    while True:
        try:
            line = sys.stdin.readline()
        except (KeyboardInterrupt, EOFError):
            break
        if line == "":   # EOF (Ctrl-D)
            break
        # `readline` keeps the trailing newline; strip it but only
        # the trailing newline, not internal whitespace.
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped == "":
            blank_run += 1
            if blank_run >= 2:
                break
            lines.append("")
            continue
        blank_run = 0
        lines.append(stripped)

    # Drop trailing blank lines from the captured buffer.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


# Bug-fix 2026-05-20 — Lovable GitHub repo URL prompt. The operator's
# common workflow is: design UI in Lovable.dev → Lovable exports a
# GitHub repo → bootstrap clones that repo as a new sites/<domain>/
# project. The `--git-url` flag already wires this through the
# `--from-genai` path; this helper adds the interactive surface.

def _resolve_git_url(*, flag_value: str, non_interactive: bool,
                     max_attempts: int = 3) -> str:
    """Return the Lovable-repo URL the operator wants to clone (or "").

    Resolution order:
      1. `--git-url <url>` flag → returned verbatim (no prompt).
      2. `--non-interactive` → "" (blank-scaffold path).
      3. Else: interactive prompt. Empty input → "" (blank-scaffold).
         Non-empty input must start with `http://`, `https://`, or
         `git@`; otherwise re-prompt up to `max_attempts` times before
         warning-and-skipping.
    """
    if flag_value:
        return flag_value
    if non_interactive:
        return ""

    console.print(
        "\n[bold]Lovable GitHub repo URL[/]"
        " [dim](Enter to skip and scaffold blank)[/]"
    )
    for _ in range(max_attempts):
        raw = typer.prompt(
            "  >", default="", show_default=False,
        ).strip()
        if not raw:
            return ""
        if re.match(r"^https?://", raw) or re.match(r"^git@", raw):
            return raw
        console.print(
            "  [yellow]Expected an https:// URL or a git@host:path "
            "shape; try again or hit Enter to skip.[/]"
        )
    console.print(
        "  [yellow]3 invalid attempts; skipping — bootstrap will "
        "scaffold a blank project.[/]"
    )
    return ""


# Bug-fix 2026-05-20 — pre-flight banner. Print the full list of
# prompts BEFORE the first prompt fires so the operator can prep
# paragraph-length answers or hit Enter to skip. Skipped when running
# non-interactively or when every per-section flag is supplied (no
# prompts would fire anyway).

def _render_bootstrap_preflight(
    *, domain: str, non_interactive: bool, git_url: str,
    summary: str, audience: str, icp: str, goal: str,
    content_strategy: str, growth_hypothesis: str,
    registered: bool | None, registrar: str,
) -> None:
    """Print a single banner listing all 9 upcoming prompts.

    No-op when:
      - `non_interactive=True` (no prompts fire)
      - Every section already has a flag value AND `git_url` is set
        AND `registered`+`registrar` are set (no prompts fire)
    """
    if non_interactive:
        return
    all_supplied = (
        bool(git_url)
        and bool(summary.strip()) and bool(audience.strip())
        and bool(icp.strip()) and bool(goal.strip())
        and bool(content_strategy.strip())
        and bool(growth_hypothesis.strip())
        and registered is not None and bool(registrar)
    )
    if all_supplied:
        return

    console.print(
        f"\n[bold]About to bootstrap [cyan]{domain}[/].[/] "
        "You'll be asked 9 questions:\n"
    )
    rows = [
        ("1.", "Lovable GitHub repo URL", "Enter to skip; scaffolds blank"),
        ("2.", "Summary", "one paragraph"),
        ("3.", "Audience", "one sentence"),
        ("4.", "ICP", "specific ideal customer"),
        ("5.", "Goals", "1-2 sentences"),
        ("6.", "Content strategy", "page types · topics · format mix"),
        ("7.", "Domain registered?", "Y/n"),
        ("8.", "Registrar", "porkbun / godaddy / namecheap / other"),
        ("9.", "Growth hypothesis", "one paragraph"),
    ]
    for num, label, hint in rows:
        console.print(
            f"  {num} [bold]{label:<32}[/] [dim]({hint})[/]"
        )
    console.print(
        "\n  [dim]Skip individual prompts with --<flag>; "
        "skip all with --non-interactive.[/]"
    )
    console.print(
        "  [dim]Paragraph prompts (1, 2, 4, 6, 9): "
        "finish with Enter twice or Ctrl-D.[/]"
    )


# v9.D — growth-hypothesis prompt. Single prompt for one paragraph
# that seeds docs/growth.md's first dated entry.


def _resolve_growth_hypothesis(*, flag_value: str,
                               non_interactive: bool) -> str:
    """Return the operator's growth hypothesis as a single string
    (possibly empty).

    Resolution order:
      1. `--growth-hypothesis "X"` flag (whitespace stripped) → no
         prompt.
      2. `--non-interactive` → empty (docs/growth.md gets the
         pre-v9.D default first entry).
      3. Else: interactive multi-line prompt. Empty answer → empty
         result.

    Uses the multi-line prompt helper (bug-fix 2026-05-20) so
    multi-paragraph pastes don't overflow into the shell.
    """
    if flag_value.strip():
        return flag_value.strip()
    if non_interactive:
        return ""
    return _prompt_multiline(
        "\n[bold]Growth hypothesis[/]"
        " [dim](v9.D — seeds docs/growth.md's first dated entry)[/]",
        hint=(
            "One paragraph: what's your bet for how this site reaches "
            "its audience? Press Enter twice (or Ctrl-D) when done. "
            "Hit Enter twice immediately to skip — growth.md will get "
            "the default \"site scaffolded\" first entry."
        ),
    )


# v9.C — domain-registration prompt + portfolio.json auto-update.
# Shape: `_resolve_inventory_inputs` gathers the operator's intent
# (registered?, registrar?) ONCE — before the bootstrap call —
# returning a dict the post-bootstrap code consumes. Failures in
# `run_bootstrap` don't waste the prompt answers; re-running with
# the same flags is idempotent.

_REGISTRARS = ("porkbun", "godaddy", "namecheap", "other")


def _resolve_inventory_inputs(*, domain: str, registered: bool | None,
                              registrar: str, non_interactive: bool) -> dict:
    """Determine whether to update portfolio.json + with what fields.

    Returns a dict with keys:
      action:    "append" → call append_domain_row
                 "skip"   → no inventory write (operator opted out or
                            non-interactive without explicit flag)
                 "exists" → predetermined: row already in portfolio.json
                            (idempotent re-run); informational only
      registered: bool (when action != "skip")
      registrar:  str (when action != "skip")

    Decision rules:
      - If `name` already in portfolio.json → action="exists", no prompts.
      - If `registered` flag set + `registrar` flag set → action="append".
      - If `non_interactive` AND no `registered` flag → action="skip"
        (no inventory write; operator runs cleanup later).
      - Else interactive: prompt Y/n for registration + select registrar.
    """
    from .data import PORTFOLIO_JSON
    import json as _json

    # Existing-row short-circuit: skip prompts + inventory write entirely.
    if PORTFOLIO_JSON.exists():
        try:
            payload = _json.loads(PORTFOLIO_JSON.read_text())
            existing = {row.get("name", "").lower()
                        for row in payload.get("domains", [])}
        except (OSError, _json.JSONDecodeError):
            existing = set()
        if domain.lower() in existing:
            return {"action": "exists"}

    # Both flags supplied → no prompts.
    if registered is not None and registrar:
        if registrar not in _REGISTRARS:
            console.print(
                f"[red]--registrar must be one of {', '.join(_REGISTRARS)}; "
                f"got {registrar!r}.[/]"
            )
            raise typer.Exit(2)
        return {"action": "append", "registered": registered,
                "registrar": registrar}

    if non_interactive:
        # No explicit flag in batch mode → skip inventory write.
        # Operator can update later via fleet cleanup or a direct edit.
        if registered is None:
            return {"action": "skip"}
        # Flag set in non-interactive mode but registrar omitted →
        # default to "other" so we don't lose the registration signal.
        return {"action": "append", "registered": registered,
                "registrar": registrar or "other"}

    # Interactive path. Prompt for registration status, then registrar.
    console.print(
        f"\n[bold]Domain inventory ([cyan]{domain}[/])[/]"
        " [dim](v9.C — auto-updates portfolio.json so "
        "`project check {domain}` resolves)[/]"
    )
    if registered is None:
        answer = typer.prompt(
            "  Is the domain registered? [Y/n]",
            default="Y", show_default=False,
        ).strip().lower()
        registered = answer not in ("n", "no")
    if not registrar:
        # Bug-fix 2026-05-20 — registrar prompt was accepting free
        # text; tighten to the canonical set with up to 3 retries
        # then fall back to "other". Case-insensitive + whitespace-
        # stripped.
        registrar = _prompt_registrar()

    return {"action": "append", "registered": registered,
            "registrar": registrar}


def _prompt_registrar(max_attempts: int = 3) -> str:
    """Interactive registrar prompt with retry-on-invalid.

    Accepts (case-insensitive, whitespace-stripped): porkbun / godaddy
    / namecheap / other. After `max_attempts` invalid responses, falls
    back to "other" rather than raising — keeps the bootstrap flow
    moving forward.
    """
    for _ in range(max_attempts):
        raw = typer.prompt(
            f"  Registrar [{'/'.join(_REGISTRARS)}]",
            default="porkbun", show_default=False,
        )
        candidate = raw.strip().lower()
        if candidate in _REGISTRARS:
            return candidate
        console.print(
            f"  [yellow]Accepted: {', '.join(_REGISTRARS)}[/]"
        )
    console.print(
        "  [dim]3 invalid attempts; defaulting to 'other'.[/]"
    )
    return "other"


def _apply_inventory_decision(domain: str, decision: dict) -> None:
    """Execute the resolved inventory decision. Logs the outcome so
    the operator sees what happened in the summary."""
    action = decision.get("action")
    if action == "skip":
        # Silent — non-interactive runs deliberately skipped this.
        return
    if action == "exists":
        console.print(
            f"[dim]  portfolio.json: row for {domain} already present; "
            f"no update.[/]"
        )
        return
    if action == "append":
        from .data import append_domain_row

        result = append_domain_row(
            name=domain,
            registrar=decision["registrar"],
            registered=decision["registered"],
        )
        status = "Active" if decision["registered"] else "Pending"
        if result == "added":
            console.print(
                f"[green]  ✓ portfolio.json: appended {domain} "
                f"(registrar={decision['registrar']}, status={status})[/]"
            )
        elif result == "exists":
            # Race condition (unlikely but defensive) — pre-check
            # didn't see the row but append did. Still informational.
            console.print(
                f"[dim]  portfolio.json: row for {domain} already present; "
                f"no update.[/]"
            )
        elif result == "no-file":
            console.print(
                f"[yellow]  ⚠ portfolio.json missing — run "
                f"`lamill fleet sync` to bootstrap the inventory, "
                f"then re-run this command (or add the row manually).[/]"
            )


def _collect_operator_inputs(*,
                             summary: str, audience: str, icp: str,
                             goal: str, content_strategy: str,
                             non_interactive: bool,
                             extras_out: dict | None = None,
                             ) -> dict[str, str]:
    """Build the {heading → content} dict the bootstrap renderer
    consumes for operator-input sections.

    Flag values take precedence. Sections without a flag value get
    interactively prompted unless `non_interactive=True`, in which
    case they're left empty and the renderer drops in `(to be filled
    in)` placeholders.

    Bug-fix 2026-05-20 — smart multi-section paste. The first
    paragraph-style prompt (typically Summary) inspects the captured
    text via `parse_multisection_paste()`. When the operator pasted
    an LLM-staged 9-section response, the paste is split into
    canonical sections and (on operator confirm) the remaining
    AI_AGENTS prompts are auto-filled. Cross-section overrides
    (git_url / growth_hypothesis / registered / registrar) land in
    `extras_out` so the orchestrator can forward them to the
    downstream resolvers (`_resolve_git_url`, `_resolve_inventory_inputs`,
    `_resolve_growth_hypothesis`) without re-prompting.

    Returns a complete dict (one key per operator-input section,
    even if the value is empty) so the renderer doesn't need to
    guess defaults.
    """
    from .canonical_sections import operator_sections
    from .bootstrap_paste import (
        CANONICAL_LABELS,
        first_nonblank_line,
        looks_like_repo_url,
        normalize_registrar,
        normalize_yes_no,
        parse_multisection_paste,
        preview_snippet,
    )

    # Map CLI-flag value → canonical heading. Mirrors the order in
    # canonical_sections.AI_AGENTS_SECTIONS; the user-facing flag
    # names are flat (no `--` prefix here; typer adds those).
    flag_values: dict[str, str] = {
        "Summary": summary,
        "Audience": audience,
        "ICP": icp,
        "Goals": goal,
        "Content strategy": content_strategy,
    }

    inputs: dict[str, str] = {}
    pending_for_prompt: list = []
    for spec in operator_sections():
        v = flag_values.get(spec.heading, "").strip()
        if v:
            inputs[spec.heading] = v
        elif non_interactive:
            inputs[spec.heading] = ""   # placeholder will render
        else:
            pending_for_prompt.append(spec)
            inputs[spec.heading] = ""   # provisional; overwritten if prompted

    # Map canonical-paste keys → AI_AGENTS heading for operator
    # sections so a parsed paste can be sluiced into `inputs`.
    paste_key_to_heading: dict[str, str] = {
        "summary": "Summary",
        "audience": "Audience",
        "icp": "ICP",
        "goals": "Goals",
        "content_strategy": "Content strategy",
    }
    # Sections that render best on one line (single-line in AI_AGENTS).
    single_line_headings = {"Audience", "Goals"}

    if pending_for_prompt:
        console.print(
            "\n[bold]Operator content for AI_AGENTS.md[/]"
            " [dim](press Enter to skip; "
            "section will render `(to be filled in)`)[/]"
        )
        # Bug-fix 2026-05-20 — paragraph-style sections (Summary, ICP,
        # Content strategy) use the multi-line prompt helper so
        # multi-paragraph pastes don't overflow into the shell. The
        # one-line sections (Audience, Goals) stay on `typer.prompt`.
        multiline_sections = {"Summary", "ICP", "Content strategy"}
        smart_paste_attempted = False
        for spec in pending_for_prompt:
            # If smart-paste already filled this section, skip the prompt.
            if inputs.get(spec.heading):
                continue
            if spec.heading in multiline_sections:
                # Bug-fix 2026-05-20 — smart-paste hint on the first
                # paragraph prompt only. Once we've checked one
                # multiline answer for paste-shape, don't check again
                # (otherwise the second Summary-ish prompt would
                # double-prompt on a single section's content).
                hint = (
                    "Hit Enter twice when done, or Ctrl-D. "
                    "Enter twice immediately to skip."
                )
                if not smart_paste_attempted:
                    hint = (
                        "Hit Enter twice when done, or Ctrl-D. "
                        "Enter twice immediately to skip. "
                        "(Paste a multi-section response here to fill "
                        "all prompts at once.)"
                    )
                answer = _prompt_multiline(
                    f"\n  [cyan]{spec.heading}[/] — [dim]{spec.description}[/]",
                    hint=hint,
                ).strip()
                # Smart-paste detection runs on the FIRST paragraph
                # answer only. Subsequent paragraph prompts use plain
                # capture.
                if not smart_paste_attempted:
                    smart_paste_attempted = True
                    parsed = parse_multisection_paste(answer)
                    if parsed is not None and _confirm_multisection_paste(
                        parsed, current_heading=spec.heading,
                    ):
                        _apply_multisection_paste(
                            parsed,
                            inputs=inputs,
                            extras_out=extras_out,
                            paste_key_to_heading=paste_key_to_heading,
                            single_line_headings=single_line_headings,
                            current_heading=spec.heading,
                        )
                        # Skip setting `inputs[spec.heading] = answer`
                        # below — the paste payload supplied the
                        # correct section content (or left it blank
                        # if the operator pasted the OTHER sections
                        # but no Summary).
                        continue
            else:
                console.print(
                    f"\n  [cyan]{spec.heading}[/] — [dim]{spec.description}[/]"
                )
                answer = typer.prompt(
                    "  >", default="", show_default=False,
                ).strip()
            if answer:
                inputs[spec.heading] = answer

    return inputs


def _confirm_multisection_paste(parsed: dict[str, str], *,
                                current_heading: str) -> bool:
    """Print the multi-section preview banner and prompt for confirmation.

    Bug-fix 2026-05-20 — when smart-paste detects a multi-section
    response at the Summary prompt, show the operator each detected
    section's name + a short snippet so they can verify the parse
    before auto-fill commits. Default Yes (Enter to accept).

    Returns True on Y / yes / empty (default); False on N / no.
    """
    from .bootstrap_paste import CANONICAL_LABELS, preview_snippet

    n = len(parsed)
    console.print(
        f"\n[bold]Detected a multi-section paste with {n} sections:[/]"
    )
    # Preserve insertion order so the preview matches the operator's
    # mental model of how their LLM laid out the response.
    for key, content in parsed.items():
        label = CANONICAL_LABELS.get(key, key)
        snippet = preview_snippet(content, limit=80)
        console.print(
            f"  [green]✓[/] [bold]{label:<22}[/] [dim]{snippet}[/]"
        )
    raw = typer.prompt(
        "\n  Auto-fill the remaining prompts from this paste? [Y/n]",
        default="Y", show_default=False,
    ).strip().lower()
    return raw not in ("n", "no")


def _apply_multisection_paste(parsed: dict[str, str], *,
                              inputs: dict[str, str],
                              extras_out: dict | None,
                              paste_key_to_heading: dict[str, str],
                              single_line_headings: set[str],
                              current_heading: str) -> None:
    """Sluice a parsed multi-section paste into the orchestrator state.

    Populates `inputs[]` for any matched AI_AGENTS heading and
    `extras_out[]` for cross-section overrides (git_url /
    growth_hypothesis / registered / registrar). Sections missing
    from the paste are left for the regular prompt flow."""
    from .bootstrap_paste import (
        CANONICAL_LABELS,
        first_nonblank_line,
        looks_like_repo_url,
        normalize_registrar,
        normalize_yes_no,
        preview_snippet,
    )

    valid_registrars = _REGISTRARS  # ("porkbun", "godaddy", "namecheap", "other")
    filled: list[tuple[str, str]] = []

    for key, content in parsed.items():
        heading = paste_key_to_heading.get(key)
        if heading is not None:
            value = content.strip()
            if heading in single_line_headings:
                value = first_nonblank_line(value)
            if value:
                inputs[heading] = value
                filled.append((CANONICAL_LABELS.get(key, heading), value))
            continue

        # Cross-section overrides — only populated when extras_out is
        # supplied (the orchestrator path). Stand-alone callers that
        # don't pass extras_out (e.g. unit tests that don't care)
        # silently ignore these.
        if extras_out is None:
            continue

        if key == "growth_hypothesis":
            value = content.strip()
            if value:
                extras_out["growth_hypothesis"] = value
                filled.append(("Growth hypothesis", preview_snippet(value)))
        elif key == "domain_registered":
            parsed_bool = normalize_yes_no(content)
            if parsed_bool is not None:
                extras_out["registered"] = parsed_bool
                filled.append(
                    ("Domain registered?",
                     "yes" if parsed_bool else "no"),
                )
        elif key == "registrar":
            value = normalize_registrar(content, valid_registrars)
            extras_out["registrar"] = value
            filled.append(("Registrar", value))
        elif key == "lovable_repo":
            value = content.strip()
            if value and looks_like_repo_url(value):
                extras_out["git_url"] = value
                filled.append(("Lovable GitHub repo URL", value))
            elif value:
                # Non-URL-shaped — skip rather than crashing the
                # downstream `_resolve_git_url` validator.
                console.print(
                    f"  [yellow]Skipping Lovable repo value "
                    f"(doesn't look like a URL): {value!r}[/]"
                )

    if filled:
        console.print("\n[bold]Auto-filled from paste:[/]")
        for label, value in filled:
            console.print(
                f"  [green]✓[/] [bold]{label:<22}[/] "
                f"[dim]{preview_snippet(value)}[/]"
            )


def _render_bootstrap_summary(result, domain: str, *, topic: str = "") -> None:
    """Post-bootstrap report: header, file inventory, tree view, conformance
    pass/fail, predicted live URL, grouped next-step commands.

    When `topic` is non-empty, a one-line `Topic:` header is printed
    first — same operator-facing affordance as `new validate` /
    `new domain`. Empty topic omits the line.
    """
    if topic:
        console.print(f"[bold]Topic:[/] [cyan]{topic}[/]\n")
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
    console.print(f"    lamill fleet domains                       [dim]# refresh check snapshot[/]")
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


@new_app.command("validate")
def new_validate(
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
    verify: bool = typer.Option(
        False, "--verify",
        help="Run adversarial audit pass against the primary verdict "
             "(uses OpenAI gpt-4o by default; override via --audit-model). "
             "Adds ~$0.01-0.02 per run. Surfaces REVIEW_REQUIRED when "
             "the two models disagree.",
    ),
    no_verify: bool = typer.Option(
        False, "--no-verify",
        help="Disable audit pass for this run, overriding the operator "
             "profile's `verify_by_default` flag in `lamill.toml [operator]`.",
    ),
    audit_model: str = typer.Option(
        "gpt-4o", "--audit-model",
        help="OpenAI model id for the audit pass (only used with --verify). "
             "Must resolve to a different model than the primary — same-model "
             "audit defeats the model-family-diversity goal.",
    ),
    invalidate: str = typer.Option(
        "none", "--invalidate",
        help="Granular cache invalidation on a cached cluster snapshot: "
             "'interpretive' re-runs the primary pass, 'audit' re-runs the "
             "audit pass, 'all' re-runs both. Default 'none' (cached passes "
             "are reused). Use --no-cache to bypass the SerpAPI cluster "
             "cache entirely.",
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
            "  2. Skip SerpAPI: [cyan]lamill new validate <topic> --synthesis-only[/]\n"
            "     (LLM-only synthesis; heuristic verdicts, not real SERP data)"
        )
        raise typer.Exit(2)

    # Pre-flight: soft-warn at 80% quota usage; strong-warn at 95%.
    # If the local ledger says we're exhausted but SerpAPI might have
    # headroom (the ledger can drift — it's a write-only side-effect
    # counter, not authoritative), attempt a one-shot sync against
    # SerpAPI's /account endpoint before refusing.
    from .serpapi_quota import (
        is_quota_available, quota_pct_used, read_quota,
        should_warn, should_warn_strongly,
        sync_with_serpapi, QuotaSyncError,
    )
    if not is_quota_available():
        console.print(
            "[yellow]⚠  Local SerpAPI quota ledger reports exhausted. "
            "Syncing with SerpAPI for ground truth...[/]"
        )
        try:
            synced = sync_with_serpapi(serpapi_key)
            console.print(
                f"[green]  ✓ Synced: {synced['queries_used']}/{synced['limit']} "
                f"this UTC month (local ledger had drifted).[/]"
            )
        except QuotaSyncError as e:
            console.print(f"[red]  ✗ Sync failed: {e}[/]")
            # Don't refuse the run here — the existing QuotaExhausted
            # in fetch_serp will still fire if real-and-local agree.
    if should_warn():
        q = read_quota()
        console.print(
            f"[yellow]⚠  SerpAPI quota: {q['queries_used']}/{q['limit']} this UTC month "
            f"({int(quota_pct_used()*100)}%). Consider `--synthesis-only` for "
            f"ideation runs to stretch the cap.[/]"
        )
        if should_warn_strongly():
            # At 95%+ a single research run can blow through the
            # remaining quota and silently fall back to synthesis,
            # which is dangerous for competitive verdicts.
            console.print(
                "[red]⚠  Consider waiting for quota reset before running "
                "competitive research — at this usage level a single run "
                "can exhaust the quota and force the synthesis fallback "
                "(verdicts will be blocked).[/]"
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

    # v8.I — primary interpretive pass.
    # Runs only on a fresh-gates pass (or when the cached snapshot
    # lacks a primary verdict). Skips on cache hits that already
    # carry a `primary_verdict` — the operator paid the ~5-15s on the
    # previous run, no need to re-pay. Failure is non-fatal: the
    # mechanical verdict above is still useful on its own.
    # v12.F — granular cache invalidation. `--invalidate` strings
    # opt individual passes out of the cache short-circuit without
    # bypassing the SerpAPI cluster cache (that's still `--no-cache`).
    # `--invalidate=all` invalidates both passes; this is the natural
    # "re-run the LLM passes against the same cached SERP data"
    # workflow when re-tuning prompts or comparing models.
    invalidate_normalized = (invalidate or "none").strip().lower()
    invalidate_interpretive = invalidate_normalized in ("interpretive", "all")
    invalidate_audit        = invalidate_normalized in ("audit", "all")

    # v12.F — `verify_by_default` operator-profile flag. Single load
    # here used for the audit-gate decision; `_run_audit_pass_and_
    # reconcile` reloads inside itself for the audit payload. Two
    # cheap TOML reads beat threading the profile through a dozen
    # call sites.
    from .operator_profile import load_operator_profile as _load_op_profile
    op_profile = _load_op_profile()
    effective_verify = (
        (verify or op_profile.verify_by_default) and not no_verify
    )

    cache_has_primary = (
        payload.get("from_cache") and payload.get("primary_verdict")
        and not invalidate_interpretive
    )
    if not cache_has_primary:
        _run_primary_interpretive_pass(topic, payload, console=console)

    # v12.E — adversarial audit pass + reconciliation. Default-off
    # (operator opts in via --verify or `verify_by_default = true`).
    # Default model gpt-4o provides model-family diversity from the
    # Claude-CLI primary; --audit-model overrides. Persists into the
    # cluster snapshot so cache hits skip the audit on subsequent
    # runs unless `--invalidate audit` (or `=all`) is set.
    if effective_verify and "primary_verdict" in payload:
        # Same-model rejection. The audit's value is model-family
        # diversity; using the primary's model collapses that into
        # "ask twice and hope for variance," defeating the point of
        # the verdict-gate. Fail loud rather than silently produce a
        # weaker signal.
        primary_model = payload.get("primary_pass_meta", {}).get(
            "model_id", "claude-cli",
        )
        if audit_model == primary_model:
            console.print(
                f"[red]--audit-model {audit_model!r} matches the primary "
                f"model id. The audit pass requires a different model "
                f"family to be useful; pick another with --audit-model.[/]"
            )
            raise typer.Exit(2)

        cache_has_audit = (
            payload.get("from_cache") and payload.get("audit")
            and not invalidate_audit
        )
        if not cache_has_audit:
            _run_audit_pass_and_reconcile(
                topic, payload,
                audit_model=audit_model, console=console,
            )

    if json_out:
        _render_serp_json(payload)
    else:
        _render_research_v2_full(payload, console)


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


def _confidence_color(confidence: str) -> str:
    """HIGH → green, MEDIUM → yellow, LOW → red. Used by the
    interpretive-verdict header line + the rich render."""
    return {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(
        confidence, "white",
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


_VERDICT_COLOR = {
    "GO": "green",
    "NICHE-DOWN": "yellow",
    "NO-GO": "red",
    "REVIEW_REQUIRED": "magenta",   # v12.E — reconciliation's fourth verdict token
}


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


# ---------- v13.B — per-project GSC diagnostics ----------


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
            if errs:
                tail_bits.append(f"{errs} error(s)")
            if warns:
                tail_bits.append(f"{warns} warning(s)")
            if last_dl:
                tail_bits.append(f"fetched {_human_age_from_iso(last_dl)}")
            if summary:
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


def _run_project_seo_diagnostics(domain: str, *, top_n: int,
                                 refresh: bool, console) -> None:
    """v13.B — load (or fetch) per-project GSC diagnostics and
    render the block. Cache-aware: reads
    `data/gsc/<domain>/<UTC-today>.json` if fresh and `--refresh`
    wasn't set; otherwise calls `build_diagnostics()` and writes
    a new snapshot.

    Non-fatal on failure — the v5.D 1-row aggregate above this
    block is still useful on its own; the diagnostics being
    unavailable shouldn't crash the operator's workflow.
    """
    from .gsc_detail_cache import (
        is_stale, latest_snapshot, load_snapshot, save_snapshot,
    )
    from .project_seo_diagnostics import build_diagnostics

    # Cache lookup — when fresh and not --refresh, render from
    # cache and skip the GSC roundtrips.
    if not refresh:
        latest = latest_snapshot(domain)
        if latest is not None and not is_stale(latest):
            try:
                cached = load_snapshot(latest)
                console.print(
                    f"  [dim]GSC diagnostics: cached {latest.name} "
                    f"(use --refresh to re-fetch)[/]"
                )
                _render_project_seo_diagnostics(cached, console)
                return
            except (OSError, ValueError) as e:
                console.print(
                    f"  [dim]warn: could not load cached diagnostics ({e}); "
                    f"re-fetching[/]"
                )

    console.print(
        f"  [cyan]Fetching GSC diagnostics ({domain})...[/] "
        f"[dim](URL Inspection × top {top_n})[/]"
    )
    try:
        diag = build_diagnostics(domain, top_n=top_n)
    except Exception as e:    # noqa: BLE001 — GSC / OAuth errors variety
        console.print(
            f"  [yellow]✗ Diagnostics skipped: {type(e).__name__}: {e}[/]"
        )
        return

    # Persist for cache reuse — convert dataclass to a plain dict.
    from dataclasses import asdict
    try:
        save_snapshot(domain, asdict(diag))
    except OSError as e:
        console.print(
            f"  [dim]warn: could not persist diagnostics snapshot: {e}[/]"
        )

    _render_project_seo_diagnostics(diag, console)


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


@new_app.command("deploy")
def new_deploy(
    domain: str = typer.Argument(..., help="Domain whose sites/<domain>/ project to deploy (e.g. kwizicle.com)"),
    gh_owner: str = typer.Option("", "--gh-owner", help="GitHub username/org for the new repo (auto-detected via GITHUB_TOKEN or `gh api user` if empty)"),
    private: bool = typer.Option(False, "--private", help="Create the GitHub repo as private (default: public)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen; don't actually call APIs or write anything"),
    yes: bool = typer.Option(False, "--yes", help="Auto-confirm interactive prompts (e.g. registrar NS update). v15.I — non-interactive mode."),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip the local-config sanity check (cf-pages/cf-workers only)"),
    skip_repo: bool = typer.Option(False, "--skip-repo", help="Skip GitHub repo creation (cf-pages/cf-workers only)"),
    skip_pages: bool = typer.Option(False, "--skip-pages", help="Skip Cloudflare Pages project creation (cf-pages/cf-workers only)"),
    apply: bool = typer.Option(False, "--apply", help="Required to actually push files for hostgator/custom (dry-run default per ADR-0011)."),
) -> None:
    """Deploy a sites/<domain>/ project. Dispatches by lamill.toml platform.

    v15.I (ADR-0012): `cf-pages` and `cf-workers` both route through the
    unified Pages-API git-integrated pipeline. No `wrangler deploy` calls.
    Vercel + HostGator + custom paths unchanged.
    """
    from .data import ROOT as DATA_ROOT
    from . import lamill_toml as _lt

    project_dir = DATA_ROOT.parent / domain
    if not project_dir.exists():
        console.print(f"[red]Project dir not found:[/] {project_dir}")
        console.print("[dim]Run `lamill new bootstrap <domain>` first, or check the domain spelling.[/]")
        raise typer.Exit(1)

    try:
        decl = _lt.load(project_dir)
    except _lt.ParseError as e:
        console.print(f"[red]lamill.toml invalid:[/] {e}")
        raise typer.Exit(2)

    platform = decl.deploy.platform if decl else "cf-workers"
    if decl is None:
        console.print(
            "[dim]No lamill.toml found — assuming platform=cf-workers "
            "(v15.I default; was cf-pages pre-v15.I). Run `lamill "
            f"settings deploy set {domain} <platform>` to declare "
            "explicitly.[/]"
        )

    if platform == "none":
        console.print(
            f"[red]Platform is `none` for {domain}.[/]\n"
            f"[dim]Run `lamill settings deploy set {domain} <platform>` "
            "to choose a deploy target first.[/]"
        )
        raise typer.Exit(2)

    # v15.I — unified Pages-API path for cf-pages AND cf-workers.
    if platform in ("cf-pages", "cf-workers"):
        _deploy_cf_unified(
            domain=domain,
            project_dir=project_dir,
            platform=platform,
            gh_owner=gh_owner,
            private=private,
            dry_run=dry_run,
            yes=yes,
            skip_verify=skip_verify,
            skip_repo=skip_repo,
            skip_pages=skip_pages,
        )
        return

    if platform == "vercel":
        _deploy_vercel(domain=domain, project_dir=project_dir, dry_run=dry_run)
        return

    if platform in ("hostgator", "custom"):
        _deploy_hostgator_v11n(
            domain=domain,
            project_dir=project_dir,
            lamill_toml=decl,
            apply=apply,
        )
        return

    # netlify / github-pages — declared in PLATFORM_VALUES but not yet
    # implemented end-to-end. Surface a clear "not implemented" rather
    # than silently routing into cf-pages or shelling something wrong.
    console.print(
        f"[yellow]platform={platform!r} is declared but `new deploy` "
        f"doesn't implement it yet.[/]\n"
        f"[dim]Tracked for a future v11.X. For now, deploy {domain} "
        "manually via the platform's own tooling.[/]"
    )
    raise typer.Exit(2)


# ============================================================================
# v15.I — `_deploy_cf_unified()` orchestrator (ADR-0012)
# ============================================================================
#
# 8 idempotent steps. Replaces both `_deploy_cf_pages_v3c()` and
# `_deploy_cf_workers()` for `platform ∈ {cf-pages, cf-workers}`.
# Pages-API + git-integration handles both unified.


def _deploy_cf_unified(
    *,
    domain: str,
    project_dir,
    platform: str,
    gh_owner: str,
    private: bool,
    dry_run: bool,
    yes: bool,
    skip_verify: bool,
    skip_repo: bool,
    skip_pages: bool,
) -> None:
    """v15.I — git-integrated CF deploy pipeline.

    Pipeline (each step idempotent):
      1. Pre-flight (creds + project-dir clean + slug resolution)
      2. GH repo: get-or-create via REST API (or `gh` CLI fallback)
      3. Git push: ensure origin remote + push main if local ahead
      4. CF zone: resolve or create; surface NS records
      5. Registrar NS: Porkbun auto-push if mismatch (other registrars
         warn with target NS list)
      6. CF Pages project: get-or-create with git source
      7. CF Custom Domain: GET-then-POST attach if not in domains[]
      8. Build poll + live probe

    Each step prints `✓ exists, skipping` / `✓ created` / `↷ skipped: ...`
    so the operator can see progress and what state pre-existed.
    """
    from pathlib import Path

    from . import apikeys, cloudflare
    from .bootstrap import _project_name
    from .data import PORTFOLIO_JSON
    from .gh_repo import (
        GhAuthError, GhError, auth_path,
        detect_gh_owner, ensure_origin_remote,
        ensure_repo, push_to_origin,
    )
    from .porkbun_dns import (
        PorkbunDnsError, get_porkbun_ns, ns_matches, update_porkbun_ns,
    )

    slug = _project_name(domain)
    console.print(
        f"[bold]v15.I — Deploy[/] [cyan]{domain}[/] "
        f"[dim](platform={platform} · git-integrated CF Pages-API · "
        f"slug={slug} · dry-run={dry_run})[/]"
    )

    # --- Step 0: Pre-flight --------------------------------------------------
    console.print("\n[bold]0. Pre-flight[/]")

    cf_token = (apikeys.get_key("CF_API_TOKEN") or "").strip()
    cf_account = (apikeys.get_key("CF_ACCOUNT_ID") or "").strip()
    if not cf_token or not cf_account:
        console.print(
            "  [red]✗[/] CF_API_TOKEN + CF_ACCOUNT_ID required.\n"
            "  [dim]Set via `lamill settings apikeys set <KEY> <value>`.[/]"
        )
        raise typer.Exit(2)
    console.print("  [green]✓[/] CF creds present")

    # v15.N — pre-flight CF token scope probe. Catches under-scoped
    # tokens (e.g. missing `Cloudflare Pages:Edit`) BEFORE the
    # pipeline mutates GitHub state.
    scope_report = cloudflare.probe_token_scopes(account_id=cf_account)
    if not scope_report.ok:
        console.print(
            "  [red]✗[/] CF token scope insufficient. Missing:"
        )
        for m in scope_report.missing:
            console.print(f"    [red]·[/] {m}")
        console.print()
        for n in scope_report.notes:
            console.print(f"    [dim]{n}[/]")
        console.print(
            "\n  [dim]Edit your token at "
            "[bold]https://dash.cloudflare.com/profile/api-tokens[/bold] "
            "→ add the missing permissions → save (token value stays "
            "the same; permissions update). Then re-run.[/]"
        )
        raise typer.Exit(2)
    probe_summary = []
    if scope_report.pages_read_ok:
        probe_summary.append("Pages")
    if scope_report.zone_read_ok:
        probe_summary.append("Zone")
    if scope_report.account_settings_read_ok:
        probe_summary.append("Account")
    console.print(
        f"  [green]✓[/] CF token scope OK "
        f"[dim]({', '.join(probe_summary) or 'all probes passed'})[/]"
    )

    gh_auth = auth_path()
    if gh_auth == "none":
        console.print(
            "  [red]✗[/] Neither GITHUB_TOKEN nor `gh` CLI available.\n"
            "  [dim]Set GITHUB_TOKEN via `lamill settings apikeys set "
            "GITHUB_TOKEN <pat>`, or install gh + `gh auth login`.[/]"
        )
        raise typer.Exit(2)
    console.print(f"  [green]✓[/] GitHub auth via {gh_auth}")

    pb_key = (apikeys.get_key("PORKBUN_API_KEY") or "").strip()
    pb_secret = (apikeys.get_key("PORKBUN_SECRET_API_KEY") or "").strip()
    porkbun_creds = bool(pb_key and pb_secret)
    if porkbun_creds:
        console.print("  [green]✓[/] Porkbun creds present")
    else:
        console.print(
            "  [yellow]↷[/] Porkbun creds missing — NS updates will be "
            "warn-only (operator updates NS manually at registrar)"
        )

    # Resolve owner (token path or gh CLI).
    if not gh_owner:
        try:
            gh_owner = detect_gh_owner()
        except (GhAuthError, GhError) as e:
            console.print(f"  [red]✗[/] Could not resolve GitHub owner: {e}")
            raise typer.Exit(2)
    console.print(f"  [green]✓[/] GitHub owner: [cyan]{gh_owner}[/]")
    console.print(f"  [green]✓[/] CF project slug: [cyan]{slug}[/]")

    # v15.R — Porkbun per-domain API access pre-check. The account-
    # level API key works for /domain/listAll (v15.F refresh) but
    # each domain has a SEPARATE per-domain toggle. Catch this at
    # Step 0 so the operator isn't surprised mid-pipeline.
    if porkbun_creds and not dry_run:
        registrar_now = _lookup_registrar(domain) or ""
        if registrar_now.lower() == "porkbun":
            try:
                from .porkbun_dns import get_porkbun_ns, PorkbunDnsError
                get_porkbun_ns(domain, api_key=pb_key, secret=pb_secret)
            except PorkbunDnsError as e:
                if "API_ACCESS_DISABLED" in str(e) or "not opted in" in str(e):
                    console.print(
                        f"  [red]✗[/] Porkbun per-domain API access disabled for "
                        f"[cyan]{domain}[/].\n"
                        f"\n  [bold yellow]Manual enable required:[/]\n"
                        f"    1. Open: [link]https://porkbun.com/account/domains[/link]\n"
                        f"    2. Click on [cyan]{domain}[/]\n"
                        f"    3. Scroll to [bold]API ACCESS[/] section\n"
                        f"    4. Toggle [bold]API Access[/] to [bold]ON[/] → Save\n"
                        f"  [dim]Then re-run `lamill new deploy {domain} --yes`. "
                        f"Account-level API works (v15.F sync uses it) but "
                        f"per-domain toggle defaults OFF for newly-registered "
                        f"domains — each domain enables once.[/]"
                    )
                    raise typer.Exit(2)
                else:
                    # Other error (network, etc.) — non-fatal pre-flight.
                    console.print(
                        f"  [yellow]↷[/] Porkbun NS probe failed (continuing): {e}"
                    )
            else:
                console.print(
                    f"  [green]✓[/] Porkbun per-domain API access enabled for "
                    f"[cyan]{domain}[/]"
                )

    if dry_run:
        console.print(
            "\n  [yellow]dry-run mode — subsequent steps will print "
            "the plan but skip API/git writes.[/]"
        )

    # --- Step 1: GH repo -----------------------------------------------------
    console.print("\n[bold]1. GitHub repo[/]")
    if skip_repo:
        console.print(f"  [yellow]↷[/] skipped (--skip-repo)")
        gh_repo_name = slug
        clone_url = f"git@github.com:{gh_owner}/{slug}.git"
    elif dry_run:
        console.print(
            f"  [dim]would: ensure_repo({slug}, owner={gh_owner}, "
            f"private={private})[/]"
        )
        gh_repo_name = slug
        clone_url = f"git@github.com:{gh_owner}/{slug}.git"
    else:
        try:
            repo = ensure_repo(slug, owner=gh_owner, private=private)
        except (GhAuthError, GhError) as e:
            console.print(f"  [red]✗[/] GitHub repo step failed: {e}")
            raise typer.Exit(3)
        verb = "created" if repo.created else "exists, skipping"
        console.print(
            f"  [green]✓[/] {verb}: [cyan]{repo.full_name}[/] "
            f"[dim](visibility={'private' if repo.private else 'public'}; "
            f"default_branch={repo.default_branch})[/]"
        )
        gh_repo_name = repo.name
        clone_url = repo.clone_url_ssh

    # --- Step 2: Git push ----------------------------------------------------
    console.print("\n[bold]2. Git push origin/main[/]")
    if skip_repo:
        console.print(f"  [yellow]↷[/] skipped (--skip-repo)")
    elif dry_run:
        console.print(
            f"  [dim]would: ensure origin → {clone_url}; "
            f"git push -u origin main[/]"
        )
    else:
        try:
            added = ensure_origin_remote(Path(project_dir), clone_url)
            verb = "added" if added else "already configured"
            console.print(f"  [green]✓[/] origin {verb} → [cyan]{clone_url}[/]")
            pushed = push_to_origin(Path(project_dir), branch="main")
            if pushed:
                console.print("  [green]✓[/] pushed local commits to origin/main")
            else:
                console.print("  [green]✓[/] origin/main already up-to-date")
        except GhError as e:
            console.print(f"  [red]✗[/] git push step failed: {e}")
            raise typer.Exit(4)

    # --- Step 3: CF zone -----------------------------------------------------
    console.print(f"\n[bold]3. Cloudflare zone[/] [dim](for {domain})[/]")
    if dry_run:
        console.print(
            f"  [dim]would: ensure_zone({domain}, account_id={cf_account[:8]}…)[/]"
        )
        target_ns: list[str] = []
    else:
        try:
            zone = cloudflare.ensure_zone(domain, account_id=cf_account)
        except cloudflare.CloudflareAPIError as e:
            console.print(f"  [red]✗[/] CF zone step failed: {e}")
            # v15.R — surface exact "Connect a domain" URL when zone
            # creation 403s (operator's token typically lacks
            # account-level Zone:Create; the action lives in the
            # dashboard's "+ Add" dropdown).
            if "403" in str(e) or "zone.create" in str(e):
                console.print(
                    f"\n  [bold yellow]Manual zone creation required:[/]\n"
                    f"    1. Open: [link]https://dash.cloudflare.com[/link] "
                    f"(account = Foundervijo@gmail.com's Account)\n"
                    f"    2. Top-right blue [bold]+ Add[/] dropdown → "
                    f"[bold]Connect a domain[/]\n"
                    f"    3. Enter [cyan]{domain}[/] → Free plan → Continue\n"
                    f"    4. CF auto-creates the zone (status=pending) and "
                    f"shows NS records\n"
                    f"  [dim]Then re-run `lamill new deploy {domain} --yes` "
                    f"— Step 3 will resolve via cache + skip create.[/]"
                )
            raise typer.Exit(5)
        verb = "created" if zone.created else "exists, skipping"
        console.print(
            f"  [green]✓[/] zone {verb}: [cyan]{zone.name}[/] "
            f"[dim](id={zone.zone_id[:12]}… · status={zone.status})[/]"
        )
        console.print(
            f"  [dim]Cloudflare NS: {' '.join(zone.name_servers) or '<none>'}[/]"
        )
        target_ns = list(zone.name_servers)

    # --- Step 4: Registrar NS ------------------------------------------------
    console.print(f"\n[bold]4. Registrar NS[/] [dim](point {domain} at Cloudflare)[/]")
    registrar = _lookup_registrar(domain) or "unknown"
    if dry_run:
        console.print(
            f"  [dim]would: check + update NS at {registrar} to {target_ns}[/]"
        )
    elif not target_ns:
        console.print("  [yellow]↷[/] no target NS yet (zone create deferred); skipping")
    elif registrar.lower() != "porkbun":
        console.print(
            f"  [yellow]↷[/] domain registrar is [cyan]{registrar}[/] — "
            f"`lamill new deploy` only auto-pushes NS to Porkbun.\n"
            f"  [dim]Manual step: set NS at {registrar} to: "
            f"{', '.join(target_ns)}[/]"
        )
    elif not porkbun_creds:
        console.print(
            f"  [yellow]↷[/] Porkbun creds missing — manual NS update.\n"
            f"  [dim]Set NS at Porkbun to: {', '.join(target_ns)}[/]"
        )
    else:
        try:
            current_ns = get_porkbun_ns(
                domain, api_key=pb_key, secret=pb_secret,
            )
        except PorkbunDnsError as e:
            console.print(f"  [red]✗[/] could not read current Porkbun NS: {e}")
            raise typer.Exit(6)
        if ns_matches(current_ns, target_ns):
            console.print(
                f"  [green]✓[/] Porkbun NS already match Cloudflare "
                f"[dim]({', '.join(current_ns)})[/]"
            )
        else:
            console.print(
                f"  [dim]Porkbun current: {', '.join(current_ns) or '<none>'}[/]\n"
                f"  [dim]Cloudflare target: {', '.join(target_ns)}[/]"
            )
            confirm = True
            if not yes:
                confirm = typer.confirm(
                    f"  Update NS at Porkbun for {domain}?", default=True,
                )
            if not confirm:
                console.print(
                    f"  [yellow]↷[/] NS update declined — pipeline will "
                    f"continue, but the custom domain won't resolve until "
                    f"NS points at Cloudflare."
                )
            else:
                try:
                    update_porkbun_ns(
                        domain, api_key=pb_key, secret=pb_secret,
                        ns_list=target_ns,
                    )
                except PorkbunDnsError as e:
                    console.print(f"  [red]✗[/] Porkbun NS update failed: {e}")
                    raise typer.Exit(7)
                console.print("  [green]✓[/] NS updated at Porkbun")

    # --- Step 5: CF project (Pages OR Workers) ------------------------------
    # v15.P — auto-detect surface. CF unified Workers + Pages in 2025 but
    # the APIs are still separate. Operator's "Connect to Git" via the
    # unified UI usually creates a Workers Service (newer surface);
    # legacy projects (kwizicle / voltloop / etc.) are on Pages. Probe
    # both; route Step 6+ accordingly. `cf_surface` carries the choice.
    console.print("\n[bold]5. Cloudflare project (Pages OR Workers Service)[/]")
    cf_surface = "unknown"  # "pages" | "workers" | "unknown"
    if skip_pages:
        console.print(f"  [yellow]↷[/] skipped (--skip-pages)")
    elif dry_run:
        console.print(
            f"  [dim]would: probe Pages then Workers for '{slug}'; "
            f"create Pages if neither exists (Workers create requires CF dashboard)[/]"
        )
    else:
        try:
            project = cloudflare.get_pages_project(slug, account_id=cf_account)
            if project is not None:
                cf_surface = "pages"
                console.print(
                    f"  [green]✓[/] Pages project [cyan]{project.name}[/] exists, "
                    f"skipping create [dim](source={project.source_owner}/"
                    f"{project.source_repo}@{project.production_branch})[/]"
                )
            else:
                # Try Workers Services.
                worker = cloudflare.get_workers_service(slug, account_id=cf_account)
                if worker is not None:
                    cf_surface = "workers"
                    console.print(
                        f"  [green]✓[/] Workers Service [cyan]{worker.name}[/] "
                        f"exists, skipping create "
                        f"[dim](has_assets={worker.has_assets} · compat_date="
                        f"{worker.compatibility_date})[/]"
                    )
                    console.print(
                        f"  [dim]Note: Workers Builds Git integration is "
                        f"dashboard-only (CF API limitation as of Jan 2026). "
                        f"Pipeline detected the existing service + will route "
                        f"Step 6 through Workers API.[/]"
                    )
                else:
                    # Neither exists. Try to create Pages (legacy fallback).
                    project = cloudflare.create_pages_project_with_git(
                        slug,
                        account_id=cf_account,
                        gh_owner=gh_owner,
                        gh_repo=gh_repo_name,
                        production_branch="main",
                        build_command="pnpm run build",
                        destination_dir="dist",
                    )
                    cf_surface = "pages"
                    console.print(
                        f"  [green]✓[/] Pages project [cyan]{project.name}[/] created "
                        f"[dim](source={project.source_owner}/"
                        f"{project.source_repo}@{project.production_branch})[/]"
                    )
        except cloudflare.CloudflareAPIError as e:
            console.print(f"  [red]✗[/] CF project step failed: {e}")
            # v15.R — exact dashboard URLs for the manual "Connect to
            # Git" step (Workers Builds Git Integration API isn't
            # public as of Jan 2026; cloudflare/workers-sdk#12058).
            console.print(
                f"\n  [bold yellow]Manual project creation required:[/]\n"
                f"    1. Open: [link]https://dash.cloudflare.com/{cf_account}/workers-and-pages[/link]\n"
                f"    2. Click [bold]+ Add → Workers → Connect to Git[/]\n"
                f"       (NOT 'Pages' — CF's unified UI creates Workers Services "
                f"by default for git-integrated projects)\n"
                f"    3. Authorize the Cloudflare GitHub App on "
                f"[cyan]{gh_owner}/{gh_repo_name}[/] if asked\n"
                f"    4. Select repo [cyan]{gh_owner}/{gh_repo_name}[/]\n"
                f"    5. Worker name: [cyan]{slug}[/] (must match — lamill's slug)\n"
                f"    6. Production branch: [cyan]main[/]\n"
                f"    7. Build command: [cyan]pnpm run build[/]\n"
                f"    8. Build output: [cyan]dist[/]\n"
                f"    9. Save and Deploy\n"
                f"  [dim]Then re-run `lamill new deploy {domain} --yes` — "
                f"Step 5 will detect the Workers Service + route Step 6 "
                f"through the Workers API.[/]"
            )
            raise typer.Exit(8)

    # --- Step 5.5: Purge conflicting DNS records (v15.R) --------------------
    # When CF auto-adds a zone via "Connect a domain" UI, it populates
    # parking placeholders (A/CNAME on root + wildcard pointing at the
    # registrar's parking page). Those conflict with Workers Custom
    # Domain attach in Step 6 with "Hostname already has externally
    # managed DNS records". Auto-purge here using the operator's
    # DNS:Edit permission (which CF's token-create UI grants by
    # default for zone-scoped tokens).
    if not skip_pages and not dry_run and cf_surface == "workers":
        console.print(f"\n[bold]5.5 Purge conflicting DNS records[/] [dim]({domain})[/]")
        try:
            deleted = cloudflare.purge_conflicting_root_records(
                zone.zone_id, domain,
            )
        except cloudflare.CloudflareAPIError as e:
            # 2026-05-21 fix — HTTP 403 means the token can't clean
            # DNS. Surface dashboard URL + records to remove and exit
            # cleanly (matches the v15.R-era operator-action gates on
            # Steps 3/5/6). Pre-fix continued past the failure → Step
            # 6 attach then failed with stale parking records still
            # in place, leaving operator confused about which step
            # actually broke. Non-403 errors stay soft (network /
            # 5xx; transient — re-running picks up).
            if "HTTP 403" in str(e):
                console.print(f"  [red]✗[/] DNS purge denied: {e}")
                console.print(
                    f"\n  [bold yellow]Manual DNS cleanup required:[/]\n"
                    f"    1. Open this URL:\n"
                    f"       [link]https://dash.cloudflare.com/"
                    f"{cf_account}/{domain}/dns/records[/link]\n"
                    f"    2. Delete any [bold]A / AAAA / CNAME[/] records "
                    f"matching:\n"
                    f"       - [cyan]{domain}[/]\n"
                    f"       - [cyan]*.{domain}[/]\n"
                    f"       - [cyan]www.{domain}[/]\n"
                    f"    3. Re-run [cyan]lamill new deploy {domain} "
                    f"--yes[/]\n"
                    f"  [dim]Step 5.5 needs DNS:Edit on the zone. Edit "
                    f"token scopes at "
                    f"https://dash.cloudflare.com/profile/api-tokens "
                    f"if your token lacks it.[/]"
                )
                raise typer.Exit(7)
            console.print(
                f"  [yellow]↷[/] DNS purge probe failed (continuing): {e}"
            )
        else:
            if not deleted:
                console.print(
                    "  [green]✓[/] no conflicting root/wildcard A/AAAA/CNAME "
                    "records found"
                )
            else:
                for d in deleted:
                    console.print(
                        f"  [green]✓[/] removed: [cyan]{d.type}[/] "
                        f"[dim]{d.name} → {d.content}[/]"
                    )

    # --- Step 6: Custom Domain attach ----------------------------------------
    # v15.P — dispatch on cf_surface. Pages: POST /pages/projects/{name}/domains.
    # Workers: PUT /workers/domains with {service, hostname, zone_id}.
    console.print(f"\n[bold]6. Custom domain[/] [dim]({domain} → {slug} · surface={cf_surface})[/]")
    if skip_pages:
        console.print(f"  [yellow]↷[/] skipped (--skip-pages)")
    elif dry_run:
        console.print(
            f"  [dim]would: attach {domain} to {cf_surface} '{slug}'[/]"
        )
    else:
        try:
            if cf_surface == "workers":
                attached = cloudflare.attach_workers_custom_domain(
                    slug, domain,
                    account_id=cf_account,
                    zone_id=zone.zone_id,
                )
            else:
                # cf_surface == "pages" or "unknown" (try Pages path).
                attached = cloudflare.attach_pages_custom_domain(
                    slug, domain, account_id=cf_account,
                )
        except cloudflare.CloudflareAPIError as e:
            console.print(f"  [red]✗[/] custom domain step failed: {e}")
            # v15.R — surface exact dashboard URL inline for the
            # 403-on-PUT path (token lacks the specific permission
            # despite Workers Scripts:Edit at Account scope; CF's
            # permission model for workers/domains is more granular
            # than the UI label suggests).
            if cf_surface == "workers":
                console.print(
                    f"\n  [bold yellow]Manual attach required:[/]\n"
                    f"    1. Open this URL:\n"
                    f"       [link]https://dash.cloudflare.com/{cf_account}/workers/services/view/{slug}/production/domains[/link]\n"
                    f"    2. Click [bold]+ Add → Custom Domain[/]\n"
                    f"    3. Enter [cyan]{domain}[/] → Save\n"
                    f"  [dim]Then re-run `lamill new deploy {domain} --yes` — "
                    f"Step 6 will detect the attachment via GET-then-PUT "
                    f"(v15.Q) and skip cleanly.[/]"
                )
            raise typer.Exit(9)
        if attached:
            console.print(f"  [green]✓[/] {domain} attached to {slug}")
        else:
            console.print(f"  [green]✓[/] {domain} already attached, skipping")

    # --- Step 7: Build poll --------------------------------------------------
    # v15.P — only polls the Pages API. For Workers Services, build
    # status lives on a different endpoint (Workers Builds API,
    # dashboard-only as of Jan 2026). Skip with a clear note + point
    # the operator at the dashboard.
    console.print("\n[bold]7. Build status[/]")
    if dry_run:
        console.print("  [dim]would: poll deployment until terminal[/]")
    elif skip_pages:
        console.print(f"  [yellow]↷[/] skipped (--skip-pages)")
    elif cf_surface == "workers":
        console.print(
            "  [yellow]↷[/] skipped (Workers Services build status is "
            "dashboard-only as of Jan 2026; CF Workers Builds API not yet "
            "publicly programmable)."
        )
        console.print(
            f"  [dim]Watch builds at: "
            f"https://dash.cloudflare.com/{cf_account[:8]}.../workers/services/view/{slug}/production/builds[/]"
        )
    else:
        try:
            stage, dep_id, _ = cloudflare.latest_deployment_status(
                slug, account_id=cf_account,
            )
            if not stage:
                console.print(
                    "  [yellow]↷[/] no deployment yet — CF may still be "
                    "queuing the build. Re-run `lamill new deploy` in a few "
                    "minutes, or check the CF dashboard."
                )
            else:
                console.print(
                    f"  [dim]Current stage: {stage} status={dep_id}; "
                    "polling for terminal state (~5min timeout)...[/]"
                )

                def _on_status(stage_name, status):
                    console.print(
                        f"  [dim]· {stage_name}: {status}[/]"
                    )

                final_status, dep_id_final = cloudflare.poll_build(
                    slug, account_id=cf_account,
                    timeout_s=300, interval_s=5,
                    on_status=_on_status,
                )
                if final_status == "success":
                    console.print(f"  [green]✓[/] build complete — deployment {dep_id_final}")
                elif final_status == "failure":
                    console.print(f"  [red]✗[/] build failed — check CF dashboard for {slug}")
                elif final_status == "canceled":
                    console.print(f"  [yellow]↷[/] build canceled")
                else:
                    console.print(
                        f"  [yellow]↷[/] build still in flight after timeout "
                        f"(last stage status: {final_status}). Re-poll later."
                    )
        except cloudflare.CloudflareAPIError as e:
            console.print(f"  [yellow]↷[/] build poll error: {e}")

    # --- Step 8: Live probe --------------------------------------------------
    console.print(f"\n[bold]8. Live probe[/] [dim](https://{domain}/)[/]")
    if dry_run:
        console.print("  [dim]would: GET https://<domain>/[/]")
    else:
        try:
            import httpx
            r = httpx.get(
                f"https://{domain}/",
                timeout=5.0, follow_redirects=True,
            )
            if 200 <= r.status_code < 400:
                console.print(
                    f"  [green]✓[/] {r.status_code} {r.reason_phrase} "
                    f"[dim]({len(r.text)} bytes)[/]"
                )
            else:
                console.print(
                    f"  [yellow]↷[/] {r.status_code} {r.reason_phrase} — "
                    "may indicate NS propagation in flight or SSL not yet "
                    "provisioned. Re-probe in 5-30 min."
                )
        except httpx.HTTPError as e:
            console.print(
                f"  [yellow]↷[/] live probe failed: {type(e).__name__}: {e} — "
                "expected within ~30min of NS update (DNS propagation + "
                "edge SSL provisioning)."
            )

    console.print(
        f"\n[green]Deploy complete.[/] [dim]All 8 steps ran. "
        f"https://{domain}/ should resolve once DNS + SSL settle "
        f"(5-30 min from NS update).[/]\n"
    )


def _lookup_registrar(domain: str) -> str | None:
    """Read `data/portfolio.json` to find which registrar holds
    `domain`. Returns the lowercased registrar name or None if the
    domain isn't tracked."""
    from .data import PORTFOLIO_JSON
    import json

    if not PORTFOLIO_JSON.is_file():
        return None
    try:
        data = json.loads(PORTFOLIO_JSON.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    domains = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(domains, list):
        return None
    for d in domains:
        if not isinstance(d, dict):
            continue
        if (d.get("name") or "").lower() == domain.lower():
            return (d.get("registrar") or "").lower() or None
    return None


# v15.I (ADR-0012) deleted `_deploy_cf_pages_v3c()` + `_deploy_cf_workers()`.
# Both routes go through `_deploy_cf_unified()` above. v15.K (this commit)
# removes the dead code. `deploy_cf_workers_via_shell` in deploy.py also
# removed in the same pass.


def _deploy_vercel(*, domain: str, project_dir, dry_run: bool) -> None:
    """v11.M vercel path: shell out to `vercel deploy --prod`."""
    from .deploy import deploy_vercel_via_shell

    console.print(f"[bold]Deploy[/] [cyan]{domain}[/]  [dim](platform=vercel · vercel CLI)[/]")
    console.print(f"  project dir:  {project_dir}")
    console.print(f"  dry-run:      {dry_run}")
    result = deploy_vercel_via_shell(project_dir, dry_run=dry_run)
    if result.skipped:
        console.print(f"\n  [yellow]↷[/] {result.detail}")
        return
    if result.ok:
        console.print(f"\n  [green]✓[/] {result.detail}")
        console.print("[green]Deploy complete.[/]")
        return
    console.print(f"\n  [red]✗[/] {result.detail}")
    raise typer.Exit(6)


def _deploy_hostgator_v11n(
    *,
    domain: str,
    project_dir,
    lamill_toml,
    apply: bool,
) -> None:
    """v11.N — UAPI file upload for hostgator/custom. Stage-then-rename
    via cPanel Fileman (see ADR-0011)."""
    from . import apikeys, hosting, hosting_cache

    account_id = (
        (lamill_toml.deploy.account or "").strip().lower()
        if lamill_toml.deploy.account else ""
    )
    if not account_id:
        console.print(
            f"[red]lamill.toml deploy.account is empty for {domain}.[/]"
        )
        console.print(
            "[dim]Add an `account = \"<hg-account-id>\"` line under "
            "the deploy section (e.g. gator3164) and re-run.[/]"
        )
        raise typer.Exit(2)

    token = apikeys.get_key(f"HOSTGATOR_TOKEN_{account_id.upper()}") or ""
    if not token:
        console.print(
            f"[red]Missing HOSTGATOR_TOKEN_{account_id.upper()} in "
            f"portfolio.env.[/]\n"
            f"[dim]Run `lamill settings apikeys set "
            f"HOSTGATOR_TOKEN_{account_id.upper()} <token>` and try again.[/]"
        )
        raise typer.Exit(2)
    cpanel_user = apikeys.hg_user_for_account(account_id)

    snapshot_path = hosting_cache.latest_snapshot()
    if snapshot_path is None:
        console.print(
            "[red]No hosting snapshot found in data/hosting/.[/]\n"
            "[dim]Run `lamill fleet hosting --refresh` first so v11.N "
            "can read wp_version + hg_account_id metadata before pushing.[/]"
        )
        raise typer.Exit(2)
    result = hosting_cache.result_from_snapshot(
        hosting_cache.load_snapshot(snapshot_path)
    )
    matching = [
        r for r in result.rows
        if r.domain == domain
        and r.provider == hosting.PROVIDER_HOSTGATOR
        and (r.hg_account_id or "").lower() == account_id
    ]
    if not matching:
        console.print(
            f"[red]Domain {domain} not found as a hostgator row on "
            f"account {account_id} in the latest snapshot.[/]\n"
            f"[dim]Snapshot: {snapshot_path}. Run `lamill fleet hosting "
            "--refresh` to rebuild.[/]"
        )
        raise typer.Exit(2)
    row = matching[0]

    dry_run = not apply
    console.print(
        f"[bold]Deploy[/] [cyan]{domain}[/]  "
        f"[dim](platform={lamill_toml.deploy.platform} · cPanel UAPI · "
        f"{'DRY-RUN' if dry_run else 'APPLY'})[/]"
    )
    console.print(f"  project dir:    {project_dir}")
    console.print(
        f"  deploy_source:  "
        f"{lamill_toml.hosting.deploy_source if lamill_toml.hosting else '(none)'}"
    )
    console.print(
        f"  public_html:    "
        f"{lamill_toml.hosting.public_html_path if lamill_toml.hosting else '(none)'}"
    )
    console.print(f"  account:        {account_id}  (user={cpanel_user})")

    dr = hosting.deploy_hg_files(
        row,
        lamill_toml=lamill_toml,
        token=token,
        cpanel_user=cpanel_user,
        dry_run=dry_run,
    )

    console.print()
    if dr.action == "would_deploy":
        console.print(
            f"  [yellow]↷ DRY-RUN[/]  "
            f"{dr.file_count} files · {hosting._fmt_bytes(dr.total_bytes)}"
        )
        console.print(f"  [dim]{dr.notes}[/]")
        console.print(
            "\n[dim]Re-run with `--apply` to actually push.[/]"
        )
        return
    if dr.action == "deployed":
        console.print(
            f"  [green]✓ Deployed[/]  "
            f"{dr.file_count} files · {hosting._fmt_bytes(dr.total_bytes)}"
        )
        console.print(f"  [dim]{dr.notes}[/]")
        return
    if dr.action == "skipped_wp":
        console.print(f"  [yellow]↷ Skipped (WP)[/]  {dr.notes}")
        raise typer.Exit(0)
    if dr.action == "skipped_no_source":
        console.print(f"  [yellow]↷ Skipped (no source)[/]  {dr.notes}")
        raise typer.Exit(2)
    if dr.action == "skipped_no_path":
        console.print(f"  [yellow]↷ Skipped (no path)[/]  {dr.notes}")
        raise typer.Exit(2)
    # failed
    console.print(f"  [red]✗ Failed[/]  {dr.error or '(no detail)'}")
    raise typer.Exit(6)


# `project` namespace — per-project ops (check, fix, seo, diagnose, set-launched).
project_app = typer.Typer(help="Per-project ops.", no_args_is_help=True)
app.add_typer(project_app, name="project")


@project_app.command("fix")
def project_fix(
    name: str = typer.Argument("", metavar="DOMAIN",
                               help="Domain (fuzzy-matched). Required unless --all."),
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
        console.print("[red]Pass either <DOMAIN> or --all, not both.[/]")
        raise typer.Exit(2)
    if fix_all:
        _run_project_fix_all(apply_changes=apply_changes,
                             rule_filter=rule_filter,
                             assume_yes=assume_yes,
                             use_ai=use_ai)
        return
    if not name:
        console.print("[red]'project fix' needs a <DOMAIN> argument (or --all).[/]")
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
    name: str = typer.Argument(..., metavar="DOMAIN",
                               help="Domain (fuzzy-matched)"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of human table"),
    catalog_only: bool = typer.Option(
        False, "--catalog-only",
        help="Skip git/deploy/prompts; show only the per-rule catalog table",
    ),
) -> None:
    """Full per-project status: conformance + git + deploy + prompts.

    With `--catalog-only`, shows just the per-rule catalog table.
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
    name: str = typer.Argument(..., metavar="DOMAIN",
                               help="Domain (single-domain runtime SEO probe)"),
    days: int = typer.Option(28, "--days"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Bypass cache; re-fetch SEO probe + GSC diagnostics"),
    sort_by: str = typer.Option("impressions", "--sort"),
    top_n: int = typer.Option(10, "--top",
                              help="Top-N URLs to inspect for coverage detail "
                                   "(v13.B; caps URL Inspection quota burn)"),
) -> None:
    """Per-project SEO view — runtime probe + GSC diagnostics.

    Renders the 1-row 28-day aggregate header (v5.D) followed by
    the v13.B diagnostics block: per-sitemap status, top-N URL
    coverage from URL Inspection API, and actionable hints. When
    `fleet focus` flags a site (e.g., "sitemap parse errors") this
    command shows what specifically is broken.

    Caches GSC diagnostics per-domain at `data/gsc/<domain>/<date>.json`
    with a 24h TTL. `--refresh` re-fetches.
    """
    domain = name.lower()
    # Existing 1-row aggregate header (v5.D).
    _run_check_seo_mode(days=days, only_domain=domain,
                        sort_by=sort_by, only="wip", concurrency=20,
                        refresh=refresh)
    # v13.B diagnostics block below the header.
    _run_project_seo_diagnostics(domain, top_n=top_n,
                                 refresh=refresh, console=console)


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


# v15.B — per-project hosting verb. Restores symmetry with
# `project check ↔ fleet check`, `project seo ↔ fleet seo`. Replaces
# the old `fleet hosting --only <domain>` single-domain probe with
# a vertical-sections renderer (📦 Deploy + 📌 Domains; 📋 Freshness
# and 🔧 Build land in v15.D/E).
@project_app.command("hosting")
def project_hosting(
    domain: str = typer.Argument(..., help="Domain (e.g. airsucks.com)"),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Re-probe the providers even if a fresh fleet snapshot exists.",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="Emit JSON instead of the vertical-sections view.",
    ),
) -> None:
    """Single-domain hosting view — provider, deploy state, branch.

    Reads the fleet hosting snapshot when fresh; re-probes with
    `--refresh` or when the snapshot is stale / missing. The
    single-domain probe never overwrites the fleet snapshot.

    Output is a stacked-sections view (vs `fleet hosting`'s table)
    so each section can grow as v15.D/E add freshness + build state.
    """
    _project_hosting_impl(
        domain=domain.lower(), refresh=refresh,
        json_out=json_out, console=console,
    )


def _project_hosting_impl(
    *, domain: str, refresh: bool, json_out: bool, console,
) -> None:
    """Body of `project hosting`. Carved out so tests can drive it
    directly without the typer surface."""
    from dataclasses import asdict
    from . import hosting_cache
    from .hosting import run_hosting
    from .project import SITES_ROOT
    from .project_hosting_render import render_project_hosting
    from .checks.seo._live import resolve_live_url
    from .version_stamp import (
        compare_versions,
        fetch_version_stamp,
        local_head_sha,
    )

    fleet_domains = {d.name.lower() for d in load_domains()}

    # Cache lookup mirrors `fleet hosting`'s logic but ALWAYS filters
    # to one domain at render time. The fleet snapshot is the source
    # of truth when fresh; --refresh forces a single-domain probe that
    # leaves the fleet snapshot alone.
    snapshot_path = hosting_cache.latest_snapshot()
    cache_eligible = (
        not refresh
        and snapshot_path is not None
        and not hosting_cache.is_stale(snapshot_path)
    )

    if cache_eligible:
        snap = hosting_cache.load_snapshot(snapshot_path)
        result = hosting_cache.result_from_snapshot(snap)
        source = f"snapshot {snapshot_path.name}"
    else:
        # Single-domain probe — passes `only_domain=` so walkers
        # short-circuit emission. Does NOT persist to the fleet
        # snapshot (would clobber a multi-domain cache with one row).
        result = run_hosting(fleet_domains, only_domain=domain)
        source = f"single-domain probe ({domain})"

    # Filter rows to the requested domain. Conflict cases keep every
    # matching row so the renderer can flag the drift.
    matched_rows = [r for r in result.rows if r.domain.lower() == domain]

    # v15.D — fetch live /version.json + compare to local HEAD to
    # surface the 📋 Freshness section. Best-effort; renderer
    # gracefully omits the section when freshness is None.
    freshness = None
    repo_path = SITES_ROOT / domain
    if repo_path.exists() and matched_rows:
        origin = resolve_live_url(str(repo_path))
        if origin:
            stamp_or_error = fetch_version_stamp(origin)
            head = local_head_sha(str(repo_path))
            freshness = compare_versions(head, stamp_or_error)

    if json_out:
        import json as _json
        payload = {
            "domain": domain,
            "source": source,
            "rows": [asdict(r) for r in matched_rows],
            "skipped": dict(result.skipped),
            "freshness": asdict(freshness) if freshness else None,
        }
        typer.echo(_json.dumps(payload, indent=2))
        return

    render_project_hosting(
        domain=domain, rows=matched_rows, skipped=result.skipped,
        source=source, console=console, freshness=freshness,
    )


# v15.M — decoupled stack translation. `lamill new bootstrap` for
# non-Astro `--git-url` repos defers translation by default (writes
# blank Astro scaffold + keeps `genai/` + writes a marker file).
# This verb runs the actual Claude-driven port from `genai/` source
# into the existing Astro scaffold — separately, with longer timeout
# / higher budget defaults, retryable, runnable in the background.


@project_app.command("translate")
def project_translate(
    domain: str = typer.Argument(..., help="Domain whose sites/<domain>/genai/ to port into the Astro scaffold (e.g. agesdk.dev)"),
    budget_usd: float = typer.Option(
        5.0, "--budget",
        help="Claude subprocess budget cap (USD). Default $5.00; "
             "complex TanStack→Astro ports can cost $1-3 with the "
             "extended toolset.",
    ),
    timeout_s: int = typer.Option(
        1800, "--timeout",
        help="Subprocess timeout in seconds. Default 30 minutes; "
             "very large repos may need more.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Run the port even if the `.lamill-translation-pending` "
             "marker file isn't present. Use when retrying after a "
             "failed translation that wiped the marker.",
    ),
) -> None:
    """v15.M — port `sites/<domain>/genai/` into the existing Astro
    scaffold via Claude subprocess.

    Required state (set up by `lamill new bootstrap --git-url <url>`
    when the cloned source is non-Astro):
      - `sites/<domain>/` exists with an Astro+Vite scaffold at root
        (`package.json` with `astro` dep, `astro.config.mjs`, etc.)
      - `sites/<domain>/genai/` exists with the untranslated source
      - `sites/<domain>/.lamill-translation-pending` marker file
        (skipped with `--force`)

    On success: commits the ported files to git as a single commit
    + removes the marker file.

    On failure: leaves project + genai/ + marker intact for retry.
    `--budget` and `--timeout` can be bumped for re-runs.
    """
    import json
    from .data import ROOT as DATA_ROOT
    from .stack_translate import (
        port_to_astro,
        validate_translation,
        StackTranslationError,
    )

    project_dir = DATA_ROOT.parent / domain
    if not project_dir.exists():
        console.print(f"[red]Project dir not found:[/] {project_dir}")
        console.print(
            "[dim]Run `lamill new bootstrap <domain> --git-url <url>` "
            "first.[/]"
        )
        raise typer.Exit(1)

    genai_dir = project_dir / "genai"
    if not genai_dir.is_dir():
        console.print(
            f"[red]No genai/ subdir at {project_dir}.[/] "
            "[dim]`project translate` only runs when the project was "
            "bootstrapped with `--git-url`. For blank-scaffold projects, "
            "use the project directly — no translation needed.[/]"
        )
        raise typer.Exit(2)

    marker = project_dir / ".lamill-translation-pending"
    if not marker.exists() and not force:
        console.print(
            f"[yellow]No translation-pending marker at {marker}.[/]\n"
            "[dim]Either the project was bootstrapped before v15.M, OR "
            "a previous `project translate` succeeded and consumed the "
            "marker. Pass `--force` to run anyway (e.g. for retrying a "
            "partially-completed port).[/]"
        )
        raise typer.Exit(2)

    # Read marker for detection signals (defaults if --force).
    source_stack = "unknown"
    source_signals: list[str] = []
    if marker.exists():
        try:
            data = json.loads(marker.read_text())
            source_stack = data.get("source_stack", "unknown")
            source_signals = list(data.get("source_signals") or [])
        except (OSError, json.JSONDecodeError):
            pass

    console.print(
        f"[bold]v15.M — Porting[/] [cyan]{domain}[/] "
        f"[dim](source_stack={source_stack} · budget=${budget_usd:.2f} "
        f"· timeout={timeout_s}s)[/]"
    )
    console.print(f"  [dim]Source signals: {', '.join(source_signals) or '<none>'}[/]")
    console.print(
        "[dim]This may take 5-30 minutes. Output appears as files in "
        "src/pages/, src/components/, public/, etc.[/]"
    )

    result = port_to_astro(
        project_dir,
        source_stack=source_stack,
        source_signals=source_signals,
        budget_usd=budget_usd,
        timeout_s=timeout_s,
    )

    if not result.ok:
        console.print(
            f"[red]Port failed:[/] {result.error}\n"
            f"[dim]{result.raw_output[:300] if result.raw_output else ''}[/]"
        )
        console.print(
            "[dim]Project state intact — marker file preserved; you can "
            "retry with a higher --budget or --timeout, or fix the "
            "source repo. Run `lamill project translate "
            f"{domain} --budget 10.0` to retry with more budget.[/]"
        )
        raise typer.Exit(3)

    # Validate.
    validation = validate_translation(project_dir)
    if not validation.ok:
        console.print(
            f"[red]Port output failed validation:[/]\n  "
            + "\n  ".join(f"- {iss}" for iss in validation.issues)
        )
        console.print(
            "[dim]Project state intact — fix the source repo's "
            "package.json / config and retry, or pass `--force` and "
            "manually fix the output.[/]"
        )
        raise typer.Exit(4)

    # Commit + remove marker.
    import subprocess
    try:
        subprocess.run(
            ["git", "add", "."],
            cwd=str(project_dir),
            capture_output=True, text=True,
            timeout=30.0, check=False,
        )
        commit_msg = (
            f"v15.M — port {source_stack} → Astro via Claude subprocess\n\n"
            f"Cost: ${result.cost_usd:.4f} · Duration: "
            f"{result.duration_s:.1f}s · Source signals: "
            f"{', '.join(source_signals) or '<none>'}"
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=str(project_dir),
            capture_output=True, text=True,
            timeout=30.0, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        console.print(f"[yellow]Port succeeded but git commit failed: {e}[/]")

    marker.unlink(missing_ok=True)

    console.print(
        f"\n[green]✓ Port complete.[/] "
        f"[dim]Cost: ${result.cost_usd:.4f} · Duration: "
        f"{result.duration_s:.1f}s[/]"
    )
    console.print(
        f"[dim]Next: `cd ~/work/projects/sites/{domain} && make buildsh` "
        "to verify the build inside Docker. Then `lamill new deploy "
        f"{domain}` to ship.[/]"
    )


@settings_deploy_app.command("set")
def settings_deploy_set(
    name: str = typer.Argument(..., metavar="DOMAIN",
                               help="Domain (e.g. airsucks.com)"),
    platform: str = typer.Argument(..., metavar="PLATFORM",
                                   help="cf-pages | cf-workers | vercel | "
                                        "netlify | github-pages | hostgator | "
                                        "custom | none"),
    account: str = typer.Option("", "--account",
                                help="Platform account/team slug"),
    branch: str = typer.Option("", "--branch",
                               help="Production branch (default: main)"),
    auto_deploy: bool = typer.Option(None, "--auto-deploy/--no-auto-deploy",
                                     help="Override platform default for "
                                          "push-triggers-build"),
    domain: list[str] = typer.Option(None, "--domain",
                                     help="Custom domain the deploy serves "
                                          "(repeatable)"),
    cpanel_user: str = typer.Option("", "--cpanel-user",
                                    help="cPanel user (hostgator/custom)"),
    cpanel_url: str = typer.Option("", "--cpanel-url",
                                   help="cPanel URL (hostgator/custom)"),
    ftp_host: str = typer.Option("", "--ftp-host",
                                 help="FTP host (hostgator/custom)"),
    ftp_user: str = typer.Option("", "--ftp-user",
                                 help="FTP user (hostgator/custom)"),
    ftp_port: int = typer.Option(None, "--ftp-port",
                                 help="FTP port (hostgator/custom)"),
    public_html_path: str = typer.Option("", "--public-html-path",
                                         help="Where public files live on "
                                              "the host (hostgator/custom)"),
    non_interactive: bool = typer.Option(False, "--non-interactive",
                                         help="Refuse prompts; fail if "
                                              "required fields missing"),
) -> None:
    """Create or update sites/<DOMAIN>/lamill.toml.

    Interactive by default — prompts for optional fields and (for
    hostgator/custom) walks the cPanel + FTP breadcrumbs. Pre-fill
    any field via the matching flag to skip its prompt. Use
    `--non-interactive` for scripted invocations; the command will
    fail if hostgator/custom is requested without enough hosting
    flags to populate the `[hosting]` section.
    """
    from .project_deploy import set_deploy
    set_deploy(
        name,
        platform,
        interactive=not non_interactive,
        account=account or None,
        branch=branch or None,
        auto_deploy=auto_deploy,
        custom_domains=list(domain) if domain else None,
        cpanel_user=cpanel_user or None,
        cpanel_url=cpanel_url or None,
        ftp_host=ftp_host or None,
        ftp_user=ftp_user or None,
        ftp_port=ftp_port,
        public_html_path=public_html_path or None,
        console=console,
    )


@settings_deploy_app.command("show")
def settings_deploy_show(
    name: str = typer.Argument(..., metavar="DOMAIN",
                               help="Domain (e.g. airsucks.com)"),
    as_json: bool = typer.Option(False, "--json",
                                 help="Emit `lamill.toml` as JSON "
                                      "instead of a rich table"),
) -> None:
    """Show the declared deployment for sites/<DOMAIN>/.

    Reads `lamill.toml` and renders platform / account / branch /
    domains plus the optional [hosting] / [backend] / [notes]
    blocks. `--json` emits the raw payload as JSON (paired with
    `to_dict()` from `lamill_toml`). When no `lamill.toml` exists
    the command exits 0 with a hint to run `settings deploy set`.
    """
    from .project_deploy import show_deploy
    rc = show_deploy(name, as_json=as_json, console=console)
    if rc != 0:
        raise typer.Exit(rc)


@settings_deploy_app.command("set-launched")
def settings_deploy_set_launched(
    name: str = typer.Argument(..., metavar="DOMAIN",
                               help="Domain"),
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
    """Top priorities across the fleet — ranked attention list."""
    focus(show_all=show_all, refresh=refresh, include_young=include_young)


@fleet_app.command("domains")
def fleet_domains(
    only: str = typer.Option("wip", "--only", "-o"),
    concurrency: int = typer.Option(20, "--concurrency", "-c"),
    summary: bool = typer.Option(
        False, "--summary",
        help="Portfolio overview — category counts + value rollup. Add --verbose for the per-domain table.",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="With --summary: also render the per-domain table.",
    ),
    expiring: int = typer.Option(
        0, "--expiring",
        help="Filter to domains expiring within N days (e.g. --expiring 180). Mutually exclusive with --summary.",
    ),
) -> None:
    """Operate on the fleet at the domain level.

    Default: fetch each domain over HTTP and classify (live-site /
    forwarder / parked / dead) → snapshot in data/checks/.

    `--summary`: portfolio overview (category counts + value rollup).
    `--summary --verbose`: same + per-domain table.

    `--expiring N`: list domains expiring within N days.
    """
    if summary and expiring:
        console.print("[red]--summary and --expiring are mutually exclusive.[/]")
        raise typer.Exit(2)

    if summary:
        info_summary()
        if verbose:
            console.print()
            info_list()
        return

    if expiring:
        info_expiring(within=expiring)
        return

    check_live(only=only, concurrency=concurrency, domain="")


@fleet_app.command("seo")
def fleet_seo(
    days: int = typer.Option(28, "--days"),
    only: str = typer.Option("wip", "--only", "-o"),
    concurrency: int = typer.Option(20, "--concurrency", "-c"),
    sort_by: str = typer.Option("impressions", "--sort"),
    refresh: bool = typer.Option(False, "--refresh"),
    detail: bool = typer.Option(
        False, "--detail",
        help="v16.D — append fleet-aggregated top queries / top pages / "
             "page-2 opportunities (across the fleet, not per-property).",
    ),
) -> None:
    """Runtime SEO probe across all live-site/forwarder domains.

    `--detail` (v16.D) renders three additional fleet-aggregated
    sections below the per-site table, reading from each domain's
    `data/gsc/<domain>/<UTC-today>.json` cache. Sections show as
    "(empty)" when no domains have cached GSC analytics data yet —
    populate via `lamill project seo <domain>` per site.
    """
    check_seo(days=days, domain="", repo="", only=only,
              concurrency=concurrency, sort_by=sort_by, refresh=refresh)

    if detail:
        _render_fleet_seo_detail(only=only)


def _render_fleet_seo_detail(*, only: str) -> None:
    """v16.D — render fleet-aggregated top queries / top pages /
    page-2 opportunities. Reads `gsc_rollup` aggregations across
    every domain in scope."""
    from .gsc_rollup import (
        fleet_aggregated_top_pages,
        fleet_aggregated_top_queries,
        fleet_page_2_opportunities,
    )

    fleet_doms = [d.name for d in load_domains()]
    # Honor the same scope as the upstream `check_seo` call.
    if only and only != "all":
        try:
            from .data import load_plan
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
    _render_top_queries_section(queries)
    console.print()
    _render_top_pages_section(pages)
    console.print()
    _render_page_2_opportunities_section(p2)
    console.print(
        "\n[dim]Source: per-domain GSC cache "
        "(`data/gsc/<domain>/<UTC-today>.json`). "
        "Populate via `lamill project seo <domain>`.[/]"
    )


def _render_top_queries_section(queries: list) -> None:
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


def _render_top_pages_section(pages: list) -> None:
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


def _render_page_2_opportunities_section(p2: list) -> None:
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


# v11.G — `fleet hosting`. Read-only multi-provider hosting state
# (Vercel + Cloudflare Pages + HostGator). Cached snapshot at
# `data/hosting/<date>.json`; default behavior reads the cache if
# fresh, otherwise re-walks. Pretty renderer is minimal in v11.G —
# v11.H upgrades it with status emoji + walker error footers.
@fleet_app.command("hosting")
def fleet_hosting(
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Re-walk providers even if a fresh snapshot exists."),
    provider: str = typer.Option("", "--provider",
                                 help="Filter rows: vercel | cloudflare-pages | cloudflare-workers | hostgator."),
    json_out: bool = typer.Option(False, "--json",
                                  help="Emit JSON instead of the table."),
    apply_declarations: bool = typer.Option(
        False, "--apply-declarations",
        help="Write lamill.toml for HG sites that lack one (HG-only; CF/Vercel already inferable via v10.C migration sweep).",
    ),
    apply: bool = typer.Option(
        False, "--apply",
        help="With --apply-declarations: actually write the files. Dry-run by default.",
    ),
) -> None:
    """Unified Vercel + Cloudflare Pages + Cloudflare Workers + HostGator hosting view.

    v15.B hard-cutover: the legacy `--only <domain>` flag was removed
    in favor of the new per-project verb `lamill project hosting
    <domain>`, which renders a vertical-sections view instead of a
    one-row table. No alias — old invocations now fail with typer's
    standard "no such option" error.
    """
    _fleet_hosting_impl(
        refresh=refresh,
        provider=provider, json_out=json_out,
        apply_declarations=apply_declarations, apply=apply,
    )


def _fleet_hosting_impl(
    *, refresh: bool, provider: str, json_out: bool,
    apply_declarations: bool = False, apply: bool = False,
) -> None:
    """Body of `fleet hosting`. Carved out for testability — the Typer
    command surface is a thin shell over this.

    Two render modes:
      - Default — read/walk and render the status table (v11.G/I).
      - `apply_declarations=True` — branch into v11.J flow: collect HG
        rows, call `apply_hg_declarations()`, render the migration
        summary instead of the table. `apply=False` (default) is
        dry-run; `apply=True` writes the files.
    """
    from . import hosting_cache
    from .hosting import (
        PROVIDER_HOSTGATOR, PROVIDERS,
        apply_hg_declarations,
        hosting_footer_summary, hosting_provider_counts,
        hosting_status_emoji, run_hosting,
    )

    # Provider-filter validation up front so the user gets a clean
    # error before any network call.
    if provider and provider not in PROVIDERS:
        console.print(
            f"[red]Unknown provider: {provider!r}. "
            f"Expected one of: {', '.join(PROVIDERS)}.[/]"
        )
        raise typer.Exit(code=2)

    # Fleet domains = every entry in portfolio.json. Walkers
    # intersect-filter; non-fleet domains drop silently.
    fleet_domains = {d.name.lower() for d in load_domains()}

    # Cache eligibility: `--refresh` forces a fresh walk. Otherwise,
    # use the latest snapshot if it's < 24h old. (v15.B removed the
    # `--only` single-domain branch — that lives at `project hosting`
    # now.)
    snapshot_path = hosting_cache.latest_snapshot()
    cache_eligible = (
        not refresh
        and snapshot_path is not None
        and not hosting_cache.is_stale(snapshot_path)
    )

    if cache_eligible:
        snap = hosting_cache.load_snapshot(snapshot_path)
        result = hosting_cache.result_from_snapshot(snap)
        source = f"snapshot {snapshot_path.name}"
    else:
        result = run_hosting(fleet_domains)
        written = hosting_cache.save_snapshot(result)
        source = f"fresh walk → {written.name}"

    # `--apply-declarations` branches before any filtering — the
    # apply path needs HG rows only and uses its own renderer.
    if apply_declarations:
        _fleet_hosting_apply_declarations(
            result=result, dry_run=not apply, json_out=json_out,
            source=source,
        )
        return

    # Apply --provider filter after collection so the cache stays
    # full-fidelity for subsequent unfiltered invocations.
    all_rows = list(result.rows)
    rows = list(all_rows)
    if provider:
        rows = [r for r in rows if r.provider == provider]
    rows.sort(key=lambda r: (r.domain, r.provider or ""))

    if json_out:
        import json as _json
        from dataclasses import asdict
        payload = {
            "source": source,
            "rows": [asdict(r) for r in rows],
            "skipped": dict(result.skipped),
        }
        typer.echo(_json.dumps(payload, indent=2))
        return

    console.print(f"[dim]Source: {source}[/]")

    if not rows:
        # Distinguish two zero-row cases (resolution from bug
        # 2026-05-19): (a) walker returned nothing, (b) --provider
        # filtered every row out. Show the pre-filter breakdown so
        # the operator can see at a glance what WAS available.
        if provider and all_rows:
            console.print(
                f"[yellow]No `{provider}` rows.[/] "
                f"[dim](Filtered from {len(all_rows)} total. "
                f"Drop the --provider flag to see all.)[/]"
            )
            console.print(
                f"  [dim]Available: "
                f"{hosting_footer_summary(all_rows, result.skipped)}[/]"
            )
        else:
            console.print("[yellow]No hosting rows.[/]")
        _print_skipped_footer(result.skipped)
        return

    # Conditional HG-extra column — only render when at least one
    # HG row would populate it. Otherwise it'd be a wide empty column
    # for every Vercel/CF row (bug 2026-05-19: cosmetic clutter).
    has_hg = any(r.provider == PROVIDER_HOSTGATOR for r in rows)

    table = Table(show_header=True, header_style="bold")
    table.add_column("", justify="center", width=2)   # status emoji
    table.add_column("Domain")
    table.add_column("Provider")
    table.add_column("Deploy state")
    table.add_column("Last Success")
    table.add_column("Failures", justify="right")
    if has_hg:
        table.add_column("HG-extra")
    for r in rows:
        emoji = hosting_status_emoji(r)
        row_cells = [
            emoji,
            r.domain,
            r.provider or "—",
            r.latest_deploy_status or "—",
            (r.last_successful_deploy_at or "—")[:19],
            str(r.consecutive_failures) if r.consecutive_failures else "0",
        ]
        if has_hg:
            hg_extra = ""
            if r.provider == PROVIDER_HOSTGATOR:
                parts: list[str] = []
                # 2026-05-21: disk_used_mb removed from per-row HG-extra —
                # it's an ACCOUNT-level total (gator3164 etc.), not a
                # per-domain figure, and repeating it on every row of
                # the same account misled operators into thinking each
                # site used that much. Now aggregated in the footer
                # block below.
                if r.wp_version:
                    parts.append(f"WP {r.wp_version}")
                if r.install_path:
                    # Truncate long doc-roots so they don't blow up
                    # the column width. `…<last 28 chars>` keeps the
                    # tail (which contains the domain segment of the
                    # path — the operator-relevant bit).
                    p = r.install_path
                    if len(p) > 30:
                        p = "…" + p[-29:]
                    parts.append(p)
                hg_extra = " · ".join(parts)
            row_cells.append(hg_extra)
        table.add_row(*row_cells)
    console.print(table)

    # Footer rollup — counts per provider + skipped/conflicts tally
    # (bug 2026-05-19: missing summary footer).
    console.print(f"[dim]  {hosting_footer_summary(rows, result.skipped)}[/]")
    # 2026-05-21: HG account disk-usage rollup (moved out of per-row
    # HG-extra). One line per account: "HG accounts: gator3164 1430MB
    # · gator4216 4959MB". Shown only when at least one HG row has
    # disk_used_mb populated.
    hg_disk_line = _hg_accounts_disk_summary(rows)
    if hg_disk_line:
        console.print(f"[dim]  {hg_disk_line}[/]")
    _print_skipped_footer(result.skipped)


def _hg_accounts_disk_summary(rows) -> str:
    """Aggregate `disk_used_mb` per HG account across the row list.

    Returns "" when no HG row carries disk data; otherwise returns
    `"HG accounts: gator3164 1430MB · gator4216 4959MB"` (sorted by
    account name for stable rendering).
    """
    from .hosting import PROVIDER_HOSTGATOR
    by_account: dict[str, int] = {}
    for r in rows:
        if r.provider != PROVIDER_HOSTGATOR:
            continue
        if not r.hg_account_id or r.disk_used_mb is None:
            continue
        # Same account_id should always carry the same disk_used_mb —
        # but if rows disagree (cache write race), keep the max so
        # we don't under-report.
        prior = by_account.get(r.hg_account_id, 0)
        by_account[r.hg_account_id] = max(prior, r.disk_used_mb)
    if not by_account:
        return ""
    pieces = [f"{acct} {mb}MB" for acct, mb in sorted(by_account.items())]
    return "HG accounts: " + " · ".join(pieces)


def _fleet_hosting_apply_declarations(
    *, result, dry_run: bool, json_out: bool, source: str,
) -> None:
    """v11.J — render the `--apply-declarations` migration summary.

    Calls `hosting.apply_hg_declarations()` with the HG rows from
    the walker output. Reports per-domain actions:
      - `would_write` (dry-run) / `wrote` (apply) — the happy paths
      - `skipped_already` — lamill.toml already exists
      - `skipped_no_site_dir` — no local `sites/<domain>/` directory
      - `skipped_archived` — site marked archived
    """
    from .hosting import apply_hg_declarations

    apply_rows = apply_hg_declarations(result.rows, dry_run=dry_run)

    if json_out:
        import json as _json
        from dataclasses import asdict
        payload = {
            "source": source,
            "dry_run": dry_run,
            "rows": [asdict(r) for r in apply_rows],
        }
        typer.echo(_json.dumps(payload, indent=2))
        return

    console.print(f"[dim]Source: {source}[/]")
    mode = "[yellow]dry-run[/]" if dry_run else "[green]apply[/]"
    console.print(f"[bold]--apply-declarations[/] ({mode})\n")

    if not apply_rows:
        console.print(
            "[dim]No HG rows in the walker output — nothing to apply. "
            "(Are your HG tokens / users set in portfolio.env?)[/]"
        )
        return

    # Group + render by action, most-actionable-first.
    by_action: dict[str, list] = {}
    for r in apply_rows:
        by_action.setdefault(r.action, []).append(r)

    action_order = [
        ("would_write", "[green]Would write[/]"),
        ("wrote", "[green]Wrote[/]"),
        ("skipped_no_site_dir", "[cyan]Skipped — no local sites/<domain>/[/]"),
        ("skipped_already", "[dim]Skipped — lamill.toml already exists[/]"),
        ("skipped_archived", "[dim]Skipped — archived[/]"),
    ]

    for action, header in action_order:
        action_rows = by_action.get(action, [])
        if not action_rows:
            continue
        console.print(f"\n{header}: {len(action_rows)}")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("domain", style="bold", no_wrap=True)
        table.add_column("account", style="dim", no_wrap=True)
        table.add_column("notes")
        for r in action_rows:
            table.add_row(r.domain, r.hg_account_id, r.notes or "")
        console.print(table)

    # Footer summary + next-step hint.
    n_would = len(by_action.get("would_write", []))
    n_wrote = len(by_action.get("wrote", []))
    n_skipped = sum(
        len(by_action.get(k, []))
        for k in ("skipped_no_site_dir", "skipped_already", "skipped_archived")
    )
    console.print(
        f"\n[dim]{len(apply_rows)} HG rows · "
        f"{n_would} would-write · {n_wrote} wrote · "
        f"{n_skipped} skipped[/]"
    )
    if dry_run and n_would:
        console.print(
            "  [dim]Re-run with [bold]--apply[/bold] to actually write the files.[/]"
        )


def _print_skipped_footer(skipped: dict[str, str]) -> None:
    """Per resolution 11.H — each skipped provider/account gets a
    one-line footer so the operator sees why a known provider isn't
    in the table."""
    if not skipped:
        return
    console.print("")
    for label, reason in sorted(skipped.items()):
        console.print(f"  [dim]{label} skipped: {reason}[/]")


@fleet_app.command("check")
def fleet_check(
    detail: bool = typer.Option(False, "--detail"),
    check_id: str = typer.Option("", "--check"),
) -> None:
    """Cross-repo catalog summary across every sites/<domain>/ repo."""
    check_git(detail=detail, check_id=check_id, domain="", repo="")


@fleet_app.command("fix")
def fleet_fix(
    apply_changes: bool = typer.Option(False, "--apply"),
    rule_filter: list[str] = typer.Option(None, "--rule"),
    assume_yes: bool = typer.Option(False, "--yes"),
    use_ai: bool = typer.Option(False, "--ai"),
) -> None:
    """Fleetwide remediation — auto-fix conformance gaps across every eligible site."""
    _run_project_fix_all(apply_changes=apply_changes,
                         rule_filter=rule_filter,
                         assume_yes=assume_yes,
                         use_ai=use_ai)


@fleet_app.command("drift")
def fleet_drift() -> None:
    """Surface inconsistencies across the four sources of truth."""
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
    add_deploy_declarations: bool = typer.Option(
        False, "--add-deploy-declarations",
        help="v10.C migration: walk every sites/<dir>/ without a "
             "lamill.toml, classify by detected platform-config "
             "markers, write the file for unambiguous cases.",
    ),
    dry_run: bool = typer.Option(
        True, "--dry-run/--apply",
        help="When --add-deploy-declarations is set: --dry-run "
             "(default) shows the plan without writing; --apply "
             "actually writes lamill.toml files.",
    ),
    include_ambiguous: bool = typer.Option(
        False, "--include-ambiguous",
        help="When --add-deploy-declarations + --apply: also write "
             "for sites with multiple platform-config files, picking "
             "via vercel > cf-pages > cf-workers > netlify priority "
             "and embedding a notes warning. Default refuses ambiguous "
             "cases — operator must run `settings deploy set` "
             "manually.",
    ),
) -> None:
    """Audit each sites/<domain>/ for git-layer state (read-only).

    Classifies every site into one of: clean standalone, nested
    anti-pattern, standalone unpublished, monorepo-only, unversioned,
    or empty stub. Also flags any remote whose name truncates the
    domain (full-domain naming convention; CHECK_040 covers per-site).

    Write modes for the git-layer state (`--fix`, `--remote`) are
    intentionally not implemented in this version — audit-only by
    design. The `--add-deploy-declarations` flag (v10.C) is a
    separate migration sweep that writes `lamill.toml` files, not a
    git-layer fix.
    """
    # v10.C migration path.
    if add_deploy_declarations:
        from .project_deploy import (
            migrate_deploy_declarations,
            render_migration_summary,
        )
        rows = migrate_deploy_declarations(
            dry_run=dry_run,
            include_ambiguous=include_ambiguous,
        )
        if dry_run:
            console.print(
                "[dim]Dry-run — no files written. Re-run with "
                "[bold]--apply[/dim][/bold] [dim]to commit the plan.[/]"
            )
        render_migration_summary(rows, console)
        return

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
    probes (≈ same cost as `fleet domains` + `fleet seo --refresh`).
    """
    if scope not in ("wip", "all"):
        console.print(f"[red]--only must be 'wip' or 'all', got {scope!r}.[/]")
        raise typer.Exit(2)
    if sort not in ("attention", "name", "imp", "age"):
        console.print(f"[red]--sort must be attention|name|imp|age, got {sort!r}.[/]")
        raise typer.Exit(2)
    from .dashboard import run_dashboard
    run_dashboard(scope=scope, sort=sort, refresh=refresh, console=console)


@fleet_app.command("sync")
def fleet_sync(
    refresh_rdap: bool = typer.Option(
        False, "--refresh-rdap",
        help="Also fetch RDAP creation_date per domain (~0.5s each, ~15s for full fleet)."
    ),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="v15.F — pull live Porkbun domain list via API (writes data/domains/porkbun.csv) "
             "before merging. GoDaddy/Namecheap CSVs remain manual until those registrars' "
             "account-API setup lands.",
    ),
    watch: bool = typer.Option(
        False, "--watch",
        help="v15.F — block and re-merge whenever any data/domains/*.csv changes on disk. "
             "Composes with --refresh (initial pull then watch). Ctrl-C to exit.",
    ),
    interval: float = typer.Option(
        2.0, "--interval",
        help="Polling interval (seconds) for --watch. Ignored without --watch.",
    ),
) -> None:
    """Rebuild data/portfolio.json from registrar CSVs.

    Default: read existing CSVs and merge. `--refresh-rdap` adds the
    domain-age fetch. `--refresh` pulls live from Porkbun first.
    `--watch` runs continuously, re-merging on CSV change.
    """
    if refresh:
        _do_porkbun_refresh()

    info_cleanup(refresh_rdap=refresh_rdap)

    if watch:
        _watch_domains_loop(refresh_rdap=refresh_rdap, interval=interval)


def _do_porkbun_refresh() -> None:
    """v15.F — fetch Porkbun owned-domain list + write
    data/domains/porkbun.csv. Errors warn but don't fail the rest of
    `fleet sync` (operator may have CSVs already in place)."""
    from .apikeys import get_key
    from .data import DOMAINS_DIR
    from .porkbun_list import PorkbunListError, refresh_porkbun_csv

    api_key = get_key("PORKBUN_API_KEY") or ""
    secret = get_key("PORKBUN_SECRET_API_KEY") or ""
    if not api_key or not secret:
        console.print(
            "[yellow]⚠  --refresh skipped:[/] PORKBUN_API_KEY / "
            "PORKBUN_SECRET_API_KEY not set in portfolio.env. "
            "[dim](Add them via `lamill settings apikeys set`.)[/]"
        )
        return

    csv_path = DOMAINS_DIR / "porkbun.csv"
    console.print("[cyan]Porkbun listAll →[/] " + str(csv_path) + " ...")
    try:
        count = refresh_porkbun_csv(api_key, secret, csv_path)
    except PorkbunListError as e:
        console.print(f"[red]Porkbun refresh failed:[/] {e}")
        return
    console.print(f"[green]✓[/] wrote {count} rows to porkbun.csv")


def _watch_domains_loop(*, refresh_rdap: bool, interval: float) -> None:
    """v15.F — poll data/domains/*.csv mtimes; re-run info_cleanup on
    any change. Bounded by `interval` seconds (default 2s). Ctrl-C
    exits cleanly. Simpler than the `watchdog` library — no new
    dependency and good enough for the CSV-edit cadence."""
    import time
    from .data import DOMAINS_DIR

    console.print(
        f"[dim]Watching {DOMAINS_DIR} for CSV changes "
        f"(interval={interval:.1f}s) — Ctrl-C to exit.[/]"
    )

    def _snapshot_mtimes() -> dict[str, float]:
        out: dict[str, float] = {}
        if not DOMAINS_DIR.exists():
            return out
        for f in DOMAINS_DIR.glob("*.csv"):
            try:
                out[f.name] = f.stat().st_mtime
            except OSError:
                pass
        return out

    seen = _snapshot_mtimes()
    try:
        while True:
            time.sleep(interval)
            current = _snapshot_mtimes()
            if current == seen:
                continue
            changed = {
                name for name, mt in current.items()
                if seen.get(name) != mt
            }
            seen = current
            console.print(
                f"\n[dim]→ CSV change detected ({', '.join(sorted(changed))}); "
                f"re-running merge ...[/]"
            )
            info_cleanup(refresh_rdap=refresh_rdap)
    except KeyboardInterrupt:
        console.print("\n[yellow](watch interrupted)[/]")
        return


# ---------- settings namespace ----------


@settings_catalog_app.command("list")
def settings_catalog_list(
    category: str = typer.Option("", "--category", "-c"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """List every check in the catalog."""
    check_catalog(category=category, json_out=json_out)


@settings_catalog_app.command("describe")
def settings_catalog_describe(
    check_id: str = typer.Argument(..., help="Check ID (e.g. CHECK_001)"),
) -> None:
    """Show one check's metadata + source link."""
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
    """Set up / refresh GSC OAuth — one-time interactive login."""
    gsc_auth(force=force)


# v18.C — settings ga4 auth (parallel shape to settings gsc auth)


@settings_ga4_app.command("auth")
def settings_ga4_auth(
    force: bool = typer.Option(
        False, "--force",
        help="Force re-auth even if a valid token is cached"),
) -> None:
    """Set up / refresh GA4 Admin API OAuth — one-time interactive login.

    Used by `new bootstrap` (v18.D) to auto-create GA4 properties for
    new domains. Token is cached at `~/lamill/ga4/token.json` and
    refreshes automatically for ~6 months. Re-run with `--force` after
    operator changes the GA4 account they want lamill to manage."""
    from .ga4_admin import (
        MissingCredentialsError as GA4MissingCredentialsError,
        TOKEN_PATH as GA4_TOKEN_PATH,
        authenticate as ga4_authenticate,
    )

    try:
        console.print(
            "[cyan]Opening a browser for Google sign-in. Approve "
            "access to Google Analytics (analytics.edit scope).[/]"
        )
        ga4_authenticate(force=force)
    except GA4MissingCredentialsError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(1)
    console.print(
        f"[green]Authenticated.[/] Token cached at [dim]{GA4_TOKEN_PATH}[/]"
    )


@settings_gsc_app.command("recrawl")
def settings_gsc_recrawl(
    site: str = typer.Option(..., "--site",
                             help="Site domain (e.g. washcalc.app). Must be a "
                                  "registered GSC property and have a "
                                  "sites/<domain>/ directory."),
    urls: str = typer.Option(None, "--urls",
                             help="Path to a newline-list of URLs to inspect. "
                                  "Default: every URL in the site's sitemap."),
    since: str = typer.Option(None, "--since",
                              help="ISO-8601 baseline timestamp (e.g. "
                                   "2026-05-15T12:39Z). Default: HEAD commit "
                                   "time of the site's git repo."),
    no_append: bool = typer.Option(False, "--no-append",
                                   help="Print the report but don't append it "
                                        "to docs/growth.md."),
) -> None:
    """Report which sitemap URLs Google has re-crawled since a baseline.

    Read-only — uses webmasters.readonly scope. CANNOT trigger a re-crawl;
    Google's Indexing API is officially restricted to JobPosting and
    BroadcastEvent content. For general web pages, "Request Indexing"
    must still be clicked manually in Search Console.

    Quota: urlInspection.index.inspect is capped at ~2000/property/day.
    Default URL set comes from the site's sitemap (typically 5-50 URLs);
    batch large sites by passing --urls explicitly.
    """
    from pathlib import Path
    from .gsc_recrawl import (
        RecrawlError, append_to_growth_md, format_markdown_report,
        read_urls_from_file, resolve_site_dir, run_recrawl,
    )
    try:
        site_dir = resolve_site_dir(site)
    except RecrawlError as e:
        console.print(f"[red]Recrawl error:[/] {e}")
        raise typer.Exit(2)

    url_list = None
    if urls:
        url_path = Path(urls).expanduser()
        if not url_path.is_file():
            console.print(f"[red]--urls file not found:[/] {url_path}")
            raise typer.Exit(2)
        url_list = read_urls_from_file(url_path)
        if not url_list:
            console.print(f"[red]--urls file is empty:[/] {url_path}")
            raise typer.Exit(2)

    try:
        report = run_recrawl(site, urls=url_list, since=since)
    except RecrawlError as e:
        console.print(f"[red]Recrawl error:[/] {e}")
        raise typer.Exit(2)
    except Exception as e:
        console.print(f"[red]Inspection failed:[/] {type(e).__name__}: {e}")
        raise typer.Exit(2)

    md = format_markdown_report(report)
    console.print(md)

    if not no_append:
        try:
            written = append_to_growth_md(site_dir, md)
            console.print(f"\n[dim]Appended to {written.relative_to(site_dir)}[/]")
        except OSError as e:
            console.print(f"[yellow]warn: could not append to growth.md: {e}[/]")


@settings_gsc_app.command("status")
def settings_gsc_status(
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Pull latest GSC totals + write a snapshot."),
    days: int = typer.Option(28, "--days", "-d",
                             help="Window size for --refresh"),
    lag_days: int = typer.Option(3, "--lag-days"),
    concurrency: int = typer.Option(5, "--concurrency", "-c"),
) -> None:
    """GSC integration status. Default: verified properties + WIP-domain
    cross-reference + latest snapshot diff. `--refresh` pulls fresh
    totals + writes a new snapshot.
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
    """List every known credential in portfolio.env, with a set/not-set
    marker AND a connectivity tick per provider.

    Probes hit each provider's API once (~5-10s total). Catches typos
    immediately rather than discovering failures later when the actual
    feature uses the credential.
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
    """Set a credential in portfolio.env. Strict by default (only known
    keys); `--force` allows arbitrary key names.

    Atomic write — preserves comments, blank lines, and ordering of
    untouched keys. Existing keys are updated in place; new keys append.
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
    """Remove a credential from portfolio.env."""
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


@settings_operator_app.command("show")
def settings_operator_show() -> None:
    """Print the loaded operator profile from sites/portfolio/lamill.toml.

    Shows "no profile configured" if the file or [operator] section is
    absent. When configured, prints each field on its own line. Used by
    `new validate` to apply expertise / workflow / cadence fit-checks
    on top of the three gates.
    """
    from .operator_profile import LAMILL_TOML, load_operator_profile

    profile = load_operator_profile()

    if not profile.configured:
        console.print("[dim]No operator profile configured.[/]")
        console.print(
            f"[dim]Add an \\[operator] section to {LAMILL_TOML} — "
            f"see docs/prd.md §8.3 §4.1.[/]"
        )
        return

    console.print(f"[bold]Operator profile[/] [dim]({LAMILL_TOML})[/]")
    if profile.expertise:
        console.print("  expertise:")
        for item in profile.expertise:
            console.print(f"    · {item}")
    else:
        console.print("  expertise: [dim](none)[/]")
    console.print(f"  workflow_preference: {profile.workflow_preference}")
    console.print(f"  motivation_cadence:  {profile.motivation_cadence}")


# settings cloudflare — set + inspect the CF API token used by CHECK_057's
# tier-1 purge fix. Parallel to `settings gsc {auth,status}`.


@settings_cloudflare_app.command("token")
def settings_cloudflare_token(
    no_verify: bool = typer.Option(
        False, "--no-verify",
        help="Save without hitting CF to verify the token works.",
    ),
) -> None:
    """Save a Cloudflare API token to ~/.config/portfolio/cloudflare/token.

    Prompts for the token (hidden input), writes it to the standard path
    at mode 0600, then verifies it by calling CF's
    `GET /user/tokens/verify` endpoint — catches paste errors / wrong
    permissions before the next `project fix --apply` discovers them.

    Create the token at https://dash.cloudflare.com/profile/api-tokens →
    Create Custom Token → Permissions: Zone | Cache Purge | Purge →
    Zone Resources: Include | All zones.
    """
    from . import cloudflare

    token = typer.prompt("Cloudflare API token", hide_input=True).strip()
    if not token:
        console.print("[red]Empty token — nothing saved.[/]")
        raise typer.Exit(2)

    try:
        cloudflare.save_token(token)
    except (OSError, ValueError) as e:
        console.print(f"[red]Failed to save token:[/] {e}")
        raise typer.Exit(2)
    console.print(f"[green]✓ Saved token to {cloudflare.TOKEN_PATH} (mode 0600)[/]")

    if no_verify:
        console.print("[dim](skipped verification — run "
                      "`settings cloudflare status --verify` later)[/]")
        return

    console.print("[cyan]Verifying token with Cloudflare...[/]")
    try:
        info = cloudflare.verify_token()
    except cloudflare.CloudflareAPIError as e:
        console.print(f"[red]Token saved but verification failed:[/] {e}")
        console.print("[yellow]Double-check the token has Zone:Cache Purge "
                      "permission and didn't get truncated when pasted.[/]")
        raise typer.Exit(2)
    status = info.get("status", "unknown")
    expires = info.get("expires_on") or "never"
    console.print(f"[green]✓ Verified — status={status}, expires={expires}[/]")


@settings_cloudflare_app.command("status")
def settings_cloudflare_status(
    verify: bool = typer.Option(
        False, "--verify",
        help="Also hit CF to confirm the saved token is still valid.",
    ),
) -> None:
    """Show Cloudflare config state — is a token saved, is the parent
    directory locked down, and how many zone IDs are cached locally.

    Doesn't print the token itself. `--verify` makes one network call
    against `GET /user/tokens/verify` to confirm CF still accepts it.
    """
    from . import cloudflare

    state = cloudflare.token_status()
    console.print("[bold]Cloudflare configuration[/]")
    console.print(f"  Token path:      {state['token_path']}")
    if state["token_present"]:
        console.print(f"  Token present:   [green]yes[/] (mode {state['token_mode']})")
    else:
        console.print("  Token present:   [red]no[/]")
        console.print(
            "  [dim]Configure with: `settings cloudflare token`[/]"
        )
    console.print(f"  Parent dir mode: {state['parent_mode'] or '[dim](missing)[/]'}")
    console.print(f"  Zone-id cache:   {state['zones_cache_path']} "
                  f"({state['zones_cached']} domain(s) cached)")

    if not verify:
        return
    if not state["token_present"]:
        console.print("[yellow]Skipping --verify — no token saved.[/]")
        raise typer.Exit(1)
    console.print("\n[cyan]Verifying with Cloudflare...[/]")
    try:
        info = cloudflare.verify_token()
    except cloudflare.MissingCredentialsError as e:
        console.print(f"[red]No token:[/] {e}")
        raise typer.Exit(1)
    except cloudflare.CloudflareAPIError as e:
        console.print(f"[red]Token rejected:[/] {e}")
        raise typer.Exit(1)
    console.print(
        f"[green]✓ Token OK[/] — status={info.get('status', '?')}, "
        f"id={info.get('id', '?')}, expires={info.get('expires_on') or 'never'}"
    )


# settings serpapi-quota — show local ledger + sync against SerpAPI's
# authoritative /account endpoint when the two have drifted.


@settings_serpapi_app.command("show")
def settings_serpapi_quota_show() -> None:
    """Print the local SerpAPI quota ledger state.

    Local-only — no network call. If the local number looks wrong
    (e.g., reports exhausted but SerpAPI's dashboard says otherwise),
    use `settings serpapi-quota sync` to overwrite with the
    authoritative numbers from SerpAPI's /account endpoint.
    """
    from .serpapi_quota import quota_pct_used, read_quota

    q = read_quota()
    pct = int(quota_pct_used() * 100)
    color = "red" if pct >= 95 else "yellow" if pct >= 80 else "green"
    console.print("[bold]SerpAPI quota (local ledger)[/]")
    console.print(f"  Month:        {q['month']}")
    console.print(
        f"  Used:         [{color}]{q['queries_used']}/{q['limit']} "
        f"({pct}%)[/]"
    )
    console.print(f"  Last update:  {q.get('last_updated') or '—'}")
    synced = q.get("synced_with_serpapi_at")
    if synced:
        console.print(f"  Last sync:    {synced}")
    else:
        console.print(
            "  [dim]Ledger has never been synced with SerpAPI. "
            "Run `lamill settings serpapi-quota sync` to verify.[/]"
        )


@settings_serpapi_app.command("sync")
def settings_serpapi_quota_sync() -> None:
    """Sync the local ledger with SerpAPI's authoritative /account record.

    Pulls `this_month_usage` + `searches_per_month` from SerpAPI and
    overwrites the local file. Useful when the counter has drifted
    (e.g., shows exhausted but the SerpAPI dashboard shows headroom).
    """
    from .apikeys import get_key
    from .serpapi_quota import (
        QuotaSyncError, quota_pct_used, read_quota, sync_with_serpapi,
    )

    api_key = get_key("SERPAPI_KEY") or ""
    if not api_key:
        console.print(
            "[red]SERPAPI_KEY not set.[/] Set it with "
            "`lamill settings apikeys set SERPAPI_KEY <your-key>` first."
        )
        raise typer.Exit(2)

    before = read_quota()
    console.print(
        f"[dim]Before sync: {before['queries_used']}/{before['limit']} "
        f"({int(quota_pct_used()*100)}%)[/]"
    )
    console.print("[cyan]Syncing with SerpAPI /account...[/]")
    try:
        after = sync_with_serpapi(api_key)
    except QuotaSyncError as e:
        console.print(f"[red]Sync failed:[/] {e}")
        raise typer.Exit(2)
    drift = before["queries_used"] - after["queries_used"]
    drift_note = ""
    if drift > 0:
        drift_note = (
            f"  [yellow]Local ledger was over-counting by {drift} call(s); "
            f"overwritten with SerpAPI's records.[/]"
        )
    elif drift < 0:
        drift_note = (
            f"  [yellow]Local ledger was under-counting by {-drift} call(s); "
            f"overwritten with SerpAPI's records.[/]"
        )
    console.print(
        f"[green]✓ Synced:[/] {after['queries_used']}/{after['limit']} "
        f"this UTC month ({int(after['queries_used']/after['limit']*100)}%)"
    )
    if drift_note:
        console.print(drift_note)


if __name__ == "__main__":
    app()
