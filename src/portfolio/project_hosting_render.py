"""v15.B — `project hosting <domain>` vertical-sections renderer.

Renders one domain's hosting state as stacked sections (header,
📦 Deploy, 📌 Domains) instead of a one-row table. Mirrors the
v13.B `project_seo_diagnostics` rendering pattern — per-project
output is vertical so each section can grow without horizontal
crowding.

Sections 📋 Freshness and 🔧 Build are intentionally out of scope
here; v15.D and v15.E add those later. This module renders only
what's available on the existing `HostingRow` dataclass.

The renderer is duck-typed on the row argument: accepts a
`HostingRow` instance OR a dict reconstructed from the snapshot
cache. Same shape both ways.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


# Status glyph for the deploy state. Mirrors `hosting_status_emoji`
# but lighter — the vertical view only needs the success/failure
# binary for the section header.
def _deploy_status_glyph(status: str | None) -> tuple[str, str, str]:
    """Return `(glyph, color, label)` for a deploy state. Falls back
    to a neutral marker when the state is unknown."""
    if status is None:
        return ("·", "dim", "UNKNOWN")
    upper = status.upper()
    if upper in ("READY", "SUCCESS", "ACTIVE"):
        return ("✓", "green", "DEPLOYED")
    if upper in ("ERROR", "CANCELED", "FAILED"):
        return ("✗", "red", upper)
    if upper in ("BUILDING", "INITIALIZING", "QUEUED", "PENDING"):
        return ("⋯", "yellow", upper)
    return ("·", "dim", upper)


def _humanize_age(iso: str | None) -> str:
    """`2026-05-19T07:02:23+00:00` → `12h ago`. Returns empty string
    when input is None / unparseable so the renderer can omit the
    parenthetical entirely instead of showing `(— ago)`."""
    if not iso:
        return ""
    try:
        ts = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(timezone.utc)
    delta = now - ts
    secs = int(delta.total_seconds())
    if secs < 0:
        return ""
    if secs < 3600:
        return f"{max(1, secs // 60)}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    if secs < 86400 * 14:
        return f"{secs // 86400}d ago"
    if secs < 86400 * 90:
        return f"{secs // (86400 * 7)}w ago"
    return f"{secs // (86400 * 365)}y ago"


def _format_iso_short(iso: str | None) -> str:
    """`2026-05-19T07:02:23+00:00` → `2026-05-19 07:02`. Returns
    `—` when input is None or unparseable."""
    if not iso:
        return "—"
    try:
        ts = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return "—"
    return ts.strftime("%Y-%m-%d %H:%M")


def _get(obj: Any, key: str, default=None):
    """Duck-typed accessor — works for both dataclass and dict."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def render_project_hosting(
    *, domain: str, rows: list, skipped: dict[str, str], source: str,
    console, freshness: Any = None,
) -> None:
    """Render the vertical-sections view for a single domain.

    `rows` is the subset of HostingRow objects (or cached dicts) that
    matched `domain`. For most domains it's a list of length 1; for
    provider-conflict cases (same domain under two walkers) it can be
    longer — each provider then gets its own header + deploy block,
    grouped under one 📌 Domains rollup.

    `freshness` is an optional `FreshnessReport` (v15.D) — adds the
    📋 Freshness section between Deploy and Domains. Omitted entirely
    when None (the v15.B baseline keeps working).
    """
    console.print(f"[dim]Source: {source}[/]")

    if not rows:
        console.print(
            f"\n  [yellow]No hosting rows for {domain}.[/]\n"
            f"  [dim]The domain isn't claimed by any configured "
            f"provider (Vercel / Cloudflare / HostGator).[/]"
        )
        if skipped:
            console.print()
            for label, reason in sorted(skipped.items()):
                console.print(f"  [dim]{label} skipped: {reason}[/]")
        return

    # Per-provider section. Most domains have one row; conflict cases
    # render every matching row.
    for row in rows:
        _render_one_row(row, console)

    # v15.D — Freshness section (between Deploy and Domains).
    if freshness is not None:
        _render_freshness_section(freshness, console)

    # Domains rollup at the end — collects custom_domains across
    # every matched row (with dedup) plus the canonical domain.
    _render_domains_section(domain, rows, console)

    if skipped:
        console.print()
        for label, reason in sorted(skipped.items()):
            console.print(f"  [dim]{label} skipped: {reason}[/]")


