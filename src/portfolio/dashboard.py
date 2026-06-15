"""v7.B-pre — unified `fleet dashboard` view.

Joins three cached signals into a single per-domain row:

  - Live  (data/checks/<date>.json)  — HTTP class + status from `fleet domains`
  - SEO   (data/seo/<date>.json)     — robots/sitemap/GSC from `fleet seo`
  - Git   (local filesystem)         — own-repo + last-commit age + catalog
                                       pass% from `project check` machinery

Read-only by default: just joins what's already on disk. `--refresh`
re-probes live + seo (git is always live since it's local FS).

The point of this surface is "one place to see whether each domain is
healthy across all dimensions" — daily-driver replacement for running
three separate fleet commands.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .console import spinner_counter

from datetime import date

from .check import (
    all_domains,
    best_per_domain,
    latest_snapshot as live_latest_snapshot,
    load_snapshot as live_load_snapshot,
    wip_domains,
)
from .data import load_domains, update_domain_field
from .project import SITES_ROOT, build_status, fetch_first_commit_date
from .seo_cache import (
    latest_snapshot as seo_latest_snapshot,
    load_snapshot as seo_load_snapshot,
    rows_from_snapshot,
)
from .seo_runtime import SEORow, overall_status as seo_overall_status

_GREEN = "🟢"
_YELLOW = "🟡"
_RED = "🔴"
_GREY = "—"

_LIVE_GREEN = {"live-site"}
_LIVE_YELLOW = {"parked", "forwarder"}
_LIVE_RED = {"dead", "error", "ssl-broken"}

_CONF_GREEN = 0.90
_CONF_YELLOW = 0.60
_AGE_GREEN_DAYS = 30
_AGE_YELLOW_DAYS = 90


@dataclass
class DashRow:
    domain: str
    # Live
    live_class: str | None = None
    http_status: int | None = None
    live_dot: str = _GREY
    # Git
    has_dir: bool = False
    own_repo: bool = False
    last_commit_age_days: int | None = None
    conf_pass: int = 0
    conf_total: int = 0
    git_dot: str = _GREY
    # SEO
    seo_dot: str = _GREY
    gsc_impressions: int | None = None
    gsc_clicks: int | None = None
    gsc_position: float | None = None
    # Hosting (v11.K integration — joins data/hosting/<date>.json)
    host_provider: str | None = None  # "vercel" | "cloudflare-pages" | "cloudflare-workers" | "hostgator" | None
    host_conflict: bool = False
    host_dot: str = _GREY
    # Age signals (site = first-commit / manual; domain = RDAP registration)
    site_age_days: int | None = None
    domain_age_days: int | None = None
    # Worst rollup across all four (None for "no data anywhere")
    rollup_dot: str = _GREY


def _live_dot(classification: str | None) -> str:
    if classification in _LIVE_GREEN:
        return _GREEN
    if classification in _LIVE_YELLOW:
        return _YELLOW
    if classification in _LIVE_RED:
        return _RED
    return _GREY


def _git_dot(*, has_dir: bool, own_repo: bool,
             age_days: int | None, conf_pct: float | None) -> str:
    if not has_dir:
        return _GREY
    if not own_repo:
        return _RED  # has dir but not its own git repo — that's a fail
    age_ok_green = age_days is not None and age_days < _AGE_GREEN_DAYS
    age_ok_yellow = age_days is not None and age_days < _AGE_YELLOW_DAYS
    conf_green = conf_pct is not None and conf_pct >= _CONF_GREEN
    conf_yellow = conf_pct is not None and conf_pct >= _CONF_YELLOW
    if conf_green and age_ok_green:
        return _GREEN
    if (conf_yellow and age_ok_yellow) or (conf_green and age_ok_yellow):
        return _YELLOW
    return _RED


_DOT_RANK = {_GREEN: 0, _YELLOW: 1, _RED: 2, _GREY: -1}


def _rollup(*dots: str) -> str:
    """Worst non-grey dot across the three dimensions. If all are grey, grey."""
    real = [d for d in dots if d != _GREY]
    if not real:
        return _GREY
    return max(real, key=lambda d: _DOT_RANK.get(d, -1))


def _domains_for_scope(scope: str) -> list[str]:
    if scope == "wip":
        return wip_domains()
    if scope == "all":
        return all_domains()
    raise ValueError(f"Unknown scope: {scope!r}")


def _load_live_index() -> tuple[Path | None, dict[str, dict]]:
    """Return (snapshot_path, {domain → best-classification row})."""
    snap = live_latest_snapshot()
    if snap is None:
        return None, {}
    try:
        data = live_load_snapshot(snap)
    except (OSError, ValueError):
        return snap, {}
    return snap, best_per_domain(data)


def _load_seo_index() -> tuple[Path | None, dict[str, SEORow]]:
    snap = seo_latest_snapshot()
    if snap is None:
        return None, {}
    try:
        data = seo_load_snapshot(snap)
    except (OSError, ValueError):
        return snap, {}
    return snap, {r.domain: r for r in rows_from_snapshot(data)}


def _load_hosting_index() -> tuple[Path | None, dict[str, list]]:
    """v11.K — read the latest `data/hosting/<date>.json` snapshot.
    Returns `(snapshot_path, {domain → list-of-HostingRow})`. The
    value is a LIST not a single row because a domain can appear
    under multiple providers (cross-walker conflict per resolution
    11.F, e.g. addon on both HG accounts). Dashboard reads the list
    to surface conflicts; collapses to first row when no conflict."""
    from . import hosting_cache

    snap = hosting_cache.latest_snapshot()
    if snap is None:
        return None, {}
    try:
        data = hosting_cache.load_snapshot(snap)
        result = hosting_cache.result_from_snapshot(data)
    except (OSError, ValueError):
        return snap, {}
    out: dict[str, list] = {}
    for r in result.rows:
        out.setdefault(r.domain, []).append(r)
    return snap, out


def _host_dot(host_rows: list) -> tuple[str, str | None, bool]:
    """Map a per-domain list of HostingRows to a (dot, provider_label,
    conflict_flag) tuple for the dashboard.

    Resolution 11.C age thresholds + the conflict / runaway-failure /
    unowned overrides — same priority cascade as
    `hosting.hosting_status_emoji` but maps to the dashboard's
    color-dot vocabulary (🟢 / 🟡 / 🔴 / —) rather than the rich
    status-emoji set.

    Conflict precedence: when multiple walker rows match a domain
    (cross-provider or same-provider duplicate), the dot is 🔴 and
    the conflict flag is set. The provider label shows the first row's
    provider, suffixed with `…+` when there are more.
    """
    from .hosting import (
        MAX_DEPLOY_LOOKBACK, RECENT_DAYS, STALE_DAYS,
    )
    from datetime import datetime, timezone

    if not host_rows:
        return _GREY, None, False

    # Cross-walker conflict — flag red regardless of provider state.
    if len(host_rows) > 1 or any(r.provider_conflict for r in host_rows):
        primary = host_rows[0].provider or "—"
        if len(host_rows) > 1:
            primary = f"{primary}+"
        return _RED, primary, True

    row = host_rows[0]
    provider = row.provider

    if row.consecutive_failures >= MAX_DEPLOY_LOOKBACK:
        return _RED, provider, False

    last_ok = row.last_successful_deploy_at
    if not last_ok:
        # HG has no build pipeline → green (presence is good enough).
        # Other providers with no last_successful means walker found
        # the project but it hasn't shipped — yellow.
        if provider == "hostgator":
            return _GREEN, provider, False
        return _YELLOW, provider, False

    try:
        ts = datetime.fromisoformat(last_ok.replace("Z", "+00:00"))
    except ValueError:
        return _GREY, provider, False
    age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
    if age_days < RECENT_DAYS:
        return _GREEN, provider, False
    if age_days < STALE_DAYS:
        return _YELLOW, provider, False
    return _RED, provider, False


def _git_summary_for(domain: str) -> dict:
    """Run the v5.E catalog and the v1 git pulse for a single domain.
    Pure local-FS — no network. Slow path is the catalog (~50ms per project).
    """
    project_dir = SITES_ROOT / domain
    if not project_dir.exists():
        return {"has_dir": False, "own_repo": False,
                "age_days": None, "conf_pass": 0, "conf_total": 0}
    status = build_status(domain)
    git = status.get("git") or {}
    last = git.get("last_commit") or {}
    conf = status.get("conformance") or {}
    passed = conf.get("passed") or []
    failed = conf.get("failed") or []
    skipped = conf.get("skipped") or []
    # Skipped checks don't count toward total (they're "not applicable").
    total = len(passed) + len(failed)
    age = last.get("age_days")
    return {
        "has_dir": True,
        "own_repo": bool(git.get("own_repo_pass")),
        "age_days": age,
        "conf_pass": len(passed),
        "conf_total": total,
        "skipped": len(skipped),
    }


def _site_age_days(domain: str, launched: date | None) -> int | None:
    """Site age = days since `launched` (manual) or first git commit (auto).

    Auto-inferred values aren't persisted — the dashboard recomputes on
    each read so projects that get a fresh first commit naturally update.
    `settings deploy set-launched` persists an explicit override that wins over
    the inference.
    """
    today = date.today()
    if launched is not None:
        return (today - launched).days
    project_dir = SITES_ROOT / domain
    inferred = fetch_first_commit_date(project_dir) if project_dir.exists() else None
    if inferred is None:
        return None
    return (today - inferred).days


def build_dashboard_rows(scope: str = "wip",
                         progress=None) -> tuple[list[DashRow], dict]:
    """Build one DashRow per domain in scope. Returns (rows, freshness)
    where freshness reports which caches were used.

    `progress`, if given, is called `(done, total, domain)` after each
    domain's row is built — the per-site `_git_summary_for` (git + per-repo
    conformance) makes this loop the slow, silent phase otherwise."""
    domains = _domains_for_scope(scope)
    live_path, live_index = _load_live_index()
    seo_path, seo_index = _load_seo_index()
    host_path, host_index = _load_hosting_index()

    # portfolio.json metadata: launched + domain_created (RDAP age).
    meta_by_name = {dom.name: dom for dom in load_domains()}

    rows: list[DashRow] = []
    for i, d in enumerate(domains, start=1):
        live = live_index.get(d)
        cls = live.get("classification") if live else None
        live_dot = _live_dot(cls)

        git = _git_summary_for(d)
        conf_pct = (git["conf_pass"] / git["conf_total"]) if git["conf_total"] else None
        git_dot = _git_dot(has_dir=git["has_dir"],
                           own_repo=git["own_repo"],
                           age_days=git["age_days"],
                           conf_pct=conf_pct)

        meta = meta_by_name.get(d)
        site_age = _site_age_days(d, meta.launched if meta else None)
        dom_age = meta.domain_age_days if meta else None

        seo = seo_index.get(d)
        # P4 — pass site age into the grader so young sites don't get
        # 🔴'd for the normal "zero impressions yet" + "no position data"
        # state that any new indexed site has.
        seo_dot = seo_overall_status(seo, site_age_days=site_age) if seo else _GREY
        # seo_runtime emits ⚪ for "no data" — normalize to our _GREY ("—")
        if seo_dot == "⚪":
            seo_dot = _GREY

        host_rows = host_index.get(d, [])
        host_dot, host_provider, host_conflict = _host_dot(host_rows)

        rollup = _rollup(live_dot, git_dot, seo_dot, host_dot)

        rows.append(DashRow(
            domain=d,
            live_class=cls,
            http_status=live.get("status") if live else None,
            live_dot=live_dot,
            has_dir=git["has_dir"],
            own_repo=git["own_repo"],
            last_commit_age_days=git["age_days"],
            conf_pass=git["conf_pass"],
            conf_total=git["conf_total"],
            git_dot=git_dot,
            seo_dot=seo_dot,
            gsc_impressions=seo.gsc_impressions if seo else None,
            gsc_clicks=seo.gsc_clicks if seo else None,
            gsc_position=seo.gsc_position if seo else None,
            host_provider=host_provider,
            host_conflict=host_conflict,
            host_dot=host_dot,
            site_age_days=site_age,
            domain_age_days=dom_age,
            rollup_dot=rollup,
        ))
        if progress is not None:
            progress(i, len(domains), d)

    freshness = {
        "live_snapshot": live_path.name if live_path else None,
        "seo_snapshot": seo_path.name if seo_path else None,
        "hosting_snapshot": host_path.name if host_path else None,
        "scope": scope,
    }
    return rows, freshness


_SORT_KEYS = {
    "attention": lambda r: (
        -_DOT_RANK.get(r.rollup_dot, -1),  # red (rank 2) → most negative? no, we want red FIRST so highest rank first
        r.domain,
    ),
    "name": lambda r: (r.domain,),
    "imp": lambda r: (-(r.gsc_impressions or 0), r.domain),
    "age": lambda r: (-(r.last_commit_age_days or -1), r.domain),
}


def sort_rows(rows: list[DashRow], key: str) -> list[DashRow]:
    if key == "attention":
        # Want red(rank 2) first, then yellow(1), then green(0), then grey(-1).
        # Sort descending by rank.
        return sorted(rows, key=lambda r: (-_DOT_RANK.get(r.rollup_dot, -1), r.domain))
    if key == "name":
        return sorted(rows, key=lambda r: r.domain)
    if key == "imp":
        return sorted(rows, key=lambda r: (-(r.gsc_impressions or 0), r.domain))
    if key == "age":
        # Newest commits (smaller age_days) first; missing → last.
        def age_key(r: DashRow) -> tuple:
            age = r.last_commit_age_days
            return (1, "", "") if age is None else (0, age, r.domain)
        return sorted(rows, key=age_key)
    raise ValueError(f"Unknown sort key: {key!r}")


def _fmt_int(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else _GREY


def _fmt_pos(v: float | None) -> str:
    return f"{v:.1f}" if isinstance(v, float) else _GREY


def _fmt_age(days: int | None) -> str:
    if days is None:
        return _GREY
    if days < 1:
        return "today"
    return f"{days}d"


def _fmt_long_age(days: int | None) -> str:
    """Compact age for site/domain columns. Days/weeks/months/years.
    Differs from `_fmt_age` (commit age) which always shows days because
    that column tops out around 90d in practice."""
    if days is None:
        return _GREY
    if days < 1:
        return "today"
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"


def _fmt_conf(pass_n: int, total: int) -> str:
    if total == 0:
        return _GREY
    pct = pass_n / total
    return f"{int(pct * 100)}%"


def _provider_short(provider: str | None) -> str:
    """Compact provider label for the dashboard's narrow Host column.
    Maps `hosting.PROVIDERS` strings to 2-letter codes so the column
    stays scannable next to the colored dot."""
    if not provider:
        return _GREY
    plain = provider.rstrip("+")
    code = {
        "vercel": "VC",
        "cloudflare-pages": "CFP",
        "cloudflare-workers": "CFW",
        "hostgator": "HG",
    }.get(plain, plain[:3].upper())
    return code + ("+" if provider.endswith("+") else "")


def render_dashboard(rows: list[DashRow], freshness: dict, *,
                     sort_key: str, console: Console) -> None:
    scope = freshness.get("scope", "?")
    live_snap = freshness.get("live_snapshot") or "—"
    seo_snap = freshness.get("seo_snapshot") or "—"
    host_snap = freshness.get("hosting_snapshot") or "—"

    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]fleet dashboard · scope={scope} · {len(rows)} domains · sort={sort_key}[/]",
              title_justify="left")
    # Size the Domain column to the longest domain in the data so Rich
    # never squeezes/truncates it (`hyb…`, `air…`) when the terminal is
    # narrow and the many trailing metric columns compete for width.
    # `no_wrap` + an explicit `width` keep full domains rendering even
    # off-TTY / at standard COLUMNS; the metric columns flex instead.
    domain_width = max((len(r.domain) for r in rows), default=6)
    domain_width = max(domain_width, len("Domain"))

    t.add_column("")              # rollup dot
    t.add_column("Domain", no_wrap=True, width=domain_width)
    t.add_column("Live", justify="center")
    t.add_column("HTTP", justify="right")
    t.add_column("Git", justify="center")
    t.add_column("Last", justify="right")     # last commit age
    t.add_column("Conf", justify="right")
    t.add_column("SEO", justify="center")
    t.add_column("Imp", justify="right")
    t.add_column("Clicks", justify="right")
    t.add_column("Pos", justify="right")
    t.add_column("Host", justify="center")    # v11.K — hosting dot
    t.add_column("Prov", justify="left")      # v11.K — provider code
    t.add_column("Site", justify="right")     # since launched
    t.add_column("Domain", justify="right")   # since RDAP creation
    # v16.D — GSC rollup columns. Read from per-domain caches
    # (`data/gsc/<domain>/<UTC-today>.json`). Render `—` when cache
    # absent / stale / section not yet populated.
    t.add_column("Cov %", justify="right")        # v16.D — Coverage %
    t.add_column("Crawl-err", justify="right")    # v16.D — Non-indexed URLs (from v16.C inspections)
    t.add_column("P2-opp", justify="right")       # v16.D — Page-2 opportunities count

    # v16.D — bulk-load per-domain GSC rollup once per render (cheap;
    # each lookup just reads one JSON file). Bulk-loading here avoids
    # importing gsc_rollup at module top to keep dashboard's import
    # surface minimal.
    from . import gsc_rollup as _rollup

    for r in rows:
        http_cell = _fmt_int(r.http_status) if r.http_status else _GREY

        cov = _rollup.domain_coverage_stats(r.domain)
        cov_pct_cell = f"{cov.coverage_pct:.0f}%" if cov else "—"
        crawl_err_cell = str(cov.crawl_errors) if cov else "—"
        p2_count = _rollup.page_2_opp_count(r.domain)
        p2_cell = str(p2_count) if p2_count is not None else "—"

        cells = [
            r.rollup_dot,
            r.domain,
            r.live_dot,
            http_cell,
            r.git_dot,
            _fmt_age(r.last_commit_age_days),
            _fmt_conf(r.conf_pass, r.conf_total),
            r.seo_dot,
            _fmt_int(r.gsc_impressions),
            _fmt_int(r.gsc_clicks),
            _fmt_pos(r.gsc_position),
            r.host_dot,
            _provider_short(r.host_provider),
            _fmt_long_age(r.site_age_days),
            _fmt_long_age(r.domain_age_days),
            cov_pct_cell,
            crawl_err_cell,
            p2_cell,
        ]
        t.add_row(*cells)
    console.print(t)

    # Footer: rollup tally + freshness.
    from collections import Counter
    counts = Counter(r.rollup_dot for r in rows)
    parts = []
    for emoji, label in ((_GREEN, "green"), (_YELLOW, "yellow"),
                         (_RED, "red"), (_GREY, "no-data")):
        if counts.get(emoji):
            parts.append(f"{emoji} {counts[emoji]} {label}")
    if parts:
        console.print("\n[dim]" + " · ".join(parts) + "[/]")
    console.print(
        f"[dim]Sources: live={live_snap} · seo={seo_snap} · "
        f"host={host_snap} · git=live (FS)[/]"
    )


def run_dashboard(*, scope: str = "wip", sort: str = "attention",
                  refresh: bool = False, console: Console) -> None:
    """Driver — pulls all three caches, optionally re-probes live+seo, renders."""
    if refresh:
        # Re-probe live then seo. Keeps the existing flows authoritative;
        # dashboard just consumes their snapshots.
        from .check import run_check
        from .seo_cache import save_snapshot as seo_save_snapshot
        from .seo_runtime import _live_domains_from_snapshot, run_seo
        from .suggest import load_env

        _live_total = len(wip_domains() if scope == "wip" else all_domains())
        with spinner_counter(f"live snapshot ({scope})", _live_total) as live_prog:
            snap_path, _ = run_check(only=scope, concurrency=20,
                                     progress=live_prog)
        console.print(f"[green]✓[/] live snapshot: {snap_path.name} · "
                      f"{live_prog.elapsed:.0f}s")
        domains = _live_domains_from_snapshot(live_load_snapshot(snap_path))
        if domains:
            crux_key = load_env().get("CRUX_API_KEY", "").strip()
            with spinner_counter("SEO probes", len(domains)) as progress:
                seo_rows = run_seo(domains, days=28, crux_api_key=crux_key,
                                   progress_callback=progress)
            cache_path = seo_save_snapshot(seo_rows, days=28)
            console.print(f"[green]✓[/] SEO probes: {len(domains)} domains "
                          f"({cache_path.name}) · {progress.elapsed:.0f}s")

    _rows_total = len(wip_domains() if scope == "wip" else all_domains())
    with spinner_counter("building dashboard", _rows_total) as build_prog:
        rows, freshness = build_dashboard_rows(scope=scope, progress=build_prog)
    rows = sort_rows(rows, sort)
    render_dashboard(rows, freshness, sort_key=sort, console=console)
