"""Tests for v33.I — delegate dirty-tree friction removal.

(1) `project delegate` runs the preflight (resolve + clean-tree) BEFORE
collecting the request, so a dirty tree refuses instantly instead of after
the operator pastes a whole prompt. (2) `new bootstrap`'s .gitignore now
ignores `.astro/` so generated cache never accumulates and trips the
dirty-tree precondition fleet-wide.
"""
from __future__ import annotations

import portfolio.cli as climod
import portfolio.delegate as deleg
from portfolio.bootstrap import _gitignore
from typer.testing import CliRunner


# ---------- (2) bootstrap gitignores .astro ----------


def test_bootstrap_gitignore_ignores_astro():
    gi = _gitignore()
    assert ".astro/" in gi
    # sanity: still covers the long-standing entries
    assert "node_modules/" in gi
    assert "dist/" in gi


# ---------- (1) preflight runs before request collection ----------


def _docker_present(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker")


def test_dirty_tree_refuses_before_reading_request(monkeypatch):
    _docker_present(monkeypatch)
    read_called = []
    monkeypatch.setattr(
        climod, "_resolve_delegate_request",
        lambda r: (read_called.append(1), "should-not-be-used")[1])

    def refuse(domain, *, force=False):
        raise deleg.DelegateRefused("✗ Won't delegate — dirty tree")
    monkeypatch.setattr(deleg, "preflight", refuse)

    result = CliRunner().invoke(climod.app, ["project", "delegate", "example.com"])
    assert result.exit_code == 1
    assert "Won't delegate" in result.output
    assert read_called == []          # request was NEVER collected — no wasted paste


def test_preflight_runs_before_request_then_empty_aborts(monkeypatch, tmp_path):
    _docker_present(monkeypatch)
    order = []
    monkeypatch.setattr(
        deleg, "preflight",
        lambda domain, *, force=False: (order.append("preflight"), tmp_path)[1])
    monkeypatch.setattr(
        climod, "_resolve_delegate_request",
        lambda r: (order.append("resolve"), "")[1])   # empty → caller aborts

    result = CliRunner().invoke(climod.app, ["project", "delegate", "example.com"])
    assert result.exit_code == 0
    assert "no request, aborting" in result.output
    assert order == ["preflight", "resolve"]   # preflight strictly before request
