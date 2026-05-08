"""v4.D interactive launcher.

When `portfolio` is invoked with no subcommand (e.g. via `make run`), the
top-level Typer callback drops the user into a grouped menu rendered here.
The menu groups commands as **Manage** / **Build** / **Reports**, walks the
user through positional args + an optional flag walkthrough, then dispatches
to the subcommand via subprocess. After the subcommand exits, control returns
to the menu; `q` exits.

Dispatch via subprocess (rather than in-process invocation) keeps each
subcommand's behavior identical to direct CLI use — no shared state, no
global mutation, no surprises. Cost is one fork per command (~200ms),
imperceptible in interactive use.

The MENU_GROUPS spec hardcodes positionals + the most common optional flags
per command. Power users invoke commands directly via the CLI for full
optionality. The launcher is for "I forgot the command name" muscle memory.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

import typer
from rich.console import Console

console = Console()


@dataclass
class CmdSpec:
    """One menu entry. `cli_args` is the base subcommand prefix (e.g.
    ['domain', 'suggest']); positionals + walked options append to it.
    `positionals` is a list of (label, description) — required unless the
    description leads with 'optional'. `options` is a list of (flag,
    description, default-as-display-string)."""
    key: str
    label: str
    description: str
    cli_args: list[str]
    positionals: list[tuple[str, str]] = field(default_factory=list)
    options: list[tuple[str, str, str]] = field(default_factory=list)


MENU_GROUPS: list[tuple[str, list[CmdSpec]]] = [
    ("Build", [
        CmdSpec("1", "domain suggest", "Validation-mode brainstorm + grid + decide",
                ["domain", "suggest"],
                positionals=[("topic", "product idea or short description")],
                options=[("--max-price", "Filter price > N USD/yr", "10"),
                         ("--browse", "Use legacy per-strategy flow (y/n)", "n"),
                         ("--with-abstract", "Include abstract-brandable strategy (y/n)", "n")]),
        CmdSpec("2", "bootstrap", "Scaffold a new sites/<domain>/ project",
                ["bootstrap"],
                positionals=[("domain", "domain name (e.g. kwizicle.com)")],
                options=[("--stack", "astro or vite", "astro"),
                         ("--topic", "one-line project topic", ""),
                         ("--from-genai", "Copy genai/ → root (y/n)", "n")]),
        CmdSpec("3", "deploy", "Set up GitHub repo + Cloudflare Pages",
                ["deploy"],
                positionals=[("domain", "domain to deploy")],
                options=[("--gh-owner", "GitHub username/org (auto-detect if blank)", ""),
                         ("--private", "Create repo as private (y/n)", "n"),
                         ("--dry-run", "Show planned API calls; don't execute (y/n)", "n")]),
    ]),
    ("Manage", [
        CmdSpec("4", "summary", "Portfolio overview (counts, value, expirations)",
                ["summary"]),
        CmdSpec("5", "project status", "Status of one project under sites/",
                ["project", "status"],
                positionals=[("name", "project name (fuzzy-matched)")],
                options=[("--json", "Emit JSON instead of table (y/n)", "n")]),
        CmdSpec("6", "cleanup", "Rebuild data/portfolio.json from registrar CSVs",
                ["cleanup"]),
        CmdSpec("7", "check", "Fetch + classify each domain → check snapshot",
                ["check"],
                options=[("--only", "Scope: 'wip' or 'all'", "wip"),
                         ("--concurrency", "Max parallel HTTP requests", "20")]),
    ]),
    ("Reports", [
        CmdSpec("8", "expiring", "Domains expiring within N days",
                ["expiring"],
                options=[("--within", "Days from today", "180")]),
        CmdSpec("9", "category", "Domains grouped by plan category",
                ["category"],
                positionals=[("name", "optional: category substring (Enter for all)")]),
        CmdSpec("10", "wip", "Work-in-progress domains (My brand / SEO / Next session)",
                ["wip"]),
        CmdSpec("11", "list", "Every domain in the registrar CSVs",
                ["list"]),
    ]),
]


# Boolean-flag options in CmdSpec.options use a 'y/n' convention in their
# description. The collect_args walker recognizes them and emits the bare
# flag (`--browse`) when the user types y/yes.
_TRUTHY = {"y", "yes", "true", "on", "1"}
_FALSY = {"n", "no", "false", "off", "0", ""}


def render_top_menu() -> None:
    console.print("\n[bold]portfolio — pick a command:[/]\n")
    for group_name, cmds in MENU_GROUPS:
        console.print(f"  [bold cyan]{group_name}[/]")
        for cmd in cmds:
            key_padded = f"{cmd.key:>3}."
            console.print(f"  {key_padded} [bold]{cmd.label}[/]  [dim]— {cmd.description}[/]")
        console.print()
    console.print("    q. Quit\n")


def find_command(key: str) -> CmdSpec | None:
    for _, cmds in MENU_GROUPS:
        for cmd in cmds:
            if cmd.key == key:
                return cmd
    return None


def _is_optional_positional(label: str, description: str) -> bool:
    return "optional" in label.lower() or description.lower().startswith("optional")


def _is_boolean_option(description: str) -> bool:
    """Heuristic: descriptions ending in '(y/n)' are boolean toggles."""
    return description.rstrip().endswith("(y/n)")


def collect_args(cmd: CmdSpec) -> list[str] | None:
    """Walk positionals + optional flags. Returns the full args list ready
    for dispatch, or None if the user cancelled (empty required positional).

    Rich markup is rendered via `console.print` BEFORE each prompt; the
    actual `typer.prompt` call uses a bare `>` since typer/click don't
    render Rich tags inline.
    """
    args = list(cmd.cli_args)

    for label, description in cmd.positionals:
        is_optional = _is_optional_positional(label, description)
        console.print(f"  [bold]{label}[/]  [dim]({description})[/]")
        val = typer.prompt("  >", default="", show_default=False).strip()
        if not val:
            if is_optional:
                continue
            console.print("[yellow]No value provided — back to menu.[/]")
            return None
        args.append(val)

    if cmd.options:
        # List the optional flags + defaults so the user knows what they're
        # agreeing to before answering Y/n.
        console.print("\n  [dim]Optional flags:[/]")
        for flag, description, default in cmd.options:
            default_hint = f" [dim](default: {default})[/]" if default else " [dim](default: off)[/]"
            console.print(f"    [cyan]{flag}[/] — {description}{default_hint}")
        use_defaults = typer.confirm("  Use defaults for all of these?", default=True)
        if not use_defaults:
            for flag, description, default in cmd.options:
                default_hint = f" [dim](default: {default})[/]" if default else ""
                console.print(f"    [cyan]{flag}[/]  [dim]{description}[/]{default_hint}")
                val = typer.prompt("    >", default="", show_default=False).strip()
                if not val:
                    continue
                if _is_boolean_option(description):
                    if val.lower() in _TRUTHY:
                        args.append(flag)
                    # falsy → omit flag (keeps default behavior)
                else:
                    args.append(flag)
                    args.append(val)

    return args


def dispatch(args: list[str]) -> int:
    """Run `portfolio <args>` as a subprocess with inherited stdio.
    Returns the subprocess exit code."""
    cmd = ["portfolio"] + args
    console.print(f"\n[dim]→ {' '.join(cmd)}[/]\n")
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        console.print(
            "[red]Could not find the `portfolio` executable on PATH.[/]\n"
            "[dim]Run via `make run` or activate the project venv.[/]"
        )
        return 127


def run_menu() -> None:
    """Top-level menu loop. Re-renders after every dispatched command;
    exits cleanly on `q` or KeyboardInterrupt."""
    try:
        while True:
            render_top_menu()
            choice = typer.prompt(">", default="", show_default=False).strip().lower()
            if choice == "q":
                return
            cmd = find_command(choice)
            if cmd is None:
                console.print("[red]Type 1-11 or q.[/]")
                continue
            args = collect_args(cmd)
            if args is None:
                continue
            dispatch(args)
    except KeyboardInterrupt:
        console.print("\n[yellow](interrupted)[/]")
        return
