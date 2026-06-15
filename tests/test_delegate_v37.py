"""v37 — OSS/OpenHands fallback backend + the agent-adapter seam.

Covers the parts testable without docker/a real agent: the OpenHands adapter's
parse/diagnose, the OSSAgentBackend's terminal-result synthesis + parse hook,
and the auto cap-hand-off (Claude caps → OSS backend finishes) in
run_delegate_resilient / run_delegate_split.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from portfolio.delegate import (
    QuotaStatus,
    ResilientConfig,
    StreamEvent,
    run_delegate,
    run_delegate_resilient,
    run_delegate_split,
)
from portfolio.delegate_oss import (
    _OSS_TERMINAL_OK,
    OSSAgentBackend,
    OpenHandsAdapter,
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


def _rate_limit_line(resets):
    return ('{"type":"rate_limit_event","rate_limit_info":{"status":"rejected",'
            f'"resetsAt":"{resets.isoformat()}","overageStatus":"rejected",'
            '"overageDisabledReason":"org_level_disabled"}}')


class _FakeTime:
    def __init__(self, start):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += timedelta(seconds=s)


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


# ---------- OpenHands adapter: parse + diagnose ----------


def test_adapter_parse_agent_action_is_tool_use():
    a = OpenHandsAdapter(api_key="k")
    ev = a.parse_line('{"source":"agent","kind":"ActionEvent",'
                      '"action":{"kind":"FileEditAction","path":"foo.txt"}}')
    assert ev.kind == "tool_use" and ev.fingerprint == "FileEditAction:foo.txt"


def test_adapter_parse_environment_and_footer():
    a = OpenHandsAdapter(api_key="k")
    assert a.parse_line('{"source":"environment","observation":"x","tool_name":"bash"}').kind == "text"
    assert a.parse_line("Conversation ID: abc-123").kind == "other"   # non-JSON footer
    assert a.parse_line("") is None


def test_adapter_parse_error_event():
    a = OpenHandsAdapter(api_key="k")
    ev = a.parse_line('{"kind":"ErrorEvent","error":{"type":"auth"},"message":"bad key"}')
    assert ev.kind == "error" and ev.api_error_status == "auth" and ev.text == "bad key"


def test_adapter_diagnose():
    a = OpenHandsAdapter(api_key="k")
    assert "rate limit" in a.diagnose(exit_code=1, stderr_tail="OpenAI rate limit 429").lower()
    assert "auth" in a.diagnose(exit_code=1, stderr_tail="authentication failed").lower()
    assert "not found" in a.diagnose(exit_code=127, stderr_tail="").lower()
    assert a.diagnose(exit_code=0, stderr_tail="") is None   # defer to generic


# ---------- OSSAgentBackend: terminal sentinel + parse hook (no docker) ----------


def test_backend_parse_line_sentinel_is_result():
    b = OSSAgentBackend("example.com", OpenHandsAdapter(api_key="k"))
    ev = b.parse_line(_OSS_TERMINAL_OK)
    assert ev.kind == "result" and ev.is_error is False
    # non-sentinel lines delegate to the adapter
    assert b.parse_line('{"source":"agent","action":{"kind":"X"}}').kind == "tool_use"


def test_backend_diagnose_delegates_to_adapter():
    b = OSSAgentBackend("example.com", OpenHandsAdapter(api_key="k"))
    assert "rate limit" in b.diagnose(exit_code=1, stderr_tail="429 rate limit").lower()


# ---------- run_delegate: backend-supplied parser hook ----------


class _CustomParserBackend:
    """A backend whose own parse_line marks a custom line as the result."""
    def __init__(self):
        self.killed = 0

    def start(self, sd): self.sd = sd

    def stream(self, prompt, system_prompt=None):
        (self.sd / "made.txt").write_text("x\n")
        yield "AGENT_DONE"

    def kill(self): self.killed += 1

    def parse_line(self, line):
        if line.strip() == "AGENT_DONE":
            return StreamEvent("result", None, None, is_error=False)
        return StreamEvent("other")


def test_run_delegate_uses_backend_parse_line(site):
    res = run_delegate("example.com", "x", backend=_CustomParserBackend(),
                       clock=lambda: 0.0, sites_root=site.parent)
    assert res.status == "done"          # the backend's parser produced a result
    assert "made.txt" in res.changed_files


# ---------- auto cap-hand-off: Claude caps → OSS fallback finishes ----------


def test_resilient_hands_off_to_fallback_on_cap(site):
    ft = _FakeTime(datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=5)
    claude = _ScriptedBackend([_rate_limit_line(resets)],
                              side_effect=lambda sd: (sd / "partial.txt").write_text("c\n"))
    oss = _ScriptedBackend([_RESULT_OK],
                           side_effect=lambda sd: (sd / "oss.txt").write_text("o\n"))
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: claude,
        fallback_backend_factory=lambda: oss,
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=2),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "done"                  # OSS fallback finished it
    assert oss.killed == 1                        # the fallback actually ran
    assert ft.now() == datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)  # no wait — immediate hand-off
    assert (site / "partial.txt").exists()        # Claude's partial kept (resumed)
    assert (site / "oss.txt").exists()            # OSS continued on top


def test_resilient_preflight_cap_hands_off_to_fallback(site):
    """Already capped at start → hand off to the fallback, don't wait it out.

    Regression: the pre-flight cap path used to always _wait_out(); with a
    fallback configured it must hand off immediately (no Claude run, no wait).
    """
    ft = _FakeTime(datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=999)
    claude_started = {"n": 0}

    def _claude():
        claude_started["n"] += 1
        return _ScriptedBackend([_RESULT_OK])

    oss = _ScriptedBackend([_RESULT_OK],
                           side_effect=lambda sd: (sd / "oss.txt").write_text("o\n"))
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=_claude,
        fallback_backend_factory=lambda: oss,
        preflight_probe=lambda: QuotaStatus(capped=True, resets_at=resets),
        config=ResilientConfig(wait=True, max_wait_s=3600),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "done"                  # the fallback finished it
    assert claude_started["n"] == 0              # Claude never even started
    assert oss.killed == 1                        # the fallback ran
    assert ft.now() == datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)  # no wait
    assert (site / "oss.txt").exists()


def test_split_hands_off_capped_subtask_to_fallback(site):
    ft = _FakeTime(datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=5)
    # Two sub-tasks; sub-task 1 caps on "claude" then the fallback finishes it,
    # sub-task 2 succeeds on "claude".
    claude_backends = iter([
        _ScriptedBackend([_rate_limit_line(resets)],
                         side_effect=lambda sd: (sd / "p1.txt").write_text("c\n")),
        _ScriptedBackend([_RESULT_OK],
                         side_effect=lambda sd: (sd / "t2.txt").write_text("c2\n")),
    ])
    res = run_delegate_split(
        "example.com", "big",
        backend_factory=lambda: next(claude_backends),
        fallback_backend_factory=lambda: _ScriptedBackend(
            [_RESULT_OK], side_effect=lambda sd: (sd / "oss1.txt").write_text("o\n")),
        planner=lambda d, r: ["task one", "task two"],
        config=ResilientConfig(wait=True, max_wait_s=3600), sites_root=site.parent,
        sleep=ft.sleep, now_fn=ft.now)
    assert res.all_done
    assert (site / "oss1.txt").exists()    # sub-task 1 finished by the fallback
    assert (site / "t2.txt").exists()      # sub-task 2 finished by claude


# ---------- CLI: --backend validation ----------


def test_cli_rejects_bad_backend(monkeypatch, tmp_path):
    import portfolio.cli as climod
    import portfolio.delegate as deleg
    from typer.testing import CliRunner
    monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/docker")
    monkeypatch.setattr(deleg, "preflight",
                        lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "do x")
    res = CliRunner().invoke(
        climod.app, ["project", "delegate", "example.com", "--no-verify",
                     "--backend", "bogus"])
    assert res.exit_code == 2
    assert "auto|claude|oss" in res.output
