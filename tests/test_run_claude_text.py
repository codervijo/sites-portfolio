"""Tests for v8.E P4.A.4 — `run_claude_text` Claude-CLI text-capture helper.

Mirrors the subprocess-mocking pattern Tier-2 fixers will use indirectly.
All tests monkeypatch `subprocess.run` so no real `claude` invocation
happens; ditto `claude_available` so tests don't depend on the binary
being on PATH in CI.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from portfolio import fix_helpers


def _fake_completed(stdout: str, *, returncode: int = 0,
                   stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["claude"], returncode=returncode,
        stdout=stdout, stderr=stderr,
    )


def _patch_claude_available(monkeypatch, *, available: bool = True) -> None:
    monkeypatch.setattr(fix_helpers, "claude_available", lambda: available)


def test_run_claude_text_returns_assistant_text_on_success(monkeypatch, tmp_path):
    _patch_claude_available(monkeypatch)
    payload = json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": 4200, "total_cost_usd": 0.04,
        "result": "### verdict\n\nGO\n",
    })
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _fake_completed(payload))

    r = fix_helpers.run_claude_text("hello", cwd=tmp_path)
    assert r.ok
    assert r.text == "### verdict\n\nGO\n"
    assert r.cost_usd == 0.04
    assert r.duration_s == 4.2
    assert r.error is None


def test_run_claude_text_passes_empty_allowed_tools(monkeypatch, tmp_path):
    """No tool use is the load-bearing distinction from `run_claude`.
    A regression here would let the model `Edit` files during a
    research / audit run."""
    _patch_claude_available(monkeypatch)
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return _fake_completed(json.dumps({
            "type": "result", "is_error": False,
            "duration_ms": 100, "total_cost_usd": 0.0,
            "result": "ok",
        }))
    monkeypatch.setattr(subprocess, "run", fake_run)

    fix_helpers.run_claude_text("p", cwd=tmp_path)
    # The argv contains "--allowedTools" followed by an empty string.
    idx = captured["cmd"].index("--allowedTools")
    assert captured["cmd"][idx + 1] == ""


def test_run_claude_text_returns_claude_not_found_when_binary_missing(
    monkeypatch, tmp_path,
):
    _patch_claude_available(monkeypatch, available=False)
    # subprocess.run should never be called in this branch.
    def must_not_call(*a, **k):
        raise AssertionError("subprocess.run invoked despite missing claude")
    monkeypatch.setattr(subprocess, "run", must_not_call)

    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    assert not r.ok
    assert r.text == ""
    assert r.error == "claude-not-found"


def test_run_claude_text_handles_timeout(monkeypatch, tmp_path):
    _patch_claude_available(monkeypatch)

    def raise_timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=k.get("timeout"))
    monkeypatch.setattr(subprocess, "run", raise_timeout)

    r = fix_helpers.run_claude_text("p", cwd=tmp_path, timeout_s=42)
    assert not r.ok
    assert r.error == "timeout"
    assert r.duration_s == 42.0


def test_run_claude_text_handles_oserror(monkeypatch, tmp_path):
    _patch_claude_available(monkeypatch)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: (_ for _ in ()).throw(
                            OSError("permission denied")))
    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    assert not r.ok
    assert r.error is not None
    assert "permission denied" in r.error


def test_run_claude_text_returns_bad_json_when_stdout_not_parseable(
    monkeypatch, tmp_path,
):
    _patch_claude_available(monkeypatch)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _fake_completed("not actually json"))
    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    assert not r.ok
    assert r.error == "bad-json"
    assert r.raw_output.startswith("not actually")


def test_run_claude_text_surfaces_cli_is_error(monkeypatch, tmp_path):
    """The CLI can return `is_error: true` with a `subtype` describing
    the cause (e.g. quota exhaustion). Must surface as ok=False with
    the subtype in `error`, but still carry cost/duration metadata
    for accounting."""
    _patch_claude_available(monkeypatch)
    payload = json.dumps({
        "type": "result", "is_error": True, "subtype": "rate_limited",
        "duration_ms": 800, "total_cost_usd": 0.0,
    })
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _fake_completed(payload))
    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    assert not r.ok
    assert r.error == "rate_limited"
    assert r.duration_s == 0.8


def test_run_claude_text_treats_missing_result_as_failure(monkeypatch, tmp_path):
    """A non-error response with no `result` field is a real surprise —
    surface it rather than returning empty text as 'ok'."""
    _patch_claude_available(monkeypatch)
    payload = json.dumps({
        "type": "result", "is_error": False,
        "duration_ms": 100, "total_cost_usd": 0.01,
        # no "result" field
    })
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _fake_completed(payload))
    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    assert not r.ok
    assert r.error == "empty-result"
    assert r.text == ""


def test_run_claude_text_parses_error_envelope_on_nonzero_exit(monkeypatch, tmp_path):
    """When the CLI exits non-zero BUT still emitted a JSON error
    envelope on stdout, we parse the envelope rather than calling it
    'exit-N'. Matches `run_claude`'s tolerant pattern."""
    _patch_claude_available(monkeypatch)
    payload = json.dumps({
        "type": "result", "is_error": True, "subtype": "auth_failed",
        "duration_ms": 50, "total_cost_usd": 0.0,
    })
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _fake_completed(payload, returncode=1))
    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    # NOT "exit-1" — we got the envelope and used its subtype instead.
    assert r.error == "auth_failed"


def test_run_claude_text_returns_exit_n_when_no_envelope(monkeypatch, tmp_path):
    _patch_claude_available(monkeypatch)
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: _fake_completed(
                            "stderr blob, no json", returncode=2,
                            stderr="boom"))
    r = fix_helpers.run_claude_text("p", cwd=tmp_path)
    assert r.error == "exit-2"
    assert "boom" in r.raw_output


def test_run_claude_text_passes_budget_and_timeout(monkeypatch, tmp_path):
    """Budget and timeout must flow through to subprocess.run — without
    them the CLI could run unbounded on a quota-exhausted account."""
    _patch_claude_available(monkeypatch)
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return _fake_completed(json.dumps({
            "type": "result", "is_error": False,
            "duration_ms": 100, "total_cost_usd": 0.0,
            "result": "ok",
        }))
    monkeypatch.setattr(subprocess, "run", fake_run)

    fix_helpers.run_claude_text("p", cwd=tmp_path,
                                budget_usd=2.50, timeout_s=300)
    assert captured["timeout"] == 300
    idx = captured["cmd"].index("--max-budget-usd")
    assert captured["cmd"][idx + 1] == "2.5"


def test_run_claude_text_runs_in_specified_cwd(monkeypatch, tmp_path):
    _patch_claude_available(monkeypatch)
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        return _fake_completed(json.dumps({
            "type": "result", "is_error": False,
            "duration_ms": 100, "total_cost_usd": 0.0,
            "result": "ok",
        }))
    monkeypatch.setattr(subprocess, "run", fake_run)

    target = tmp_path / "proj"
    target.mkdir()
    fix_helpers.run_claude_text("p", cwd=target)
    assert captured["cwd"] == str(target)
