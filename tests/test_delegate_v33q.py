"""v33.Q — auto-split a too-big delegate request into sub-tasks.

The planner decomposes a request into ordered independent sub-tasks (degrading
to a single task whenever it's atomic / unavailable / unparseable), and the
split orchestrator runs each through resume-on-cap in turn, ACCUMULATING in the
working tree, stopping the chain on the first non-`done` sub-task.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from portfolio.delegate import (
    ResilientConfig,
    _parse_subtask_json,
    plan_subtasks,
    run_delegate_split,
)


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
    (d / "README.md").write_text("hi\n")
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)
    return d


_RESULT_OK = '{"type":"result","is_error":false,"total_cost_usd":0.05}'


class _ScriptedBackend:
    def __init__(self, lines, *, side_effect=None):
        self.lines = lines
        self.side_effect = side_effect
        self.killed = 0

    def start(self, site_dir):
        self.sd = site_dir

    def stream(self, prompt, system_prompt=None):
        if self.side_effect:
            self.side_effect(self.sd)
        for ln in self.lines:
            yield ln

    def kill(self):
        self.killed += 1


def _runner(stdout):
    return lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")


# ---------- planner parsing ----------


def test_parse_subtask_json_variants():
    assert _parse_subtask_json('prose ["a","b","c"] tail') == ["a", "b", "c"]
    assert _parse_subtask_json('```json\n["x","y"]\n```') == ["x", "y"]
    assert _parse_subtask_json("no array") == []
    assert _parse_subtask_json('[1, 2, "ok"]') == ["ok"]   # non-strings dropped


def test_plan_subtasks_splits():
    out = plan_subtasks("x.com", "big task",
                        runner=_runner('["task a", "task b", "task c"]'))
    assert out == ["task a", "task b", "task c"]


def test_plan_subtasks_atomic_returns_single():
    out = plan_subtasks("x.com", "do one thing",
                        runner=_runner('["do one thing"]'))
    assert out == ["do one thing"]            # 1 item → original request


def test_plan_subtasks_falls_back_when_unparseable():
    out = plan_subtasks("x.com", "original", runner=_runner("sorry, no JSON"))
    assert out == ["original"]


def test_plan_subtasks_falls_back_when_no_claude():
    def boom(cmd):
        raise FileNotFoundError("claude")
    assert plan_subtasks("x.com", "original", runner=boom) == ["original"]


def test_plan_subtasks_caps_count():
    many = "[" + ",".join(f'"t{i}"' for i in range(20)) + "]"
    out = plan_subtasks("x.com", "big", runner=_runner(many), max_subtasks=5)
    assert len(out) == 5


# ---------- split orchestration ----------


def _route_backend(route: str, lines=(_RESULT_OK,)):
    def se(sd):
        (sd / route).write_text("ssr\n")
    return _ScriptedBackend(list(lines), side_effect=se)


def test_split_runs_each_subtask_accumulating_in_tree(site):
    backends = iter([_route_backend("route1.txt"),
                     _route_backend("route2.txt"),
                     _route_backend("route3.txt")])
    res = run_delegate_split(
        "example.com", "make all routes SSR",
        backend_factory=lambda: next(backends),
        planner=lambda d, r: ["SSR route1", "SSR route2", "SSR route3"],
        config=ResilientConfig(wait=True), sites_root=site.parent)

    assert res.was_split and res.all_done
    assert len(res.outcomes) == 3
    # every sub-task's work accumulated in the one tree (sub-task 2+ ran with
    # force, starting from the prior sub-tasks' changes).
    assert (site / "route1.txt").exists()
    assert (site / "route2.txt").exists()
    assert (site / "route3.txt").exists()


def test_split_stops_chain_on_first_non_done(site):
    backends = iter([
        _route_backend("route1.txt"),       # sub-task 1 → done
        _ScriptedBackend([]),               # sub-task 2 → no result → error
        _route_backend("route3.txt"),       # sub-task 3 → never reached
    ])
    res = run_delegate_split(
        "example.com", "big",
        backend_factory=lambda: next(backends),
        planner=lambda d, r: ["a", "b", "c"],
        config=ResilientConfig(wait=True), sites_root=site.parent)

    assert res.was_split and not res.all_done
    assert len(res.outcomes) == 2                  # stopped after the failure
    assert res.outcomes[0].status == "done"
    assert res.outcomes[1].status == "error"
    assert not (site / "route3.txt").exists()      # never ran sub-task 3


def test_split_single_task_behaves_like_one_run(site):
    res = run_delegate_split(
        "example.com", "atomic",
        backend_factory=lambda: _route_backend("only.txt"),
        planner=lambda d, r: ["atomic"],           # 1 item — no real split
        config=ResilientConfig(wait=True), sites_root=site.parent)
    assert not res.was_split
    assert res.all_done and len(res.outcomes) == 1
    assert (site / "only.txt").exists()


def test_cli_splits_by_default(monkeypatch, tmp_path):
    """The CLI delegate command splits by default — planner → N sub-tasks →
    run_delegate_split → 'Auto-split: N/N' (both I/O ends mocked)."""
    import portfolio.cli as climod
    import portfolio.delegate as deleg
    from typer.testing import CliRunner

    monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/docker")
    monkeypatch.setattr(
        deleg, "preflight",
        lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request",
                        lambda r: "make every route SSR")
    monkeypatch.setattr(deleg, "plan_subtasks",
                        lambda d, r: ["SSR /a", "SSR /b"])
    monkeypatch.setattr(
        deleg, "run_delegate_resilient",
        lambda domain, request, **kw: deleg.DelegateResult(status="done",
                                                           reason="ok"))
    res = CliRunner().invoke(
        climod.app, ["project", "delegate", "example.com", "--no-verify"])
    assert res.exit_code == 0
    assert "Auto-split: 2/2" in res.output


def test_cli_no_split_runs_single(monkeypatch, tmp_path):
    """--no-split bypasses the planner → one run_delegate_resilient, no
    'Auto-split' header."""
    import portfolio.cli as climod
    import portfolio.delegate as deleg
    from typer.testing import CliRunner

    monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/docker")
    monkeypatch.setattr(
        deleg, "preflight",
        lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "do it")
    calls = {"plan": 0}
    monkeypatch.setattr(deleg, "plan_subtasks",
                        lambda d, r: calls.__setitem__("plan", calls["plan"] + 1) or [r])
    monkeypatch.setattr(
        deleg, "run_delegate_resilient",
        lambda domain, request, **kw: deleg.DelegateResult(status="done",
                                                           reason="ok"))
    res = CliRunner().invoke(
        climod.app,
        ["project", "delegate", "example.com", "--no-verify", "--no-split"])
    assert res.exit_code == 0
    assert "Auto-split" not in res.output
    assert calls["plan"] == 0          # planner not consulted under --no-split


def test_split_uses_default_planner_when_none_given(site, monkeypatch):
    """With no injected planner it calls plan_subtasks — patched here to avoid
    a real `claude` call — proving the default path is wired."""
    import portfolio.delegate as deleg
    monkeypatch.setattr(deleg, "plan_subtasks", lambda d, r: ["one", "two"])
    backends = iter([_route_backend("a.txt"), _route_backend("b.txt")])
    res = run_delegate_split(
        "example.com", "whatever",
        backend_factory=lambda: next(backends),
        config=ResilientConfig(wait=True), sites_root=site.parent)
    assert res.was_split and res.all_done and len(res.outcomes) == 2
