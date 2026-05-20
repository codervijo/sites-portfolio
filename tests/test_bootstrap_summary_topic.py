"""Tests for the `Topic:` title line at the top of the
`new bootstrap` summary report.

Operator-facing affordance — same shape as `new validate` and
`new domain`. The renderer is a long sequence of `console.print`
calls that touch the filesystem (tree + conformance); these tests
patch the heavy downstream helpers so the assertions focus on the
Topic-line behavior at the top.
"""
from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from portfolio import cli as cli_mod


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


def _stub_result(tmp_path: Path) -> SimpleNamespace:
    """Minimal BootstrapResult duck — only the fields the renderer
    actually reads. Lets us exercise the report without a real
    bootstrap on disk."""
    return SimpleNamespace(
        project_dir=tmp_path / "sites" / "example.com",
        stack="astro",
        path="template",
        files_copied=[],
        cf_fixes=[],
        files_written=[],
        git_initialized=True,
        initial_commit_sha="abc1234",
        warnings=[],
        next_steps=[],
    )


def _patch_renderer_deps(monkeypatch):
    """The bootstrap summary calls `_render_project_tree` and
    `_render_bootstrap_conformance`. Both walk a real project dir;
    no-op them so the test stays focused on the Topic-line surface
    at the top of the report."""
    monkeypatch.setattr(cli_mod, "_render_project_tree", lambda *a, **k: None)
    monkeypatch.setattr(cli_mod, "_render_bootstrap_conformance",
                        lambda *a, **k: None)


def test_bootstrap_summary_renders_topic_line_at_top(monkeypatch, tmp_path):
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    _patch_renderer_deps(monkeypatch)

    cli_mod._render_bootstrap_summary(
        _stub_result(tmp_path), "example.com",
        topic="cordless drill comparison site",
    )
    out = cap.file.getvalue()
    assert "Topic:" in out
    assert "cordless drill comparison site" in out
    # Topic line is the FIRST output — before the "Bootstrapped"
    # check-mark line. Operator sees the topic first when scrolling.
    topic_idx = out.index("Topic:")
    bootstrapped_idx = out.index("Bootstrapped")
    assert topic_idx < bootstrapped_idx


def test_bootstrap_summary_omits_topic_line_when_empty(monkeypatch, tmp_path):
    """Empty `topic` (the default) must not print a bare `Topic:` line
    with nothing beside it. Mirrors `_render_grid`'s contract."""
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    _patch_renderer_deps(monkeypatch)

    cli_mod._render_bootstrap_summary(
        _stub_result(tmp_path), "example.com",
        topic="",
    )
    out = cap.file.getvalue()
    assert "Topic:" not in out
    # And the report still renders.
    assert "Bootstrapped" in out


def test_bootstrap_summary_default_topic_omits_topic_line(monkeypatch, tmp_path):
    """The default for `topic` is an empty string — callers that don't
    pass it should get the same omit-Topic behavior (backward compat
    for any future internal caller, plus tests)."""
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    _patch_renderer_deps(monkeypatch)

    cli_mod._render_bootstrap_summary(
        _stub_result(tmp_path), "example.com",
    )   # no topic kwarg
    out = cap.file.getvalue()
    assert "Topic:" not in out
