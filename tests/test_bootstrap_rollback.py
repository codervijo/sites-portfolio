"""Tests for v15.K — transactional rollback + translation budget.

Verifies that mid-flight bootstrap failures clean up the project dir
so the operator can re-run from clean state. Also covers the
v15.K budget passthrough.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio.bootstrap import BootstrapError, bootstrap
from portfolio.fix_helpers import ClaudeResult
from portfolio.stack_translate import StackTranslationError


def _make_lovable_tanstack_genai(genai_dir: Path) -> None:
    """Set up a fake TanStack-style genai dir that triggers the v15.H
    translation path."""
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


# ---- rollback on translation failure ----


def _fake_git_clone_populates_tanstack(genai_target: Path) -> None:
    """Helper used by mocked git-clone calls — populates the target
    with a TanStack-style genai fixture."""
    _make_lovable_tanstack_genai(genai_target)


def _patch_clone_succeeds(monkeypatch):
    """Patch `_clone_to_genai` to skip the real `git clone` and just
    populate the target with a TanStack fixture (so v15.H translation
    fires)."""
    def fake_clone(project_dir, git_url):
        target = project_dir / "genai"
        _fake_git_clone_populates_tanstack(target)

    monkeypatch.setattr(
        "portfolio.bootstrap._clone_to_genai", fake_clone
    )


def test_rollback_when_claude_subprocess_fails(tmp_path, monkeypatch):
    """git_url path — bootstrap creates project_dir, clones (mocked),
    detects TanStack, translation fails with budget-exceeded →
    v15.K rollback removes project_dir entirely."""
    domain = "agesdk.dev"
    project_dir = tmp_path / domain

    _patch_clone_succeeds(monkeypatch)

    # Force translation to fail with budget-exceeded.
    monkeypatch.setattr(
        "portfolio.stack_translate.claude_available", lambda: True
    )
    monkeypatch.setattr(
        "portfolio.stack_translate.run_claude",
        lambda *a, **kw: ClaudeResult(
            ok=False, cost_usd=0.524, duration_s=66.0,
            error="error_max_budget_usd", raw_output="budget exceeded",
        ),
    )

    with pytest.raises(StackTranslationError, match="error_max_budget_usd"):
        bootstrap(
            domain,
            git_url="https://github.com/test/lovable-fixture.git",
            sites_root=tmp_path,
            translate_now=True,  # v15.M — exercise synchronous translation
        )

    # Project dir should be cleaned up.
    assert not project_dir.exists(), \
        f"v15.K rollback failed — {project_dir} still present after failure"


def test_rollback_when_translator_output_fails_validation(tmp_path, monkeypatch):
    """Claude succeeds (subprocess ok) but emits broken Astro shape —
    validator rejects → StackTranslationError raised → rollback fires."""
    domain = "agesdk.dev"

    _patch_clone_succeeds(monkeypatch)
    monkeypatch.setattr(
        "portfolio.stack_translate.claude_available", lambda: True
    )

    # Claude "succeeded" but didn't write any Astro shape; validator
    # rejects (no package.json, no astro.config, no src/pages/).
    monkeypatch.setattr(
        "portfolio.stack_translate.run_claude",
        lambda *a, **kw: ClaudeResult(
            ok=True, cost_usd=0.50, duration_s=30.0,
            error=None, raw_output="",
        ),
    )

    with pytest.raises(StackTranslationError, match="failed validation"):
        bootstrap(
            domain,
            git_url="https://github.com/test/lovable-fixture.git",
            sites_root=tmp_path,
            translate_now=True,
        )

    assert not (tmp_path / domain).exists()


def test_rollback_does_not_remove_pre_existing_project_dir(tmp_path):
    """When bootstrap refuses a pre-existing project_dir at pre-flight
    (the operator's typo-or-stale-state case), rollback does NOT fire
    — that would delete the operator's existing work."""
    project_dir = tmp_path / "preexisting.com"
    project_dir.mkdir()
    (project_dir / "important.txt").write_text("don't delete me")

    # The git_url path checks `project_dir.exists()` BEFORE any mkdir,
    # so the BootstrapError fires while `_we_created_dir` is False.
    with pytest.raises(BootstrapError, match="already exists"):
        bootstrap(
            "preexisting.com",
            git_url="https://github.com/x/y.git",
            sites_root=tmp_path,
        )

    assert project_dir.exists()
    assert (project_dir / "important.txt").exists()


def test_rollback_when_template_path_fails(tmp_path, monkeypatch):
    """The template (non-genai) path also creates project_dir; rollback
    should still fire if any step after mkdir fails."""
    # Force the template path to fail by passing an unsupported stack.
    with pytest.raises(BootstrapError, match="unsupported --stack"):
        bootstrap(
            "newsite.com", stack="bogus-stack", sites_root=tmp_path,
        )
    # Project dir should not survive the failure.
    assert not (tmp_path / "newsite.com").exists()


def test_rollback_permission_error_warns_instead_of_crashing(
    tmp_path, monkeypatch
):
    """Docker-owned files inside the project dir (e.g.
    `genai/node_modules/`) raise PermissionError on `rmtree`. v15.K
    handles via ignore_errors fallback — doesn't propagate."""
    domain = "stuck.com"

    _patch_clone_succeeds(monkeypatch)
    monkeypatch.setattr(
        "portfolio.stack_translate.claude_available", lambda: True
    )
    monkeypatch.setattr(
        "portfolio.stack_translate.run_claude",
        lambda *a, **kw: ClaudeResult(
            ok=False, cost_usd=0.0, duration_s=0.0,
            error="any-failure", raw_output="",
        ),
    )

    # Patch shutil.rmtree (via the local-import in _rollback_project_dir)
    # to raise PermissionError on first call, succeed on the
    # ignore_errors fallback.
    call_count = {"n": 0}
    original_rmtree = shutil.rmtree

    def fake_rmtree(path, ignore_errors=False, **kw):
        call_count["n"] += 1
        if not ignore_errors:
            raise PermissionError("docker-owned files")
        return original_rmtree(path, ignore_errors=True)

    monkeypatch.setattr("shutil.rmtree", fake_rmtree)

    # Bootstrap should raise StackTranslationError, NOT
    # PermissionError. The rollback's PermissionError gets caught.
    with pytest.raises(StackTranslationError):
        bootstrap(
            domain,
            git_url="https://github.com/test/x.git",
            sites_root=tmp_path,
            translate_now=True,
        )

    # The first rmtree attempt failed; the ignore_errors fallback ran.
    assert call_count["n"] >= 1


# ---- budget passthrough ----


def test_translation_budget_passthrough(tmp_path, monkeypatch):
    """The `translation_budget_usd` parameter on `bootstrap()` flows
    into `translate_to_astro()`'s `budget_usd` kwarg."""
    domain = "budget.com"

    _patch_clone_succeeds(monkeypatch)

    captured = {}

    def fake_translate(project_dir, *, detection, budget_usd=None, **kw):
        captured["budget_usd"] = budget_usd
        return ClaudeResult(
            ok=False, cost_usd=0.0, duration_s=0.0,
            error="forced-fail", raw_output="",
        )

    # The import inside bootstrap.py uses
    # `from .stack_translate import translate_to_astro`. The actual
    # imported name inside the inner function is local to that
    # function, so patch the source.
    monkeypatch.setattr(
        "portfolio.stack_translate.translate_to_astro",
        fake_translate,
    )

    with pytest.raises(StackTranslationError):
        bootstrap(
            domain,
            git_url="https://github.com/test/x.git",
            sites_root=tmp_path,
            translation_budget_usd=5.50,
            translate_now=True,
        )

    assert captured.get("budget_usd") == 5.50


def test_translation_budget_default_when_none_passed(tmp_path, monkeypatch):
    """When `translation_budget_usd=None`, `translate_to_astro` is
    called without `budget_usd` kwarg — module default ($2.00 post-
    v15.K) applies."""
    domain = "default-budget.com"

    _patch_clone_succeeds(monkeypatch)

    captured = {}

    def fake_translate(project_dir, *, detection, **kw):
        captured["budget_usd_kwarg_present"] = "budget_usd" in kw
        return ClaudeResult(
            ok=False, cost_usd=0.0, duration_s=0.0,
            error="forced-fail", raw_output="",
        )

    monkeypatch.setattr(
        "portfolio.stack_translate.translate_to_astro",
        fake_translate,
    )

    with pytest.raises(StackTranslationError):
        bootstrap(
            domain,
            git_url="https://github.com/test/x.git",
            sites_root=tmp_path,
            translation_budget_usd=None,
            translate_now=True,
        )

    assert captured.get("budget_usd_kwarg_present") is False


def test_stack_translate_default_budget_is_2_usd():
    """v15.K bumped the default from $0.50 to $2.00."""
    from portfolio.stack_translate import _DEFAULT_BUDGET_USD
    assert _DEFAULT_BUDGET_USD == 2.00
