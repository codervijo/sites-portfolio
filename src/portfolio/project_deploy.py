"""v10.B — CLI surfaces for the `lamill.toml` deploy declaration.

Implements `settings project set-deploy` (create/update) and
`settings project show-deploy` (inspect). Thin layer on top of
`lamill_toml`'s pure data API (v10.A).

`set_deploy()`:
- Resolves `<name>` against `portfolio.json` (fuzzy match via
  `resolve_project`).
- Reads any existing `<repo>/lamill.toml` so untouched fields
  survive an update.
- Resolves each field in priority order: explicit CLI flag → existing
  file value → interactive prompt (TTY only) → dataclass default.
- In `--non-interactive` mode, refuses when `platform ∈ {hostgator,
  custom}` AND no hosting field is available from either flag or
  existing file (the resulting `[hosting]` would be empty —
  technically valid, practically useless).
- Writes via `lamill_toml.write()` (atomic; no comments preserved).

`show_deploy()` (slice 2; not in this commit) — pretty rendering.
"""
from __future__ import annotations

from pathlib import Path

import typer

from dataclasses import dataclass, field

from .lamill_toml import (
    HOSTING_REQUIRED_PLATFORMS,
    LAMILL_TOML_FILENAME,
    PLATFORM_VALUES,
    BackendBlock,
    DeployBlock,
    HostingBlock,
    LamillToml,
    ParseError,
    detect_platform_signals,
    infer_from_existing_configs,
    load,
    to_dict,
    write,
)
from .project import SITES_ROOT, resolve_project


# ---- public entry point --------------------------------------------


def set_deploy(
    name: str,
    platform: str,
    *,
    interactive: bool = True,
    account: str | None = None,
    branch: str | None = None,
    auto_deploy: bool | None = None,
    custom_domains: list[str] | None = None,
    cpanel_user: str | None = None,
    cpanel_url: str | None = None,
    ftp_host: str | None = None,
    ftp_user: str | None = None,
    ftp_port: int | None = None,
    public_html_path: str | None = None,
    console: typer.rich_utils.Console | None = None,  # injected by CLI
) -> Path:
    """Create or update `sites/<name>/lamill.toml`.

    Returns the path written. Raises `typer.Exit` on:
    - Unresolvable `name` (no portfolio.json match).
    - Invalid `platform` (not in `PLATFORM_VALUES`).
    - Non-interactive mode missing required hosting fields for
      `hostgator` / `custom`.
    """
    from rich.console import Console
    cons = console if console is not None else Console()

    # Validate platform up-front (cheaper than prompting for fields first).
    if platform not in PLATFORM_VALUES:
        cons.print(
            f"[red]Invalid platform:[/] {platform!r}. Expected one of: "
            f"{', '.join(PLATFORM_VALUES)}."
        )
        raise typer.Exit(2)

    # Resolve name → sibling repo dir.
    res = resolve_project(name)
    if res.matched is None:
        if res.candidates:
            cons.print(
                f"[red]Ambiguous name:[/] {name!r} matches "
                f"{', '.join(res.candidates)}. Be more specific."
            )
        else:
            cons.print(
                f"[red]Domain not found in portfolio.json:[/] {name!r}."
            )
        raise typer.Exit(1)
    repo_dir = SITES_ROOT / res.matched
    if not repo_dir.exists():
        cons.print(
            f"[red]Sibling repo missing:[/] {repo_dir}. "
            f"`new bootstrap {res.matched}` first."
        )
        raise typer.Exit(1)

    # Load existing lamill.toml if present so we can preserve untouched fields.
    existing: LamillToml | None
    try:
        existing = load(repo_dir)
    except ParseError as e:
        cons.print(f"[red]Existing lamill.toml is malformed:[/] {e}")
        cons.print(
            "[dim]Fix or remove the existing file before running set-deploy.[/]"
        )
        raise typer.Exit(1) from e

    # Resolve each [deploy] field: flag → existing → prompt-or-default.
    existing_deploy = existing.deploy if existing else None

    resolved_account = _resolve_str_field(
        "account",
        flag_value=account,
        existing=existing_deploy.account if existing_deploy else None,
        interactive=interactive,
        cons=cons,
    )
    resolved_branch = _resolve_str_field(
        "production branch",
        flag_value=branch,
        existing=existing_deploy.production_branch if existing_deploy else None,
        interactive=interactive,
        default="main",
        cons=cons,
    ) or "main"
    resolved_auto_deploy = _resolve_bool_field(
        "auto_deploy (push triggers a build)",
        flag_value=auto_deploy,
        existing=existing_deploy.auto_deploy if existing_deploy else None,
        interactive=interactive,
        platform_default=platform in {"cf-pages", "vercel", "netlify", "github-pages"},
        cons=cons,
    )
    resolved_domains = _resolve_domain_list(
        flag_value=custom_domains,
        existing=existing_deploy.custom_domains if existing_deploy else None,
        interactive=interactive,
        cons=cons,
    )

    deploy = DeployBlock(
        platform=platform,
        account=resolved_account,
        production_branch=resolved_branch,
        auto_deploy=resolved_auto_deploy,
        custom_domains=resolved_domains,
    )

    # [hosting] block — required for hostgator/custom.
    hosting = _resolve_hosting(
        platform=platform,
        interactive=interactive,
        existing=existing.hosting if existing else None,
        cpanel_user=cpanel_user,
        cpanel_url=cpanel_url,
        ftp_host=ftp_host,
        ftp_user=ftp_user,
        ftp_port=ftp_port,
        public_html_path=public_html_path,
        cons=cons,
    )

    # [backend] block — preserved from existing if untouched. v10.B doesn't
    # prompt for backend fields; the operator edits via $EDITOR for now.
    backend = existing.backend if existing else None

    # [notes] block — preserved.
    notes = existing.notes if existing else None

    payload = LamillToml(
        deploy=deploy,
        hosting=hosting,
        backend=backend,
        notes=notes,
    )
    write(repo_dir, payload)
    target = repo_dir / "lamill.toml"
    cons.print(f"[green]Wrote[/] {target}")
    cons.print(
        f"[dim]platform={platform} · branch={resolved_branch} · "
        f"auto_deploy={deploy.effective_auto_deploy()}"
        f"{' · domains=' + ','.join(resolved_domains) if resolved_domains else ''}"
        f"[/]"
    )
    return target


