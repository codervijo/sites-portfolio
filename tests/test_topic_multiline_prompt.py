"""Tests for 2026-05-24 multi-line topic input in `lamill new validate`.

Operator-hit bug: pasted a multi-line product brief into the `Topic:`
prompt; `typer.prompt()` read only line 1, and the rest of the paste
leaked into the shell as `command-not-found` errors.

Fix: `_prompt_topic_multiline` reads lines until an empty line, strips
bullet prefixes (`- `, `* `, `• `), and concatenates with `. ` into a
single phrase the cluster-expansion LLM can handle.

Tests mock `input()` (the builtin) to simulate single-line, paste-bomb,
and edge cases.
"""
from __future__ import annotations

import builtins

import pytest

from portfolio.cli import _prompt_topic_multiline


def _fake_input(lines):
    """Return a function suitable for monkeypatching `builtins.input`
    that yields lines one at a time then raises EOFError."""
    it = iter(lines)

    def _inner(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError()
    return _inner


def test_single_line_topic_terminates_on_empty_enter(monkeypatch):
    """Type 'AI vacuum diagnostics' + Enter (which yields '') → submits."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "AI vacuum diagnostics",
        "",
    ]))
    out = _prompt_topic_multiline()
    assert out == "AI vacuum diagnostics"


def test_pasted_multiline_brief_concatenates_with_periods(monkeypatch):
    """Pasted multi-line product brief — each line joined with '. '."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "Build a lightweight fire inspection compliance SaaS",
        "Digital inspection reports replacing paper certificates",
        "NFPA 10 compliance checklists built in",
        "",
    ]))
    out = _prompt_topic_multiline()
    assert out == (
        "Build a lightweight fire inspection compliance SaaS. "
        "Digital inspection reports replacing paper certificates. "
        "NFPA 10 compliance checklists built in"
    )


def test_pasted_bulleted_lines_strip_dash_prefix(monkeypatch):
    """Common bullet prefixes ('- ', '* ', '• ') stripped before join."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "Build a fire inspection SaaS",
        "- Digital reports",
        "* NFPA 10 checklists",
        "• Client portal",
        "",
    ]))
    out = _prompt_topic_multiline()
    assert out == (
        "Build a fire inspection SaaS. "
        "Digital reports. "
        "NFPA 10 checklists. "
        "Client portal"
    )


def test_leading_blank_lines_are_skipped(monkeypatch):
    """Leading empty lines (e.g., paste starting with blank) → keep
    waiting until real content arrives."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "",
        "",
        "real topic here",
        "",
    ]))
    out = _prompt_topic_multiline()
    assert out == "real topic here"


def test_eof_terminates_cleanly(monkeypatch):
    """EOF (Ctrl-D) returns whatever was collected so far."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "line one",
        "line two",
    ]))
    out = _prompt_topic_multiline()
    assert out == "line one. line two"


def test_only_whitespace_returns_empty(monkeypatch):
    """If operator types nothing meaningful and then EOFs, return empty
    so the caller's 'topic cannot be empty' check fires."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "   ",
        "\t",
    ]))
    out = _prompt_topic_multiline()
    assert out == ""


def test_inner_whitespace_in_lines_preserved(monkeypatch):
    """Multi-word lines keep internal spacing; only leading/trailing
    whitespace stripped."""
    monkeypatch.setattr(builtins, "input", _fake_input([
        "  AI vacuum diagnostics  ",
        "",
    ]))
    out = _prompt_topic_multiline()
    assert out == "AI vacuum diagnostics"
