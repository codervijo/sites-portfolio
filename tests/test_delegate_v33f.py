"""Tests for v33.F — `project delegate` request-input ergonomics.

Covers `_resolve_delegate_request` — the helper that lets a full multi-step
prompt arrive without surviving shell quoting: inline arg ▸ interactive paste
▸ piped stdin ▸ empty. (The v33.F /dev/tty confirm was removed in v33.J when
the pre-run confirmation gate was dropped.)
"""
from __future__ import annotations

import io

from portfolio.cli import _resolve_delegate_request


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
