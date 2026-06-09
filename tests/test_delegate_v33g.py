"""Tests for v33.G — site-grounded system prompt + docs map-on-demand.

Covers `docs_listing` (the cheap `docs/` filename map), the split system
prompt (`build_delegate_system_prompt` — guardrails + context + docs map,
NOT the request), `run_delegate` routing the request to the user turn and
the guardrails to `system_prompt`, and `DockerBackend._claude_cmd` wiring
`--append-system-prompt`.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.delegate import (
    DockerBackend,
    build_delegate_system_prompt,
    docs_listing,
    run_delegate,
)


# ---------- docs_listing (the map) ----------


def test_docs_listing_lists_sorted_files(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "prd.md").write_text("x")
    (docs / "CLAUDE.md").write_text("x")
    (docs / "growth.md").write_text("x")
    out = docs_listing(tmp_path)
    assert out == "docs/ contains: CLAUDE.md, growth.md, prd.md"


def test_docs_listing_skips_dotfiles_and_dirs(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "prd.md").write_text("x")
    (docs / ".hidden").write_text("x")
    (docs / "audits").mkdir()           # a subdir, not a file
    assert docs_listing(tmp_path) == "docs/ contains: prd.md"


def test_docs_listing_empty_when_no_docs_dir(tmp_path: Path):
    assert docs_listing(tmp_path) == ""


def test_docs_listing_empty_when_docs_dir_empty(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    assert docs_listing(tmp_path) == ""


# ---------- build_delegate_system_prompt ----------


def test_system_prompt_has_guardrails_but_not_request(tmp_path: Path):
    sysp = build_delegate_system_prompt(tmp_path)
    assert "Do not commit" in sysp
    assert "smallest coherent change" in sysp
    # The request is the separate user turn — never folded into the system.
    assert "=== REQUEST ===" not in sysp


def test_system_prompt_inlines_ai_agents_and_maps_docs(tmp_path: Path):
    (tmp_path / "AI_AGENTS.md").write_text("# Site\nConventions here.\n")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "prd.md").write_text("x")
    (docs / "CLAUDE.md").write_text("x")
    sysp = build_delegate_system_prompt(tmp_path)
    assert "Conventions here." in sysp                      # AI_AGENTS inlined
    assert "docs/ contains: CLAUDE.md, prd.md" in sysp      # docs mapped, not slurped
    assert "read AI_AGENTS.md and any relevant files" in sysp


def test_system_prompt_degrades_without_docs(tmp_path: Path):
    # No docs/ → no listing, no read-docs instruction, no crash.
    sysp = build_delegate_system_prompt(tmp_path)
    assert "docs/ contains:" not in sysp
    assert "Do not commit" in sysp                          # guardrails still there


# ---------- run_delegate routes request vs system prompt ----------


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "sites"
    d = root / "example.com"
    d.mkdir(parents=True)
    _git(["init"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "AI_AGENTS.md").write_text("# Example\nBe terse.\n")
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)
    return d


class _RecordingBackend:
    def __init__(self):
        self.prompt = None
        self.system_prompt = None

    def start(self, site_dir):
        pass

    def stream(self, prompt, system_prompt=None):
        self.prompt = prompt
        self.system_prompt = system_prompt
        yield '{"type":"result","is_error":false,"total_cost_usd":0.01}'

    def kill(self):
        pass


def test_run_delegate_splits_request_and_system(site):
    be = _RecordingBackend()
    run_delegate("example.com", "  add a dark mode toggle  ", backend=be,
                 sites_root=site.parent)
    # request → user turn (stripped); guardrails → system prompt.
    assert be.prompt == "add a dark mode toggle"
    assert "Do not commit" in be.system_prompt
    assert "Be terse." in be.system_prompt          # site's AI_AGENTS grounded in


# ---------- DockerBackend._claude_cmd wires --append-system-prompt ----------


def test_claude_cmd_appends_system_prompt():
    be = DockerBackend("example.com", docker_cmd=["docker"])
    cmd = be._claude_cmd("do x", "SYSTEM GUARDRAILS")
    assert "--append-system-prompt" in cmd
    assert cmd[cmd.index("--append-system-prompt") + 1] == "SYSTEM GUARDRAILS"
    # request still rides on -p
    assert cmd[cmd.index("-p") + 1] == "do x"


def test_claude_cmd_omits_system_prompt_when_absent():
    be = DockerBackend("example.com", docker_cmd=["docker"])
    assert "--append-system-prompt" not in be._claude_cmd("do x", None)
    assert "--append-system-prompt" not in be._claude_cmd("do x", "")
