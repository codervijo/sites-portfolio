"""v35.F incr 10 — `fleet` command implementation helpers, extracted from
cli.py (behavior-preserving, H1; approach A — sibling module).

The impl functions behind the fleet commands (focus / live / domains
summary+expiring / sync-cleanup / drift / hosting) plus their refresh +
watch + footer helpers. All fleet-exclusive; the `@fleet_app.command(...)`
callbacks stay in cli.py and delegate to these. Renderers + colour maps are
imported from check_render one-directionally (no cycle).
"""
from __future__ import annotations

from collections import Counter
from datetime import date

import typer
from rich.table import Table

from .check import run_check
from .check_render import LIVE_CLS_COLORS, _render_status
from .console import console, spinner_counter
from .data import cleanup as run_cleanup, load_domains, load_plan


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
            with spinner_counter("SEO probes", len(domains)) as progress:
                seo_rows = run_seo(domains, days=28, crux_api_key=crux_key,
                                   progress_callback=progress)
            cache_path = seo_save_snapshot(seo_rows, days=28)
            console.print(f"[green]✓[/] SEO probes: {len(domains)} domains "
                          f"({cache_path.name}) · {progress.elapsed:.0f}s")

    # Pull every signal source. None / empty means "skip that signal."
    live_path = live_latest()
    live_data = load_live(live_path) if live_path else None

    seo_path = seo_latest()
    seo_data = load_seo(seo_path) if seo_path else None

    all_domains = load_domains()

    # 2026-05-29 — honor `[fleet] dark_sites` (per docs/CLAUDE.md global
    # memory "Dark sites — not for public SEO"): drop internal/private
    # domains from every focus surface (CF cache probe, signal
    # aggregation, ranked output). Mirrors the same config knob that
    # `fleet fix` already honors at cli.py:8259.
    from .checks.config import load_config as _focus_load_cfg
    _focus_dark = {s.lower() for s in _focus_load_cfg().dark_sites}
    if _focus_dark:
        all_domains = [
            d for d in all_domains if d.name.lower() not in _focus_dark
        ]

    domains_expiry = domains_with_expiry_from_portfolio(all_domains)
    # Build domain → category map so focus can skip "To be deleted immediately"
    # rows. Lowercase keys for case-insensitive matching.
    domain_categories = {d.name.lower(): (d.category or "") for d in all_domains}
    # Registrar-truth mute: auto_renew=off ⇒ operator is letting it lapse ⇒
    # suppress all focus nags (no plan.md edit + resync needed). v31 made
    # auto_renew live from the GoDaddy API.
    auto_renew_off = {
        d.name.lower() for d in all_domains
        if (d.auto_renew or "").strip().lower() == "off"
    }

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

    # v27.F — 📝 todo signal. Each site's top open `high`-priority todo
    # becomes a focus one-liner. Reads `lamill.toml` only (no fetch), so
    # it's available even when --refresh is off and no live snapshot
    # exists — honoring focus's "never blocks on a live fetch" contract.
    # Additive-optional: a site with no lamill.toml / no [[todo]] table /
    # no high open todo contributes nothing; a malformed file is skipped
    # rather than sinking the whole run.
    from .fleet_repos import list_site_dirs as _focus_list_site_dirs
    from .lamill_toml import ParseError as _FocusParseError
    from .todos import build_project_todos as _focus_build_project_todos

    domain_high_todos: dict[str, str] = {}
    for _site_dir in _focus_list_site_dirs():
        try:
            _pt = _focus_build_project_todos(_site_dir, domain=_site_dir.name)
        except _FocusParseError:
            continue
        _high = next(
            (t for t in _pt.open_items if t.priority == "high"), None
        )
        if _high is not None:
            domain_high_todos[_site_dir.name.lower()] = _high.task

    suppressed_young: list[str] = []
    items = build_focus_list(
        live_snapshot=live_data,
        seo_snapshot=seo_data,
        domains_with_expiry=domains_expiry,
        domain_categories=domain_categories,
        auto_renew_off=auto_renew_off,
        domain_site_age_days=domain_site_age,
        domain_check_failures=domain_check_failures,
        domain_high_todos=domain_high_todos,
        include_young=include_young,
        suppressed_young_out=suppressed_young,
    )

    # 2026-05-29 — second pass on the output: build_focus_list iterates
    # over live/seo snapshot data directly, so a dark site that was
    # probed before being marked dark would still surface a signal from
    # the cache. Drop those here.
    if _focus_dark:
        _items_before = len(items)
        items = [it for it in items if it.domain.lower() not in _focus_dark]
        _dark_skipped = _items_before - len(items)
    else:
        _dark_skipped = 0

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

    # Surface the dark-site exclusion (mirrors the `fleet fix` footer).
    # Silent exclusion hides the wrong-default risk. `\[fleet\]` escapes
    # the literal brackets so Rich doesn't read them as a markup tag.
    if _focus_dark:
        console.print(
            f"\n[dim]↷ excluding {len(_focus_dark)} dark site(s): "
            f"{', '.join(sorted(_focus_dark))} "
            f"(edit [cyan]\\[fleet] dark_sites[/] in config.toml to change)[/]"
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
        hit = miss = 0
        with spinner_counter("RDAP creation dates", len(domains)) as progress:
            for i, d in enumerate(domains, start=1):
                progress(i, len(domains), d.name)
                if d.domain_created is not None:
                    # Already cached — RDAP creation_date doesn't change. Skip.
                    hit += 1
                    continue
                cd = rdap_creation_date(d.name)
                if cd is not None:
                    update_domain_field(d.name, "domain_created", cd)
                    hit += 1
                else:
                    miss += 1
        console.print(f"[green]✓[/] RDAP creation dates: {hit} resolved · "
                      f"{miss} unresolved · {progress.elapsed:.0f}s")

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


def _do_godaddy_refresh() -> None:
    """v31.B — fetch GoDaddy domains via the Management API + merge-refresh
    data/domains/godaddy.csv (expiry/status/auto-renew/NS), preserving the
    manual export's other columns. Soft-fail: warn + keep the existing CSV
    when keys are absent or the API errors (mirrors `_do_porkbun_refresh`)."""
    from . import godaddy
    from .apikeys import get_key
    from .data import DOMAINS_DIR

    api_key = get_key("GODADDY_API_KEY") or ""
    secret = get_key("GODADDY_API_SECRET") or ""
    if not api_key or not secret:
        console.print(
            "[yellow]⚠  --refresh: GoDaddy skipped[/] — GODADDY_API_KEY / "
            "GODADDY_API_SECRET not set in portfolio.env. "
            "[dim](Add them via `lamill settings apikeys set`.)[/]"
        )
        return
    csv_path = DOMAINS_DIR / "godaddy.csv"
    console.print("[cyan]GoDaddy /v1/domains →[/] " + str(csv_path) + " ...")
    try:
        count = godaddy.refresh_godaddy_csv(api_key, secret, csv_path)
    except godaddy.GoDaddyError as e:
        console.print(f"[red]GoDaddy refresh failed:[/] {e}")
        return
    console.print(f"[green]✓[/] wrote {count} rows to godaddy.csv")


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
