"""Tests for v33.H — post-run doc trail.

(1) `append_delegate_prompt_log` — orchestrator-owned, deterministic: appends
a dated `## YYYY-MM-DD — delegate` entry to docs/Prompts.md (creating it from
the standard skeleton if absent) that `project check` can parse. (2) the agent
gets a relevance-gated instruction to update prd.md/CLAUDE.md (and to leave
Prompts.md alone) via the system prompt. The CLI wires (1) after a successful
run that changed files.
"""
from __future__ import annotations

from pathlib import Path

import portfolio.cli as climod
import portfolio.delegate as deleg
from portfolio.delegate import (append_delegate_prompt_log,
                                build_delegate_system_prompt)
from typer.testing import CliRunner


# ---------- (1) Prompts.md append ----------


def test_creates_prompts_md_with_skeleton_when_absent(tmp_path: Path):
    ok = append_delegate_prompt_log(tmp_path, "example.com", "Add a copy button",
                                    files=2, cost=0.51, today="2026-06-09")
    assert ok is True
    text = (tmp_path / "docs" / "Prompts.md").read_text()
    assert "# Prompt History — example.com" in text
    assert "## 2026-06-09 — delegate" in text          # parseable dated H2
    assert "> Add a copy button · 2 file(s) · $0.51" in text


def test_appends_to_existing_prompts_md_preserving_content(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "Prompts.md").write_text(
        "# Prompt History — example.com\n\n## 2026-06-02 — scaffolded\n> seed\n")
    append_delegate_prompt_log(tmp_path, "example.com", "Reorder slots",
                               files=1, cost=0.2, today="2026-06-09")
    text = (docs / "Prompts.md").read_text()
    assert "## 2026-06-02 — scaffolded" in text          # old entry preserved
    assert text.index("2026-06-02") < text.index("2026-06-09")  # append at bottom
    assert "> Reorder slots · 1 file(s) · $0.20" in text


def test_log_uses_first_nonempty_request_line(tmp_path: Path):
    append_delegate_prompt_log(tmp_path, "x.com", "\n\nFirst real line\nsecond",
                               files=1, cost=0.1, today="2026-06-09")
    text = (tmp_path / "docs" / "Prompts.md").read_text()
    assert "> First real line ·" in text


# ---------- (2) agent doc-update instruction ----------


def test_system_prompt_has_doc_routing_instruction(tmp_path: Path):
    sysp = build_delegate_system_prompt(tmp_path)
    assert "docs/prd.md" in sysp
    assert "docs/CLAUDE.md" in sysp
    assert "Do not edit docs/Prompts.md" in sysp


# ---------- CLI wiring: log only on done + changed files ----------


def _docker(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda c: "/usr/bin/docker")


def test_cli_logs_prompts_md_on_done_with_changes(monkeypatch, tmp_path):
    _docker(monkeypatch)
    monkeypatch.setattr(deleg, "preflight", lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "do a thing")
    monkeypatch.setattr(
        deleg, "run_delegate",
        lambda d, r, **kw: deleg.DelegateResult(
            status="done", reason="ok", cost_usd=0.3, changed_files=["src/x.tsx"]))

    res = CliRunner().invoke(
        climod.app, ["project", "delegate", "example.com", "--no-verify"])
    assert res.exit_code == 0
    log = tmp_path / "docs" / "Prompts.md"
    assert log.exists() and "delegate" in log.read_text()


def test_cli_skips_log_on_no_change_run(monkeypatch, tmp_path):
    _docker(monkeypatch)
    monkeypatch.setattr(deleg, "preflight", lambda domain, *, force=False, sites_root=None: tmp_path)
    monkeypatch.setattr(climod, "_resolve_delegate_request", lambda r: "inspect only")
    monkeypatch.setattr(
        deleg, "run_delegate",
        lambda d, r, **kw: deleg.DelegateResult(status="done", reason="ok",
                                                changed_files=[]))

    CliRunner().invoke(climod.app, ["project", "delegate", "example.com", "--no-verify"])
    assert not (tmp_path / "docs" / "Prompts.md").exists()   # no changes → no log
