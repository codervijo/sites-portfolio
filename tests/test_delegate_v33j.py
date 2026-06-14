"""Tests for v33.J — dropped the pre-run confirmation gate.

delegate's safety is the uncommitted reviewable diff + the sandbox/verify
gate (ADR-0023), not a prompt — so `project delegate` runs without a
`Proceed?` confirmation. `--yes` is kept as an accepted no-op.
"""
from __future__ import annotations

import portfolio.cli as climod
import portfolio.delegate as deleg
from typer.testing import CliRunner


def _docker_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker")


def test_no_confirm_prompt_runs_directly(monkeypatch, tmp_path):
    _docker_present(monkeypatch)
    monkeypatch.setattr(deleg, "preflight", lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "do x")
    seen = {}

    def fake_run(domain, request, **kw):
        seen["request"] = request
        return deleg.DelegateResult(status="done", reason="ok")
    monkeypatch.setattr(deleg, "run_delegate", fake_run)

    result = CliRunner().invoke(
        climod.app, ["project", "delegate", "example.com", "--no-verify"])
    assert result.exit_code == 0
    assert "Proceed?" not in result.output      # no confirmation prompt
    assert seen["request"] == "do x"            # proceeded straight to the run


def test_yes_flag_still_parses_as_noop(monkeypatch, tmp_path):
    _docker_present(monkeypatch)
    monkeypatch.setattr(deleg, "preflight", lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "do x")
    monkeypatch.setattr(
        deleg, "run_delegate",
        lambda domain, request, **kw: deleg.DelegateResult(status="done", reason="ok"))

    # --yes is accepted (compat no-op), doesn't error.
    result = CliRunner().invoke(
        climod.app, ["project", "delegate", "example.com", "--no-verify", "--yes"])
    assert result.exit_code == 0


def test_confirm_helper_removed():
    # The v33.F /dev/tty confirm helper is gone (no dead code).
    assert not hasattr(climod, "_delegate_confirm")
