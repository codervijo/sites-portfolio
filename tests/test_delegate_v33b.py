"""Tests for v33.B — `project delegate` container-independent core.

Covers preflight (site resolution + dirty-tree refusal + the operator-facing
message), the stream parser, and the two-axis supervisor (liveness `idle`,
progress `spinning`, the `timeout`/`budget` backstops, and the cases that
must NOT trip — real progress, novel actions, deep-thinking quiet bursts).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.delegate import (
    Bounds,
    DelegateRefused,
    StreamEvent,
    Supervisor,
    build_delegate_prompt,
    changed_files,
    format_dirty_tree_error,
    parse_stream_line,
    preflight,
    resolve_site_dir,
    run_delegate,
    working_tree_dirty,
)


# ---------- fixtures ----------


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    """A clean git-backed sites/<domain>/ checkout."""
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


# ---------- preflight: resolution ----------


def test_resolve_missing_site_refuses(tmp_path):
    with pytest.raises(DelegateRefused) as e:
        resolve_site_dir("nope.com", sites_root=tmp_path / "sites")
    assert "no site directory" in str(e.value).lower()


def test_resolve_non_git_refuses(tmp_path):
    root = tmp_path / "sites"
    (root / "plain.com").mkdir(parents=True)
    with pytest.raises(DelegateRefused) as e:
        resolve_site_dir("plain.com", sites_root=root)
    assert "not a git repository" in str(e.value).lower()


def test_resolve_clean_site_ok(site):
    got = resolve_site_dir("example.com", sites_root=site.parent)
    assert got == site


# ---------- preflight: dirty-tree gate ----------


def test_clean_tree_passes_preflight(site):
    assert working_tree_dirty(site) == []
    assert preflight("example.com", sites_root=site.parent) == site


def test_dirty_tree_refuses(site):
    (site / "README.md").write_text("changed\n")
    (site / "new.txt").write_text("x\n")
    dirty = working_tree_dirty(site)
    assert len(dirty) == 2
    with pytest.raises(DelegateRefused) as e:
        preflight("example.com", sites_root=site.parent)
    msg = str(e.value)
    assert "uncommitted changes" in msg
    assert "README.md" in msg
    assert "stash" in msg and "commit" in msg          # safe recovery shown
    assert msg.index("commit") < msg.index("--force")  # recovery before bypass


def test_force_skips_dirty_gate(site):
    (site / "README.md").write_text("changed\n")
    # force still resolves the dir but does not refuse on dirtiness
    assert preflight("example.com", force=True, sites_root=site.parent) == site


def test_dirty_error_truncates_long_listing(site):
    dirty = [f"?? f{i}.txt" for i in range(20)]
    msg = format_dirty_tree_error("example.com", site, dirty)
    assert "and 8 more" in msg


# ---------- stream parser ----------


def test_parse_blank_and_garbage():
    assert parse_stream_line("") is None
    assert parse_stream_line("not json") is None
    assert parse_stream_line("[1,2,3]") is None  # not a dict


def test_parse_tool_use_fingerprint():
    line = (
        '{"type":"assistant","message":{"content":'
        '[{"type":"tool_use","name":"Edit",'
        '"input":{"file_path":"src/Header.astro"}}]}}'
    )
    ev = parse_stream_line(line)
    assert ev.kind == "tool_use"
    assert ev.fingerprint == "edit:src/Header.astro"


def test_parse_result_cost():
    ev = parse_stream_line('{"type":"result","total_cost_usd":0.42}')
    assert ev.kind == "result"
    assert ev.cost_usd == pytest.approx(0.42)


def test_parse_assistant_text_only():
    ev = parse_stream_line(
        '{"type":"assistant","message":{"content":'
        '[{"type":"text","text":"thinking"}]}}'
    )
    assert ev.kind == "text"


def test_bash_fingerprint_whitespace_normalized():
    a = parse_stream_line(
        '{"type":"assistant","message":{"content":'
        '[{"type":"tool_use","name":"Bash","input":{"command":"npm   run  build"}}]}}'
    )
    assert a.fingerprint == "bash:npm run build"


# ---------- supervisor: backstops ----------


def _b(**kw) -> Bounds:
    base = dict(wall_clock_s=1000, budget_usd=3.0, idle_s=90,
                progress_window_s=200, min_events_for_spin=4,
                novelty_floor=0.5, diff_epsilon=0)
    base.update(kw)
    return Bounds(**base)


def test_budget_backstop():
    s = Supervisor(_b(), start=0.0)
    assert s.tick(1.0, 0, StreamEvent("result", None, 3.5)) == "budget"


def test_timeout_backstop():
    s = Supervisor(_b(wall_clock_s=100), start=0.0)
    assert s.tick(50, 5) is None
    assert s.tick(100, 6) == "timeout"


def test_idle_liveness():
    s = Supervisor(_b(idle_s=90), start=0.0)
    s.tick(10, 1, StreamEvent("tool_use", "edit:a"))
    assert s.tick(80, 1) is None          # 70s since last event — alive
    assert s.tick(101, 1) == "idle"       # 91s since last event — silent


# ---------- supervisor: progress axis (the load-bearing one) ----------


def test_spinning_when_repeating_with_no_diff_growth():
    """Tokens flowing (events present), but same two actions over and over
    and zero net diff growth across the window → spinning."""
    s = Supervisor(_b(progress_window_s=100, min_events_for_spin=4,
                      novelty_floor=0.5), start=0.0)
    fps = ["edit:a", "edit:a", "bash:test", "edit:a", "bash:test", "edit:a"]
    out = None
    for i, fp in enumerate(fps):
        out = s.tick(101 + i, 0, StreamEvent("tool_use", fp))
    assert out == "spinning"


def test_not_spinning_when_diff_grows():
    """Same heavy activity, but the tree is actually growing → real work,
    not spinning."""
    s = Supervisor(_b(progress_window_s=100), start=0.0)
    out = "x"
    for i, fp in enumerate(["edit:a"] * 8):
        out = s.tick(101 + i, 10 * (i + 1), StreamEvent("tool_use", fp))
    assert out is None


def test_not_spinning_when_actions_are_novel():
    """Active with no diff growth yet, but every action is distinct (genuine
    exploration / reading) → high novelty, not spinning."""
    s = Supervisor(_b(progress_window_s=100, novelty_floor=0.5), start=0.0)
    out = "x"
    for i in range(8):
        out = s.tick(101 + i, 0, StreamEvent("tool_use", f"read:f{i}"))
    assert out is None


def test_not_spinning_before_full_window():
    """Repetition inside the first window is tolerated — don't kill a run
    that just started."""
    s = Supervisor(_b(progress_window_s=200), start=0.0)
    out = "x"
    for i in range(6):
        out = s.tick(10 + i, 0, StreamEvent("tool_use", "edit:a"))
    assert out is None


def test_quiet_thinking_burst_is_alive_not_spinning():
    """A reasoning burst (text events, no tool actions, no diff) within the
    idle window is neither idle nor spinning — too few actions to judge
    progress, and the stream is still flowing."""
    s = Supervisor(_b(idle_s=90, progress_window_s=100,
                      min_events_for_spin=4), start=0.0)
    out = "x"
    for i in range(5):
        out = s.tick(101 + i * 10, 0, StreamEvent("text", None))
    assert out is None


# ---------- prompt assembly ----------


def test_prompt_includes_request_and_context(site):
    (site / "AI_AGENTS.md").write_text("# Example site\nConventions here.\n")
    prompt = build_delegate_prompt(site, "  add a dark mode toggle  ")
    assert "add a dark mode toggle" in prompt
    assert "Do not commit" in prompt
    assert "Conventions here." in prompt


# ---------- orchestration: run_delegate (fake backend) ----------


class FakeBackend:
    """Scripted backend: yields the given raw lines, records lifecycle."""

    def __init__(self, lines, *, raise_on_stream=False):
        self.lines = lines
        self.raise_on_stream = raise_on_stream
        self.started_with = None
        self.killed = 0

    def start(self, site_dir):
        self.started_with = site_dir

    def stream(self, prompt):
        self.prompt = prompt
        if self.raise_on_stream:
            raise RuntimeError("boom")
        for ln in self.lines:
            yield ln

    def kill(self):
        self.killed += 1


def _clock(times):
    it = iter(times)
    return lambda: next(it)


def test_run_delegate_refused_dirty_never_starts(site):
    (site / "README.md").write_text("dirty\n")
    be = FakeBackend([])
    res = run_delegate("example.com", "do x", backend=be, sites_root=site.parent)
    assert res.status == "refused"
    assert "uncommitted" in res.message
    assert be.started_with is None         # never touched the sandbox
    assert be.killed == 0


def test_run_delegate_done_reports_changed_files(site):
    # the "agent" creates a file mid-run; backend just streams events
    def stream_with_side_effect(self, prompt):
        (site / "feature.txt").write_text("new\n")
        yield '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Write","input":{"file_path":"feature.txt"}}]}}'
        yield '{"type":"result","total_cost_usd":0.12}'
    be = FakeBackend([])
    be.stream = stream_with_side_effect.__get__(be, FakeBackend)
    res = run_delegate("example.com", "add feature.txt", backend=be,
                       clock=_clock([0, 1, 2, 3]), sites_root=site.parent)
    assert res.status == "done"
    assert res.cost_usd == pytest.approx(0.12)
    assert "feature.txt" in res.changed_files
    assert be.killed >= 1                   # container always torn down


def test_run_delegate_spinning_kills(site):
    # force spinning: window 0, any repeat, no diff growth
    b = Bounds(progress_window_s=0, min_events_for_spin=1, novelty_floor=1.0,
               diff_epsilon=0, idle_s=999, wall_clock_s=999, budget_usd=999)
    line = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"a"}}]}}'
    be = FakeBackend([line, line, line])
    res = run_delegate("example.com", "x", backend=be, bounds=b,
                       clock=_clock([0, 5, 6, 7, 8]),
                       diff_sampler=lambda _: 0, sites_root=site.parent)
    assert res.status == "spinning"
    assert be.killed >= 1


def test_run_delegate_idle_kills(site):
    b = Bounds(idle_s=10, wall_clock_s=999, budget_usd=999,
               progress_window_s=999)
    be = FakeBackend(["", "", ""])          # only heartbeats, no events
    res = run_delegate("example.com", "x", backend=be, bounds=b,
                       clock=_clock([0, 5, 20, 30]),
                       diff_sampler=lambda _: 0, sites_root=site.parent)
    assert res.status == "idle"
    assert be.killed >= 1


def test_run_delegate_backend_error_is_caught(site):
    be = FakeBackend([], raise_on_stream=True)
    res = run_delegate("example.com", "x", backend=be,
                       clock=_clock([0, 1]), sites_root=site.parent)
    assert res.status == "error"
    assert "boom" in res.reason
    assert be.killed >= 1                   # still torn down


def test_run_delegate_no_result_event_is_error_not_done(site):
    """The v33.B false-green: the agent never really ran (no `result`
    event) → must be `error`, never a green `done`."""
    line = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"a"}}]}}'
    be = FakeBackend([line])               # tool_use but NO result event
    res = run_delegate("example.com", "x", backend=be,
                       clock=_clock([0, 1, 2]), sites_root=site.parent)
    assert res.status == "error"
    assert "no result" in res.reason


def test_run_delegate_errored_result_is_error(site):
    be = FakeBackend(['{"type":"result","is_error":true,"total_cost_usd":0.04}'])
    res = run_delegate("example.com", "x", backend=be,
                       clock=_clock([0, 1, 2]), sites_root=site.parent)
    assert res.status == "error"
    assert res.cost_usd == pytest.approx(0.04)


def test_parse_result_is_error_flag():
    ev = parse_stream_line('{"type":"result","is_error":true,"total_cost_usd":0.1}')
    assert ev.kind == "result" and ev.is_error is True
    ev2 = parse_stream_line('{"type":"result","total_cost_usd":0.1}')
    assert ev2.is_error is False
