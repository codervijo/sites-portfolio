from __future__ import annotations

import re
from collections import Counter
from datetime import date

import typer
from rich.markup import escape
from rich.table import Table

from .check import (
    best_per_domain,
    latest_snapshot,
    list_snapshots,
    load_snapshot,
    previous_snapshot,
    run_check,
)
from .console import console, spinner_counter
from .data import PORTFOLIO_JSON, cleanup as run_cleanup, load_domains, load_plan

app = typer.Typer(
    help="lamill — manage your domain fleet + sites/ workspace.",
    add_completion=False,
)

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


# `info wip` was removed in v5.F.1 — covered by `info list --grouped`
# (the user picks the WIP-relevant categories visually). Deprecation
# shim lives at the bottom of the file with the other v5.F shims.

# `info category` was merged into `info list` in v5.F.1 — same single
# command supports flat (default), grouped, and category-filtered modes.
# Deprecation shim at the bottom of the file.


_SEVERITY_COLOR = {"error": "red", "warn": "yellow", "info": "cyan"}


# ---------- v5.F.2: check live / git / seo as real subcommands ----------
#
# Pre-v5.F.2 these were callback flags (`check --live`, `check --git`,
# `check --seo`). The callback form is preserved as a deprecation alias
# (see `check_callback` below) so existing scripts keep working through
# one transition window.


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
    sort_by: str = typer.Option("domain", "--sort",
                                help="Sort by: domain (default, alphabetical) | impressions | clicks | position | ctr"),
    refresh: bool = typer.Option(False, "--refresh",
                                 help="Ignore cached SEO snapshot and re-probe (HTTP + GSC + CrUX)"),
    since: str = "",
) -> None:
    """Per-domain runtime SEO probe — HTTP + GSC + CrUX.

    Reads from `data/seo/<latest>.json` by default if it covers every
    domain in scope. `--refresh` forces a fresh probe and overwrites
    today's cache file. `--domain <one>` always probes fresh. `since`
    (e.g. "7d"/"28d") appends a Δ column on the fleet path — empty == off.
    """
    target = _resolve_domain_repo_synonyms(domain, repo)
    _run_check_seo_mode(days=days, only_domain=target, sort_by=sort_by,
                        only=only, concurrency=concurrency, refresh=refresh,
                        since=since)


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


_SINCE_ALLOWED = {7: "7d", 28: "28d"}


def _parse_since(since: str) -> int | None:
    """`"7d"`/`"28d"` → 7/28. Empty/None → None (Δ off). Anything else exits."""
    if not since:
        return None
    s = since.strip().lower()
    m = re.fullmatch(r"(\d+)d?", s)
    n = int(m.group(1)) if m else None
    if n not in _SINCE_ALLOWED:
        console.print(
            f"[red]--since must be one of {', '.join(_SINCE_ALLOWED.values())}, "
            f"got {since!r}.[/]"
        )
        raise typer.Exit(2)
    return n


def _seo_deltas_for(rows, *, current_path, since: str):
    """Pair `rows` (the current snapshot) against an earlier baseline and
    return `(deltas, baseline_pick)` — or `(None, None)` when Δ is off.

    `deltas` is non-None whenever Δ is requested (so the column renders),
    even if the pick is None (renderer shows the "no baseline" footer)."""
    since_days = _parse_since(since)
    if since_days is None:
        return None, None
    from .seo_cache import list_snapshots
    from .seo_delta import compute_deltas, load_baseline_rows, pick_baseline
    from datetime import date as _date

    name = current_path.name if current_path is not None else ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", name)
    current_date = (_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    if m else _date.today())
    pick = pick_baseline(list_snapshots(), since_days=since_days,
                         current_date=current_date)
    if pick is None:
        return {}, None
    return compute_deltas(rows, load_baseline_rows(pick)), pick


def _run_check_seo_mode(*, days: int, only_domain: str, sort_by: str,
                        only: str, concurrency: int,
                        refresh: bool = False, since: str = "") -> None:
    """Driver for `portfolio check seo`. Picks domains from the latest
    classification snapshot (live-site + forwarder), reads cached SEO
    data when available (or runs HTTP/GSC/CrUX probes when `refresh` is
    set or no cache exists), renders one row per domain.

    Caching (v5.F.1): without `--refresh`, reads `data/seo/<latest>.json`
    if it exists and includes all needed domains. With `--refresh`, runs
    the full probe and overwrites today's cache file. `--domain <one>`
    always probes fresh (single-domain runs aren't cached).
    """
    from .check import all_domains as _all_domains
    from .check import latest_snapshot as live_latest_snapshot
    from .check import load_snapshot, run_check
    from .check import wip_domains as _wip_domains
    from .seo_cache import (
        latest_snapshot as seo_latest_snapshot,
        load_snapshot as seo_load_snapshot,
        rows_from_snapshot,
        save_snapshot as seo_save_snapshot,
    )
    from .seo_runtime import _live_domains_from_snapshot, run_seo, sort_rows
    from .suggest import load_env

    if sort_by not in ("domain", "impressions", "clicks", "position", "ctr"):
        console.print(f"[red]--sort must be domain|impressions|clicks|position|ctr, got {sort_by!r}[/]")
        raise typer.Exit(2)
    if only not in ("wip", "all"):
        console.print(f"[red]--only must be 'wip' or 'all', got {only!r}.[/]")
        raise typer.Exit(2)
    _parse_since(since)  # fail fast on a bad --since before any probing

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
            _live_total = len(_wip_domains() if only == "wip" else _all_domains())
            with spinner_counter(f"live classification ({only})", _live_total) as live_prog:
                snap_path, _ = run_check(only=only, concurrency=concurrency,
                                         progress=live_prog)
            console.print(f"[green]✓[/] live classification: {snap_path.name} · "
                          f"{live_prog.elapsed:.0f}s")

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
                deltas, pick = _seo_deltas_for(rows, current_path=cache_path,
                                               since=since)
                _render_seo_table(rows, days=cached.get("days", days),
                                  sort_by=sort_by, deltas=deltas, delta_meta=pick)
                return

    env = load_env()
    crux_key = env.get("CRUX_API_KEY", "").strip()
    if not crux_key:
        console.print("[dim]CRUX_API_KEY not set in portfolio.env — Core Web Vitals columns will be empty.[/]")

    with spinner_counter("SEO probes", len(domains)) as progress:
        rows = run_seo(domains, days=days, crux_api_key=crux_key,
                       progress_callback=progress)
    console.print(f"[green]✓[/] SEO probes: {len(domains)} domain(s) — "
                  f"HTTP + GSC ({days}d) + CrUX · {progress.elapsed:.0f}s")

    fresh_path = None
    if cache_eligible:
        fresh_path = seo_save_snapshot(rows, days=days)
        console.print(f"[dim]Cached: {fresh_path.name}[/]")

    rows = sort_rows(rows, sort_by)
    # Δ only on the fleet path (a single --domain run has no current
    # snapshot to anchor the diff).
    deltas, pick = ((None, None) if not cache_eligible
                    else _seo_deltas_for(rows, current_path=fresh_path, since=since))
    _render_seo_table(rows, days=days, sort_by=sort_by,
                      deltas=deltas, delta_meta=pick)


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
    # 2026-05-24 — multi-line capable so pasted product descriptions don't
    # leak the rest of the paste into the shell as command-not-found
    # noise after typer.prompt's single-line read returns. Empty line
    # submits; pasted bullets are stripped + concatenated to a single
    # phrase the cluster-expansion LLM can handle.
    topic = _prompt_topic_multiline()
    if not topic:
        console.print("[red]Topic cannot be empty.[/]")
        raise typer.Exit(2)
    return topic


