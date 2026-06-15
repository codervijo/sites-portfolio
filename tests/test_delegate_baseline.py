"""v37.E — the baseline-build gate: build the pristine tree before the agent
runs, and bail if it fails (broken env, not the agent's change)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.delegate import run_delegate

_RESULT_OK = '{"type":"result","is_error":false,"total_cost_usd":0.01}'


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, check=False)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "sites"
    d = root / "example.com"
    d.mkdir(parents=True)
    _git(["init"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "package.json").write_text('{"scripts":{"build":"astro build"}}')
    (d / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")  # → _detect_build picks pnpm
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)
    return d


class _Backend:
    def __init__(self, *, exec_rc=0, lines=None):
        self.exec_rc = exec_rc
        self.lines = lines if lines is not None else [_RESULT_OK]
        self.exec_calls: list[str] = []
        self.stream_called = False
        self.killed = 0

    def start(self, sd): self.sd = sd

    def exec(self, cmd, *, timeout=600):
        self.exec_calls.append(cmd)
        return (self.exec_rc, "ok" if self.exec_rc == 0 else "ERROR: missing dep / wrong PM")

    def stream(self, prompt, system_prompt=None):
        self.stream_called = True
        for ln in self.lines:
            yield ln

    def kill(self): self.killed += 1


def _run(site, backend, **kw):
    return run_delegate("example.com", "do x", backend=backend,
                        clock=lambda: 0.0, sites_root=site.parent, **kw)


def test_baseline_failure_aborts_before_agent(site):
    b = _Backend(exec_rc=1)
    res = _run(site, b)
    assert res.status == "error"
    assert res.reason == "baseline-build-failed"
    assert "doesn't build cleanly" in res.message
    assert b.stream_called is False          # agent never ran
    assert len(b.exec_calls) == 1            # only the baseline build
    assert b.killed == 1                     # container torn down


def test_baseline_ok_runs_the_agent(site):
    b = _Backend(exec_rc=0)
    res = _run(site, b)
    assert res.status == "done"
    assert b.stream_called is True
    assert b.exec_calls and "run build" in b.exec_calls[0]  # baseline ran


def test_baseline_skipped_when_no_build_script(site):
    # remove the build script → _detect_build returns None → no baseline
    (site / "package.json").write_text('{"scripts":{"dev":"astro dev"}}')
    _git(["commit", "-am", "drop build"], site)
    b = _Backend(exec_rc=1)                   # would fail IF it ran
    res = _run(site, b)
    assert res.status == "done"
    assert b.stream_called is True
    assert b.exec_calls == []                 # baseline never invoked


def test_no_baseline_flag_skips_the_gate(site):
    b = _Backend(exec_rc=1)                   # would abort IF the gate ran
    res = _run(site, b, baseline_check=False)
    assert res.status == "done"
    assert b.stream_called is True
    assert b.exec_calls == []


def test_baseline_skipped_on_dirty_tree(site):
    # a resume scenario: tree carries a partial → not pristine → skip baseline.
    (site / "partial.txt").write_text("agent's work\n")
    b = _Backend(exec_rc=1)                   # would abort IF the gate ran
    res = _run(site, b, force=True)           # force past the clean-tree preflight
    assert res.status == "done"
    assert b.stream_called is True
    assert b.exec_calls == []
