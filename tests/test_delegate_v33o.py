"""v33.O — delegate debuggability: honest no-result diagnosis.

A silent no-result run used to be hardcoded as "sandbox/auth failure". These
tests pin the real behavior: the stream's `rate_limit_event` / `api_error` /
`result.api_error_status` are parsed, and `diagnose_no_result` builds the
reason from real evidence (rate-limit > api-error > exit-code+stderr > stderr
> the sandbox/auth guess only as a last resort)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.delegate import (
    RunEvidence,
    diagnose_no_result,
    parse_stream_line,
    run_delegate,
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


def _clock(times):
    it = iter(times)
    return lambda: next(it)


# ---------- parse_stream_line: new event kinds ----------


def test_parse_rate_limit_event():
    line = ('{"type":"rate_limit_event","rate_limit_info":{"status":"exhausted",'
            '"resetsAt":"2026-06-13T20:00:00Z","overageStatus":"rejected",'
            '"overageDisabledReason":"org_level_disabled"}}')
    ev = parse_stream_line(line)
    assert ev is not None and ev.kind == "rate_limit"
    assert ev.rate_limit == {
        "status": "exhausted",
        "resets_at": "2026-06-13T20:00:00Z",
        "overage_status": "rejected",
        "overage_disabled_reason": "org_level_disabled",
    }


def test_parse_result_carries_api_error_status():
    ev = parse_stream_line(
        '{"type":"result","is_error":true,"total_cost_usd":0.0,'
        '"api_error_status":"overloaded_error"}')
    assert ev.kind == "result" and ev.is_error is True
    assert ev.api_error_status == "overloaded_error"


def test_parse_standalone_error_line():
    ev = parse_stream_line(
        '{"type":"error","error":{"type":"authentication_error",'
        '"message":"invalid x-api-key"}}')
    assert ev is not None and ev.kind == "error"
    assert ev.api_error_status == "authentication_error"
    assert ev.text == "invalid x-api-key"


def test_parse_result_without_api_error_status_is_none():
    ev = parse_stream_line('{"type":"result","total_cost_usd":0.1}')
    assert ev.api_error_status is None and ev.rate_limit is None


# ---------- diagnose_no_result: evidence precedence ----------


def test_diagnose_prefers_rate_limit():
    msg = diagnose_no_result(
        exit_code=1, stderr_tail="some noise",
        rate_limit={"status": "exhausted", "resets_at": "2026-06-13T20:00:00Z",
                    "overage_status": "rejected",
                    "overage_disabled_reason": "org_level_disabled"},
        api_error="overloaded_error")
    assert "rate-limited" in msg
    assert "2026-06-13T20:00:00Z" in msg
    assert "org_level_disabled" in msg
    assert "sandbox/auth" not in msg


def test_diagnose_api_error_when_no_rate_limit():
    msg = diagnose_no_result(exit_code=0, stderr_tail="", rate_limit=None,
                             api_error="overloaded_error")
    assert "API error: overloaded_error" in msg
    assert "sandbox/auth" not in msg


def test_diagnose_exit_code_and_stderr():
    msg = diagnose_no_result(exit_code=127, stderr_tail="claude: command not found",
                             rate_limit=None, api_error=None)
    assert "exited 127" in msg
    assert "command not found" in msg


def test_diagnose_stderr_only_when_exit_zero():
    msg = diagnose_no_result(exit_code=0, stderr_tail="some warning text",
                             rate_limit=None, api_error=None)
    assert "no result" in msg
    assert "some warning text" in msg


def test_diagnose_no_evidence_is_last_resort_guess():
    msg = diagnose_no_result(exit_code=None, stderr_tail="",
                             rate_limit=None, api_error=None)
    assert "sandbox/auth" in msg
    assert "--debug" in msg


def test_diagnose_rate_limit_without_block_status_falls_through():
    # A rate_limit event whose status isn't a hard block shouldn't masquerade
    # as the cause — fall through to the next signal.
    msg = diagnose_no_result(exit_code=2, stderr_tail="boom",
                             rate_limit={"status": "allowed", "overage_status": "ok"},
                             api_error=None)
    assert "rate-limited" not in msg
    assert "exited 2" in msg


# ---------- run_delegate: evidence wired through the no-result path ----------


class _EvidenceBackend:
    """Fake backend exposing the optional `last_run_evidence` capability."""

    def __init__(self, lines, evidence: RunEvidence):
        self.lines = lines
        self._evidence = evidence
        self.killed = 0

    def start(self, site_dir):
        pass

    def stream(self, prompt, system_prompt=None):
        for ln in self.lines:
            yield ln

    def kill(self):
        self.killed += 1

    def last_run_evidence(self) -> RunEvidence:
        return self._evidence


def test_run_delegate_rate_limited_no_result_reports_real_reason(site):
    """The headline bug: a rate-limited run must NOT be misreported as
    'sandbox/auth failure'."""
    lines = [
        '{"type":"rate_limit_event","rate_limit_info":{"status":"exhausted",'
        '"resetsAt":"2026-06-13T20:00:00Z","overageStatus":"rejected",'
        '"overageDisabledReason":"org_level_disabled"}}',
    ]  # NO result event
    be = _EvidenceBackend(lines, RunEvidence(exit_code=1, stderr_tail="x"))
    res = run_delegate("example.com", "do x", backend=be,
                       clock=_clock([0, 1, 2, 3]), sites_root=site.parent)
    assert res.status == "error"
    assert "rate-limited" in res.reason
    assert "sandbox/auth" not in res.reason
    assert be.killed == 1


def test_run_delegate_no_result_uses_exit_code_and_stderr(site):
    be = _EvidenceBackend(
        [],  # no events at all
        RunEvidence(exit_code=127, stderr_tail="claude: not found"))
    res = run_delegate("example.com", "do x", backend=be,
                       clock=_clock([0, 1, 2]), sites_root=site.parent)
    assert res.status == "error"
    assert "exited 127" in res.reason
    assert "not found" in res.reason


def test_run_delegate_errored_result_includes_api_error(site):
    be = _EvidenceBackend(
        ['{"type":"result","is_error":true,"total_cost_usd":0.02,'
         '"api_error_status":"overloaded_error"}'],
        RunEvidence())
    res = run_delegate("example.com", "do x", backend=be,
                       clock=_clock([0, 1, 2]), sites_root=site.parent)
    assert res.status == "error"
    assert "overloaded_error" in res.reason


def test_run_delegate_backend_without_evidence_still_works(site):
    """A backend lacking `last_run_evidence` (the existing fakes) must still
    produce an honest no-result error via the last-resort guess."""
    class _Bare:
        def start(self, sd): pass
        def stream(self, p, system_prompt=None):
            yield '{"type":"assistant","message":{"content":[{"type":"text"}]}}'
        def kill(self): pass

    res = run_delegate("example.com", "x", backend=_Bare(),
                       clock=_clock([0, 1, 2]), sites_root=site.parent)
    assert res.status == "error"
    assert "no result" in res.reason