def _prompt_topic_multiline() -> str:
    """Read a topic from stdin, supporting both single-line and pasted
    multi-line input. Terminates on an empty line.

    Why this exists: `typer.prompt()` reads exactly one line. When the
    operator pastes a multi-line product brief, only line 1 lands in
    the prompt and the remaining lines end up in the shell as commands
    ("Digital: command not found", etc.). Reading until an empty line
    consumes the whole paste before control returns to the shell.

    Single-line case still works: type the topic, press Enter (which
    yields an empty next-line submit).

    Pasted lines are stripped of common bullet prefixes (`- `, `* `,
    `• `) and concatenated with `. ` separators into a phrase suitable
    for the cluster-expansion LLM.
    """
    console.print(
        "[bold]Topic[/] "
        "[dim](type or paste; finish with an empty line — Enter on a "
        "blank line submits)[/]: ",
        end="",
    )
    raw_lines: list[str] = []
    bullet_prefixes = ("- ", "* ", "• ", "·  ", "·")
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            if raw_lines:
                break
            # Empty line before any content — keep waiting.
            continue
        stripped = line.strip()
        for prefix in bullet_prefixes:
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].lstrip()
                break
        raw_lines.append(stripped)
    return ". ".join(raw_lines)


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
    skip_ga4: bool = typer.Option(
        False, "--skip-ga4",
        help="v18.D — skip GA4 property auto-creation for this site. "
             "Default attempts to create a GA4 property + web stream "
             "via the Admin API (requires GA4 OAuth + GA4_ACCOUNT_ID) "
             "and writes the resulting measurement ID into the new "
             "site's `lamill.toml [analytics] ga4_id`. Pass `--skip-ga4` "
             "for dark sites (csinorcal.church etc.) or when GA4 isn't "
             "appropriate.",
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
                    "Run `lamill fleet sync --refresh` to pull the "
                    "latest Porkbun list (most common case after a "
                    "fresh purchase). If you're sure the domain is "
                    "yours, pass --force to bootstrap anyway."
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

    # Bug-fix 2026-05-28 — copy-paste LLM prompt template. Printed after
    # the preflight banner so the operator can stage the 6 content
    # sections in ChatGPT/claude.ai and paste the whole reply at the
    # first prompt (smart-paste fills the rest). No-op on --non-interactive
    # or when every content section is already flag-supplied.
    _render_llm_prompt_template(
        domain=domain, topic=topic, non_interactive=non_interactive,
        summary=summary, audience=audience, icp=icp, goal=goal,
        content_strategy=content_strategy,
        growth_hypothesis=growth_hypothesis,
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
            skip_ga4=skip_ga4,
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


# Bug-fix 2026-05-20 — Lovable GitHub repo URL prompt. The operator's
# common workflow is: design UI in Lovable.dev → Lovable exports a
# GitHub repo → bootstrap clones that repo as a new sites/<domain>/
# project. The `--git-url` flag already wires this through the
# `--from-genai` path; this helper adds the interactive surface.


# Bug-fix 2026-05-20 — pre-flight banner. Print the full list of
# prompts BEFORE the first prompt fires so the operator can prep
# paragraph-length answers or hit Enter to skip. Skipped when running
# non-interactively or when every per-section flag is supplied (no
# prompts would fire anyway).


# Bug-fix 2026-05-28 — copy-paste LLM prompt template. Before the first
# interactive prompt, print a ready-to-paste prompt the operator can drop
# into ChatGPT / claude.ai. The template instructs the LLM to format its
# reply in the EXACT numbered+labeled shape the smart-paste parser
# (bootstrap_paste) expects, so the operator pastes the whole reply at the
# first prompt and every section auto-fills. Pairs with the multi-section
# paste parser (2026-05-25) to make the LLM-stage → paste workflow one step.


# v9.D — growth-hypothesis prompt. Single prompt for one paragraph
# that seeds docs/growth.md's first dated entry.


# v9.C — domain-registration prompt + portfolio.json auto-update.
# Shape: `_resolve_inventory_inputs` gathers the operator's intent
# (registered?, registrar?) ONCE — before the bootstrap call —
# returning a dict the post-bootstrap code consumes. Failures in
# `run_bootstrap` don't waste the prompt answers; re-running with
# the same flags is idempotent.


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


# ---------- v13.B — per-project GSC diagnostics ----------


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


# v35.F (H1) — SERP-synthesis renderers + the v13.B SEO-diagnostics
# renderer extracted to research_render.py. Re-imported into this namespace
# so existing `from portfolio.cli import _render_*` (tests) and in-module
# callers (e.g. _run_project_seo_diagnostics) keep working unchanged.
from .research_render import (  # noqa: E402
    _render_trends,
    _render_fleet_seo_detail,
    _SITEMAP_STATUS_GLYPH,
    _SYNTHESIS_PREFIX,
    _UNSAFE_SYNTHESIS_FIELDS,
    _VERDICT_BLOCKED_BLOCK,
    _VERDICT_COLOR,
    _confidence_color,
    _coverage_glyph,
    _gate_marker,
    _hint_severity_color,
    _human_age_from_iso,
    _render_gates_block,
    _render_primary_verdict_block,
    _render_project_seo_diagnostics,
    _render_reconciliation_block,
    _render_research_v2_full,
    _render_serp_brief,
    _render_serp_full,
    _render_serp_json,
    _strip_unsafe_synthesis_fields,
    _verdict_marker,
)

# v35.F (H1) incr 4 — the `new domain` menu/decide/grid engine + its two
# orchestrators + shared input parsers extracted to cli_domain.py. Re-imported
# into this namespace so the `@new_app.command("domain")` callback above and
# existing `from portfolio.cli import _menu_*/parse_*` (tests) keep working
# unchanged. cli_domain depends only on the neutral .console (no cli import),
# so there is no import cycle.

# v35.F incr 7 — fleet/project check + SEO/status/GSC renderers + their
# shared formatting leaves extracted to check_render.py. Re-imported so
# command callbacks (check_live, fleet/project check, project seo) + tests
# using `from portfolio.cli import X` stay unchanged. check_render imports
# nothing from cli (one-directional), so no cycle.

# v35.F incr 8 — `new bootstrap` helpers/renderers extracted to
# bootstrap_cli.py (one-directional import; no cycle). Re-exported so the
# bootstrap command callback + tests using `from portfolio.cli import X`
# stay unchanged.

# v35.F incr 9 — `new validate` research orchestration extracted to
# research_cli.py (one-directional; imports renderers from research_render).

# v35.F incr 10 — fleet command impl helpers extracted to fleet_cli.py
# (one-directional; renderers from check_render). Re-exported so the
# @fleet_app.command callbacks + tests stay unchanged.

# v35.F incr 11 — fix engine -> fix_cli.py; shared repo-walk -> neutral
# repo_walk.py (breaks the cli<->fix_cli cycle). repo_walk names are also
# used directly by _run_check_git_mode (stays here); fix names re-exported.
from .repo_walk import _is_likely_repo, _iterate_repos  # noqa: E402
from .fix_cli import (  # noqa: E402
    _DELETE_CATEGORY,
    _TIER_2_COST_ESTIMATE_USD,
    _list_fleet_eligible_projects,
    _run_project_fix_all,
)

from .fleet_cli import (  # noqa: E402
    _do_godaddy_refresh,
    _do_porkbun_refresh,
    _fleet_hosting_apply_declarations,
    _fleet_hosting_impl,
    _hg_accounts_disk_summary,
    _print_skipped_footer,
    _watch_domains_loop,
    check_live,
    focus,
    info_cleanup,
    info_drift,
    info_expiring,
    info_list,
    info_summary,
)

from .research_cli import (  # noqa: E402
    _prompt_for_moat,
    _run_audit_pass_and_reconcile,
    _run_gates_with_prompt,
    _run_primary_interpretive_pass,
    _run_research_synthesis,
    _update_cost_summary,
)

from .bootstrap_cli import (  # noqa: E402
    _LLM_TEMPLATE_SECTIONS,
    _OPERATOR_SECTION_NUMBERS,
    _REGISTRARS,
    _apply_inventory_decision,
    _apply_multisection_paste,
    _collect_operator_inputs,
    _confirm_multisection_paste,
    _prompt_multiline,
    _prompt_registrar,
    _render_bootstrap_conformance,
    _render_bootstrap_preflight,
    _render_bootstrap_summary,
    _render_llm_prompt_template,
    _render_project_tree,
    _resolve_git_url,
    _resolve_growth_hypothesis,
    _resolve_inventory_inputs,
)

from .check_render import (  # noqa: E402
    CLASSIFICATION_COLORS,
    LIVE_CLS_COLORS,
    VERDICT_COLORS,
    _CATEGORY_LABEL,
    _CATEGORY_ORDER,
    _EMOJI_TO_RICH_COLOR,
    _MANUAL_HINTS,
    _color_value,
    _fmt_cls,
    _fmt_int,
    _fmt_ms,
    _fmt_pct,
    _fmt_pos,
    _render_action_plan,
    _render_common_failures,
    _render_gsc_snapshot,
    _render_per_repo_detail,
    _render_project_status,
    _render_seo_table,
    _render_single_check_table,
    _render_status,
    _render_summary_table,
    _sort_ids_by_category,
)

from .cli_domain import (  # noqa: E402
    COMING_SOON_HINTS,
    MENU_ITEMS,
    TLD_REFERENCE,
    TLD_REFERENCE_SUMMARY,
    _cell_str,
    _decide_step1_brand_collision,
    _decide_step2_uspto,
    _decide_step3_extensibility,
    _decide_step4_cost,
    _decide_step5_phone_test,
    _decide_step6_memory_test,
    _domain_suggest_browse,
    _domain_suggest_validation,
    _expand_and_pick,
    _menu_add_names,
    _menu_ask_ai,
    _menu_decide,
    _menu_expand,
    _menu_keys_hint,
    _menu_pick,
    _menu_shortlist,
    _menu_show_marked,
    _menu_widen,
    _parse_user_added_names,
    _post_pick_flow,
    _print_shortlist,
    _render_decide_table,
    _render_expanded_row,
    _render_grid,
    _render_menu,
    _render_tld_reference,
    _renewal_cliff_marker,
    parse_expand_input,
    parse_pick_input,
    parse_shortlist_input,
)


# v19.B — `lamill new trends <topic>` standalone Google Trends fetcher.


@new_app.command("trends")
def new_trends(
    topic: str = typer.Argument(
        ..., help="Topic to fetch trends for (e.g. 'home solar').",
    ),
    timeframe: str = typer.Option(
        "12m", "--timeframe", "-t",
        help="One of: 7d, 30d, 90d, 12m, 5y, all. Default 12m.",
    ),
    region: str = typer.Option(
        "", "--region", "-r",
        help="ISO country code (e.g. US, GB). Empty = worldwide.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit JSON instead of the rendered tables.",
    ),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Bypass the 24h cache and re-fetch from Google Trends.",
    ),
) -> None:
    """Fetch Google Trends data for a topic and render it.

    Uses `pytrends`. Per-topic cache at `data/gtrends/<topic-hash>.json`
    with 24h TTL. Pass `--refresh` to bypass. On HTTP 429 rate-limit,
    falls back to ANY cached payload (renderer prints a yellow stale-
    age warning header).

    For "what's trending right now" discovery, use Google Trends
    directly at https://trends.google.com/trending — the no-topic
    surface in this CLI was dropped 2026-05-22 PM after both
    pytrends daily endpoints AND Google's public RSS feed all
    returned 404s; no viable no-auth surface exists.

    Exits 2 on invalid `--timeframe`, 3 on pytrends fetch failure
    (network / rate-limit / parse error). 0 on success even when
    Google returns empty result sets.
    """
    from .gtrends import (
        GTrendsError, GTrendsRateLimitError, TIMEFRAME_MAP, fetch_trends,
    )

    if timeframe not in TIMEFRAME_MAP:
        console.print(
            f"[red]Invalid --timeframe {timeframe!r}.[/] "
            f"Pick one of: {', '.join(TIMEFRAME_MAP)}"
        )
        raise typer.Exit(2)

    try:
        payload = fetch_trends(
            topic, timeframe=timeframe, region=region, refresh=refresh,
        )
    except GTrendsRateLimitError as e:
        # Rate-limit hit AND no stale cache available (else fetch_trends
        # would have returned the cached payload). Render yellow
        # (transient) instead of red (permanent failure). Closes the
        # docs/bugs.md 2026-05-22 cryptic-429 entry.
        console.print(f"[yellow]Trends fetch rate-limited:[/] {e}")
        raise typer.Exit(3)
    except GTrendsError as e:
        # All other pytrends failures (network, ImportError-wrap,
        # parse error). Red — permanent or operator-side issue
        # (e.g., `uv sync` needed for the ImportError case).
        console.print(f"[red]Trends fetch failed:[/] {e}")
        raise typer.Exit(3)

    if json_out:
        import json as _json
        from dataclasses import asdict
        print(_json.dumps(asdict(payload), indent=2))
        return

    _render_trends(payload, console=console)


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
    skip_dns_purge: bool = typer.Option(
        False, "--skip-dns-purge",
        help=(
            "Skip Step 5.5 DNS parking-record purge (cf-workers only). "
            "Use when current DNS records are legitimate (Workers-managed "
            "from a prior run, or operator-curated) so the purge logic "
            "doesn't false-flag them as conflicts."
        ),
    ),
    skip_gsc: bool = typer.Option(False, "--skip-gsc", help="Skip the v24.C GSC property auto-registration step (cf-pages/cf-workers only)"),
    watch: bool = typer.Option(
        False, "--watch",
        help=(
            "After Steps 1-9 complete, block polling until zone is "
            "active + build success + live HEAD 200 (or 30 min "
            "timeout). Useful for fresh-domain deploys when you want "
            "single-command confirmation of full resolution. Ctrl-C "
            "to cancel cleanly."
        ),
    ),
    apply: bool = typer.Option(False, "--apply", help="Required to actually push files for hostgator/custom (dry-run default per ADR-0011)."),
    clear_forwarding: bool = typer.Option(
        False, "--clear-forwarding",
        help=(
            "v32.D — if Porkbun URL Forwarding is active on the apex (it "
            "pins the domain to Porkbun NS and silently blocks the CF "
            "cutover), delete it via the registrar API before setting NS. "
            "Confirm-gated unless --yes; idempotent (no-op when none)."
        ),
    ),
    repair: bool = typer.Option(
        False, "--repair",
        help=(
            "v32.F — recover a custom domain stuck in pending-verification / "
            "CF 1014: re-point the apex CNAME at the project's real "
            "*.pages.dev subdomain, then remove + re-add the custom domain so "
            "CF re-verifies. Confirm-gated unless --yes. cf-pages only."
        ),
    ),
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
            skip_dns_purge=skip_dns_purge,
            skip_gsc=skip_gsc,
            watch=watch,
            clear_forwarding=clear_forwarding,
            repair=repair,
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
    skip_dns_purge: bool = False,
    skip_gsc: bool = False,
    watch: bool = False,
    clear_forwarding: bool = False,
    repair: bool = False,
) -> None:
    """v15.I — git-integrated CF deploy pipeline.

    ========================================================================
    INVARIANT — IDEMPOTENCY (ADR-0015, accepted 2026-05-23)
    ========================================================================
    EVERY step inside this function MUST be idempotent. Re-running
    `lamill new deploy <domain>` on an already-deployed (or partially
    deployed) domain MUST succeed cleanly without modifying state.

    Concretely, every state-changing API call MUST be preceded by a
    "probe-then-act" pattern (GET-then-POST, list-then-create,
    status-equality-check-then-skip). "Already exists" responses from
    CF / GitHub / Porkbun / Google (which surface as HTTP 200 with
    flags, HTTP 409, or provider-specific HTTP 400 + error codes like
    CF code 8000018) MUST be caught and mapped to a success outcome,
    not raised.

    Why this exists: the pipeline depends on external state that
    settles over 5-30 min (NS propagation, CF build, SSL provisioning).
    Quick + idempotent default beats always-wait — operator re-runs
    when state has changed instead of locking the shell for half an
    hour. `--watch` is the opt-in for single-command full-resolution
    confirmation.

    If you're about to add a new step, ADD A PROBE BEFORE THE WRITE.
    If you're modifying an existing step, verify the "second run on
    already-completed state" path still returns clean ✓ markers.

    Full rationale: `docs/decisions/0015-deploy-pipeline-must-remain-idempotent.md`.
    Operator-facing reminder: `docs/CLAUDE.md § Locked target shapes`.
    ========================================================================

    Pipeline (each step MUST be idempotent — see invariant above):
      1. Pre-flight (creds + project-dir clean + slug resolution)
      2. GH repo: get-or-create via REST API (or `gh` CLI fallback)
      3. Git push: ensure origin remote + push main if local ahead
      3.5. Zone DNS:Edit pre-flight probe (v25.B)
      4. CF zone: resolve or create; surface NS records
      5. Registrar NS: Porkbun + GoDaddy auto-push if mismatch (other
         registrars warn with target NS list)
      5.5. Purge conflicting parking DNS records (v15.R, workers only)
      6. CF Pages/Workers project + custom domain attach (idempotent
         via GET-then-POST + 400/8000018 "already added" handling)
      7. Build poll (90s queue wait + 5min terminal poll)
      8. Live HEAD probe
      9. GSC verify + add + sitemap (FILE-first / DNS_TXT fallback)
      --watch (optional): block polling until zone-active + build-success
                          + live-200 or 30-min timeout. Opt-in only.

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
        ensure_repo, parse_github_remote, push_to_origin,
        read_local_origin,
    )
    from .porkbun_dns import (
        PorkbunApiAccessError, PorkbunDnsError, delete_porkbun_url_forward,
        get_porkbun_ns, get_porkbun_url_forwarding, ns_matches,
        update_porkbun_ns,
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

    # v31.C — GoDaddy creds (Step 4 auto-pushes NS to GoDaddy too, when the
    # domain's registrar is GoDaddy). Detected silently here; presence /
    # absence is surfaced in Step 4 only for GoDaddy-registered domains, so
    # Porkbun deploys see no extra output.
    gd_key = (apikeys.get_key("GODADDY_API_KEY") or "").strip()
    gd_secret = (apikeys.get_key("GODADDY_API_SECRET") or "").strip()
    godaddy_creds = bool(gd_key and gd_secret)

    # Resolve owner (token path or gh CLI).
    if not gh_owner:
        try:
            gh_owner = detect_gh_owner()
        except (GhAuthError, GhError) as e:
            console.print(f"  [red]✗[/] Could not resolve GitHub owner: {e}")
            raise typer.Exit(2)
    console.print(f"  [green]✓[/] GitHub owner: [cyan]{gh_owner}[/]")
    console.print(f"  [green]✓[/] CF project slug: [cyan]{slug}[/]")

    # 2026-05-27 — slug-mismatch fix. When the operator's local
    # origin points at <gh_owner>/<X>, treat <X> as the canonical
    # GH repo target (overriding the TLD-stripped default). Without
    # this, operators with pre-lamill repo naming (e.g.
    # `codervijo/kwizicle.com.git`) hit a Step 2 push failure because
    # ensure_origin_remote strict-checks the URL and Step 1 created
    # /detected the wrong repo. `slug` (the CF Pages project name)
    # stays as _project_name(domain) — CF naming constraints don't
    # allow dots — but the GH repo target tracks the operator's
    # actual remote. See docs/bugs.md (2026-05-27 entry).
    gh_repo_target = slug
    if not skip_repo:
        local_origin = read_local_origin(Path(project_dir))
        if local_origin:
            parsed = parse_github_remote(local_origin)
            if parsed and parsed.owner.lower() == gh_owner.lower():
                if parsed.name != slug:
                    gh_repo_target = parsed.name
                    console.print(
                        f"  [yellow]↷[/] local origin → "
                        f"[cyan]{parsed.owner}/{parsed.name}[/] — using "
                        f"[cyan]{parsed.name}[/] as GH repo target "
                        f"[dim](override of derived [cyan]{slug}[/])[/]"
                    )

    # v15.R — Porkbun per-domain API access pre-check. The account-
    # level API key works for /domain/listAll (v15.F refresh) but
    # each domain has a SEPARATE per-domain toggle. Catch this at
    # Step 0 so the operator isn't surprised mid-pipeline.
    if porkbun_creds and not dry_run:
        registrar_now = _lookup_registrar(domain) or ""
        if registrar_now.lower() == "porkbun":
            try:
                from .porkbun_dns import (
                    PorkbunApiAccessError, PorkbunDnsError, get_porkbun_ns,
                )
                get_porkbun_ns(domain, api_key=pb_key, secret=pb_secret)
            except PorkbunApiAccessError:
                # Operator-action-needed (a dashboard toggle, no API for it).
                # Fail fast at Step 0 so the operator isn't surprised mid-run.
                console.print(f"  [red]✗[/] {_porkbun_api_access_help(domain)}")
                raise typer.Exit(2)
            except PorkbunDnsError as e:
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
        gh_repo_name = gh_repo_target
        clone_url = f"git@github.com:{gh_owner}/{gh_repo_target}.git"
    elif dry_run:
        console.print(
            f"  [dim]would: ensure_repo({gh_repo_target}, owner={gh_owner}, "
            f"private={private})[/]"
        )
        gh_repo_name = gh_repo_target
        clone_url = f"git@github.com:{gh_owner}/{gh_repo_target}.git"
    else:
        try:
            repo = ensure_repo(gh_repo_target, owner=gh_owner, private=private)
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

    # --- Step 3.5: Zone-level DNS:Edit probe (v25.B) -------------------------
    # Catches the dropaudit.co failure mode: token has Zone-scope DNS:Edit on
    # "All zones from an account," but THIS zone isn't in that account (e.g.,
    # the zone was created in a different account or the token's resources
    # filter excludes it). Without this probe, Step 5.5 (parking-record purge)
    # and Step 9 (GSC TXT verification) each fail mid-pipeline with HTTP 403,
    # leaving the operator to back-trace which step actually broke. v25.B
    # surfaces the gap once, here, with a single actionable hint.
    if not dry_run:
        console.print(f"\n[bold]3.5 Zone DNS:Edit probe[/] [dim]({domain})[/]")
        try:
            probe = cloudflare.probe_zone_write_capability(zone.zone_id)
        except cloudflare.CloudflareAPIError as e:
            # 404 / 5xx — let the operator see the raw error and retry.
            console.print(f"  [red]✗[/] DNS:Edit probe failed: {e}")
            raise typer.Exit(8)
        if not probe.can_write:
            console.print(
                f"  [red]✗[/] Token cannot write DNS records on this zone "
                f"[dim]({probe.missing_scope})[/]"
            )
            console.print(
                f"\n  [bold yellow]Token scope fix required:[/]\n"
                f"    1. Open: [link]https://dash.cloudflare.com/profile/api-tokens[/link]\n"
                f"    2. Edit your token (or create a new one) with:\n"
                f"       - Permissions: [cyan]Zone → DNS → Edit[/]\n"
                f"       - Zone resources: include [cyan]{domain}[/] "
                f"(or 'All zones from an account' covering this zone)\n"
                f"    3. Update the token via "
                f"[cyan]lamill settings apikeys set CF_API_TOKEN <value>[/]\n"
                f"    4. Re-run [cyan]lamill new deploy {domain} --yes[/]\n"
                f"\n  [dim]Step 5.5 (DNS parking purge) and Step 9 (GSC TXT "
                f"verification) both need DNS:Edit on this zone. Step 3.5 "
                f"catches the gap here to avoid mid-pipeline failures.[/]"
            )
            raise typer.Exit(8)
        console.print(
            f"  [green]✓[/] Zone DNS:Edit OK [dim](token can write to "
            f"{zone.name})[/]"
        )

    # --- Step 4: Registrar NS ------------------------------------------------
    console.print(f"\n[bold]4. Registrar NS[/] [dim](point {domain} at Cloudflare)[/]")
    registrar = _lookup_registrar(domain) or "unknown"
    if dry_run:
        console.print(
            f"  [dim]would: check + update NS at {registrar} to {target_ns}[/]"
        )
    elif not target_ns:
        console.print("  [yellow]↷[/] no target NS yet (zone create deferred); skipping")
    elif registrar.lower() == "godaddy":
        # v31.C — GoDaddy NS auto-push, symmetric with the Porkbun path:
        # GET-then-compare (idempotent), confirm, PUT via the Management API.
        if not godaddy_creds:
            console.print(
                f"  [yellow]↷[/] GoDaddy creds missing — manual NS update.\n"
                f"  [dim]Set GODADDY_API_KEY / GODADDY_API_SECRET, or set NS "
                f"at GoDaddy to: {', '.join(target_ns)}[/]"
            )
        else:
            from .godaddy import (
                GoDaddyError, get_nameservers, set_nameservers,
            )
            try:
                current_ns = get_nameservers(
                    domain, api_key=gd_key, secret=gd_secret,
                )
            except GoDaddyError as e:
                console.print(
                    f"  [red]✗[/] could not read current GoDaddy NS: {e}"
                )
                raise typer.Exit(6)
            if ns_matches(current_ns, target_ns):
                console.print(
                    f"  [green]✓[/] GoDaddy NS already match Cloudflare "
                    f"[dim](registrar API: {', '.join(current_ns)})[/]"
                )
                _print_ns_delegation(domain, target_ns)
            else:
                console.print(
                    f"  [dim]GoDaddy current: "
                    f"{', '.join(current_ns) or '<none>'}[/]\n"
                    f"  [dim]Cloudflare target: {', '.join(target_ns)}[/]"
                )
                confirm = True
                if not yes:
                    confirm = typer.confirm(
                        f"  Update NS at GoDaddy for {domain}?", default=True,
                    )
                if not confirm:
                    console.print(
                        f"  [yellow]↷[/] NS update declined — pipeline will "
                        f"continue, but the custom domain won't resolve until "
                        f"NS points at Cloudflare."
                    )
                else:
                    try:
                        set_nameservers(
                            domain, api_key=gd_key, secret=gd_secret,
                            ns_list=target_ns,
                        )
                    except GoDaddyError as e:
                        console.print(
                            f"  [red]✗[/] GoDaddy NS update failed: {e}"
                        )
                        raise typer.Exit(7)
                    console.print("  [green]✓[/] NS updated at GoDaddy")
                    _print_ns_delegation(domain, target_ns)
    elif registrar.lower() != "porkbun":
        console.print(
            f"  [yellow]↷[/] domain registrar is [cyan]{registrar}[/] — "
            f"`lamill new deploy` only auto-pushes NS to Porkbun + GoDaddy.\n"
            f"  [dim]Manual step: set NS at {registrar} to: "
            f"{', '.join(target_ns)}[/]"
        )
    elif not porkbun_creds:
        console.print(
            f"  [yellow]↷[/] Porkbun creds missing — manual NS update.\n"
            f"  [dim]Set NS at Porkbun to: {', '.join(target_ns)}[/]"
        )
    else:
        # v32.D — clear/detect URL Forwarding first; it pins NS to Porkbun
        # and silently blocks the cutover regardless of the stored NS value.
        _porkbun_forwarding_preflight(
            domain, api_key=pb_key, secret=pb_secret,
            clear=clear_forwarding, yes=yes,
        )
        try:
            current_ns = get_porkbun_ns(
                domain, api_key=pb_key, secret=pb_secret,
            )
        except PorkbunApiAccessError:
            console.print(f"  [red]✗[/] {_porkbun_api_access_help(domain)}")
            raise typer.Exit(6)
        except PorkbunDnsError as e:
            console.print(f"  [red]✗[/] could not read current Porkbun NS: {e}")
            raise typer.Exit(6)
        if ns_matches(current_ns, target_ns):
            console.print(
                f"  [green]✓[/] Porkbun NS already match Cloudflare "
                f"[dim](registrar API: {', '.join(current_ns)})[/]"
            )
            _print_ns_delegation(domain, target_ns)
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
                except PorkbunApiAccessError:
                    console.print(f"  [red]✗[/] {_porkbun_api_access_help(domain)}")
                    raise typer.Exit(7)
                except PorkbunDnsError as e:
                    console.print(f"  [red]✗[/] Porkbun NS update failed: {e}")
                    raise typer.Exit(7)
                console.print("  [green]✓[/] NS updated at Porkbun")
                _print_ns_delegation(domain, target_ns)

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
        except cloudflare.CloudflareTransientError as e:
            # Network timeout/transport error talking to CF (not a CF
            # response error). Transient + retryable per ADR-0015 — report
            # ↷ and stop cleanly; re-running converges. No raw traceback,
            # and no misleading "GitHub App not connected" manual block.
            console.print(f"  [yellow]↷[/] CF project create did not confirm: {e}")
            raise typer.Exit(8)
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
    # 2026-05-22 PM — explicit `--skip-dns-purge` visible message. The
    # broad A/AAAA/CNAME-on-root/wildcard/www match catches legitimate
    # Workers-managed DNS (or operator-curated routing) as if it were
    # parking placeholders. Operator opts out when they know there's
    # no parking to clean.
    if skip_dns_purge and cf_surface == "workers" and not dry_run:
        console.print(f"\n[bold]5.5 Purge conflicting DNS records[/] [dim]({domain})[/]")
        console.print(
            "  [yellow]↷[/] skipped (--skip-dns-purge) — "
            "trusting current DNS records as legitimate"
        )

    if not skip_pages and not dry_run and cf_surface == "workers" and not skip_dns_purge:
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

                # 2026-05-22 PM — surface the EXACT records that
                # need deletion. The DNS:Read scope on the token is
                # still working (Step 5.5's list_dns_records call
                # inside purge_conflicting_root_records succeeded
                # before the DELETE 403); we can re-fetch and render
                # the conflict list so the operator knows exactly
                # what to delete in the dashboard. Without this they
                # have to scan ~10 records and infer which are the
                # CF-injected parking entries.
                conflicting: list = []
                try:
                    all_records = cloudflare.list_dns_records(zone.zone_id)
                    _targets = {domain, f"*.{domain}", f"www.{domain}"}
                    _conflict_types = {"A", "AAAA", "CNAME"}
                    conflicting = [
                        r for r in all_records
                        if r.type in _conflict_types and r.name in _targets
                    ]
                except cloudflare.CloudflareAPIError:
                    # If LIST also fails, token doesn't even have
                    # DNS:Read. Skip the per-record breakdown; the
                    # generic "delete A/AAAA/CNAME on root/wildcard/
                    # www" hint below still applies.
                    pass

                console.print(
                    f"\n  [bold yellow]Manual DNS cleanup required:[/]\n"
                    f"    1. Open this URL:\n"
                    f"       [link]https://dash.cloudflare.com/"
                    f"{cf_account}/{domain}/dns/records[/link]\n"
                )

                if conflicting:
                    console.print(
                        f"    2. Delete these [bold]"
                        f"{len(conflicting)} record(s)[/]:"
                    )
                    for r in conflicting:
                        # Truncate long content (parking page URLs
                        # can be 80+ chars) so the line stays
                        # readable in narrow terminals.
                        content = r.content
                        if len(content) > 50:
                            content = content[:47] + "..."
                        console.print(
                            f"       • [cyan]{r.type:<6}[/]"
                            f"[bold]{r.name:<{len(domain) + 6}}[/]"
                            f"[dim]→ {content}[/]"
                        )
                else:
                    console.print(
                        f"    2. Delete any [bold]A / AAAA / CNAME[/] "
                        f"records matching:\n"
                        f"       - [cyan]{domain}[/]\n"
                        f"       - [cyan]*.{domain}[/]\n"
                        f"       - [cyan]www.{domain}[/]"
                    )

                console.print(
                    f"    3. Re-run [cyan]lamill new deploy {domain} "
                    f"--yes[/]\n"
                    f"\n  [dim]Alternative: if the records above are "
                    f"legitimate (Workers-managed routing from a prior "
                    f"successful attach, or operator-curated), bypass "
                    f"this step with[/] [cyan]--skip-dns-purge[/]\n"
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

    # --- Step 5.7: Trigger first build if project was just created ----------
    # 2026-05-23 fix — CF's POST /pages/projects (Step 5 above when
    # `created=True`) doesn't auto-trigger the first build the way the
    # dashboard's "Connect to Git → Save and Deploy" wizard does. Without
    # this explicit trigger, fresh-domain deploys end up with a project
    # that's connected to git but has zero deployments — Step 7 polls
    # forever and the watch loop times out. Idempotency: only triggers
    # when `project.created=True` (just created this run). Re-runs
    # against an existing project don't re-trigger; CF's git webhook
    # handles subsequent commits.
    _project_obj = locals().get("project")
    if (not skip_pages and not dry_run and cf_surface == "pages"
            and _project_obj is not None
            and getattr(_project_obj, "created", False)):
        console.print(
            f"\n[bold]5.7 Trigger first build[/] "
            f"[dim](new Pages project needs explicit kick — "
            f"CF API doesn't auto-build on creation)[/]"
        )
        try:
            dep_id = cloudflare.trigger_pages_deployment(
                slug, account_id=cf_account, branch="main",
            )
        except cloudflare.CloudflareAPIError as e:
            console.print(
                f"  [yellow]↷[/] auto-trigger failed (continuing — Step 7 "
                f"will poll; operator can push a commit or click "
                f"'Create deployment' in dashboard if no build appears): {e}"
            )
        else:
            console.print(
                f"  [green]✓[/] first build queued "
                f"[dim](deployment id: {dep_id[:12]}…)[/]"
            )

    # --- Step 6.5: Ensure DNS CNAME for custom domain ----------------------
    # 2026-05-23 fix — CF's `attach_pages_custom_domain` (Step 6) registers
    # the domain with the Pages project but does NOT auto-create the DNS
    # record that routes queries to the Pages worker. The dashboard's
    # "Connect a domain" wizard does this; the API doesn't. Without this
    # step, the project sits in CF's `Verifying` state forever (until the
    # operator manually clicks "Complete DNS setup" in the dashboard).
    #
    # Same pattern as Step 5.7 (explicit first-build trigger) — fills a
    # gap between the API path and the dashboard path. Idempotency
    # invariant (ADR-0015) preserved: probe existing DNS records first,
    # skip create if a matching CNAME already points to the right target.
    # Workers Services use a different DNS shape; this step is Pages-only.
    if not skip_pages and not dry_run and cf_surface == "pages":
        # The apex CNAME must target the project's ACTUAL *.pages.dev
        # hostname. CF appends a random suffix when the bare name collides
        # globally (e.g. `scopeguard-abu.pages.dev`), so `{slug}.pages.dev`
        # is wrong in that case → permanent CF 1014 "CNAME Cross-User
        # Banned" + a custom domain stuck on `pending` (bugs.md 2026-05-31).
        # v32.E — resolve the project's ACTUAL subdomain (re-fetching if the
        # just-created object doesn't carry it yet); never silently guess.
        target_content, authoritative = _resolve_pages_subdomain(
            project, slug, cf_account)
        console.print(
            f"\n[bold]6.5 DNS record for custom domain[/] "
            f"[dim]({domain} → {target_content})[/]"
        )
        if not authoritative:
            console.print(
                f"  [yellow]↷[/] couldn't read the project's authoritative "
                f"[cyan]*.pages.dev[/] subdomain — using the slug guess "
                f"[cyan]{target_content}[/]. If CF assigned a suffixed "
                f"subdomain (e.g. [cyan]{slug}-xyz.pages.dev[/]) this CNAME "
                f"will [bold]1014[/]; re-run once the project finishes "
                f"provisioning, or set the apex CNAME to the real subdomain "
                f"shown in the CF dashboard."
            )
        try:
            existing_records = cloudflare.list_dns_records(zone.zone_id)
        except cloudflare.CloudflareAPIError as e:
            console.print(
                f"  [yellow]↷[/] dns list failed (continuing — Step 8 "
                f"live probe will surface unresolved DNS): {e}"
            )
        else:
            apex_records = [
                r for r in existing_records
                if r.name == domain and r.type in ("CNAME", "A", "AAAA")
            ]
            already_pointing = any(
                r.type == "CNAME"
                and r.content.rstrip(".") == target_content.rstrip(".")
                for r in apex_records
            )
            if already_pointing:
                console.print(
                    f"  [green]✓[/] CNAME @ → {target_content} already "
                    f"exists, skipping [dim](idempotent re-run)[/]"
                )
            elif apex_records:
                # Apex has OTHER records — don't overwrite; let operator
                # decide. Show what's there + dashboard link.
                others = ", ".join(
                    f"{r.type} → {r.content[:40]}" for r in apex_records
                )
                console.print(
                    f"  [yellow]↷[/] apex already has "
                    f"{len(apex_records)} record(s) ({others}); not "
                    f"auto-creating CNAME to avoid clobber. Review at "
                    f"https://dash.cloudflare.com/{cf_account}/{domain}/dns/records"
                )
            else:
                try:
                    cloudflare.create_dns_record(
                        zone.zone_id,
                        type="CNAME", name=domain,
                        content=target_content, proxied=True,
                    )
                except cloudflare.CloudflareAPIError as e:
                    console.print(
                        f"  [red]✗[/] CNAME create failed: {e}"
                    )
                    console.print(
                        f"  [dim]Manual fix: in CF dashboard, add "
                        f"[cyan]CNAME @ → {target_content}[/] (proxied). "
                        f"https://dash.cloudflare.com/{cf_account}/{domain}/dns/records[/]"
                    )
                else:
                    console.print(
                        f"  [green]✓[/] created CNAME @ → {target_content} "
                        f"(proxied) [dim](one-shot at attach; CF webhook "
                        f"handles future routing)[/]"
                    )

    # --- Step 6.6: Repair stuck custom domain (v32.F, --repair only) --------
    if repair and not dry_run:
        if cf_surface == "pages":
            _deploy_repair_custom_domain(
                domain=domain, slug=slug, zone=zone,
                cf_account=cf_account, yes=yes,
            )
        else:
            console.print(
                f"\n[bold]6.6 Repair custom domain[/] [dim]({domain})[/]\n"
                f"  [yellow]↷[/] --repair is cf-pages only "
                f"(surface={cf_surface}); skipping."
            )

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
            # 2026-05-23 fix — on a freshly-created Pages project,
            # CF can take 10-60s to queue the first deployment. The
            # original one-shot check bailed with "no deployment yet"
            # if Step 7 ran before CF had even started queuing. Now
            # we retry with backoff for up to 90s waiting for the
            # first deployment to appear, THEN hand off to poll_build
            # for terminal-state tracking.
            import time as _time
            queue_intervals_s = (5, 10, 15, 20, 20, 20)  # 90s total
            stage = ""
            dep_id = ""
            for attempt_idx in range(len(queue_intervals_s) + 1):
                stage, dep_id, _ = cloudflare.latest_deployment_status(
                    slug, account_id=cf_account,
                )
                if stage:
                    break
                if attempt_idx == 0:
                    console.print(
                        f"  [dim]No deployment yet — waiting up to 90s for "
                        f"CF to queue the first build…[/]"
                    )
                if attempt_idx == len(queue_intervals_s):
                    break
                _time.sleep(queue_intervals_s[attempt_idx])

            if not stage:
                console.print(
                    "  [yellow]↷[/] still no deployment after 90s wait — "
                    "CF zone may still be `pending` (NS propagation 5-30 "
                    "min on fresh domains). Re-run `lamill new deploy` "
                    "after the zone activates, or check the CF dashboard."
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

    # --- Optional watch: with --watch, block here until deploy is fully ----
    # --- live BEFORE running Steps 8 (live probe) + 9 (GSC) so they only ---
    # --- execute on a confirmed-live deploy. Without --watch, Steps 8 + 9 -
    # --- run immediately and any DNS-not-yet-propagated state surfaces as -
    # --- ↷ (operator re-runs idempotently after settlement — ADR-0015). --
    if watch and not dry_run:
        watch_result = _deploy_watch_loop(
            domain=domain, zone_id=zone.zone_id, slug=slug,
            cf_account=cf_account, cf_surface=cf_surface,
        )
    else:
        watch_result = None  # not in watch mode → run 8/9 unconditionally

    # --- Step 8: Live probe --------------------------------------------------
    # Skip when watch ran but didn't reach "live" — Step 8 would just fail
    # the same way. Operator can re-run when ready (idempotent per ADR-0015).
    if watch_result is not None and watch_result != "live":
        console.print(
            f"\n[bold]8. Live probe[/] [dim](https://{domain}/)[/]"
        )
        console.print(
            f"  [yellow]↷[/] skipped — watch returned [cyan]{watch_result}[/] "
            f"(not 'live'). Re-run [cyan]lamill new deploy {domain} --yes[/] "
            f"once the deploy resolves to exercise this step."
        )
        apex_live = False
    else:
        apex_live = _deploy_step8_live_probe(domain=domain, dry_run=dry_run)

    # --- Step 9: GSC property + sitemap (v24.C / v25.C) -----------------------
    # Step 9 (GSC verify + sitemap submit) needs the deploy reachable to
    # Google's fetcher. Gate it on a confirmed-live apex (bug log 2026-06-06):
    #   - --watch path: liveness is `watch_result == "live"`.
    #   - no-watch path: liveness is Step 8's probe (`apex_live`).
    # Running it against un-propagated DNS just burns a GSC verify-poll and
    # emits a scary ✗ for a transient state. Deferred → the idempotent
    # re-run completes it once live (ADR-0015). Honesty: nothing is reported
    # submitted that wasn't (no false-green).
    if watch_result is not None and watch_result != "live":
        console.print(f"\n[bold]9. GSC property + sitemap[/] [dim]({domain})[/]")
        console.print(
            f"  [yellow]↷[/] skipped — watch returned [cyan]{watch_result}[/] "
            f"(not 'live'). GSC verification needs the deploy reachable; "
            f"re-run once live."
        )
        gsc_status, gsc_detail = (f"skipped:watch_{watch_result}", "")
    elif not apex_live:
        console.print(f"\n[bold]9. GSC property + sitemap[/] [dim]({domain})[/]")
        console.print(
            f"  [yellow]↷[/] deferred — apex not serving {domain} yet "
            f"(NS/SSL still settling). GSC verification + sitemap need the "
            f"deploy reachable; re-run [cyan]lamill new deploy {domain} --yes[/] "
            f"once live."
        )
        gsc_status, gsc_detail = ("skipped:not_live", "")
    else:
        gsc_status, gsc_detail = _deploy_step9_gsc(
            domain=domain, zone=zone, project_dir=project_dir,
            dry_run=dry_run, skip_gsc=skip_gsc,
        )

    # --- Step 10: IndexNow ping (v30.D) — soft-fail, ledger-gated ---------
    _deploy_step10_indexnow(domain=domain, project_dir=project_dir, dry_run=dry_run)

    console.print(
        f"\n[green]Deploy complete.[/] [dim]All 10 steps ran. "
        f"https://{domain}/ should resolve once DNS + SSL settle "
        f"(5-30 min from NS update).[/]"
    )
    # Surface the GSC outcome on its own line so operators see at a
    # glance whether they need to do anything (e.g., re-consent OAuth).
    if gsc_status == "created":
        console.print(
            f"[green]✓[/] GSC: [cyan]sc-domain:{domain}[/] verified · "
            f"property added · sitemap submitted"
        )
    elif gsc_status == "created:sitemap_deferred":
        # Honesty (bug log 2026-06-06): verify+add succeeded but the
        # sitemap was NOT submitted (URL unreachable) — don't claim it was.
        console.print(
            f"[yellow]↷[/] GSC: [cyan]sc-domain:{domain}[/] verified · "
            f"property added · [yellow]sitemap deferred[/] — re-run "
            f"[cyan]lamill new deploy {domain} --yes[/] once the sitemap is live"
        )
    elif gsc_status == "already-registered:sitemap_deferred":
        console.print(
            f"[yellow]↷[/] GSC: [cyan]sc-domain:{domain}[/] already verified + "
            f"added · [yellow]sitemap deferred[/] — re-run once live"
        )
    elif gsc_status == "already-registered":
        console.print(
            f"[green]✓[/] GSC: [cyan]sc-domain:{domain}[/] {gsc_detail}"
        )
    elif gsc_status.startswith("skipped:"):
        console.print(
            f"[yellow]↷[/] GSC: {gsc_status[len('skipped:'):]}"
        )
    elif gsc_status.startswith("failed:"):
        console.print(
            f"[red]✗[/] GSC: {gsc_status[len('failed:'):]}"
        )
    console.print("")


def _deploy_step10_indexnow(*, domain: str, project_dir, dry_run: bool) -> None:
    """v30.D — ping IndexNow for new sitemap URLs after deploy. Soft-fail and
    idempotent (ledger-gated); silent when IndexNow isn't provisioned. Pings
    Bing/Yandex/Naver/Seznam/Yep (Google doesn't participate)."""
    from . import indexnow, lamill_toml
    doc = lamill_toml.load(project_dir)
    if (doc is None or doc.index is None or not doc.index.indexnow_enabled
            or not doc.index.indexnow_key):
        return
    console.print(f"\n[bold]10. IndexNow ping[/] [dim]({domain})[/]")
    if dry_run:
        console.print("  [yellow]↷[/] dry-run — would ping new sitemap URLs")
        return
    key = doc.index.indexnow_key
    try:
        if not indexnow.key_is_live(domain, key):
            console.print(
                f"  [yellow]↷[/] key not live at https://{domain}/{key}.txt — "
                f"skip (re-run once live)"
            )
            return
        pending = indexnow.new_urls(domain, indexnow.fetch_sitemap_urls(domain))
        if not pending:
            console.print("  [green]✓[/] ledger current — nothing new to ping")
            return
        n = indexnow.submit_urls(domain, key, pending)
        indexnow.append_ledger(domain, pending)
        console.print(f"  [green]✓[/] pinged {n} new URL(s) to IndexNow (Bing/Yandex/…)")
    except Exception as e:  # soft-fail — never block the deploy on indexing
        console.print(f"  [yellow]↷[/] IndexNow ping soft-failed ({type(e).__name__}: {e})")


def _probe_apex_live(domain: str, *, head: bool = False,
                     timeout: float = 5.0) -> tuple[bool, str, str | None]:
    """ADR-0022 rule (a) — does `https://<domain>/` serve *this* site itself?

    Follows redirects, then classifies the final response with
    `check._classify` (the same eTLD+1-vs-final-host classifier `fleet live`
    uses). Returns `(is_live, token, detail)`:

      - `is_live` — True *only* when the apex serves this domain (classification
        `live-site`). A `3xx` that lands on a parking / forwarder host (a
        *different* registrable domain, or a known parked suffix like `l.ink`)
        is **not live** — even though it returns `200`. Same-site redirects
        (apex→www, http→https) stay live.
      - `token` — short status token for the state line (`"200"`, `"forwarder"`,
        `"parked"`, `"for-sale"`, `"DNS"`, `"err"`, or a non-2xx status code).
      - `detail` — final host (for forwarder/parked/for-sale) or the error type,
        else None.

    `head=True` uses a HEAD request (watch loop's cheap repeated probe); the
    GET path also passes the body so `_classify` can catch JS parking redirects.
    """
    import httpx
    from .check import _classify
    try:
        fn = httpx.head if head else httpx.get
        r = fn(f"https://{domain}/", timeout=timeout, follow_redirects=True)
        final_url = str(r.url)
        body = None if head else (r.text[:1000] if r.text else None)
        classification, _reason = _classify(
            domain, final_url, r.status_code, None, body)
        if classification == "live-site":
            return True, str(r.status_code), None
        if classification in ("forwarder", "parked", "for-sale"):
            return False, classification, httpx.URL(final_url).host or None
        return False, str(r.status_code), None
    except httpx.ConnectError:
        return False, "DNS", None
    except httpx.HTTPError as e:
        return False, "err", type(e).__name__


def _ns_delegation(domain: str, target_ns: list[str]) -> tuple[list[str], bool]:
    """v32.C — the *real* delegation via `dig NS`, distinct from the registrar
    API's stored value. A registrar can report "NS set to Cloudflare" while the
    parent zone is still delegated elsewhere (propagation lag, or Porkbun URL
    Forwarding pinning Porkbun NS). Returns `(delegated, matches_target)` where
    `delegated` is the dig answer (lowercased, trailing dot stripped). An empty
    answer ⇒ delegation not yet visible (propagating) ⇒ `matches=False`, so
    callers report "awaiting delegation", never a hard failure (ADR-0015)."""
    from .diagnose import _dig
    from .porkbun_dns import ns_matches
    delegated = [d.rstrip(".").lower() for d in _dig(domain, "NS") if d.strip()]
    return delegated, bool(delegated) and ns_matches(delegated, target_ns)


def _print_ns_delegation(domain: str, target_ns: list[str]) -> None:
    """v32.C — report registrar-API state vs real `dig NS` delegation as
    distinct lines, so a `✓ match` off the API alone is never mistaken for a
    completed cutover (ADR-0022 rule b)."""
    delegated, matched = _ns_delegation(domain, target_ns)
    if matched:
        console.print(
            f"  [green]✓[/] delegation confirmed "
            f"[dim](dig NS → {', '.join(delegated)})[/]"
        )
    elif not delegated:
        console.print(
            "  [yellow]↷[/] delegation not yet visible (dig NS returned "
            "nothing) — propagating; re-check in 5-30 min"
        )
    else:
        console.print(
            "  [yellow]↷[/] NS set at registrar, awaiting delegation "
            "[dim](registry/resolver propagation)[/]\n"
            f"  [dim]requested (registrar): {', '.join(target_ns)}[/]\n"
            f"  [dim]delegated (dig NS):    {', '.join(delegated)}[/]"
        )


def _resolve_pages_subdomain(project, slug: str,
                             cf_account: str) -> tuple[str, bool]:
    """v32.E — the authoritative `*.pages.dev` hostname for the apex CNAME.

    CF appends a random suffix when `<slug>.pages.dev` collides globally
    (`scopeguard-abu.pages.dev`), and the **create** response's `subdomain`
    is often empty until CF finishes assigning the hostname — so trusting the
    just-created project object (or guessing `<slug>.pages.dev`) is what
    produced the permanent `1014` (bugs.md 2026-05-31). We prefer
    `project.subdomain`, else **re-fetch** the project to read the current
    value, and only fall back to the slug guess as a last resort.

    Returns `(target, authoritative)`. `authoritative=False` means we couldn't
    read the real subdomain and are guessing — the caller warns, because a
    wrong target is a permanent `1014`, not a propagation delay."""
    from . import cloudflare
    sub = getattr(project, "subdomain", None)
    if sub:
        return sub, True
    try:
        fresh = cloudflare.get_pages_project(slug, account_id=cf_account)
    except cloudflare.CloudflareAPIError:
        fresh = None
    if fresh is not None and fresh.subdomain:
        return fresh.subdomain, True
    return f"{slug}.pages.dev", False


def _deploy_repair_custom_domain(
    *, domain: str, slug: str, zone, cf_account: str, yes: bool,
) -> None:
    """v32.F — recover a Pages custom domain stuck in pending-verification /
    CF `1014`. Re-points the apex CNAME at the project's authoritative
    `*.pages.dev` subdomain, then removes + re-adds the custom domain so CF
    re-verifies against the corrected record. Confirm-gated unless `yes`;
    each CF call soft-reports failure (this is a recovery path, not the
    happy-path pipeline)."""
    from . import cloudflare
    console.print(f"\n[bold]6.6 Repair custom domain[/] [dim]({domain})[/]")
    project = cloudflare.get_pages_project(slug, account_id=cf_account)
    if project is None:
        console.print(
            f"  [red]✗[/] no Pages project [cyan]{slug}[/] to repair — "
            f"create it first (re-run without --repair)."
        )
        return
    target, authoritative = _resolve_pages_subdomain(project, slug, cf_account)
    if not authoritative:
        console.print(
            f"  [yellow]↷[/] can't read the real [cyan]*.pages.dev[/] "
            f"subdomain yet — aborting repair (a guessed target would just "
            f"1014 again). Re-run once the project finishes provisioning."
        )
        return
    if not yes and not typer.confirm(
        f"  Re-point apex CNAME → {target} and re-add the custom domain "
        f"for {domain}?", default=True,
    ):
        console.print("  [yellow]↷[/] repair declined.")
        return

    # 1. Apex CNAME → real subdomain (delete any wrong CNAME, create correct).
    try:
        records = cloudflare.list_dns_records(zone.zone_id)
    except cloudflare.CloudflareAPIError as e:
        console.print(f"  [red]✗[/] dns list failed: {e}")
        return
    apex_cnames = [r for r in records if r.name == domain and r.type == "CNAME"]
    if any(r.content.rstrip(".") == target.rstrip(".") for r in apex_cnames):
        console.print(f"  [green]✓[/] apex CNAME already → {target}")
    else:
        try:
            for r in apex_cnames:
                cloudflare.delete_dns_record(zone.zone_id, r.record_id)
            cloudflare.create_dns_record(
                zone.zone_id, type="CNAME", name=domain,
                content=target, proxied=True,
            )
        except cloudflare.CloudflareAPIError as e:
            console.print(f"  [red]✗[/] apex CNAME re-point failed: {e}")
            return
        console.print(f"  [green]✓[/] apex CNAME re-pointed → {target}")

    # 2. Remove + re-add the custom domain to force re-verification.
    try:
        removed = cloudflare.delete_pages_custom_domain(
            slug, domain, account_id=cf_account)
        cloudflare.attach_pages_custom_domain(
            slug, domain, account_id=cf_account)
    except cloudflare.CloudflareAPIError as e:
        console.print(f"  [red]✗[/] custom-domain re-add failed: {e}")
        return
    console.print(
        f"  [green]✓[/] custom domain {'re-added' if removed else 'added'} → "
        f"CF re-verifying against {target} (allow a few min; --watch to track)"
    )


def _porkbun_forwarding_preflight(
    domain: str, *, api_key: str, secret: str, clear: bool, yes: bool,
) -> None:
    """v32.D — detect Porkbun URL Forwarding on the apex. URL Forwarding pins
    a domain to Porkbun nameservers regardless of the stored NS value, so an
    active apex forward silently no-ops the CF cutover (the mdburst.com
    false-green root cause). With `clear=True`, delete it via the registrar
    API (confirm-gated unless `yes`). Idempotent: no forwarding ⇒ silent
    no-op. Read/clear-read failures warn but never abort the deploy (this is
    a diagnostic preflight; the NS read right after owns hard failures)."""
    from .porkbun_dns import (
        PorkbunApiAccessError, PorkbunDnsError,
        delete_porkbun_url_forward, get_porkbun_url_forwarding,
    )
    try:
        forwards = get_porkbun_url_forwarding(
            domain, api_key=api_key, secret=secret)
    except PorkbunApiAccessError:
        return  # the NS read surfaces the API-access toggle help; don't double-warn
    except PorkbunDnsError as e:
        console.print(
            f"  [yellow]↷[/] could not read URL Forwarding (continuing): {e}")
        return

    apex = [f for f in forwards if f.is_apex]
    if not apex:
        return  # nothing pinning NS — clean

    locs = ", ".join(f.location for f in apex if f.location) or "?"
    if not clear:
        console.print(
            f"  [yellow]↷[/] Porkbun URL Forwarding active on the apex "
            f"([cyan]{locs}[/]) — this pins [cyan]{domain}[/] to Porkbun NS "
            f"and will silently block the Cloudflare cutover.\n"
            f"  [dim]Remove it at "
            f"[link]https://porkbun.com/account/domain/{domain}[/link] "
            f"or re-run with [bold]--clear-forwarding[/].[/]"
        )
        return

    confirm = yes or typer.confirm(
        f"  Delete {len(apex)} apex URL forward(s) for {domain}?", default=True)
    if not confirm:
        console.print(
            "  [yellow]↷[/] URL Forwarding left in place (declined) — the "
            "cutover will not complete until it's removed.")
        return
    for f in apex:
        try:
            delete_porkbun_url_forward(
                domain, f.id, api_key=api_key, secret=secret)
        except PorkbunDnsError as e:
            console.print(
                f"  [red]✗[/] failed to delete URL forward {f.id}: {e}")
            raise typer.Exit(7)
    console.print(f"  [green]✓[/] cleared {len(apex)} apex URL forward(s)")


def _deploy_step8_live_probe(*, domain: str, dry_run: bool) -> bool:
    """v15.I — single HTTP HEAD probe of `https://<domain>/`. Soft-warns
    on non-2xx or connection error (expected on fresh deploys where DNS
    / SSL hasn't fully propagated). Extracted from inline Step 8 code
    2026-05-23 PM to enable `--watch`-mode reordering (run after watch
    confirms live, not before).

    Returns True when the apex is confirmed serving this site (or under
    --dry-run), False otherwise. The caller gates Step 9 on this — GSC
    verify + sitemap submit need the deploy reachable (bug log 2026-06-06)."""
    console.print(f"\n[bold]8. Live probe[/] [dim](https://{domain}/)[/]")
    if dry_run:
        console.print("  [dim]would: GET https://<domain>/[/]")
        return True
    # v32.B — "live" means the apex serves THIS site, not just any 200.
    # A 3xx that lands on a parking/forwarder host (e.g. Porkbun URL
    # Forwarding → l.ink) is NOT live, even though the chain ends 200.
    is_live, token, detail = _probe_apex_live(domain, head=False)
    if is_live:
        console.print(f"  [green]✓[/] {token} — serving {domain}")
    elif token in ("forwarder", "parked", "for-sale"):
        console.print(
            f"  [yellow]↷[/] not live — {token} → "
            f"[cyan]{detail or '?'}[/]. The apex still redirects off-domain "
            f"(NS may not have cut over, or URL Forwarding is active). "
            f"Re-probe in 5-30 min; see Step 4 for the delegation state."
        )
    elif token == "DNS":
        console.print(
            "  [yellow]↷[/] no DNS answer yet — expected within ~30min of "
            "NS update (propagation + edge SSL provisioning). Re-probe later."
        )
    else:
        console.print(
            f"  [yellow]↷[/] {token} — may indicate NS propagation in flight "
            "or SSL not yet provisioned. Re-probe in 5-30 min."
        )
    return is_live


def _porkbun_api_access_help(domain: str) -> str:
    """Operator-facing fix for Porkbun's per-domain API-access toggle.

    The toggle defaults OFF on newly-registered domains and Porkbun
    exposes no API to flip it, so the deploy pipeline can't read or set
    nameservers until the operator enables it once in the dashboard.
    Returns rich markup; the caller prefixes the `✗`."""
    return (
        f"Porkbun per-domain API access is OFF for [cyan]{domain}[/] — the "
        f"API can't read or set its nameservers until you enable it.\n"
        f"\n  [bold yellow]Manual enable (one-time per domain; no API exists "
        f"for this):[/]\n"
        f"    1. Open: [link]https://porkbun.com/account/domains[/link]\n"
        f"    2. Click [cyan]{domain}[/]\n"
        f"    3. Find the [bold]API ACCESS[/] section\n"
        f"    4. Toggle [bold]API ACCESS[/] to [bold]ON[/] → Save\n"
        f"  [dim]Then re-run `lamill new deploy {domain} --yes`. The account-"
        f"level key works (`apikeys list` shows ✓ valid, `fleet sync` uses "
        f"it), but the per-domain toggle is separate and defaults OFF.[/]"
    )


def _deploy_watch_loop(
    *, domain: str, zone_id: str, slug: str, cf_account: str,
    cf_surface: str, timeout_s: int = 1800, interval_s: int = 20,
    sleep: callable = None, monotonic: callable = None,
) -> str:
    """v25 follow-up — block polling until the deploy is fully live OR
    the budget expires OR Ctrl-C. Polls three things every `interval_s`
    seconds:

      - CF zone status (`pending` → `active`)
      - Latest deployment status on the Pages project
      - Live HEAD probe on `https://<domain>/`

    Returns one of:
      - "live"      — all three green
      - "timeout"   — budget exhausted, soft-skip with hint
      - "build_failed"  — CF build returned `failure`; fail fast
      - "pending_verification" — v32.F: zone+build green but the custom
        domain never verified (often the 1014 wrong-CNAME case); names the
        state + points at `--repair` instead of a generic timeout
      - "cancelled" — operator pressed Ctrl-C

    `sleep` and `monotonic` are injectable for tests.
    """
    import time as _time
    import httpx as _httpx
    from . import cloudflare

    _sleep = sleep or _time.sleep
    _mono = monotonic or _time.monotonic

    start = _mono()
    deadline = start + timeout_s
    last_state: tuple[str, str, str] | None = None

    console.print(
        f"\n[bold]🔁 Watch[/] [cyan]{domain}[/] "
        f"[dim](max {timeout_s // 60} min · Ctrl-C to cancel)[/]"
    )

    try:
        while True:
            elapsed = int(_mono() - start)
            mm, ss = elapsed // 60, elapsed % 60

            # Zone status probe.
            try:
                zone_info = cloudflare.get_zone(zone_id)
                zone_status = zone_info.status
            except cloudflare.CloudflareAPIError:
                zone_status = "?"

            # Build status probe (Pages only; Workers Services build
            # status isn't on a public API yet).
            if cf_surface == "workers":
                build_status = "n/a"
            else:
                try:
                    # 2026-05-23 bug fix — latest_deployment_status returns
                    # (stage_name, stage_status, deployment_id). Prior
                    # ordering had stage_status and deployment_id swapped,
                    # so build_status compared against the UUID and never
                    # matched "success" → watch loop never exited "live".
                    stage, raw_status, _dep_id = cloudflare.latest_deployment_status(
                        slug, account_id=cf_account,
                    )
                    if not stage:
                        build_status = "queued?"
                    elif raw_status == "success":
                        build_status = "success"
                    elif raw_status == "failure":
                        build_status = "failed"
                    else:
                        build_status = f"{stage[:8]}/{(raw_status or '?')[:8]}"
                except cloudflare.CloudflareAPIError:
                    build_status = "?"

            # Live HEAD probe — v32.B: classify, don't trust the status code.
            # A forwarded/parked apex returns 200 but isn't serving the site,
            # so `live_ok` requires classification == live-site, not 2xx/3xx.
            apex_live, live_token, live_detail = _probe_apex_live(
                domain, head=True)
            live_status = (
                f"{live_token}→{live_detail}" if live_detail else live_token)

            # Render state line only when something changed (avoid
            # spamming identical rows when nothing's moving).
            state = (zone_status, build_status, live_status)
            if state != last_state:
                console.print(
                    f"  [dim][{mm:02d}:{ss:02d}][/] "
                    f"zone=[cyan]{zone_status:<10}[/] "
                    f"build=[cyan]{build_status:<14}[/] "
                    f"live=[cyan]{live_status}[/]"
                )
                last_state = state

            zone_ok = zone_status == "active"
            build_ok = build_status in ("success", "n/a")
            live_ok = apex_live  # v32.B — same-site 200 only (ADR-0022 rule a)

            if zone_ok and build_ok and live_ok:
                console.print(
                    f"\n[bold green]✓ {domain} fully live[/] "
                    f"[dim](zone active · build success · "
                    f"HTTP {live_status} · {elapsed}s)[/]"
                )
                return "live"

            if build_status == "failed":
                console.print(
                    f"\n[bold red]✗ Build failed[/] for [cyan]{slug}[/] "
                    f"— check CF dashboard for the build logs."
                )
                return "build_failed"

            if _mono() >= deadline:
                # v32.F — when zone+build are green but the apex still isn't
                # serving the site, the custom domain is likely stuck in
                # pending-verification (often the 1014 wrong-CNAME case), not
                # merely propagating. Probe the domain status once to name it.
                if cf_surface == "pages" and zone_ok and build_ok and not live_ok:
                    try:
                        dom_status = cloudflare.get_pages_domain_status(
                            slug, domain, account_id=cf_account)
                    except cloudflare.CloudflareAPIError:
                        dom_status = None
                    if dom_status and dom_status != "active":
                        console.print(
                            f"\n[bold red]✗ {domain} custom domain stuck: "
                            f"{dom_status}[/] [dim](zone active · build success "
                            f"· live={live_status})[/]\n"
                            f"  CF never finished verifying the custom domain — "
                            f"usually the apex CNAME points at the wrong "
                            f"[cyan]*.pages.dev[/] host (CF error [bold]1014[/]).\n"
                            f"  [dim]Recover: [cyan]lamill new deploy {domain} "
                            f"--repair --yes[/] (re-points the apex CNAME at the "
                            f"real subdomain + re-adds the custom domain to "
                            f"re-verify).[/]"
                        )
                        return "pending_verification"
                console.print(
                    f"\n[yellow]↷[/] Watch timeout after "
                    f"{timeout_s // 60} min. Still resolving: "
                    f"zone={zone_status} build={build_status} "
                    f"live={live_status}. Re-run "
                    f"[cyan]lamill new deploy {domain} --yes --watch[/] "
                    f"later or check the CF dashboard."
                )
                return "timeout"

            _sleep(interval_s)
    except KeyboardInterrupt:
        console.print(
            f"\n[yellow]↷[/] Watch cancelled by user "
            f"(state at cancel: zone={last_state[0] if last_state else '?'} "
            f"build={last_state[1] if last_state else '?'} "
            f"live={last_state[2] if last_state else '?'})."
        )
        return "cancelled"


def _step9_file_verify(domain, project_dir, gsc_admin) -> tuple[str, str]:
    """v25.C — FILE-method GSC verification.

    Five sub-steps:
      1. `get_verification_token(method="FILE")` — returns filename.
      2. `write_verification_file()` — writes <project_dir>/public/<token>.
         If `public/` doesn't exist, returns ("fallback", reason) so the
         caller switches to DNS_TXT.
      3. git add + commit + push (only if there's an uncommitted change).
      4. `wait_for_verification_file_live` — HEAD-polls the URL until 200.
      5. `verify_domain(method="FILE")` — Google's ownership check.

    Returns `(status, detail)`:
      - ("verified", "")                  — happy path
      - ("fallback", reason)               — structural issue; caller
                                             should try DNS_TXT
      - ("skipped:<reason>", "")           — OAuth scope insufficient
      - ("failed:<sub-step>:<msg>", "")    — propagation timeout, git
                                             push fail, API error
    """
    import subprocess

    # Step 9a-F: Get FILE-method token from Google.
    try:
        token = gsc_admin.get_verification_token(
            domain, method=gsc_admin.VERIFICATION_METHOD_FILE,
        )
    except gsc_admin.GSCAdminError as e:
        msg = str(e)
        if "403" in msg:
            cause, hint = gsc_admin.classify_403(msg)
            console.print(f"  [yellow]↷[/] GSC 403 ({cause}): {hint}")
            return (f"skipped:{cause}", hint)
        console.print(f"  [red]✗[/] get_verification_token (FILE) failed: {e}")
        return (f"failed:get_token_file:{_short(msg)}", "")

    # Step 9b-F: Write the verification file to public/.
    try:
        file_path = gsc_admin.write_verification_file(project_dir, token)
    except gsc_admin.GSCAdminError as e:
        # Structural: project doesn't have public/. Caller falls back.
        return ("fallback", f"{e}")
    except OSError as e:
        return ("fallback", f"file write failed: {e}")
    console.print(
        f"  [green]✓[/] wrote verification file: "
        f"[cyan]public/{token}[/]"
    )

    # Step 9c-F: Commit + push if there's a change to the file.
    rel_path = file_path.relative_to(project_dir)
    try:
        status_check = subprocess.run(
            ["git", "status", "--porcelain", str(rel_path)],
            cwd=str(project_dir),
            capture_output=True, text=True, check=False,
        )
    except OSError as e:
        return (f"failed:git_status:{_short(str(e))}", "")

    if status_check.returncode != 0:
        return (
            f"failed:git_status:{_short(status_check.stderr.strip())}",
            "",
        )

    if status_check.stdout.strip():
        # File is new / modified — stage + commit + push.
        try:
            subprocess.run(
                ["git", "add", str(rel_path)],
                cwd=str(project_dir), check=True,
                capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "commit", "-m",
                 f"GSC verification file ({domain})"],
                cwd=str(project_dir), check=True,
                capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=str(project_dir), check=True,
                capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            return (
                f"failed:git_push_file:{_short(stderr or str(e))}",
                "",
            )
        console.print(
            f"  [green]✓[/] committed + pushed verification file "
            f"[dim](CF auto-deploy triggers in seconds)[/]"
        )
    else:
        console.print(
            f"  [green]✓[/] verification file already committed "
            f"[dim](no-op)[/]"
        )

    # Step 9d-F: Wait for the file to be reachable.
    console.print(
        f"  [dim]Polling https://{domain}/{token} for liveness "
        f"(up to ~180s)…[/]"
    )
    live = gsc_admin.wait_for_verification_file_live(domain, token)
    if not live:
        return (
            "failed:verify_file_not_live:"
            "deploy not ready; re-run deploy after CF build completes",
            "",
        )
    console.print(
        f"  [green]✓[/] verification file reachable at "
        f"[link]https://{domain}/{token}[/]"
    )

    # Step 9e-F: Tell Google to verify via FILE method.
    try:
        gsc_admin.verify_domain(
            domain, method=gsc_admin.VERIFICATION_METHOD_FILE,
        )
    except gsc_admin.VerificationFailedError as e:
        console.print(f"  [yellow]↷[/] verification timed out: {e}")
        return ("failed:verify_file:propagation_timeout", "")
    except gsc_admin.GSCAdminError as e:
        msg = str(e)
        if "403" in msg:
            cause, hint = gsc_admin.classify_403(msg)
            console.print(f"  [yellow]↷[/] GSC 403 ({cause}): {hint}")
            return (f"skipped:{cause}", hint)
        console.print(f"  [red]✗[/] verify_domain (FILE) failed: {e}")
        return (f"failed:verify_file:{_short(msg)}", "")
    console.print(
        f"  [green]✓[/] domain ownership verified by Google "
        f"[dim](FILE method — no DNS:Edit needed)[/]"
    )
    return ("verified", "")


def _step9_dns_verify(domain, zone, cloudflare, gsc_admin) -> tuple[str, str]:
    """v25.C — DNS_TXT-method GSC verification (fallback / explicit-opt-in).

    The original v24.C path preserved: get DNS_TXT token, write TXT to
    CF zone, verify with poll loop. Requires `DNS:Edit` on the zone
    (the dropaudit.co failure mode). Used when FILE method isn't
    available (project doesn't expose `public/`).

    Same return shape as `_step9_file_verify`.
    """
    # Step 9a-D: Get DNS_TXT token.
    try:
        token = gsc_admin.get_verification_token(
            domain, method=gsc_admin.VERIFICATION_METHOD_DNS_TXT,
        )
    except gsc_admin.GSCAdminError as e:
        msg = str(e)
        if "403" in msg:
            cause, hint = gsc_admin.classify_403(msg)
            console.print(f"  [yellow]↷[/] GSC 403 ({cause}): {hint}")
            return (f"skipped:{cause}", hint)
        console.print(
            f"  [red]✗[/] get_verification_token (DNS_TXT) failed: {e}"
        )
        return (f"failed:get_token_dns:{_short(msg)}", "")

    # Step 9b-D: Write TXT record (idempotent probe-then-create).
    expected_txt_name = domain
    try:
        existing_records = cloudflare.list_dns_records(zone.zone_id)
    except cloudflare.CloudflareAPIError as e:
        console.print(f"  [red]✗[/] dns list failed: {e}")
        return (f"failed:dns_list:{_short(str(e))}", "")

    txt_already_present = any(
        r.type == "TXT" and r.name == expected_txt_name and r.content == token
        for r in existing_records
    )
    if txt_already_present:
        console.print(
            f"  [green]✓[/] verification TXT already in zone "
            f"[dim](no write)[/]"
        )
    else:
        try:
            cloudflare.create_dns_record(
                zone.zone_id,
                type="TXT", name=expected_txt_name, content=token,
            )
        except cloudflare.CloudflareAPIError as e:
            console.print(f"  [red]✗[/] TXT record create failed: {e}")
            return (f"failed:dns_create:{_short(str(e))}", "")
        console.print(
            f"  [green]✓[/] wrote verification TXT to CF zone "
            f"[dim](TTL=auto)[/]"
        )

    # Step 9c-D: Verify via DNS_TXT.
    try:
        gsc_admin.verify_domain(
            domain, method=gsc_admin.VERIFICATION_METHOD_DNS_TXT,
        )
    except gsc_admin.VerificationFailedError as e:
        console.print(f"  [yellow]↷[/] verification timed out: {e}")
        return ("failed:verify_dns:propagation_timeout", "")
    except gsc_admin.GSCAdminError as e:
        msg = str(e)
        if "403" in msg:
            cause, hint = gsc_admin.classify_403(msg)
            console.print(f"  [yellow]↷[/] GSC 403 ({cause}): {hint}")
            return (f"skipped:{cause}", hint)
        console.print(f"  [red]✗[/] verify_domain (DNS_TXT) failed: {e}")
        return (f"failed:verify_dns:{_short(msg)}", "")
    console.print(
        f"  [green]✓[/] domain ownership verified by Google "
        f"[dim](DNS_TXT method)[/]"
    )
    return ("verified", "")


def _deploy_step9_gsc(
    *, domain: str, zone, project_dir, dry_run: bool, skip_gsc: bool,
) -> tuple[str, str]:
    """v24.C / v25.C — GSC registration + sitemap submission as Step 9.

    v25.C: verification method order is FILE first, DNS_TXT fallback.
    FILE doesn't need DNS:Edit on the zone (avoids the dropaudit.co
    failure mode); falls back to DNS_TXT only on structural issues
    (project doesn't expose `public/` — HG static-only sites).

    Returns `(status, detail)` where status is one of:

      - "created"             — verified + added + submitted (happy path)
      - "already-registered"  — property + sitemap already known to GSC
      - "skipped:--skip-gsc"  — operator opted out
      - "skipped:<other>"     — dry-run / OAuth not configured / etc.
      - "failed:<step>:<msg>" — any one sub-step failed; deploy continues

    Lazy imports so cf-pages/cf-workers deploys for sites that don't
    use GSC (rare but possible) don't pay the import cost.
    """
    console.print(f"\n[bold]9. GSC property + sitemap[/] [dim]({domain})[/]")

    if skip_gsc:
        console.print("  [yellow]↷[/] skipped (--skip-gsc)")
        return ("skipped:--skip-gsc", "")
    if dry_run:
        console.print(
            "  [dim]would: try FILE verification (write public/google<t>.html, "
            "commit+push, poll URL, verify); fall back to DNS_TXT if no "
            "public/; add sc-domain property, submit /sitemap.xml[/]"
        )
        return ("skipped:--dry-run", "")

    # Lazy imports — only load when this step actually runs.
    from . import cloudflare, gsc_admin
    from .gsc import TOKEN_PATH as GSC_TOKEN_PATH

    # Pre-flight: GSC OAuth token must exist. Check the file directly
    # rather than calling gsc.authenticate() (which would open a
    # browser) — operator needs to run `lamill settings gsc auth` once
    # before deploys auto-register GSC properties.
    if not GSC_TOKEN_PATH.exists():
        console.print(
            "  [yellow]↷[/] skipped (GSC OAuth not configured — run "
            "`lamill settings gsc auth` once, then re-run deploy)"
        )
        return ("skipped:GSC OAuth not configured", "")

    # --- 9a-c: Verify ownership ---
    # v25.F (2026-05-23) — DNS_TXT first now (was FILE first in v25.A/C).
    # See ADR-0016: DNS_TXT verifies the Domain property (sc-domain:<domain>)
    # that add_site / submit_sitemap operate on. FILE only verifies the
    # URL-prefix property — discovered after permittruck.xyz hit a 403 on
    # submit_sitemap despite FILE-verification succeeding. Step 3.5 (v25.B)
    # already gates the pipeline on DNS:Edit being available, so the
    # original "FILE-first to avoid DNS:Edit" rationale doesn't apply.
    status, detail = _step9_dns_verify(
        domain, zone, cloudflare, gsc_admin,
    )

    if status.startswith("skipped"):
        return (status, detail)
    if status.startswith("failed"):
        return (status, detail)

    # --- 9d: Add the GSC property (idempotent — returns False if exists) ---
    try:
        newly_added = gsc_admin.add_site(domain)
    except gsc_admin.GSCAdminError as e:
        console.print(f"  [red]✗[/] sites.add failed: {e}")
        return (f"failed:add_site:{_short(str(e))}", "")
    if newly_added:
        console.print(
            f"  [green]✓[/] added [cyan]sc-domain:{domain}[/] to GSC"
        )
    else:
        console.print(
            f"  [green]✓[/] [cyan]sc-domain:{domain}[/] already in GSC "
            f"[dim](no add)[/]"
        )

    # --- 9e: HEAD-probe + sitemap submission ---
    # v32.G — submit the site's ACTUAL sitemap (the robots.txt `Sitemap:`
    # line, e.g. `/sitemap-index.xml` for @astrojs/sitemap), not an assumed
    # `/sitemap.xml` (which the SPA catch-all serves as HTML → GSC parse error).
    sitemap_url = gsc_admin.resolve_sitemap_url(domain)
    try:
        import httpx as _httpx
        head_resp = _httpx.head(
            sitemap_url, timeout=5.0, follow_redirects=True,
        )
        sitemap_reachable = 200 <= head_resp.status_code < 400
    except _httpx.HTTPError:
        sitemap_reachable = False

    if not sitemap_reachable:
        console.print(
            f"  [yellow]↷[/] sitemap submission skipped — "
            f"{sitemap_url} not reachable yet "
            f"[dim](CHECK_063 covers /sitemap.xml presence; re-run "
            f"deploy after sitemap goes live)[/]"
        )
        # Verify+add succeeded, but the sitemap was NOT submitted — return a
        # distinct status so the summary doesn't false-green "sitemap
        # submitted" (bug log 2026-06-06). The idempotent re-run submits it
        # once the sitemap URL is reachable.
        if newly_added:
            return ("created:sitemap_deferred", "verified + added, sitemap deferred")
        return ("already-registered:sitemap_deferred", "already verified + added (sitemap deferred)")

    try:
        newly_submitted = gsc_admin.submit_sitemap(domain, sitemap_url)
    except gsc_admin.GSCAdminError as e:
        console.print(f"  [red]✗[/] sitemaps.submit failed: {e}")
        # Verify + add still succeeded; surface the partial state.
        return (f"failed:submit_sitemap:{_short(str(e))}", "")
    if newly_submitted:
        console.print(
            f"  [green]✓[/] submitted [cyan]{sitemap_url}[/] to GSC"
        )
        return ("created", "")
    console.print(
        f"  [green]✓[/] {sitemap_url} already submitted "
        f"[dim](no re-submit)[/]"
    )
    if newly_added:
        return ("created", "verified + added, sitemap already known")
    return ("already-registered", "fully registered already")


def _short(msg: str, *, n: int = 80) -> str:
    """Truncate a long error message for the gsc_status detail string.
    Keeps the result one-line for renderer purposes."""
    msg = msg.replace("\n", " ").strip()
    if len(msg) <= n:
        return msg
    return msg[:n - 1] + "…"


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

    # v36 — problem-surfacing diagnosis: gather every crawl/discovery/index
    # signal and compute an honest State (healthy/unproven/blocked) + a
    # prioritized Blockers list. Project-scoped — the fleet grade is untouched.
    # Degrades gracefully (never crashes the view) if a probe/source is absent.
    from .seo_diagnose import gather_seo_diagnosis
    from .research_render import render_seo_blockers, render_seo_state_header
    diag = None
    try:
        diag = gather_seo_diagnosis(domain)
    except Exception as e:    # noqa: BLE001 — diagnosis is additive, never fatal
        console.print(f"  [dim]↷ SEO diagnosis skipped: {type(e).__name__}: {e}[/]")

    # State headline ABOVE the table (so the honest verdict leads).
    if diag is not None:
        render_seo_state_header(diag, console)

    # Existing 1-row aggregate header (v5.D).
    _run_check_seo_mode(days=days, only_domain=domain,
                        sort_by=sort_by, only="wip", concurrency=20,
                        refresh=refresh)
    # v13.B diagnostics block below the header.
    _run_project_seo_diagnostics(domain, top_n=top_n,
                                 refresh=refresh, console=console)

    # v36 — the Blockers section last (the whole point). Never ends on green
    # when blockers exist.
    if diag is not None:
        render_seo_blockers(diag, console)


# v27.D — per-site todo read view. Reads `lamill.toml [[todo]]` only;
# no live fetch. Plural-symmetric with `fleet todos` (CLI naming rule).
@project_app.command("todos")
def project_todos(
    name: str = typer.Argument(..., metavar="DOMAIN", help="Domain or repo dir name"),
    add: str = typer.Option(
        None, "--add", metavar="TASK",
        help="Add an open todo with this task text.",
    ),
    priority: str = typer.Option(
        None, "--priority", "-p",
        help="Priority for --add: high | medium | low.",
    ),
    due: str = typer.Option(
        None, "--due",
        help="Due hint for --add (e.g. +14d, +2w, 2026-06-13) appended to "
             "the task text. Text-only — no schema field.",
    ),
    done: int = typer.Option(
        None, "--done", metavar="N",
        help="Mark the todo at file-order index N done (strips its priority).",
    ),
    reopen: int = typer.Option(
        None, "--reopen", metavar="N",
        help="Reopen the done todo at file-order index N.",
    ),
) -> None:
    """Per-project todo tracker — open items grouped by priority, done dimmed.

    With no flags, a pure read of the site's `lamill.toml [[todo]]` table
    (a site with no `lamill.toml` / no todos renders empty — additive-
    optional, never required). The write verbs mutate in place via a
    surgical upsert (`lamill_toml_edit`), so `[content]`, comments, and
    table ordering are preserved (ADR-0018) — then re-render the result.

    `<N>` for --done / --reopen is the 1-based file-order index shown as
    `[n]` in the read view.
    """
    from .project import resolve_project, SITES_ROOT
    from . import todos as todos_mod
    from . import lamill_toml
    from . import lamill_toml_edit as edit

    res = resolve_project(name)
    if not res.matched:
        console.print(f"[red]No project matches '{name}'.[/]")
        if res.candidates:
            console.print(f"[dim]Did you mean: {', '.join(res.candidates)}?[/]")
        raise typer.Exit(1)
    repo = SITES_ROOT / res.matched

    # One mutation per call; --priority / --due only modify --add.
    n_actions = sum(x is not None for x in (add, done, reopen))
    if n_actions > 1:
        console.print("[red]✗ choose one of --add / --done / --reopen per call.[/]")
        raise typer.Exit(2)
    if (priority is not None or due is not None) and add is None:
        console.print("[red]✗ --priority / --due only apply with --add.[/]")
        raise typer.Exit(2)

    try:
        if add is not None:
            task = add + (edit.due_hint(due) if due is not None else "")
            item = edit.add_todo(repo, task=task, priority=priority)
            console.print(
                f"[green]✓ added[/] ({priority or 'unprioritized'}) {escape(item.task)}"
            )
        elif done is not None:
            item = edit.complete_todo(repo, done)
            console.print(f"[green]✓ done[/] \\[{done}] {escape(item.task)}")
        elif reopen is not None:
            item = edit.reopen_todo(repo, reopen)
            console.print(f"[green]✓ reopened[/] \\[{reopen}] {escape(item.task)}")
    except edit.TodoEditError as e:
        console.print(f"[red]✗ {res.matched}: {e}[/]")
        raise typer.Exit(1)
    except lamill_toml.ParseError as e:
        console.print(f"[red]✗ {res.matched}: malformed lamill.toml — {e}[/]")
        raise typer.Exit(1)

    try:
        pt = todos_mod.build_project_todos(repo, domain=res.matched)
    except lamill_toml.ParseError as e:
        console.print(f"[red]✗ {res.matched}: malformed lamill.toml — {e}[/]")
        raise typer.Exit(1)
    todos_mod.render_project_todos(pt, console)


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


# v33.F — request input ergonomics. A full multi-step prompt shouldn't have
# to survive shell quoting as one positional arg. `request` is optional: an
# inline arg wins; otherwise read from stdin — an interactive paste or a
# silent read when piped (`delegate <d> < req.txt`).
# v33.K — interactive paste ends on a lone `.` sentinel (deterministic
# regardless of trailing newline), with Ctrl-D/EOF kept as a fallback. The
# old Ctrl-D-only path was flaky: a terminal only signals EOF at line start,
# so a no-trailing-newline paste needed a second Ctrl-D.
def _resolve_delegate_request(request: str | None) -> str:
    """Resolve the delegate request from an inline arg, an interactive paste,
    or piped stdin. Returns the stripped request (``""`` when empty — the
    caller aborts)."""
    import sys

    if request is not None:
        return request.strip()
    if not sys.stdin.isatty():
        # Piped (`< prompt.txt`, heredoc): read to EOF; no sentinel needed.
        return sys.stdin.read().strip()
    # Interactive: read lines until a lone `.` sentinel, or EOF (Ctrl-D).
    console.print("[dim]Paste your request, then a line with just "
                  "'.' (or Ctrl-D):[/]")
    lines: list[str] = []
    for line in sys.stdin:
        if line.strip() == ".":        # lone-dot terminator (sentinel)
            break
        lines.append(line)
    return "".join(lines).strip()


# v33.B — `project delegate`. Hands a site a multi-step instruction and
# lets Claude implement it semi-autonomously inside a fresh, disposable
# container (only the site dir mounted RW + host ~/.claude), supervised on
# two axes (liveness + progress), stopping at an uncommitted reviewable
# diff. Third local-FS write surface (ADR-0023). Verify gate = v33.C/D.
@project_app.command("delegate")
def project_delegate(
    domain: str = typer.Argument(..., help="Site to work on (e.g. drdebug.dev)"),
    request: str = typer.Argument(
        None,
        help="What to implement. Omit to paste it (Ctrl-D to end) or pipe it "
             "in (`delegate <domain> < prompt.txt`)."),
    force: bool = typer.Option(
        False, "--force",
        help="Run even if the working tree is dirty (diff will be muddied — "
             "not recommended).",
    ),
    budget: float = typer.Option(
        3.0, "--budget", help="Cost cap in USD for the agent run."),
    timeout: int = typer.Option(
        1200, "--timeout", help="Wall-clock cap in seconds."),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Deprecated no-op — delegate no longer prompts (kept for "
             "compatibility)."),
    no_verify: bool = typer.Option(
        False, "--no-verify",
        help="Skip the post-run verify gate (build + project check + visual)."),
    no_visual: bool = typer.Option(
        False, "--no-visual",
        help="Run build + check, but skip the Playwright visual probe."),
    debug: bool = typer.Option(
        False, "--debug",
        help="Persist the raw stream-json + stderr + docker argv to a "
             "transcript file for post-mortem (also via LAMILL_DELEGATE_DEBUG=1)."),
    no_wait: bool = typer.Option(
        False, "--no-wait",
        help="On the 5-hour usage cap, fail fast with the reset time instead "
             "of waiting it out. (Default: wait + retry. Non-TTY contexts fail "
             "fast automatically.) The real fix is enabling org-level overage "
             "billing, which removes the hard cap entirely."),
    wait: bool = typer.Option(
        False, "--wait",
        help="Force wait-out-the-cap even in a non-TTY/scripted context "
             "(which otherwise fails fast)."),
    max_wait: float = typer.Option(
        6.0, "--max-wait",
        help="Max hours to wait out a usage cap before giving up (default 6h)."),
    max_retries: int = typer.Option(
        2, "--max-retries",
        help="Max post-cap re-runs before giving up (default 2)."),
    no_split: bool = typer.Option(
        False, "--no-split",
        help="Run the request as ONE monolithic agent task. By default a "
             "cheap planner first splits a large request into ordered, "
             "independently-verifiable sub-tasks that run in sequence "
             "(accumulating in the tree) — so a big job finishes in bites "
             "instead of one quota-burning marathon."),
    backend: str = typer.Option(
        "auto", "--backend",
        help="Which agent backend: 'auto' (default — Claude primary, hand off "
             "to the OpenHands/OpenAI fallback the moment Claude hits the 5h "
             "cap), 'claude' (Claude only; waits out the cap), or 'oss' "
             "(OpenHands/OpenAI directly — keeps Claude quota free). The OSS "
             "backend needs the lamill-openhands image (build "
             "b2b/ai/openhands)."),
) -> None:
    """Delegate an open-ended change to Claude, in a sandboxed container.

    Claude runs INSIDE a disposable container with only `sites/<domain>/`
    mounted read-write; it edits the working tree in place and lamill leaves
    the changes UNCOMMITTED for you to review (`git diff`) and commit. The
    run is bounded (wall-clock + budget) and supervised — it's killed if it
    stalls (no activity) or spins (active but no net progress). Refuses on a
    dirty tree so the resulting diff is unambiguous.

    After a clean run it verifies the change: build + `project check`
    (regressions ⇒ verify-fail) and a best-effort visual probe. If the
    visual probe can't confirm, the run reports `needs-review` and leaves
    it for you to eyeball — it does not auto-proceed.
    """
    import shutil

    from .delegate import (Bounds, DelegateRefused, DockerBackend,
                           DockerVerifier, ResilientConfig, SplitResult,
                           append_delegate_prompt_log, format_local,
                           preflight, probe_quota_host,
                           run_delegate_resilient, run_delegate_split,
                           run_project_checks)

    domain = domain.lower()
    if shutil.which("docker") is None:
        console.print("[red]✗ docker not found on PATH.[/] delegate runs the "
                      "agent inside a container; install/start Docker first.")
        raise typer.Exit(1)

    # v33.I — preflight (resolve site dir + clean-tree precondition) BEFORE
    # collecting the request, so a dirty tree refuses instantly instead of
    # after the operator has pasted a whole multi-step prompt.
    try:
        site_dir = preflight(domain, force=force)
    except DelegateRefused as e:
        console.print(str(e))
        raise typer.Exit(1)

    # v33.F — resolve the request (inline arg ▸ interactive paste ▸ piped
    # stdin) so a full multi-step prompt needn't survive shell quoting.
    request = _resolve_delegate_request(request)
    if not request:
        console.print("↷ no request, aborting.")
        raise typer.Exit(0)

    # v33.J — no pre-run confirmation prompt. delegate's safety is the
    # uncommitted reviewable diff (you review before committing) + the
    # sandbox/supervisor/verify gate (ADR-0023), not a prompt; typing the
    # command + supplying a request is intent enough. `--yes` is kept as an
    # accepted no-op for compatibility.

    # Build the verify gate: snapshot conformance BEFORE the agent runs (on
    # the clean tree) so we can flag only *new* failures. One shared baseline;
    # a per-sub-task verifier (its own request drives the visual judge). Each
    # completed sub-task introduces no new failures, so comparing every
    # sub-task to the original clean baseline stays correct as the tree grows.
    baseline = None if no_verify else run_project_checks(site_dir)

    def _make_verifier(sub_request: str):
        if no_verify:
            return None
        return DockerVerifier(sub_request, check_baseline=baseline,
                              do_visual=not no_visual)

    bounds = Bounds(wall_clock_s=timeout, budget_usd=budget)
    # v33.O — opt-in post-mortem transcript (raw stream-json + stderr + argv).
    import os
    debug = debug or os.environ.get("LAMILL_DELEGATE_DEBUG", "") not in ("", "0", "false")
    debug_path = None
    if debug:
        from datetime import datetime
        dbg_dir = Path.home() / "lamill" / "delegate-debug"
        dbg_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        debug_path = dbg_dir / f"{domain}-{stamp}.log"
    def _make_backend():
        # Fresh disposable container per attempt (a retry's prior container is
        # already killed); same debug transcript path (last attempt wins).
        return DockerBackend(domain, budget_usd=budget, debug_path=debug_path)

    # v37 — backend selection. auto = Claude primary + OpenHands fallback on a
    # hard cap; claude = Claude only (waits out the cap); oss = OpenHands/OpenAI
    # directly (keeps Claude quota free for interactive work).
    backend = backend.lower()
    if backend not in ("auto", "claude", "oss"):
        console.print(f"[red]✗ --backend must be one of auto|claude|oss "
                      f"(got '{backend}').[/]")
        raise typer.Exit(2)

    def _make_oss_backend():
        from .apikeys import get_key
        from .delegate_oss import OpenHandsAdapter, OSSAgentBackend
        key = get_key("OPENAI_API_KEY") or ""
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — the OpenHands/OSS backend needs it. "
                "Set it: `lamill settings apikeys set OPENAI_API_KEY <key>`.")
        return OSSAgentBackend(
            domain, OpenHandsAdapter(api_key=key), debug_path=debug_path)

    if backend == "oss":
        primary_factory, fallback_factory = _make_oss_backend, None
    elif backend == "claude":
        primary_factory, fallback_factory = _make_backend, None
    else:                                   # auto
        primary_factory, fallback_factory = _make_backend, _make_oss_backend

    console.print(f"▸ delegate · [cyan]{domain}[/] — backend [cyan]{backend}[/] "
                  f"— running in sandbox…")
    if debug_path is not None:
        console.print(f"  [dim]↷ debug transcript → {debug_path}[/]")

    # v33.P — quota-aware self-healing on the 5-hour cap. Wait-by-default; but
    # in a non-TTY/scripted context behave as --no-wait (never hang automation
    # for hours) unless --wait forces it. --no-wait always wins.
    is_tty = console.is_terminal
    effective_wait = False if no_wait else (True if wait else is_tty)
    config = ResilientConfig(wait=effective_wait, max_wait_s=max_wait * 3600,
                             max_retries=max_retries)
    # Pre-flight quota probe (host-side, best-effort) — don't bring up a doomed
    # sandbox if the cap is already exhausted. Skipped (None) on non-TTY when
    # not waiting, since fail-fast doesn't need the extra call.
    # The host-side probe checks CLAUDE quota — irrelevant when running OSS-only.
    preflight_probe = (None if backend == "oss"
                       else (probe_quota_host if (effective_wait or is_tty) else None))

    # v33.L/v33.P — live progress + a Ctrl-C-interruptible quota countdown,
    # both driven through one rich spinner (suppressed off-TTY).
    import contextlib

    status_cm = (console.status("[cyan]starting…[/]", spinner="dots")
                 if is_tty else contextlib.nullcontext())
    try:
        with status_cm as status:
            def _on_progress(kind: str, detail: str) -> None:
                if kind == "reset":
                    console.print(f"  [green]✓ quota reset — resuming…[/]")
                    return
                if status is None:
                    return
                if kind == "phase":
                    status.update(f"[cyan]{detail}[/]")
                elif kind == "action":
                    status.update(f"[cyan]agent:[/] [dim]{detail}[/]")

            def _on_wait(remaining_s: float, target) -> None:
                if status is None:
                    return
                import math
                mins = max(1, math.ceil(remaining_s / 60))
                status.update(
                    f"[yellow]rate-limited — waiting for quota · resets "
                    f"{format_local(target)} · ~{mins}m left[/]")

            def _on_subtask(i: int, total: int, sub: str) -> None:
                if total > 1:
                    snippet = sub if len(sub) <= 80 else sub[:79] + "…"
                    console.print(f"\n  [bold cyan]▸ sub-task {i + 1}/{total}[/] "
                                  f"[dim]{escape(snippet)}[/]")

            if no_split:
                result = run_delegate_resilient(
                    domain, request, backend_factory=primary_factory,
                    config=config, bounds=bounds, force=force,
                    verifier=_make_verifier(request),
                    preflight_probe=preflight_probe,
                    fallback_backend_factory=fallback_factory,
                    on_progress=_on_progress, on_wait=_on_wait)
                split = SplitResult(subtasks=[request], outcomes=[result])
            else:
                # v33.Q — default: plan → run each sub-task through resume-on-cap,
                # accumulating in the tree. v37 — auto hands a capped sub-task to
                # the OSS fallback.
                split = run_delegate_split(
                    domain, request, backend_factory=primary_factory,
                    make_verifier=_make_verifier, config=config, bounds=bounds,
                    force=force, preflight_probe=preflight_probe,
                    fallback_backend_factory=fallback_factory,
                    on_progress=_on_progress, on_wait=_on_wait,
                    on_subtask=_on_subtask)
    except KeyboardInterrupt:
        # v33.P resume — don't hard-discard the agent's partial on abort either;
        # keep it in the tree (consistent with resume-on-cap) and tell the
        # operator how to continue or clean it.
        from .delegate import changed_files
        kept = changed_files(site_dir)
        if kept:
            console.print(
                f"\n  [yellow]↷ aborted — partial progress kept in the tree "
                f"({len(kept)} file(s)).[/]\n"
                f"  [dim]continue: re-run with --force · discard: "
                f"git -C sites/{domain} checkout -- . && git -C sites/{domain} "
                f"clean -fd[/]")
        else:
            console.print("\n  [yellow]↷ aborted — clean tree (no changes).[/]")
        raise typer.Exit(130)

    final = split.final
    # v33.H — append this run to the site's docs/Prompts.md (orchestrator-owned,
    # deterministic log) on full success that changed files. Logged once for the
    # whole request, against the accumulated diff.
    if split.all_done and final is not None and final.changed_files:
        total_cost = sum(o.cost_usd for o in split.outcomes)
        if append_delegate_prompt_log(
                site_dir, domain, request,
                files=len(final.changed_files), cost=total_cost,
                today=date.today().isoformat()):
            final.changed_files = sorted(
                set(final.changed_files) | {"docs/Prompts.md"})

    if split.was_split:
        _render_delegate_split(split, domain, request)
    else:
        _render_delegate_result(split.outcomes[0], domain, request)

    if not split.all_done:
        statuses = {o.status for o in split.outcomes}
        raise typer.Exit(1 if statuses & {"error", "refused"} else 0)


