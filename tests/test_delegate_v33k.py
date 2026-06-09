"""Tests for v33.K — reliable paste terminator.

The interactive paste ends on a lone `.` sentinel (deterministic regardless
of trailing newline), with Ctrl-D/EOF as a fallback. Piped stdin still reads
straight to EOF (no sentinel). Replaces the flaky Ctrl-D-only path.
"""
from __future__ import annotations

import io

from portfolio.cli import _resolve_delegate_request


def _tty(text: str):
    fake = io.StringIO(text)
    fake.isatty = lambda: True  # type: ignore[attr-defined]
    return fake


def _piped(text: str):
    fake = io.StringIO(text)
    fake.isatty = lambda: False  # type: ignore[attr-defined]
    return fake


def test_sentinel_ends_paste(monkeypatch):
    monkeypatch.setattr("sys.stdin", _tty("line one\nline two\n.\n"))
    assert _resolve_delegate_request(None) == "line one\nline two"


def test_sentinel_not_folded_into_request(monkeypatch):
    monkeypatch.setattr("sys.stdin", _tty("only line\n.\n"))
    out = _resolve_delegate_request(None)
    assert out == "only line"
    assert "." not in out.splitlines()        # the terminator never leaks in


def test_eof_without_sentinel_still_works(monkeypatch):
    # No trailing sentinel — EOF (Ctrl-D) ends the read (the fallback).
    monkeypatch.setattr("sys.stdin", _tty("no sentinel here\nsecond line\n"))
    assert _resolve_delegate_request(None) == "no sentinel here\nsecond line"


def test_line_containing_a_dot_is_not_the_terminator(monkeypatch):
    # Only a *lone* `.` terminates; prose dots and version numbers are kept.
    monkeypatch.setattr("sys.stdin", _tty("end the meeting.\nuse v1.2.3\n.\n"))
    assert _resolve_delegate_request(None) == "end the meeting.\nuse v1.2.3"


def test_piped_reads_to_eof_ignoring_sentinel(monkeypatch):
    # Piped input has no interactive terminator — a literal "." line is kept.
    monkeypatch.setattr("sys.stdin", _piped("a\n.\nb\n"))
    assert _resolve_delegate_request(None) == "a\n.\nb"


def test_inline_request_still_bypasses_stdin(monkeypatch):
    def _boom():
        raise AssertionError("stdin must not be touched for an inline request")
    monkeypatch.setattr("sys.stdin", type("S", (), {
        "isatty": staticmethod(_boom), "read": staticmethod(_boom),
        "__iter__": staticmethod(_boom)})())
    assert _resolve_delegate_request("  do x  ") == "do x"