# ---- field-resolution helpers --------------------------------------


def _resolve_str_field(
    label: str,
    *,
    flag_value: str | None,
    existing: str | None,
    interactive: bool,
    default: str | None = None,
    cons,
) -> str | None:
    if flag_value is not None:
        return flag_value or None
    if existing is not None and not interactive:
        return existing
    if not interactive:
        return default
    prompt_default = existing or default or ""
    raw = typer.prompt(
        f"{label}",
        default=prompt_default,
        show_default=True,
    )
    return raw.strip() or None


def _resolve_bool_field(
    label: str,
    *,
    flag_value: bool | None,
    existing: bool | None,
    interactive: bool,
    platform_default: bool,
    cons,
) -> bool | None:
    if flag_value is not None:
        return flag_value
    if existing is not None:
        return existing
    if not interactive:
        # Leave as None — the parser will apply the platform default.
        return None
    return typer.confirm(label, default=platform_default)


def _resolve_domain_list(
    *,
    flag_value: list[str] | None,
    existing: list[str] | None,
    interactive: bool,
    cons,
) -> list[str]:
    if flag_value:
        return list(flag_value)
    if existing:
        return list(existing)
    if not interactive:
        return []
    raw = typer.prompt(
        "custom_domains (comma-separated; blank for none)",
        default="",
        show_default=False,
    ).strip()
    if not raw:
        return []
    return [d.strip() for d in raw.split(",") if d.strip()]