def _render_delegate_split(split, domain: str, request: str) -> None:
    """Render an auto-split run: the sub-task checklist + the accumulated diff
    + commit suggestion. `split` is a `delegate.SplitResult`."""
    total = len(split.subtasks)
    done = sum(1 for o in split.outcomes if o.status == "done")
    head = "green" if split.all_done else "yellow"
    console.print(f"\n  [bold {head}]Auto-split:[/] {done}/{total} sub-task(s) "
                  f"complete")
    for i, sub in enumerate(split.subtasks):
        snippet = sub if len(sub) <= 72 else sub[:71] + "…"
        if i < len(split.outcomes):
            o = split.outcomes[i]
            ok = o.status == "done"
            glyph, color = ("✓", "green") if ok else ("✗", "red")
            console.print(f"    [{color}]{glyph}[/] {i + 1}. {escape(snippet)}")
            if not ok:
                console.print(f"        [dim]{escape(o.reason)}[/]")
        else:
            console.print(f"    [dim]·[/] {i + 1}. [dim]{escape(snippet)} "
                          f"(not reached)[/]")

    final = split.final
    if final is not None and final.summary:
        text = final.summary.strip()
        if len(text) > 4000:
            text = text[:4000] + "\n… (summary truncated)"
        console.print(f"\n[bold]Last sub-task summary:[/]\n{escape(text)}")

    files = final.changed_files if final else []
    if files:
        shown = "\n".join(f"    {escape(f)}" for f in files[:20])
        more = f"\n    … and {len(files) - 20} more" if len(files) > 20 else ""
        site = f"sites/{domain}"
        msg = escape(_suggested_commit_msg(request))
        console.print(f"\n  {len(files)} file(s) changed across the run, left "
                      f"UNCOMMITTED:\n{shown}{more}")
        console.print(f"  diff:    [dim]git -C {site} diff[/]", soft_wrap=True)
        console.print(f"  commit:  [dim]git -C {site} add -A && "
                      f"git -C {site} commit -m \"{msg}\"[/]", soft_wrap=True)
        console.print("  [dim](review first — lamill never commits for you.)[/]")
    elif split.all_done:
        console.print("  (no file changes)")


