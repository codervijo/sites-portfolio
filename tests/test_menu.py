"""Tests for v4.D interactive launcher (src/portfolio/menu.py)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from portfolio import menu
from portfolio.menu import (
    CmdSpec,
    MENU_GROUPS,
    collect_args,
    dispatch,
    find_command,
    render_top_menu,
    run_menu,
)


# ---------- find_command + MENU_GROUPS shape ----------


def test_v4d_menu_groups_three_groups():
    """Build first (most common entry-point), Manage second, Reports last."""
    names = [g for g, _ in MENU_GROUPS]
    assert names == ["Build", "Manage", "Reports"]


def test_v4d_menu_groups_keys_unique_and_sequential():
    keys = [c.key for _, cmds in MENU_GROUPS for c in cmds]
    assert len(keys) == len(set(keys)), "duplicate menu key"
    # Keys are strings of integers 1..N
    assert keys == [str(i) for i in range(1, len(keys) + 1)]


def test_v4d_find_command_returns_known_keys():
    """v4.D 2026-05-08 reorder: Build is now first (1=domain suggest);
    Manage starts at 4 (4=summary)."""
    cmd = find_command("1")
    assert cmd is not None
    assert "domain suggest" in cmd.label
    assert cmd.cli_args == ["domain", "suggest"]

    cmd = find_command("4")
    assert cmd is not None
    assert cmd.label == "summary"
    assert cmd.cli_args == ["summary"]


def test_v4d_find_command_returns_none_for_unknown_key():
    assert find_command("99") is None
    assert find_command("foo") is None
    assert find_command("") is None


def test_v4d_menu_includes_expected_commands():
    """Sanity: every command we promised in PRD v4.D is in the menu."""
    labels = {c.label for _, cmds in MENU_GROUPS for c in cmds}
    for required in (
        "summary", "project status", "cleanup", "check",
        "domain suggest", "bootstrap", "deploy",
        "expiring", "category", "wip", "list",
    ):
        assert required in labels, f"missing {required}"


# ---------- render_top_menu ----------


def test_v4d_render_top_menu_groups_and_keys():
    with menu.console.capture() as cap:
        render_top_menu()
    out = cap.get()
    for group in ("Manage", "Build", "Reports"):
        assert group in out
    # All 11 keys appear as "N." prefixes
    for i in range(1, 12):
        assert f"{i}." in out
    assert "q. Quit" in out


def test_v4d_render_top_menu_includes_descriptions():
    """Each item shows label + dim description."""
    with menu.console.capture() as cap:
        render_top_menu()
    out = cap.get()
    assert "Portfolio overview" in out  # summary description
    assert "Validation-mode" in out      # domain suggest description


# ---------- collect_args ----------


def test_v4d_collect_args_no_positionals_no_options():
    """A command with neither (e.g. summary, key 4 post-reorder) returns
    just its base cli_args."""
    cmd = find_command("4")  # summary
    args = collect_args(cmd)
    assert args == ["summary"]


def test_v4d_collect_args_required_positional(monkeypatch):
    """Required positional → prompt → append to args."""
    cmd = find_command("5")  # project status
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "iotnews")
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: True)
    args = collect_args(cmd)
    assert args == ["project", "status", "iotnews"]


def test_v4d_collect_args_required_positional_empty_returns_none(monkeypatch):
    """Empty required positional → cancel back to menu."""
    cmd = find_command("5")  # project status (required name)
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "")
    args = collect_args(cmd)
    assert args is None


def test_v4d_collect_args_optional_positional_can_be_skipped(monkeypatch):
    """`category` has an optional positional — empty input is fine."""
    cmd = find_command("9")  # category
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "")
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: True)
    args = collect_args(cmd)
    # No name appended; just the base.
    assert args == ["category"]


def test_v4d_collect_args_walks_options_when_user_says_no(monkeypatch):
    """User declines defaults → walk through optionals one at a time."""
    cmd = find_command("8")  # expiring (--within option)
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: False)
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "60")
    args = collect_args(cmd)
    assert "--within" in args
    assert "60" in args


def test_v4d_collect_args_skipped_optional_uses_default(monkeypatch):
    """User accepts defaults → no option flags appended."""
    cmd = find_command("8")  # expiring
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: True)
    args = collect_args(cmd)
    assert args == ["expiring"]
    assert "--within" not in args


def test_v4d_collect_args_boolean_flag_yes_emits_bare_flag(monkeypatch):
    """A (y/n)-described option in y mode → emit `--flag` alone (no value)."""
    cmd = find_command("1")  # domain suggest (--browse, --with-abstract are y/n)
    # Sequence: positional "topic", confirm "use defaults?" → No,
    # then walk options: --max-price (skip), --browse "y", --with-abstract "n"
    prompt_iter = iter(["my topic", "", "y", "n"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompt_iter))
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: False)
    args = collect_args(cmd)
    # --browse should appear bare (no value); --with-abstract should be absent
    assert "--browse" in args
    # Make sure --browse isn't followed by a value token like "y"
    bi = args.index("--browse")
    assert (bi == len(args) - 1 or args[bi + 1].startswith("--"))
    assert "--with-abstract" not in args


def test_v4d_collect_args_non_boolean_option_emits_flag_value_pair(monkeypatch):
    """A non-(y/n) option emits both --flag and the user-typed value."""
    cmd = find_command("8")  # expiring (--within is non-boolean)
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: False)
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "30")
    args = collect_args(cmd)
    i = args.index("--within")
    assert args[i + 1] == "30"


# ---------- dispatch ----------


def test_v4d_dispatch_calls_subprocess_with_portfolio_prefix(monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("portfolio.menu.subprocess.run", fake_run)
    rc = dispatch(["summary"])
    assert rc == 0
    assert captured["cmd"] == ["portfolio", "summary"]


def test_v4d_dispatch_returns_subprocess_returncode(monkeypatch):
    monkeypatch.setattr("portfolio.menu.subprocess.run",
                        lambda *a, **kw: MagicMock(returncode=2))
    assert dispatch(["expiring"]) == 2


def test_v4d_dispatch_handles_missing_executable(monkeypatch):
    """If `portfolio` isn't on PATH, surface a helpful error and return 127."""
    monkeypatch.setattr("portfolio.menu.subprocess.run",
                        MagicMock(side_effect=FileNotFoundError("no portfolio")))
    rc = dispatch(["summary"])
    assert rc == 127