def _render_freshness_section(freshness: Any, console) -> None:
    """v15.D — render the 📋 Freshness section. `freshness` is a
    `FreshnessReport` (see `portfolio.version_stamp`)."""
    head = _get(freshness, "head_sha") or "?"
    live = _get(freshness, "live_sha") or "?"
    verdict = _get(freshness, "verdict", "")
    err = _get(freshness, "error_detail")

    head_short = head[:12] if head and head != "?" else "?"
    live_short = live[:12] if live and live not in ("?", "unknown") else live

    console.print()
    console.print(f"  [bold]📋 Freshness[/]")

    if verdict == "in_sync":
        console.print(f"    [dim]HEAD @[/]          {head_short}")
        console.print(
            f"    [dim]Live @[/]          {live_short}  "
            f"[green]✓ in sync[/]"
        )
        return

    if verdict == "drift":
        console.print(f"    [dim]HEAD @[/]          {head_short}")
        console.print(
            f"    [dim]Live @[/]          {live_short}  "
            f"[red]✗ drift — local HEAD ahead (or branch divergence)[/]"
        )
        console.print(
            f"    [dim]Hint:[/]           push + redeploy to align"
        )
        return

    if verdict == "head_unknown":
        console.print(
            f"    [yellow]·[/] local HEAD unavailable "
            f"[dim](not a git repo or `git` missing)[/]"
        )
        if live and live != "?":
            console.print(f"    [dim]Live @[/]          {live_short}")
        return

    if verdict == "live_unknown":
        console.print(
            f"    [yellow]·[/] live /version.json unavailable "
            f"[dim]({err or 'unknown error'})[/]"
        )
        if head_short != "?":
            console.print(f"    [dim]HEAD @[/]          {head_short}")
        return

    if verdict == "live_marker_unknown":
        console.print(
            f"    [yellow]·[/] live commit is the \"unknown\" fallback "
            f"[dim](deploy ran without git context)[/]"
        )
        if head_short != "?":
            console.print(f"    [dim]HEAD @[/]          {head_short}")
        return

    # Defensive — unknown verdict.
    console.print(
        f"    [dim]· unexpected freshness verdict: {verdict}[/]"
    )


def _render_one_row(row: Any, console) -> None:
    """Render the header + 📦 Deploy block for one HostingRow."""
    provider = _get(row, "provider") or "—"
    domain = _get(row, "domain", "?")
    hg_account = _get(row, "hg_account_id")
    project_slug = _get(row, "project_slug")
    project_id = _get(row, "project_id")
    latest_status = _get(row, "latest_deploy_status")
    latest_at = _get(row, "latest_deploy_at")
    last_success_at = _get(row, "last_successful_deploy_at")
    consecutive_failures = _get(row, "consecutive_failures", 0) or 0
    conflict = _get(row, "provider_conflict", False)
    error = _get(row, "error")
    notes = _get(row, "notes") or []

    # Account / branch resolution. Branch isn't on HostingRow — read
    # from lamill.toml if available, fall back to "main" (the schema
    # default). Same for account — HG rows have hg_account_id;
    # Vercel/CF rows don't carry a typed account slot on the row.
    account_label = hg_account or "—"
    branch_label = _resolve_branch(domain)

    # Header lines.
    console.print()
    console.print(
        f"  [bold]Property:[/] [cyan]{domain}[/]  ·  "
        f"[dim]platform:[/] {provider}"
    )
    console.print(
        f"  [dim]Account:[/] {account_label}  ·  "
        f"[dim]branch:[/] {branch_label}"
    )
    if conflict:
        console.print(
            f"  [yellow]🤐 provider conflict[/] "
            f"[dim](this domain is claimed by multiple walkers; "
            f"see fleet hosting for the cross-provider view)[/]"
        )

    # 📦 Deploy section.
    glyph, color, label = _deploy_status_glyph(latest_status)
    age = _humanize_age(last_success_at or latest_at)
    when = _format_iso_short(last_success_at or latest_at)
    when_parens = f" ({age})" if age else ""
    console.print()
    console.print(f"  [bold]📦 Deploy[/]")
    console.print(
        f"    [{color}]{glyph} {label:<14}[/] "
        f"{when}{when_parens}"
    )
    if consecutive_failures:
        console.print(
            f"    [dim]Failures:[/]        "
            f"[red]{consecutive_failures} consecutive[/]"
        )
    if project_slug:
        console.print(f"    [dim]Slug:[/]            {project_slug}")
    if project_id:
        console.print(f"    [dim]Deploy ID:[/]       {project_id}")
    if error:
        console.print(f"    [red]Error:[/]           {error}")
    if notes:
        for note in notes:
            console.print(f"    [dim]Note:[/]            {note}")


def _render_domains_section(
    domain: str, rows: list, console,
) -> None:
    """Render the 📌 Domains rollup. Lists the canonical domain plus
    any extra domains the walker(s) attached. Currently HostingRow
    doesn't carry an alias list — when v15.D/E add freshness/build
    sections, alias rollup will likely move into this block too.
    """
    console.print()
    console.print(f"  [bold]📌 Domains[/]")
    console.print(f"    {domain} [dim](canonical)[/]")


def _resolve_branch(domain: str) -> str:
    """Read the production branch from `sites/<domain>/lamill.toml`.
    Returns "main" when the file is absent or unparseable — same
    fallback used by `lamill_toml`'s schema default."""
    try:
        from .lamill_toml import load, ParseError
        from .project import SITES_ROOT
    except ImportError:
        return "main"
    repo_dir = SITES_ROOT / domain
    if not repo_dir.exists():
        return "main"
    try:
        payload = load(repo_dir)
    except ParseError:
        return "main"
    if payload is None:
        return "main"
    return payload.deploy.production_branch or "main"
