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


def test_menu_groups_four_groups():
    """v5.F: Focus → Check → New → Info."""
    names = [g for g, _ in MENU_GROUPS]
    assert names == ["Focus", "Check", "New", "Info"]


def test_v4d_menu_groups_keys_unique_and_sequential():
    keys = [c.key for _, cmds in MENU_GROUPS for c in cmds]
    assert len(keys) == len(set(keys)), "duplicate menu key"
    # Keys are strings of integers 1..N
    assert keys == [str(i) for i in range(1, len(keys) + 1)]


def test_v5f_find_command_returns_known_keys():
    """v5.F: 1=focus, 2-4=check modes, 5-7=new, 8-14=info."""
    cmd = find_command("1")
    assert cmd is not None and cmd.label == "focus"

    cmd = find_command("2")
    assert cmd is not None and cmd.label == "check live"
    assert cmd.cli_args == ["check", "live"]

    cmd = find_command("5")
    assert cmd is not None and cmd.label == "new suggest"
    assert cmd.cli_args == ["new", "suggest"]

    cmd = find_command("8")
    assert cmd is not None and cmd.label == "info summary"
    assert cmd.cli_args == ["info", "summary"]


def test_v4d_find_command_returns_none_for_unknown_key():
    assert find_command("99") is None
    assert find_command("foo") is None
    assert find_command("") is None


def test_v5f_menu_includes_expected_commands():
    """Every command in the v5.F.1 spec is in the menu (wip dropped,
    list+category merged)."""
    labels = {c.label for _, cmds in MENU_GROUPS for c in cmds}
    for required in (
        "focus",
        "check live", "check git", "check seo",
        "new suggest", "new bootstrap", "new deploy",
        "info summary", "info status", "info expiring",
        "info list", "info cleanup",
    ):
        assert required in labels, f"missing {required}"
    # Explicitly verify removed commands aren't there.
    for removed in ("info wip", "info category"):
        assert removed not in labels, f"{removed} should be removed"


# ---------- render_top_menu ----------


def test_v5f_render_top_menu_groups_and_keys():
    with menu.console.capture() as cap:
        render_top_menu()
    out = cap.get()
    for group in ("Focus", "Check", "New", "Info"):
        assert group in out
    # All 12 keys appear as "N." prefixes (post-v5.F.1: wip removed,
    # list+category merged).
    for i in range(1, 13):
        assert f"{i}." in out
    assert "q. Quit" in out


def test_v4d_render_top_menu_includes_descriptions():
    """Each item shows label + dim description."""
    with menu.console.capture() as cap:
        render_top_menu()
    out = cap.get()
    assert "Portfolio overview" in out  # info summary description
    assert "Validation-mode" in out      # new suggest description


# ---------- collect_args ----------


def test_v5f_collect_args_no_positionals_no_options():
    """A command with neither (e.g. info summary, key 8) returns just its
    base cli_args."""
    cmd = find_command("8")  # info summary
    args = collect_args(cmd)
    assert args == ["info", "summary"]


def test_v5f_collect_args_required_positional(monkeypatch):
    """Required positional → prompt → append to args."""
    cmd = find_command("9")  # info status
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "iotnews")
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: True)
    args = collect_args(cmd)
    assert args == ["info", "status", "iotnews"]


def test_v5f_collect_args_required_positional_empty_returns_none(monkeypatch):
    """Empty required positional → cancel back to menu."""
    cmd = find_command("9")  # info status (required name)
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "")
    args = collect_args(cmd)
    assert args is None


# NOTE: in v5.F.1, `info category` (which had an optional positional name)
# was merged into `info list --grouped`; no remaining menu item has an
# optional positional. The collect_args helper still handles them — that
# branch just doesn't get exercised through the menu data anymore.


def test_v5f_collect_args_walks_options_when_user_says_no(monkeypatch):
    """User declines defaults → walk through optionals one at a time."""
    cmd = find_command("10")  # info expiring (--within option)
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: False)
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "60")
    args = collect_args(cmd)
    assert "--within" in args
    assert "60" in args


def test_v5f_collect_args_skipped_optional_uses_default(monkeypatch):
    """User accepts defaults → no option flags appended."""
    cmd = find_command("10")  # info expiring
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: True)
    args = collect_args(cmd)
    assert args == ["info", "expiring"]
    assert "--within" not in args


def test_v5f_collect_args_boolean_flag_yes_emits_bare_flag(monkeypatch):
    """A (y/n)-described option in y mode → emit `--flag` alone (no value)."""
    cmd = find_command("5")  # new suggest (--browse, --with-abstract are y/n)
    # Sequence: positional "topic", then walk options:
    # --max-price (skip), --browse "y", --with-abstract "n"
    prompt_iter = iter(["my topic", "", "y", "n"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompt_iter))
    monkeypatch.setattr("portfolio.menu.typer.confirm", lambda *a, **kw: False)
    args = collect_args(cmd)
    assert "--browse" in args
    bi = args.index("--browse")
    assert (bi == len(args) - 1 or args[bi + 1].startswith("--"))
    assert "--with-abstract" not in args


def test_v5f_collect_args_non_boolean_option_emits_flag_value_pair(monkeypatch):
    """A non-(y/n) option emits both --flag and the user-typed value."""
    cmd = find_command("10")  # info expiring (--within is non-boolean)
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
    rc = dispatch(["info", "summary"])
    assert rc == 0
    assert captured["cmd"] == ["portfolio", "info", "summary"]


def test_v4d_dispatch_returns_subprocess_returncode(monkeypatch):
    monkeypatch.setattr("portfolio.menu.subprocess.run",
                        lambda *a, **kw: MagicMock(returncode=2))
    assert dispatch(["info", "expiring"]) == 2


def test_v4d_dispatch_handles_missing_executable(monkeypatch):
    """If `portfolio` isn't on PATH, surface a helpful error and return 127."""
    monkeypatch.setattr("portfolio.menu.subprocess.run",
                        MagicMock(side_effect=FileNotFoundError("no portfolio")))
    rc = dispatch(["info", "summary"])
    assert rc == 127


# ---------- run_menu loop ----------


def test_v4d_run_menu_exits_on_q(monkeypatch):
    monkeypatch.setattr("portfolio.menu.typer.prompt", lambda *a, **kw: "q")
    run_menu()  # returns without exception


def test_v4d_run_menu_handles_unknown_choice_then_quit(monkeypatch):
    prompts = iter(["99", "q"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompts))
    run_menu()  # the unknown key gets the "Type 1-14 or q." reprint


def test_v5f_run_menu_dispatches_simple_command_then_quits(monkeypatch):
    """Pick 8 (info summary, no positionals/options), then q."""
    prompts = iter(["8", "q"])
    monkeypatch.setattr("portfolio.menu.typer.prompt",
                        lambda *a, **kw: next(prompts))
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("portfolio.menu.subprocess.run", fake_run)
    run_menu()
    assert captured["cmd"] == ["portfolio", "info", "summary"]


def test_v5f_run_menu_cancelled_positional_returns_to_menu(monkeypatch):
    """User picks a command requiring a positional (9 = info status),
    types nothing → returns to menu without dispatching. Then quits."""
    prompts = iter(["9", "", "q"])
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
