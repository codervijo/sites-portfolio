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

from .lamill_toml import (
    HOSTING_REQUIRED_PLATFORMS,
    PLATFORM_VALUES,
    BackendBlock,
    DeployBlock,
    HostingBlock,
    LamillToml,
    ParseError,
    load,
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
            f"[hosting] section will be empty — populate it manually "
            f"before deploying."
        )
        return HostingBlock()
    return HostingBlock(**fields)