def _render_delegate_verify(v) -> None:
    """Render the verify-gate detail block (build / check / visual)."""
    if v is None:
        return
    if v.build_ok is True:
        console.print("  ✓ build OK")
    elif v.build_ok is False:
        console.print(f"  ✗ build failed: [dim]{v.build_detail[:160]}[/]")
    if v.check_ok is True:
        console.print("  ✓ project check — no regression")
    elif v.check_ok is False:
        console.print(f"  ✗ conformance regressed: {', '.join(v.check_new_failures)}")
    if v.visual == "pass":
        console.print(f"  ✓ visual probe — {v.visual_detail[:120]}")
    elif v.visual in ("fail", "unavailable"):
        console.print(f"  ↷ visual probe {v.visual} — {v.visual_detail[:120]}")
        if v.screenshot:
            console.print(f"     screenshot: [dim]{v.screenshot}[/]")


def _suggested_commit_msg(request: str) -> str:
    """v33.M — a ready-to-paste commit subject from the request's first
    non-empty line (double-quotes neutralized so the shell command is safe)."""
    first = next((ln.strip() for ln in request.splitlines() if ln.strip()),
                 "agent change")
    return f"delegate: {first[:60].rstrip().replace(chr(34), chr(39))}"


def _render_delegate_result(result, domain: str, request: str = "") -> None:
    """Marker-coded summary of a delegate run; surfaces the agent's closing
    summary (v33.M) and ends pointing at the diff + a ready commit command."""
    if result.status == "refused":
        console.print(result.message)
        return
    meta = f"{result.duration_s:.0f}s · ${result.cost_usd:.2f}"
    if result.status == "done":
        console.print(f"  ✓ agent finished · {meta}")
    elif result.status == "error":
        console.print(f"  ✗ {result.reason}")
    elif result.status == "verify-fail":
        console.print(f"  ✗ change rejected by verify gate — {result.reason} ({meta})")
    elif result.status == "needs-review":
        console.print(f"  ⚠ needs your review — {result.reason} ({meta})")
    else:  # idle / spinning / timeout / budget — supervisor/backstop kills
        console.print(f"  ↷ stopped — {result.reason} ({meta})")
    _render_delegate_verify(result.verify)

    # v33.M — the agent's closing summary. For an inspect-first / report-back
    # run this IS the deliverable (no file changes), so always surface it.
    if result.summary:
        text = result.summary.strip()
        if len(text) > 6000:
            text = text[:6000] + "\n… (summary truncated)"
        console.print(f"\n[bold]Agent summary:[/]\n{escape(text)}")

    files = result.changed_files
    if files:
        shown = "\n".join(f"    {escape(f)}" for f in files[:20])
        more = f"\n    … and {len(files) - 20} more" if len(files) > 20 else ""
        site = f"sites/{domain}"
        msg = escape(_suggested_commit_msg(request))
        console.print(
            f"\n  {len(files)} file(s) changed, left UNCOMMITTED:\n{shown}{more}")
        # soft_wrap so the (often long) commands emit as single logical lines —
        # the terminal wraps them visually but copy-paste stays intact.
        console.print(f"  diff:    [dim]git -C {site} diff[/]", soft_wrap=True)
        console.print(f"  commit:  [dim]git -C {site} add -A && "
                      f"git -C {site} commit -m \"{msg}\"[/]", soft_wrap=True)
        console.print("  [dim](review first — lamill never commits for you.)[/]")
    else:
        console.print("  (no file changes)")


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