def _resolve_hosting(
    *,
    platform: str,
    interactive: bool,
    existing: HostingBlock | None,
    cpanel_user: str | None,
    cpanel_url: str | None,
    ftp_host: str | None,
    ftp_user: str | None,
    ftp_port: int | None,
    public_html_path: str | None,
    cons,
) -> HostingBlock | None:
    """Resolve the `[hosting]` block.

    For platforms that don't require hosting: returns the existing
    block (if any) unchanged — operator wasn't asked, so preserve.

    For platforms that DO require hosting (hostgator/custom):
    - Merge flag values + existing + (interactive prompts | non-
      interactive defaults).
    - In non-interactive mode, refuse if no field is available from
      either flag or existing — would write an empty `[hosting]`
      section, which the parser accepts but the operator can't
      deploy from.
    """
    if platform not in HOSTING_REQUIRED_PLATFORMS:
        return existing

    # Required-hosting path. Track whether any field gets a value;
    # in --non-interactive, fail if none.
    fields = {
        "cpanel_user": cpanel_user
            or (existing.cpanel_user if existing else None),
        "cpanel_url": cpanel_url
            or (existing.cpanel_url if existing else None),
        "ftp_host": ftp_host
            or (existing.ftp_host if existing else None),
        "ftp_user": ftp_user
            or (existing.ftp_user if existing else None),
        "ftp_port": ftp_port
            if ftp_port is not None
            else (existing.ftp_port if existing else None),
        "public_html_path": public_html_path
            or (existing.public_html_path if existing else None),
    }

    if not interactive:
        if not any(v is not None for v in fields.values()):
            cons.print(
                f"[red]platform={platform!r} requires a \\[hosting] "
                "section[/]. In --non-interactive mode, pass at least "
                "one of --cpanel-user / --cpanel-url / --ftp-host / "
                "--ftp-user / --ftp-port / --public-html-path."
            )
            raise typer.Exit(2)
        return HostingBlock(**fields)

    # Interactive: prompt for each missing field, with existing as default.
    cons.print(
        f"[cyan]Platform {platform!r} requires the \\[hosting] block.[/] "
        "Press Enter to skip any field."
    )
    for field_name in (
        "cpanel_user",
        "cpanel_url",
        "ftp_host",
        "ftp_user",
        "public_html_path",
    ):
        if fields[field_name] is not None:
            # Already set by flag; don't re-prompt.
            continue
        raw = typer.prompt(
            f"  {field_name}",
            default="",
            show_default=False,
        ).strip()
        fields[field_name] = raw or None
    if fields["ftp_port"] is None:
        raw_port = typer.prompt(
            "  ftp_port (integer; blank for none)",
            default="",
            show_default=False,
        ).strip()
        if raw_port:
            try:
                fields["ftp_port"] = int(raw_port)
            except ValueError:
                cons.print(
                    f"[yellow]Skipping ftp_port — {raw_port!r} not an integer.[/]"
                )

    if not any(v is not None for v in fields.values()):
        # Operator skipped everything in interactive mode. Still
        # write the empty section so the file parses, but warn.
        cons.print(
            "[yellow]All hosting fields blank.[/] "
            f"\\[hosting] section will be empty — populate it manually "
            f"before deploying."
        )
        return HostingBlock()
    return HostingBlock(**fields)


# ---- show-deploy ----------------------------------------------------