# ---------- run_menu loop ----------


def test_v4d_run_menu_exits_on_q(monkeypatch):
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "q")
    run_menu()  # returns without exception


def test_v4d_run_menu_handles_unknown_choice_then_quit(monkeypatch):
    prompts = iter(["99", "q"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompts))
    run_menu()  # the unknown key gets the "Type 1-11 or q." reprint


def test_v4d_run_menu_dispatches_simple_command_then_quits(monkeypatch):
    """Pick 4 (summary, no positionals/options), then q."""
    prompts = iter(["4", "q"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompts))
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("portfolio.menu.subprocess.run", fake_run)
    run_menu()
    assert captured["cmd"] == ["portfolio", "summary"]


def test_v4d_run_menu_cancelled_positional_returns_to_menu(monkeypatch):
    """User picks a command requiring a positional (5 = project status),
    types nothing → returns to menu without dispatching. Then quits."""
    prompts = iter(["5", "", "q"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompts))
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: True)
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("portfolio.menu.subprocess.run", fake_run)
    run_menu()
    assert "cmd" not in captured  # never dispatched


def test_v4d_run_menu_handles_keyboard_interrupt(monkeypatch):
    """Ctrl-C during the prompt exits cleanly."""
    def fake_prompt(*a, **kw):
        raise KeyboardInterrupt

    monkeypatch.setattr("portfolio.menu.typer.prompt", fake_prompt)
    run_menu()  # returns; doesn't propagate


# ---------- callback integration ----------


def test_v4d_root_callback_invokes_run_menu_when_no_subcommand(monkeypatch):
    """When typer enters the callback with no invoked_subcommand, run_menu fires."""
    from portfolio.cli import _root_callback

    fake_ctx = MagicMock()
    fake_ctx.invoked_subcommand = None

    called = {"n": 0}
    def fake_menu():
        called["n"] += 1

    monkeypatch.setattr("portfolio.menu.run_menu", fake_menu)
    _root_callback(fake_ctx)
    assert called["n"] == 1


def test_v4d_root_callback_skips_run_menu_when_subcommand_present(monkeypatch):
    """When a subcommand IS invoked, the callback must not run the menu."""
    from portfolio.cli import _root_callback

    fake_ctx = MagicMock()
    fake_ctx.invoked_subcommand = "summary"

    called = {"n": 0}
    def fake_menu():
        called["n"] += 1

    monkeypatch.setattr("portfolio.menu.run_menu", fake_menu)
    _root_callback(fake_ctx)
    assert called["n"] == 0