# v15.T — file-activity progress feed for `project translate`. The port
# is one opaque, fully-buffered `claude` subprocess (capture_output=True),
# so nothing reaches the terminal until it exits. Instead of leaving the
# operator staring at a silent prompt for 5-30 minutes, a daemon thread
# polls the output dirs and drives a rich spinner showing files landing.
# Presentation only — `port_to_astro` / `run_claude` stay untouched.

# Output buckets watched during a port (label, path-relative-to-project).
_PORT_PROGRESS_BUCKETS = (
    ("pages", ("src", "pages")),
    ("components", ("src", "components")),
    ("public", ("public",)),
)


def _fmt_elapsed(seconds: float) -> str:
    """Humanize an elapsed duration as `1m24s` / `42s` (matches the
    header's terse style)."""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m{secs:02d}s" if minutes else f"{secs}s"


def _count_recent_files(root, since: float) -> int:
    """Count files under `root` (recursive) modified at/after `since`,
    skipping atomic-write `.tmp` artifacts (the ones `sweep_tmp_artifacts`
    later cleans — counting them would make the tally flicker)."""
    if not root.is_dir():
        return 0
    n = 0
    for path in root.rglob("*"):
        try:
            if (
                path.is_file()
                and not path.name.endswith(".tmp")
                and path.stat().st_mtime >= since
            ):
                n += 1
        except OSError:
            continue
    return n


