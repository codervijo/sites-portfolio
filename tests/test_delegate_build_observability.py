"""v37.H — parse the agent's OWN build outcomes from its stream, so a silent
build-thrash loop is visible live + named in the result (closes the
observability hole that let airsucks burn 5h without naming the build)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.delegate import classify_build_line, run_delegate


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, check=False)


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
    def __init__(self, lines):
        self.lines = lines

    def start(self, sd): self.sd = sd

    def exec(self, cmd, *, timeout=600): return (0, "ok")

    def stream(self, prompt, system_prompt=None):
        for ln in self.lines:
            yield ln

    def kill(self): pass


# ---------- classify_build_line ----------


def test_classify_build_line_failure_signatures():
    for s in ("npm ELIFECYCLE Command failed with exit code 1",
              "error during build: oops",
              "Build failed with 3 errors",
              "✘ [ERROR] Could not resolve",
              "rollup failed to resolve import"):
        assert classify_build_line(s) == "fail", s


def test_classify_build_line_success_signatures():
    for s in ("✓ built in 1.2s", "[prerender] Prerendered 8 pages",
              "compiled successfully", "✨  Done in 3.4s"):
        assert classify_build_line(s) == "pass", s


def test_classify_build_line_neutral_and_fail_precedence():
    assert classify_build_line("the agent edited vite.config.ts") is None
    assert classify_build_line("") is None
    assert classify_build_line("built in 1s then ELIFECYCLE") == "fail"  # fail wins


# ---------- run_delegate surfaces + names build failures ----------


# A claude stream-json tool_result line carrying a build failure in its output.
_FAIL_LINE = ('{"type":"user","message":{"content":[{"type":"tool_result",'
              '"content":"npm error ELIFECYCLE  Command failed with exit code 1"}]}}')


def test_run_delegate_names_agent_build_failures_in_result(site):
    # 2 failing builds, then EOF with no terminal result → no-result error path.
    b = _Backend([_FAIL_LINE, _FAIL_LINE])
    res = run_delegate("example.com", "do x", backend=b, clock=lambda: 0.0,
                       sites_root=site.parent, baseline_check=False)
    assert res.status == "error"                 # no result event
    assert "build failed ×2" in res.message
    assert "stuck on the build" in res.message


def test_run_delegate_emits_build_failures_live(site):
    events: list[tuple[str, str]] = []
    b = _Backend([_FAIL_LINE])
    run_delegate("example.com", "do x", backend=b, clock=lambda: 0.0,
                 sites_root=site.parent, baseline_check=False,
                 on_progress=lambda k, d: events.append((k, d)))
    assert any("build is failing" in d for _k, d in events)


def test_run_delegate_no_build_note_when_builds_pass(site):
    ok_line = ('{"type":"user","message":{"content":[{"type":"tool_result",'
               '"content":"✓ built in 1.2s"}]}}')
    result_ok = '{"type":"result","is_error":false,"total_cost_usd":0.01}'
    b = _Backend([ok_line, result_ok])
    res = run_delegate("example.com", "do x", backend=b, clock=lambda: 0.0,
                       sites_root=site.parent, baseline_check=False)
    assert res.status == "done"
    assert res.message == ""                      # nothing to flag
