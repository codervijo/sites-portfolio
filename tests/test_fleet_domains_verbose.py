"""Regression + guard for the v14 typer-de-registration defect.

When v14 folded `info list` / `info expiring` / `info summary` into
`fleet domains`, the three functions stopped being typer commands but two of
them kept their `typer.Option(...)` defaults. Called as plain Python
functions, those defaults bind to `OptionInfo` sentinels rather than values —
`info_list()` crashed with `AttributeError: 'OptionInfo' object has no
attribute 'lower'` because a truthy `OptionInfo` forced grouped mode.
"""

import ast
import pathlib

import pytest
from typer.testing import CliRunner

from portfolio import fleet_cli
from portfolio.cli import app

runner = CliRunner()

SRC = pathlib.Path(fleet_cli.__file__).parent


def test_info_list_callable_with_no_args(monkeypatch):
    """The `fleet domains --summary --verbose` path calls this bare."""
    monkeypatch.setattr(fleet_cli, "load_domains", lambda *a, **k: [])
    fleet_cli.info_list()  # must not raise


def test_info_expiring_callable_with_no_args(monkeypatch):
    """Latent sibling of the same defect — no call site passes it bare today."""
    monkeypatch.setattr(fleet_cli, "load_domains", lambda *a, **k: [])
    fleet_cli.info_expiring()  # must not raise


def test_fleet_domains_summary_verbose_does_not_crash():
    res = runner.invoke(app, ["fleet", "domains", "--summary", "--verbose"])
    assert res.exit_code == 0, res.output
    assert "OptionInfo" not in res.output


def _typer_defaulted_params(node):
    """Param names on `node` whose default is a `typer.Option/Argument(...)`."""
    args = node.args
    out = []
    positional = args.posonlyargs + args.args
    defaults = list(args.defaults)
    paired = list(zip(positional[len(positional) - len(defaults):], defaults))
    paired += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d]
    for arg, default in paired:
        if (
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Attribute)
            and default.func.attr in ("Option", "Argument")
        ):
            out.append(arg.arg)
    return out


def _is_registered_command(node):
    """True if decorated with `@<something>.command(...)` / `@<something>.callback`."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in ("command", "callback"):
            return True
    return False


def _modules():
    return sorted(SRC.rglob("*.py"))


# Functions de-registered as typer commands (v14 fold-in and later) that still
# carry vestigial `typer.Option(...)` defaults. None of them currently bites:
# every call site binds its params explicitly (enforced by
# `test_no_bare_calls_to_typer_commands`). This is a ratchet — the set may
# shrink, never grow. Tracked in `docs/architecture.md § Tracked refactors`.
KNOWN_VESTIGIAL = {
    "check_git", "check_seo", "check_catalog", "check_describe", "check_run",
    "gsc_auth", "gsc_sync", "info_status", "focus", "check_live",
}


def test_no_new_typer_defaults_on_unregistered_functions():
    """A function carrying `typer.Option` defaults must be a registered command.

    Otherwise its params silently bind to `OptionInfo` sentinels the moment
    someone calls it as a plain function — the BUG-090 failure mode.
    """
    offenders = []
    for path in _modules():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            params = _typer_defaulted_params(node)
            if (
                params
                and not _is_registered_command(node)
                and node.name not in KNOWN_VESTIGIAL
            ):
                offenders.append(
                    f"{path.relative_to(SRC)}:{node.lineno} {node.name}() "
                    f"has typer defaults {params} but is not a registered command"
                )
    assert not offenders, "\n".join(offenders)


def test_vestigial_ratchet_only_shrinks():
    """`KNOWN_VESTIGIAL` must not list names that are already clean."""
    live = set()
    for path in _modules():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and _typer_defaulted_params(node)
                and not _is_registered_command(node)
            ):
                live.add(node.name)
    stale = KNOWN_VESTIGIAL - live
    assert not stale, (
        f"these were cleaned up — remove them from KNOWN_VESTIGIAL: {sorted(stale)}"
    )


def test_no_bare_calls_to_typer_commands():
    """No module may call a typer-defaulted function without binding its params."""
    commands = {}
    trees = {}
    for path in _modules():
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:
            continue
        trees[path] = tree
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                params = _typer_defaulted_params(node)
                if params:
                    commands[node.name] = (path, node.lineno, params)

    offenders = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name not in commands:
                continue
            _, _, params = commands[name]
            bound = {kw.arg for kw in node.keywords if kw.arg}
            unbound = [p for p in params[len(node.args):] if p not in bound]
            if unbound:
                offenders.append(
                    f"{path.relative_to(SRC)}:{node.lineno} calls {name}() "
                    f"leaving typer params {unbound} bound to OptionInfo sentinels"
                )
    assert not offenders, "\n".join(offenders)
