"""Tests for v33.F — `project delegate` request-input ergonomics.

Covers the two CLI helpers that let a full multi-step prompt arrive without
surviving shell quoting: `_resolve_delegate_request` (inline arg ▸ interactive
paste ▸ piped stdin ▸ empty) and `_delegate_confirm` (reads /dev/tty, not the
stdin a pasted/piped request has already consumed).
"""
from __future__ import annotations

import io

import pytest
import typer

from portfolio.cli import _delegate_confirm, _resolve_delegate_request


# ---------- _resolve_delegate_request ----------


def test_inline_request_wins_and_strips(monkeypatch):
    # An inline arg is used verbatim (stripped); stdin is never touched.
    def _boom():
        raise AssertionError("stdin must not be read when an inline arg is given")

    monkeypatch.setattr("sys.stdin", type("S", (), {"read": staticmethod(_boom),
                                                    "isatty": staticmethod(_boom)})())
    assert _resolve_delegate_request("  add a dark mode toggle  ") == "add a dark mode toggle"


def test_tty_paste_reads_to_eof(monkeypatch):
    fake = io.StringIO("line one\nline two\n")
    fake.isatty = lambda: True  # type: ignore[attr-defined]
    monkeypatch.setattr("sys.stdin", fake)
    assert _resolve_delegate_request(None) == "line one\nline two"


def test_piped_stdin_reads_silently(monkeypatch, capsys):
    fake = io.StringIO("piped request body")
    fake.isatty = lambda: False  # type: ignore[attr-defined]
    monkeypatch.setattr("sys.stdin", fake)
    out = _resolve_delegate_request(None)
    assert out == "piped request body"
    # No "Paste your request" banner when stdin is piped (not a TTY).
    assert "Paste your request" not in capsys.readouterr().out


def test_empty_stdin_returns_empty(monkeypatch):
    fake = io.StringIO("   \n  \n")
    fake.isatty = lambda: True  # type: ignore[attr-defined]
    monkeypatch.setattr("sys.stdin", fake)
    assert _resolve_delegate_request(None) == ""  # caller aborts on ""


# ---------- _delegate_confirm ----------


class _FakeTty:
    """Minimal /dev/tty stand-in: records writes, replays a queued answer."""

    def __init__(self, answer: str):
        self._answer = answer
        self.written = ""

    def write(self, s):
        self.written += s

    def flush(self):
        pass

    def readline(self):
        return self._answer

    def close(self):
        pass


def _patch_tty(monkeypatch, fake):
    """Route open('/dev/tty', ...) to `fake`; anything else uses real open."""
    real_open = open

    def fake_open(path, *a, **k):
        if path == "/dev/tty":
            return fake
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", fake_open)


def test_confirm_reads_tty_not_stdin(monkeypatch):
    # stdin would raise if touched — proving the confirm uses /dev/tty.
    monkeypatch.setattr("sys.stdin", type("S", (), {
        "read": staticmethod(lambda: (_ for _ in ()).throw(AssertionError("stdin read"))),
        "readline": staticmethod(lambda: (_ for _ in ()).throw(AssertionError("stdin readline"))),
    })())
    _patch_tty(monkeypatch, _FakeTty("y\n"))
    assert _delegate_confirm("Proceed?", default=True) is True


def test_confirm_empty_line_uses_default(monkeypatch):
    _patch_tty(monkeypatch, _FakeTty("\n"))
    assert _delegate_confirm("Proceed?", default=True) is True
    _patch_tty(monkeypatch, _FakeTty("\n"))
    assert _delegate_confirm("Proceed?", default=False) is False


@pytest.mark.parametrize("answer,expected", [
    ("y\n", True), ("yes\n", True), ("Y\n", True),
    ("n\n", False), ("no\n", False), ("nope\n", False),
])
def test_confirm_parses_answer(monkeypatch, answer, expected):
    _patch_tty(monkeypatch, _FakeTty(answer))
    assert _delegate_confirm("Proceed?", default=True) is expected


def test_confirm_no_tty_exits(monkeypatch):
    def no_tty_open(path, *a, **k):
        if path == "/dev/tty":
            raise OSError("no controlling terminal")
        raise AssertionError("unexpected open")

    monkeypatch.setattr("builtins.open", no_tty_open)
    with pytest.raises(typer.Exit):
        _delegate_confirm("Proceed?", default=True)
