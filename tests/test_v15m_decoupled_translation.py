"""Tests for v15.M — decoupled translation.

Verifies:
  - Bootstrap with `--git-url` non-Astro DEFERS translation by
    default (writes blank Astro scaffold + `genai/` + marker file).
  - `lamill project translate` reads the marker + calls
    `port_to_astro` + commits on success.
  - `--translate-now` flag on bootstrap preserves the v15.H
    synchronous behavior (exercised separately in
    test_bootstrap_rollback.py).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from portfolio.bootstrap import bootstrap
from portfolio.fix_helpers import ClaudeResult


def _make_lovable_tanstack_genai(genai_dir: Path) -> None:
    """Set up a TanStack-style genai dir that triggers v15.H/M
    detection."""
    genai_dir.mkdir(parents=True, exist_ok=True)
    pkg = {
        "name": "lovable-tanstack",
        "type": "module",
        "scripts": {"dev": "vite dev", "build": "vite build"},
        "dependencies": {
            "@tanstack/react-start": "^0.1.0",
            "@tanstack/react-router": "^1.0.0",
            "react": "^19.0.0",
        },
        "devDependencies": {"vite": "^7.0.0", "@cloudflare/vite-plugin": "^1.0.0"},
    }
    (genai_dir / "package.json").write_text(json.dumps(pkg))
    (genai_dir / "src").mkdir()
    (genai_dir / "src" / "server.ts").write_text("export default {}")


def _patch_clone_succeeds(monkeypatch):
    """Patch `_clone_to_genai` to populate genai/ instead of `git clone`."""
    def fake_clone(project_dir, git_url):
        target = project_dir / "genai"
        _make_lovable_tanstack_genai(target)

    monkeypatch.setattr(
        "portfolio.bootstrap._clone_to_genai", fake_clone
    )


# ---- v15.M deferred-translation path ----


def test_bootstrap_defers_translation_when_translate_now_false(tmp_path, monkeypatch):
    """v15.M default — bootstrap with --git-url + non-Astro produces
    a blank Astro scaffold + the original genai/ + a marker file.
    Does NOT call translate_to_astro."""
    _patch_clone_succeeds(monkeypatch)

    translate_calls = {"n": 0}

    def should_not_be_called(*a, **kw):
        translate_calls["n"] += 1
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=0.0,
                            error="shouldnt-fire", raw_output="")

    monkeypatch.setattr(
        "portfolio.stack_translate.translate_to_astro",
        should_not_be_called,
    )

    result = bootstrap(
        "agesdk.dev",
        git_url="https://github.com/test/x.git",
        sites_root=tmp_path,
        translate_now=False,  # explicit default
    )

    project_dir = tmp_path / "agesdk.dev"
    assert project_dir.is_dir()
    # genai/ preserved as untranslated source
    assert (project_dir / "genai" / "package.json").exists()
    # Astro scaffold written at root
    assert (project_dir / "package.json").exists()
    pkg = json.loads((project_dir / "package.json").read_text())
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert "astro" in deps
    # Marker file present
    marker = project_dir / ".lamill-translation-pending"
    assert marker.exists()
    marker_data = json.loads(marker.read_text())
    assert marker_data["source_stack"] == "tanstack-start"
    assert any("tanstack" in s for s in marker_data["source_signals"])
    # translate_to_astro NEVER called
    assert translate_calls["n"] == 0
    # Stack is reported as astro (translation deferred, but scaffold IS Astro)
    assert result.stack == "astro"


def test_bootstrap_translate_now_true_invokes_synchronous_translation(
    tmp_path, monkeypatch,
):
    """v15.H compat — --translate-now flag still triggers synchronous
    translation. Failure mode exercised in test_bootstrap_rollback.py;
    this verifies the call path."""
    _patch_clone_succeeds(monkeypatch)

    translate_calls = {"n": 0}

    def fake_translate(project_dir, *, detection, **kw):
        translate_calls["n"] += 1
        # Return failure so we bail out without needing real Astro output
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=0.0,
                            error="test-bail", raw_output="")

    monkeypatch.setattr(
        "portfolio.stack_translate.translate_to_astro",
        fake_translate,
    )

    from portfolio.stack_translate import StackTranslationError
    with pytest.raises(StackTranslationError):
        bootstrap(
            "synchronous.com",
            git_url="https://github.com/test/x.git",
            sites_root=tmp_path,
            translate_now=True,
        )

    # translate_to_astro WAS called
    assert translate_calls["n"] == 1


def test_bootstrap_astro_source_still_direct_copies(tmp_path, monkeypatch):
    """Astro sources bypass translation entirely (no marker file)."""
    def fake_clone(project_dir, git_url):
        target = project_dir / "genai"
        target.mkdir(parents=True, exist_ok=True)
        (target / "package.json").write_text(json.dumps({
            "name": "astro-source",
            "dependencies": {"astro": "^5.0.0"},
        }))
        (target / "astro.config.mjs").write_text("export default {}")
        # Mimic an Astro layout
        (target / "src" / "pages").mkdir(parents=True)
        (target / "src" / "pages" / "index.astro").write_text("---\n---\nhi")

    monkeypatch.setattr(
        "portfolio.bootstrap._clone_to_genai", fake_clone
    )

    result = bootstrap(
        "astro-source.com",
        git_url="https://github.com/test/x.git",
        sites_root=tmp_path,
        translate_now=False,
    )

    project_dir = tmp_path / "astro-source.com"
    assert project_dir.is_dir()
    # NO marker for Astro source
    assert not (project_dir / ".lamill-translation-pending").exists()


# ---- project translate verb ----


def _setup_translation_pending_project(sites_root, domain, monkeypatch):
    """Build a project dir in the v15.M deferred state: Astro scaffold +
    genai/ + .lamill-translation-pending marker."""
    _patch_clone_succeeds(monkeypatch)
    bootstrap(
        domain,
        git_url="https://github.com/test/x.git",
        sites_root=sites_root,
        translate_now=False,
    )


def _patch_data_root(monkeypatch, tmp_path):
    """Point portfolio.data.ROOT at a fake repo dir so DATA_ROOT.parent
    becomes our tmp 'sites' root."""
    fake_repo = tmp_path / "portfolio"
    fake_repo.mkdir(exist_ok=True)
    import portfolio.data as data_mod
    monkeypatch.setattr(data_mod, "ROOT", fake_repo)
    return tmp_path


def test_project_translate_no_project_dir_exits_1(tmp_path, monkeypatch):
    _patch_data_root(monkeypatch, tmp_path)
    from portfolio.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["project", "translate", "missing.com"])
    assert r.exit_code == 1
    assert "Project dir not found" in r.output


def test_project_translate_no_genai_subdir_exits_2(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    # Make a project dir without genai/
    (sites_root / "blank.com").mkdir()
    from portfolio.cli import app

    runner = CliRunner()
    r = runner.invoke(app, ["project", "translate", "blank.com"])
    assert r.exit_code == 2
    assert "No genai/ subdir" in r.output


def test_project_translate_no_marker_exits_unless_force(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "no-marker.com"
    project.mkdir()
    (project / "genai").mkdir()
    (project / "genai" / "package.json").write_text("{}")
    # No .lamill-translation-pending marker

    from portfolio.cli import app
    runner = CliRunner()
    r = runner.invoke(app, ["project", "translate", "no-marker.com"])
    assert r.exit_code == 2
    assert "No translation-pending marker" in r.output


def test_project_translate_happy_path_calls_port(tmp_path, monkeypatch):
    """Project in deferred state → project translate → port_to_astro
    fires → validator passes → git commits."""
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    _setup_translation_pending_project(sites_root, "ok.com", monkeypatch)

    project_dir = sites_root / "ok.com"
    assert (project_dir / ".lamill-translation-pending").exists()

    port_calls = {"n": 0, "kwargs": None}

    def fake_port(project_dir, *, source_stack, source_signals,
                  budget_usd, timeout_s):
        port_calls["n"] += 1
        port_calls["kwargs"] = {
            "source_stack": source_stack,
            "budget_usd": budget_usd,
            "timeout_s": timeout_s,
        }
        return ClaudeResult(ok=True, cost_usd=0.42, duration_s=120.0,
                            error=None, raw_output="")

    monkeypatch.setattr("portfolio.stack_translate.port_to_astro", fake_port)
    # Stub git commit too — don't actually run git in the test env.
    import subprocess
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    from portfolio.cli import app
    runner = CliRunner()
    r = runner.invoke(app, [
        "project", "translate", "ok.com",
        "--budget", "3.5", "--timeout", "600",
    ])

    assert r.exit_code == 0
    assert port_calls["n"] == 1
    assert port_calls["kwargs"]["source_stack"] == "tanstack-start"
    assert port_calls["kwargs"]["budget_usd"] == 3.5
    assert port_calls["kwargs"]["timeout_s"] == 600
    # Marker consumed after success
    assert not (project_dir / ".lamill-translation-pending").exists()


def test_project_translate_port_failure_keeps_marker(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    _setup_translation_pending_project(sites_root, "fail.com", monkeypatch)

    monkeypatch.setattr(
        "portfolio.stack_translate.port_to_astro",
        lambda *a, **kw: ClaudeResult(
            ok=False, cost_usd=0.0, duration_s=0.0,
            error="timeout", raw_output="",
        ),
    )

    from portfolio.cli import app
    runner = CliRunner()
    r = runner.invoke(app, ["project", "translate", "fail.com"])
    assert r.exit_code == 3
    assert "Port failed" in r.output
    # Marker preserved for retry
    project_dir = sites_root / "fail.com"
    assert (project_dir / ".lamill-translation-pending").exists()


def test_project_translate_validator_failure_keeps_marker(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    _setup_translation_pending_project(sites_root, "validfail.com", monkeypatch)

    # Port "succeeds" but writes garbage at root → validator rejects.
    project_dir = sites_root / "validfail.com"

    def claude_succeeds_garbage(*a, **kw):
        # Wipe the package.json that bootstrap wrote — validator
        # checks for it.
        (project_dir / "package.json").unlink(missing_ok=True)
        return ClaudeResult(ok=True, cost_usd=0.42, duration_s=120.0,
                            error=None, raw_output="")

    monkeypatch.setattr(
        "portfolio.stack_translate.port_to_astro",
        claude_succeeds_garbage,
    )

    from portfolio.cli import app
    runner = CliRunner()
    r = runner.invoke(app, ["project", "translate", "validfail.com"])
    assert r.exit_code == 4
    assert "Port output failed validation" in r.output
    # Marker preserved for retry
    assert (project_dir / ".lamill-translation-pending").exists()