def show_deploy(
    name: str,
    *,
    as_json: bool = False,
    console=None,
) -> int:
    """Render `sites/<name>/lamill.toml` for inspection.

    Default mode prints a rich-formatted table. `--json` mode emits
    `to_dict(payload)` as a JSON document. Returns the exit code
    (0 on success or "missing file" — missing isn't an error,
    just a discoverability outcome).
    """
    import json

    from rich.console import Console
    from rich.table import Table

    cons = console if console is not None else Console()

    res = resolve_project(name)
    if res.matched is None:
        if as_json:
            print("null")
        else:
            if res.candidates:
                cons.print(
                    f"[red]Ambiguous name:[/] {name!r} matches "
                    f"{', '.join(res.candidates)}. Be more specific."
                )
            else:
                cons.print(
                    f"[red]Domain not found in portfolio.json:[/] {name!r}."
                )
        return 1

    repo_dir = SITES_ROOT / res.matched
    if not repo_dir.exists():
        if as_json:
            print("null")
        else:
            cons.print(
                f"[red]Sibling repo missing:[/] {repo_dir}."
            )
        return 1

    try:
        payload = load(repo_dir)
    except ParseError as e:
        if as_json:
            print(json.dumps({"error": str(e)}))
        else:
            cons.print(f"[red]lamill.toml is malformed:[/] {e}")
        return 1

    if payload is None:
        if as_json:
            print("null")
        else:
            cons.print(
                f"[dim]{res.matched} — no deploy declaration.[/]"
            )
            cons.print(
                f"[dim](Run `lamill settings project set-deploy "
                f"{res.matched} <platform>` to create one.)[/]"
            )
        return 0

    if as_json:
        print(json.dumps(to_dict(payload), indent=2))
        return 0

    # Pretty rendering.
    file_path = repo_dir / LAMILL_TOML_FILENAME
    cons.print(f"\n[bold]{res.matched}[/] — declared deployment")
    cons.print(f"[dim]source: {file_path}[/]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("field", style="dim", no_wrap=True)
    table.add_column("value")
    _render_deploy_rows(table, payload)
    cons.print(table)
    cons.print(
        "\n[dim]Drift check: deferred (v10.E — `lamill.toml` vs "
        "DNS-resolved actual).[/]"
    )
    return 0


def _render_deploy_rows(table, payload: LamillToml) -> None:
    """Append rows to a rich.Table describing the LamillToml."""
    d = payload.deploy
    table.add_row("platform", f"[bold]{d.platform}[/]")
    table.add_row("account", d.account or "[dim]—[/]")
    table.add_row("branch", d.production_branch)
    auto = (
        "yes" if d.auto_deploy is True
        else "no" if d.auto_deploy is False
        else f"[dim](platform default: "
             f"{'yes' if d.effective_auto_deploy() else 'no'})[/]"
    )
    table.add_row("auto-deploy", auto)
    table.add_row(
        "domains",
        ", ".join(d.custom_domains) if d.custom_domains else "[dim]—[/]",
    )

    if payload.hosting is not None:
        table.add_row("", "")  # blank row as visual separator
        table.add_row("[hosting]", "")
        h = payload.hosting
        if h.cpanel_user or h.cpanel_url:
            table.add_row(
                "  cpanel",
                f"{h.cpanel_user or '?'} @ {h.cpanel_url or '?'}",
            )
        if h.ftp_user or h.ftp_host:
            ftp = f"{h.ftp_user or '?'}@{h.ftp_host or '?'}"
            if h.ftp_port is not None:
                ftp += f":{h.ftp_port}"
            table.add_row("  ftp", ftp)
        if h.public_html_path:
            table.add_row("  public_html", h.public_html_path)

    if payload.backend is not None:
        table.add_row("", "")
        table.add_row("[backend]", "")
        b = payload.backend
        table.add_row("  db", b.db)
        table.add_row("  framework", b.framework)
        table.add_row("  hosting", b.hosting)

    if payload.notes:
        table.add_row("", "")
        notes_short = payload.notes if len(payload.notes) <= 80 else (
            payload.notes[:77] + "..."
        )
        table.add_row("notes", notes_short)


# ---- v10.C — migration sweep --------------------------------------


# Priority order for `--include-ambiguous` mode (per v10 design
# notes resolution 10.B): vercel > cf-pages > cf-workers > netlify.
_AMBIGUOUS_PRIORITY: tuple[str, ...] = (
    "vercel",
    "cf-pages",
    "cf-workers",
    "netlify",
)

# Portfolio.json categories that mean "this site is being retired."
# Mirrors `fleet_repos.ARCHIVED_CATEGORIES`.
_ARCHIVED_CATEGORIES: frozenset[str] = frozenset({
    "to be deleted immediately",
    "archived",
    "tombstoned",
})

_TOMBSTONE_MARKER = "TOMBSTONE.md"


@dataclass
class MigrationRow:
    """One row of the `fleet repos --add-deploy-declarations` report."""
    domain: str
    classification: str
    # Inferred platform when there's a single unambiguous signal, or
    # the priority-picked one when --include-ambiguous resolves a
    # multi-signal case. None when no signals or skipped.
    chosen_platform: str | None = None
    # Per-platform presence dict from `detect_platform_signals()`.
    signals: dict[str, bool] = field(default_factory=dict)
    # "would_write" / "wrote" / "skipped_already" / "skipped_archived"
    # / "skipped_ambiguous" / "skipped_manual" — the verb that
    # describes what the migration did (or planned to do).
    action: str = ""
    notes: str | None = None


def migrate_deploy_declarations(
    *,
    dry_run: bool = True,
    include_ambiguous: bool = False,
    sites_root=None,
    plan=None,
) -> list[MigrationRow]:
    """Walk every `sites/<dir>/` and classify lamill.toml status.

    Returns a list of `MigrationRow` — one per site, in alphabetical
    order. When `dry_run` is True (default), writes nothing; just
    reports what would happen. When False, writes `lamill.toml` for
    every unambiguous case (and ambiguous cases too if
    `include_ambiguous`).

    Classifications:
    - `already_declared` — `lamill.toml` exists; left alone.
    - `archived` — `TOMBSTONE.md` present or `portfolio.json`
      category in `_ARCHIVED_CATEGORIES`; skipped.
    - `unambiguous` — exactly one platform signal; the migration
      writes (or in `dry_run`, would write) a fresh `lamill.toml`.
    - `ambiguous` — multiple platform signals. Refused unless
      `include_ambiguous`, in which case the migration picks via the
      vercel > cf-pages > cf-workers > netlify priority order and
      embeds a `[notes].text` warning in the generated file.
    - `manual` — no signals + not archived. Operator must run
      `lamill settings project set-deploy <domain> <platform>`.

    `sites_root` overrides the default sites/ root (for tests).
    `plan` overrides the portfolio.json plan dict (for tests; live
    callers leave None to read from disk).
    """
    from .fleet_repos import list_site_dirs

    site_dirs = list_site_dirs(sites_root=sites_root)
    if plan is None:
        from .data import load_plan
        plan = load_plan()

    rows: list[MigrationRow] = []
    for site_dir in site_dirs:
        domain = site_dir.name
        row = _classify_site(
            domain=domain,
            site_dir=site_dir,
            plan=plan,
            include_ambiguous=include_ambiguous,
        )
        if not dry_run and row.action == "would_write":
            _execute_write(site_dir, row)
        rows.append(row)
    return rows


def _classify_site(
    *,
    domain: str,
    site_dir,
    plan: dict,
    include_ambiguous: bool,
) -> MigrationRow:
    if (site_dir / LAMILL_TOML_FILENAME).exists():
        return MigrationRow(
            domain=domain,
            classification="already_declared",
            action="skipped_already",
            notes="lamill.toml already exists; left alone",
        )

    if _is_archived(site_dir=site_dir, domain=domain, plan=plan):
        return MigrationRow(
            domain=domain,
            classification="archived",
            action="skipped_archived",
            notes="TOMBSTONE.md or archived category — skipped",
        )

    signals = detect_platform_signals(site_dir)
    present = [p for p, found in signals.items() if found]

    if len(present) == 0:
        return MigrationRow(
            domain=domain,
            classification="manual",
            signals=signals,
            action="skipped_manual",
            notes=(
                "no platform-config files (wrangler.jsonc / vercel.json / "
                f"netlify.toml) found; run `lamill settings project "
                f"set-deploy {domain} <platform>` interactively"
            ),
        )

    if len(present) == 1:
        return MigrationRow(
            domain=domain,
            classification="unambiguous",
            chosen_platform=present[0],
            signals=signals,
            action="would_write",
            notes=f"single signal: {present[0]}",
        )

    # Multiple signals — ambiguous.
    if not include_ambiguous:
        return MigrationRow(
            domain=domain,
            classification="ambiguous",
            signals=signals,
            action="skipped_ambiguous",
            notes=(
                f"multiple platform configs detected ({', '.join(present)}); "
                "re-run with --include-ambiguous to write via priority "
                "(vercel > cf-pages > cf-workers > netlify), or run "
                f"`lamill settings project set-deploy {domain} <platform>` "
                "manually"
            ),
        )
    picked = _resolve_ambiguous_priority(present)
    return MigrationRow(
        domain=domain,
        classification="ambiguous",
        chosen_platform=picked,
        signals=signals,
        action="would_write",
        notes=(
            f"AMBIGUOUS: multiple platform configs ({', '.join(present)}); "
            f"chose {picked!r} via priority order. Verify against actual "
            "deploy state and edit lamill.toml if wrong."
        ),
    )


def _resolve_ambiguous_priority(present: list[str]) -> str:
    """Apply `_AMBIGUOUS_PRIORITY` order. Returns the first match."""
    for p in _AMBIGUOUS_PRIORITY:
        if p in present:
            return p
    # Shouldn't reach: every entry in `present` is from
    # detect_platform_signals which returns only the 4 priority keys.
    return present[0]


def _is_archived(*, site_dir, domain: str, plan: dict) -> bool:
    if (site_dir / _TOMBSTONE_MARKER).exists():
        return True
    category = (plan.get(domain) or "").strip().lower()
    return category in _ARCHIVED_CATEGORIES


def _execute_write(site_dir, row: MigrationRow) -> None:
    """Write `lamill.toml` for an unambiguous (or priority-resolved
    ambiguous) site. Updates `row.action` to `wrote`."""
    payload = LamillToml(
        deploy=DeployBlock(
            platform=row.chosen_platform,
            custom_domains=[row.domain],
        ),
        # For ambiguous-with-include path, surface the conflict in the
        # generated file so the operator sees it on next inspection.
        notes=row.notes if row.classification == "ambiguous" else None,
    )
    write(site_dir, payload)
    row.action = "wrote"


def render_migration_summary(rows: list[MigrationRow], console) -> None:
    """Render the migration plan / result to the terminal.

    Single-table summary grouped by classification, with footer counts
    + next-step hints. Matches the `fleet repos` audit renderer's
    compact style.
    """
    from rich.table import Table

    by_class: dict[str, list[MigrationRow]] = {}
    for r in rows:
        by_class.setdefault(r.classification, []).append(r)

    # Render order: most-actionable first.
    classification_order = [
        ("unambiguous", "[green]Unambiguous — safe to write[/]"),
        ("ambiguous", "[yellow]Ambiguous — multiple signals[/]"),
        ("manual", "[cyan]Manual entry needed — no signals[/]"),
        ("already_declared", "[dim]Already declared[/]"),
        ("archived", "[dim]Archived (skipped)[/]"),
    ]

    for cls, header in classification_order:
        cls_rows = by_class.get(cls, [])
        if not cls_rows:
            continue
        console.print(f"\n{header}: {len(cls_rows)}")
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("domain", style="bold", no_wrap=True)
        table.add_column("platform", style="dim", no_wrap=True)
        table.add_column("action / note")
        for r in cls_rows:
            table.add_row(
                r.domain,
                r.chosen_platform or "—",
                _action_label(r),
            )
        console.print(table)

    # Footer rollup.
    counts = {cls: len(by_class.get(cls, [])) for cls, _ in classification_order}
    summary = " · ".join(
        f"{v} {k.replace('_', '-')}" for k, v in counts.items() if v
    )
    total = sum(counts.values())
    console.print(f"\n[bold]Total:[/] {total} sites — {summary}")


def _action_label(row: MigrationRow) -> str:
    if row.action == "wrote":
        return f"[green]wrote lamill.toml[/]"
    if row.action == "would_write":
        return f"[cyan]would write lamill.toml ({row.chosen_platform})[/]"
    if row.action == "skipped_ambiguous":
        return f"[yellow]{row.notes}[/]"
    if row.action == "skipped_manual":
        return f"[cyan]{row.notes}[/]"
    return f"[dim]{row.notes or row.action}[/]"