def _port_progress_counts(project_dir, since: float):
    """Return `[(label, count), ...]` of files written per bucket since
    `since` (wall-clock epoch seconds)."""
    return [
        (label, _count_recent_files(project_dir.joinpath(*parts), since))
        for label, parts in _PORT_PROGRESS_BUCKETS
    ]


def _watch_port_progress(project_dir, domain, status, stop, start_mono, start_wall):
    """Daemon-thread body: tick every ~2s, refresh the spinner caption
    with elapsed time + per-bucket file counts until `stop` is set."""
    import time

    while not stop.is_set():
        counts = _port_progress_counts(project_dir, start_wall)
        total = sum(c for _, c in counts)
        elapsed = _fmt_elapsed(time.monotonic() - start_mono)
        detail = " · ".join(f"{label} {c}" for label, c in counts)
        plural = "" if total == 1 else "s"
        status.update(
            f"[cyan]Porting {domain}[/]… {elapsed} · "
            f"{total} file{plural} written · {detail}"
        )
        stop.wait(2.0)


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

    # v15.T — drive a live file-activity spinner while the (opaque,
    # buffered) port subprocess runs. Skip the animation on non-TTY
    # output (CI / piped logs) so captures stay clean; the port runs
    # identically either way.
    import contextlib
    import threading
    import time

    start_mono = time.monotonic()
    start_wall = time.time()
    stop = threading.Event()
    watcher: threading.Thread | None = None
    status_cm = (
        console.status(f"[cyan]Porting {domain}[/]…", spinner="dots")
        if console.is_terminal
        else contextlib.nullcontext()
    )
    with status_cm as status:
        if status is not None:
            watcher = threading.Thread(
                target=_watch_port_progress,
                args=(project_dir, domain, status, stop, start_mono, start_wall),
                daemon=True,
            )
            watcher.start()
        try:
            result = port_to_astro(
                project_dir,
                source_stack=source_stack,
                source_signals=source_signals,
                budget_usd=budget_usd,
                timeout_s=timeout_s,
            )
        finally:
            stop.set()
            if watcher is not None:
                watcher.join(timeout=2.0)

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

    # v15.T — final tally: files landed + wall-clock elapsed alongside the
    # subprocess-reported cost.
    files_written = sum(c for _, c in _port_progress_counts(project_dir, start_wall))
    elapsed_total = _fmt_elapsed(time.monotonic() - start_mono)
    plural = "" if files_written == 1 else "s"
    console.print(
        f"\n[green]✓ Port complete.[/] "
        f"[dim]{files_written} file{plural} written in {elapsed_total} · "
        f"Cost: ${result.cost_usd:.4f}[/]"
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


# v27.D — fleetwide todo worklist. Reads every site's `lamill.toml
# [[todo]]` table; no live fetch. Plural-symmetric with `project todos`.
@fleet_app.command("todos")
def fleet_todos(
    priority: str = typer.Option(
        "", "--priority", "-p",
        help="Filter to one priority: high / medium / low.",
    ),
    status: str = typer.Option(
        "open", "--status", "-s",
        help="Filter by status: open / done / all.",
    ),
) -> None:
    """Fleetwide todo worklist — every site's todos in one ranked list.

    Default shows open items grouped by priority (high → unset). Use
    `--priority` to narrow to one level and `--status done`/`all` to
    change the slice. Sites without a `lamill.toml` or `[[todo]]` table
    contribute nothing; a malformed file is skipped, not fatal.
    """
    from .fleet_repos import list_site_dirs
    from . import todos as todos_mod

    prio = priority.lower() or None
    if prio is not None and prio not in todos_mod._PRIORITY_RANK:
        console.print("[red]--priority must be one of: high, medium, low.[/]")
        raise typer.Exit(2)

    status_norm = status.lower()
    if status_norm == "all":
        status_filter: str | None = None
    elif status_norm in ("open", "done"):
        status_filter = status_norm
    else:
        console.print("[red]--status must be one of: open, done, all.[/]")
        raise typer.Exit(2)

    rows = todos_mod.build_fleet_todos(
        list_site_dirs(), priority=prio, status=status_filter
    )
    todos_mod.render_fleet_todos(
        rows, console, priority=prio, status=status_filter
    )


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
    since: str = typer.Option(
        "7d", "--since",
        help="Δ baseline window: 7d (default) or 28d. Appends a Δ pos/imp "
             "column vs the nearest snapshot on-or-before today−N days.",
    ),
    detail: bool = typer.Option(
        False, "--detail",
        help="v16.D — append fleet-aggregated top queries / top pages / "
             "page-2 opportunities (across the fleet, not per-property).",
    ),
) -> None:
    """Runtime SEO probe across all live-site/forwarder domains.

    `--since` (v40) appends a Δ pos/imp column comparing each domain to an
    earlier dated snapshot (read-only diff of `data/seo/<date>.json`; no
    new storage). `--detail` (v16.D) renders three additional
    fleet-aggregated sections below the per-site table, reading from each
    domain's `data/gsc/<domain>/<UTC-today>.json` cache. Sections show as
    "(empty)" when no domains have cached GSC analytics data yet —
    populate via `lamill project seo <domain>` per site.
    """
    check_seo(days=days, domain="", repo="", only=only,
              concurrency=concurrency, sort_by=sort_by, refresh=refresh,
              since=since)

    if detail:
        _render_fleet_seo_detail(only=only, console=console)


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
        help="v15.F — pull live Porkbun domain list + v31.B GoDaddy inventory "
             "via API (writes data/domains/{porkbun,godaddy}.csv) before "
             "merging. Namecheap CSV remains manual until its account-API "
             "setup lands.",
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
    domain-age fetch. `--refresh` pulls live from Porkbun + GoDaddy first
    (both registrars' APIs; Namecheap stays manual).
    `--watch` runs continuously, re-merging on CSV change.
    """
    if refresh:
        _do_porkbun_refresh()
        _do_godaddy_refresh()

    info_cleanup(refresh_rdap=refresh_rdap)

    if watch:
        _watch_domains_loop(refresh_rdap=refresh_rdap, interval=interval)


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
        RecrawlError, append_to_growth_md, export_exchange_file,
        format_markdown_report, read_urls_from_file, resolve_site_dir,
        run_recrawl,
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

    # GSC Exchange v1 (lamill → rankmill): on a successful recrawl, write
    # the per-domain exchange file rankmill reads (ADR-0025). A failed pull
    # raised RecrawlError above and exited, so no partial/empty file ships.
    try:
        ex = export_exchange_file(report, site_dir)
        console.print(f"[green]✓[/] GSC exchange → {ex.relative_to(site_dir)} "
                      f"[dim]({len(report.inspections)} page(s), schema "
                      f"gsc-exchange-v1)[/]")
    except OSError as e:
        console.print(f"[yellow]warn: could not write exchange file: {e}[/]")


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


@settings_gsc_app.command("submit-sitemap")
def settings_gsc_submit_sitemap(
    site: str = typer.Option(..., "--site",
                             help="Site domain (e.g. airsucks.com). Must be a "
                                  "verified GSC property (sc-domain:<domain>)."),
    force: bool = typer.Option(False, "--force",
                               help="Force a re-fetch: delete the existing entry "
                                    "then re-submit. Use after a deploy that "
                                    "changed page content (e.g. enabling "
                                    "prerendering) to nudge Google to re-crawl."),
    url: str = typer.Option(None, "--url",
                            help="Override the sitemap URL. Default: resolved "
                                 "from the live robots.txt `Sitemap:` line."),
) -> None:
    """Submit (or re-submit) a site's sitemap to its GSC Domain property.

    Idempotent by default — skips if the sitemap is already submitted (GSC
    re-fetches submitted sitemaps on its own schedule). `--force` deletes the
    entry then re-submits, which makes Google re-fetch immediately — handy
    right after a content change. The sitemap URL comes from the live
    `robots.txt` `Sitemap:` line (v32.G), not an assumed path.
    """
    from . import gsc_admin
    from .gsc_admin import GSCAdminError
    try:
        feed = url or gsc_admin.resolve_sitemap_url(site)
        console.print(f"[dim]sitemap:[/] {feed}  [dim]→[/] sc-domain:{site}")
        existing = {s.get("path") for s in gsc_admin.list_sitemaps(site)}
        if force and feed in existing:
            gsc_admin.delete_sitemap(site, feed)
            console.print("  [yellow]↷[/] removed existing entry (forcing re-fetch)")
        added = gsc_admin.submit_sitemap(site, feed)
        if added:
            console.print(f"  [green]✓[/] submitted")
        else:
            console.print("  [yellow]↷[/] already submitted — GSC re-fetches on "
                          "its own; pass [cyan]--force[/] to re-fetch now")
    except GSCAdminError as e:
        console.print(f"  [red]✗[/] {e}")
        raise typer.Exit(2)
    except Exception as e:  # noqa: BLE001 — surface any failure cleanly, not a traceback
        console.print(f"  [red]✗[/] {type(e).__name__}: {e}")
        raise typer.Exit(2)


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


@settings_cloudflare_app.command("check-token")
def settings_cloudflare_check_token() -> None:
    """v25.D — Comprehensive CF API token diagnostic.

    Probes account-level (Pages:Edit, Workers Scripts:Edit, Account
    Settings:Read) and per-zone (DNS:Edit) permissions, then renders
    a per-zone table plus an actionable fix block when anything is
    missing. Use after `new deploy` fails with HTTP 403 / scope
    errors to see exactly which permission / zone is the gap.
    """
    from . import cloudflare

    console.print(
        "[bold]Diagnosing CF API token[/] [dim](probes accounts + "
        "zones — may take a few seconds for fleets with many zones)…[/]"
    )

    try:
        diag = cloudflare.diagnose_token()
    except cloudflare.MissingCredentialsError as e:
        console.print(f"[red]✗ No CF token configured:[/] {e}")
        raise typer.Exit(2)
    except cloudflare.CloudflareAPIError as e:
        console.print(f"[red]✗ Unexpected CF API error:[/] {e}")
        raise typer.Exit(2)

    console.print(f"\n[bold]Token status:[/] [cyan]{diag.token_status}[/]")

    if diag.accounts:
        console.print(
            f"\n[bold]Accounts[/] [dim]({len(diag.accounts)} accessible)[/]"
        )
        for acct in diag.accounts:
            pages = "[green]✓[/]" if acct.has_pages_edit else "[red]✗[/]"
            workers = "[green]✓[/]" if acct.has_workers_edit else "[red]✗[/]"
            settings = (
                "[green]✓[/]" if acct.has_account_settings_read else "[red]✗[/]"
            )
            console.print(
                f"  • [cyan]{acct.name}[/] "
                f"[dim]({acct.account_id[:8]}…)[/]"
            )
            console.print(
                f"    {pages} Pages:Edit   {workers} Workers:Edit   "
                f"{settings} Settings:Read"
            )

    if diag.zones:
        console.print(
            f"\n[bold]Zones[/] [dim]({len(diag.zones)} accessible)[/]"
        )
        for zone in diag.zones:
            dns_mark = "[green]✓[/]" if zone.has_dns_edit else "[red]✗[/]"
            purge_mark = "[green]✓[/]" if zone.has_cache_purge else "[red]✗[/]"
            settings_mark = (
                "[green]✓[/]" if zone.has_zone_settings_edit else "[red]✗[/]"
            )
            console.print(
                f"  [cyan]{zone.name}[/]   "
                f"{dns_mark} DNS:Edit   "
                f"{purge_mark} Cache Purge   "
                f"{settings_mark} Zone Settings:Edit"
            )

    if not (diag.missing_account_permissions or diag.missing_zone_permissions):
        console.print(
            "\n[bold green]✓ Token has all permissions lamill needs.[/]"
        )
        return

    console.print("\n[bold yellow]Missing permissions:[/]")
    for perm in diag.missing_account_permissions:
        console.print(f"  [red]·[/] {perm}")
    for zone_name, perm in diag.missing_zone_permissions:
        console.print(f"  [red]·[/] {zone_name} → {perm}")

    console.print(
        f"\n[bold]Fix:[/]\n"
        f"  1. Open: [link]https://dash.cloudflare.com/profile/"
        f"api-tokens[/link]\n"
        f"  2. Edit your existing token (or create a new one) with:\n"
        f"     [cyan]Account permissions[/]:  "
        f"Cloudflare Pages:Edit · Workers Scripts:Edit · Account Settings:Read\n"
        f"     [cyan]Zone permissions[/]:     "
        f"DNS:Edit · Zone:Edit · Workers Routes:Edit · SSL and Certificates:Edit\n"
        f"     [cyan]Zone resources[/]:       "
        f"Include — All zones from an account\n"
        f"  3. Save token; copy the value (CF shows it once); then:\n"
        f"     [cyan]lamill settings apikeys set CF_API_TOKEN <value>[/]\n"
        f"  4. Re-run [cyan]lamill settings cloudflare check-token[/] "
        f"to confirm.\n"
    )
    raise typer.Exit(1)


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
