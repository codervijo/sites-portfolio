"""Tests for v33.L — startup visibility.

run_delegate emits an `on_progress(kind, detail)` stream so the CLI can keep
the terminal alive during the otherwise-silent sandbox bringup + agent run:
a "starting sandbox" phase before `backend.start()`, "agent starting" after,
and an "action" per tool_use. The CLI wires this to a rich spinner.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import portfolio.cli as climod
import portfolio.delegate as deleg
import pytest
from portfolio.delegate import run_delegate
from typer.testing import CliRunner


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "sites"
    d = root / "example.com"
    d.mkdir(parents=True)
    _git(["init"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "README.md").write_text("hi\n")
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)
    return d


class _Backend:
    """Records lifecycle; streams a tool_use then a clean result."""

    def __init__(self):
        self.started = False

    def start(self, site_dir):
        self.started = True

    def stream(self, prompt, system_prompt=None):
        yield ('{"type":"assistant","message":{"content":[{"type":"tool_use",'
               '"name":"Write","input":{"file_path":"feature.txt"}}]}}')
        yield '{"type":"result","is_error":false,"total_cost_usd":0.05}'

    def kill(self):
        pass


def test_run_delegate_emits_phases_and_actions(site):
    events: list[tuple[str, str]] = []
    run_delegate("example.com", "do x", backend=_Backend(),
                 sites_root=site.parent,
                 on_progress=lambda kind, detail: events.append((kind, detail)))

    phases = [d for k, d in events if k == "phase"]
    actions = [d for k, d in events if k == "action"]

    assert any("starting sandbox" in p for p in phases)
    assert any("agent starting" in p for p in phases)
    # the streamed tool_use surfaced as a live action mentioning the file
    assert any("feature.txt" in a for a in actions)

    # ordering: sandbox phase is announced before the agent-starting phase
    sandbox_i = next(i for i, (k, d) in enumerate(events)
                     if k == "phase" and "starting sandbox" in d)
    agent_i = next(i for i, (k, d) in enumerate(events)
                   if k == "phase" and "agent starting" in d)
    assert sandbox_i < agent_i


def test_run_delegate_without_callback_still_runs(site):
    # on_progress is optional — default None must not break the run.
    res = run_delegate("example.com", "do x", backend=_Backend(),
                       sites_root=site.parent)
    assert res.status == "done"


def test_cli_passes_on_progress_to_run_delegate(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker")
    monkeypatch.setattr(deleg, "preflight", lambda domain, *, force=False: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "do x")
    captured = {}

    def fake_run(domain, request, **kw):
        captured.update(kw)
        return deleg.DelegateResult(status="done", reason="ok")
    monkeypatch.setattr(deleg, "run_delegate", fake_run)

    result = CliRunner().invoke(
        climod.app, ["project", "delegate", "example.com", "--no-verify"])
    assert result.exit_code == 0
    assert "on_progress" in captured and callable(captured["on_progress"])
