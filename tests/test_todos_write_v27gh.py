"""v27.G/H/I — surgical todo upsert editor, write verbs, bootstrap seed.

The central invariant: a CLI todo mutation must leave the rest of the
file — especially the human-authored `[content]` block and its comments
— byte-for-byte intact (upsert, not rewrite; ADR-0018). Several tests
assert `[content]` survives an add/done/reopen on a content-bearing file.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from portfolio import lamill_toml
from portfolio import lamill_toml_edit as edit
from portfolio.lamill_toml import LAMILL_TOML_FILENAME, TodoItem


_BASE = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'

_CONTENT = (
    '\n[content]\n'
    '# Declarative content identity for this site.\n'
    'site_type = ""            # e.g. "tool"\n'
    'icp = ""                  # ideal customer profile\n'
)

_WITH_TODOS = (
    _BASE
    + '\n# Tracked todos for x. status: "done" | "open".\n'
    + '[[todo]]\nstatus = "done"\ntask = "ship v1"\n\n'
    + '[[todo]]\nstatus = "open"\npriority = "high"\ntask = "fix redirect"\n'
    + _CONTENT
)

_NO_TODOS = _BASE + '\n[stack]\nframework = "astro"\n' + _CONTENT


def _site(root: Path, name: str, body: str) -> Path:
    d = root / name
    d.mkdir()
    (d / LAMILL_TOML_FILENAME).write_text(body)
    return d


# ---- due-date parsing (text-only) -----------------------------------


def test_due_relative_days():
    assert edit.resolve_due_date("+14d", today=date(2026, 5, 30)) == date(2026, 6, 13)


def test_due_relative_weeks():
    assert edit.resolve_due_date("+2w", today=date(2026, 5, 30)) == date(2026, 6, 13)


def test_due_absolute_iso():
    assert edit.resolve_due_date("2026-07-01", today=date(2026, 5, 30)) == date(2026, 7, 1)


def test_due_bad_spec_raises():
    with pytest.raises(edit.TodoEditError):
        edit.resolve_due_date("soon")


def test_due_hint_text():
    assert edit.due_hint("+14d", today=date(2026, 5, 30)) == " (revisit ~2026-06-13)"


# ---- add_todo -------------------------------------------------------


def test_add_appends_open_todo(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    item = edit.add_todo(d, task="new task", priority="medium")
    assert item.status == "open" and item.priority == "medium"
    doc = lamill_toml.load(d)
    assert [t.task for t in doc.todos][-1] == "new task"
    assert len(doc.todos) == 3


def test_add_preserves_content_block(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    edit.add_todo(d, task="new task", priority="high")
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert "[content]" in text
    assert "ideal customer profile" in text  # comment survived
    assert 'site_type = ""' in text


def test_add_on_file_without_todos_inserts_before_content(tmp_path: Path):
    d = _site(tmp_path, "x", _NO_TODOS)
    edit.add_todo(d, task="first todo")
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert text.index("[[todo]]") < text.index("[content]")
    assert "[stack]" in text and "ideal customer profile" in text
    assert lamill_toml.load(d).todos[0].task == "first todo"


def test_add_empty_task_rejected(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    with pytest.raises(edit.TodoEditError):
        edit.add_todo(d, task="   ")


def test_add_bad_priority_rejected(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    with pytest.raises(edit.TodoEditError):
        edit.add_todo(d, task="ok", priority="urgent")


def test_add_no_lamill_toml_raises(tmp_path: Path):
    (tmp_path / "x").mkdir()
    with pytest.raises(edit.TodoEditError):
        edit.add_todo(tmp_path / "x", task="ok")


# ---- complete / reopen ----------------------------------------------


def test_complete_sets_done_and_strips_priority(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    # index 2 is the open high-priority "fix redirect"
    item = edit.complete_todo(d, 2)
    assert item.status == "done" and item.priority is None
    doc = lamill_toml.load(d)
    assert doc.todos[1].status == "done" and doc.todos[1].priority is None


def test_reopen_sets_open(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    # index 1 is the done "ship v1"
    item = edit.reopen_todo(d, 1)
    assert item.status == "open"
    assert lamill_toml.load(d).todos[0].status == "open"


def test_done_preserves_content_block(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    edit.complete_todo(d, 2)
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert "[content]" in text and "ideal customer profile" in text


def test_index_out_of_range_raises(tmp_path: Path):
    d = _site(tmp_path, "x", _WITH_TODOS)
    with pytest.raises(edit.TodoEditError):
        edit.complete_todo(d, 99)
    with pytest.raises(edit.TodoEditError):
        edit.complete_todo(d, 0)


def test_roundtrip_stable_on_second_edit(tmp_path: Path):
    """A no-op-shaped sequence of edits keeps the file parseable and the
    [content] block intact across multiple writes."""
    d = _site(tmp_path, "x", _WITH_TODOS)
    edit.add_todo(d, task="t1", priority="low")
    edit.complete_todo(d, 3)
    edit.reopen_todo(d, 3)
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert "[content]" in text
    assert lamill_toml.load(d) is not None


# ---- read view shows file-order index -------------------------------


def test_render_shows_file_order_index(tmp_path: Path):
    from rich.console import Console
    import io
    from portfolio import todos as todos_mod

    d = _site(tmp_path, "x", _WITH_TODOS)
    pt = todos_mod.build_project_todos(d, domain="x")
    assert pt.numbered[0][0] == 1 and pt.numbered[1][0] == 2
    buf = io.StringIO()
    todos_mod.render_project_todos(pt, Console(file=buf, width=120, no_color=True))
    out = buf.getvalue()
    assert "[1]" in out and "[2]" in out  # both indices rendered


# ---- ensure_* skeletons (v27.I) -------------------------------------


def test_ensure_content_block_idempotent(tmp_path: Path):
    d = _site(tmp_path, "x", _BASE)  # no [content]
    assert edit.ensure_content_block(d) is True
    assert edit.ensure_content_block(d) is False  # second call no-op
    assert (d / LAMILL_TOML_FILENAME).read_text().count("[content]") == 1


def test_ensure_header_comment_idempotent(tmp_path: Path):
    d = _site(tmp_path, "x", _BASE)  # starts with `schema`, no comment
    assert edit.ensure_header_comment(d) is True
    assert edit.ensure_header_comment(d) is False
    assert (d / LAMILL_TOML_FILENAME).read_text().startswith("# lamill.toml")


# ---- bootstrap starter set (v27.I) ----------------------------------


def test_bootstrap_starter_todos_shape():
    from portfolio.bootstrap import bootstrap_starter_todos
    todos = bootstrap_starter_todos(today=date(2026, 5, 30))
    assert len(todos) == 4
    assert all(t.status == "open" for t in todos)
    assert [t.priority for t in todos] == ["high", "medium", "medium", "low"]
    # SEO check carries the text-only +14d date and is NOT high (won't
    # surface in fleet focus on bootstrap day).
    seo = todos[1]
    assert "revisit ~2026-06-13" in seo.task and seo.priority == "medium"
    # the high-priority seed is the [content] fill-in nudge
    assert "[content]" in todos[0].task and todos[0].priority == "high"


# ---- CLI wiring (`lamill project todos --add/--done/--reopen`) ------


def _wire_cli(monkeypatch, tmp_path: Path, body: str) -> Path:
    from portfolio import project as project_mod
    sites = tmp_path / "sites"
    site = sites / "x.com"
    site.mkdir(parents=True)
    (site / LAMILL_TOML_FILENAME).write_text(body)
    monkeypatch.setattr(project_mod, "SITES_ROOT", sites)
    monkeypatch.setattr(project_mod, "load_plan", lambda: {"x.com": "T"})
    return site


def test_cli_add_preserves_content(monkeypatch, tmp_path: Path):
    from typer.testing import CliRunner
    from portfolio.cli import app

    site = _wire_cli(monkeypatch, tmp_path, _WITH_TODOS)
    res = CliRunner().invoke(
        app, ["project", "todos", "x.com", "--add", "cli task", "--priority", "low"]
    )
    assert res.exit_code == 0, res.output
    text = (site / LAMILL_TOML_FILENAME).read_text()
    assert "[content]" in text and "ideal customer profile" in text
    assert lamill_toml.load(site).todos[-1].task == "cli task"


def test_cli_add_with_due_bakes_date(monkeypatch, tmp_path: Path):
    from typer.testing import CliRunner
    from portfolio.cli import app

    site = _wire_cli(monkeypatch, tmp_path, _WITH_TODOS)
    res = CliRunner().invoke(
        app, ["project", "todos", "x.com", "--add", "seo check", "--due", "2026-06-13"]
    )
    assert res.exit_code == 0, res.output
    assert "revisit ~2026-06-13" in lamill_toml.load(site).todos[-1].task


def test_cli_rejects_two_actions(monkeypatch, tmp_path: Path):
    from typer.testing import CliRunner
    from portfolio.cli import app

    _wire_cli(monkeypatch, tmp_path, _WITH_TODOS)
    res = CliRunner().invoke(
        app, ["project", "todos", "x.com", "--done", "1", "--reopen", "2"]
    )
    assert res.exit_code == 2


def test_cli_rejects_priority_without_add(monkeypatch, tmp_path: Path):
    from typer.testing import CliRunner
    from portfolio.cli import app

    _wire_cli(monkeypatch, tmp_path, _WITH_TODOS)
    res = CliRunner().invoke(
        app, ["project", "todos", "x.com", "--priority", "high"]
    )
    assert res.exit_code == 2
