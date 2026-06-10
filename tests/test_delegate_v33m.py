"""Tests for v33.M — end-of-run output (agent summary + diff + commit cmd).

The agent's closing summary (the deliverable of an inspect-first/report-back
run that changes no files) is captured from the result event and surfaced;
runs with changes also print a ready diff command + commit command.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import portfolio.cli as climod
import pytest
from portfolio.cli import _render_delegate_result, _suggested_commit_msg
from portfolio.delegate import DelegateResult, parse_stream_line, run_delegate


# ---------- capture the agent summary off the stream ----------


def test_parse_result_captures_summary_text():
    ev = parse_stream_line(
        '{"type":"result","is_error":false,"total_cost_usd":0.05,'
        '"result":"Stack is Astro; here is my plan…"}')
    assert ev is not None and ev.kind == "result"
    assert ev.text == "Stack is Astro; here is my plan…"


def test_parse_result_without_summary_is_none():
    ev = parse_stream_line('{"type":"result","is_error":false}')
    assert ev is not None and ev.text is None


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    d = tmp_path / "sites" / "example.com"
    d.mkdir(parents=True)
    _git(["init"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "README.md").write_text("hi\n")
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)
    return d


class _Backend:
    def start(self, site_dir):
        pass

    def stream(self, prompt, system_prompt=None):
        yield ('{"type":"result","is_error":false,"total_cost_usd":0.05,'
               '"result":"Findings: it is an Astro site."}')

    def kill(self):
        pass


def test_run_delegate_carries_summary(site):
    res = run_delegate("example.com", "inspect and report", backend=_Backend(),
                       sites_root=site.parent)
    assert res.status == "done"
    assert res.summary == "Findings: it is an Astro site."


# ---------- commit-message suggestion ----------


def test_suggested_commit_msg_from_first_line():
    msg = _suggested_commit_msg("Add a dark mode toggle\nwith persistence")
    assert msg == "delegate: Add a dark mode toggle"


def test_suggested_commit_msg_neutralizes_quotes():
    assert '"' not in _suggested_commit_msg('Rename "Home" to "Start"')


def test_suggested_commit_msg_empty_request():
    assert _suggested_commit_msg("   \n  ") == "delegate: agent change"


# ---------- rendering ----------


def test_render_shows_summary_on_no_change_run(capsys):
    res = DelegateResult(status="done", reason="ok", cost_usd=0.5,
                         duration_s=12.0, summary="Stack: Astro. Plan: …")
    _render_delegate_result(res, "example.com", "inspect the repo")
    out = capsys.readouterr().out
    assert "Agent summary:" in out
    assert "Stack: Astro" in out
    assert "no file changes" in out
    assert "commit:" not in out          # nothing to commit


def test_render_shows_diff_and_commit_cmd_with_changes(capsys):
    res = DelegateResult(status="done", reason="ok", cost_usd=0.5,
                         duration_s=12.0, changed_files=["src/a.tsx", "src/b.tsx"],
                         summary="Did the thing.")
    _render_delegate_result(res, "example.com", "Add a copy button to slots")
    out = capsys.readouterr().out
    assert "Agent summary:" in out
    assert "2 file(s) changed" in out
    assert "git -C sites/example.com diff" in out
    assert "git -C sites/example.com add -A" in out
    assert 'commit -m "delegate: Add a copy button to slots"' in out
