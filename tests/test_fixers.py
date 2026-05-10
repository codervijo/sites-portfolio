"""Tests for v6.C / v6.C.1 — fixer registry (co-located with check modules).

Each Tier 1 fixer is tested for:
  - dry-run produces "would-fix" but writes nothing
  - apply produces "fixed" and the failing CHECK now passes
  - second apply is a no-op ("nothing-to-do") — idempotency contract
"""
from __future__ import annotations

import json

import pytest

from portfolio.checks import run_check
from portfolio.fix_registry import (
    fixable_check_ids,
    get_tier_1 as get_fixer,
    list_tier_1,
    list_tier_2,
)


# Compat shim: tests originally written against `get_registry()` returning
# a dict[check_id → spec]. The new registry exposes `list_tier_1()` for the
# same shape.
def get_registry():
    return list_tier_1()


# ---------- registry shape ----------


def test_every_fixer_has_a_check_id_starting_with_check():
    for cid, spec in get_registry().items():
        assert cid.startswith("CHECK_")
        assert spec.check_id == cid
        assert spec.tier in (1, 2)
        assert spec.summary
        assert callable(spec.apply)


def test_v6c_ships_16_tier1_fixers():
    """v6.C ships 16 Tier 1 fixers; new fixers ship in v6.C.1+."""
    tier_1 = [s for s in get_registry().values() if s.tier == 1]
    assert len(tier_1) == 16


def test_no_tier_2_fixers_yet():
    """Tier 2 (Claude subprocess) is queued for v6.C.1 — none registered yet."""
    tier_2 = [s for s in get_registry().values() if s.tier == 2]
    assert tier_2 == []


def test_fixable_check_ids_exposes_tier_1_only():
    ids = fixable_check_ids()
    # Sanity sample of checks we expect to be fixable.
    for cid in ("CHECK_001", "CHECK_006", "CHECK_009", "CHECK_011",
                "CHECK_026", "CHECK_027", "CHECK_032"):
        assert cid in ids


# ---------- dry-run vs apply for whole-file fixers ----------


def _scaffold_for(check_id: str, tmp_path):
    """Set up just enough scaffolding so the check fails initially."""
    # Most file-existence checks just need a minimal dir.
    return tmp_path


@pytest.mark.parametrize("check_id, rel_path", [
    ("CHECK_001", "README.md"),
    ("CHECK_002", "AI_AGENTS.md"),
    ("CHECK_005", "docs/prd.md"),
    ("CHECK_006", "docs/CLAUDE.md"),
    ("CHECK_007", "docs/Prompts.md"),
    ("CHECK_008", "docs/growth.md"),
    ("CHECK_009", ".gitignore"),
    ("CHECK_011", ".env.example"),
])
def test_file_existence_fixer_dry_run_writes_nothing(check_id, rel_path, tmp_path):
    spec = get_fixer(check_id)
    target = tmp_path / rel_path
    assert not target.exists()
    result = spec.apply(tmp_path, dry_run=True, assume_yes=False)
    assert result.status == "would-fix"
    # Critically: dry-run did NOT actually create the file.
    assert not target.exists()


@pytest.mark.parametrize("check_id, rel_path", [
    ("CHECK_001", "README.md"),
    ("CHECK_002", "AI_AGENTS.md"),
    ("CHECK_005", "docs/prd.md"),
    ("CHECK_006", "docs/CLAUDE.md"),
    ("CHECK_007", "docs/Prompts.md"),
    ("CHECK_008", "docs/growth.md"),
    ("CHECK_009", ".gitignore"),
    ("CHECK_011", ".env.example"),
])
def test_file_existence_fixer_apply_writes_file(check_id, rel_path, tmp_path):
    spec = get_fixer(check_id)
    result = spec.apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert (tmp_path / rel_path).is_file()


@pytest.mark.parametrize("check_id, rel_path", [
    ("CHECK_001", "README.md"),
    ("CHECK_006", "docs/CLAUDE.md"),
    ("CHECK_009", ".gitignore"),
])
def test_file_existence_fixer_makes_check_pass(check_id, rel_path, tmp_path):
    """End-to-end: starting state fails the check; after apply the check passes."""
    assert run_check(check_id, str(tmp_path)).status == "fail"
    get_fixer(check_id).apply(tmp_path, dry_run=False, assume_yes=False)
    assert run_check(check_id, str(tmp_path)).status == "pass"


@pytest.mark.parametrize("check_id", ["CHECK_001", "CHECK_006", "CHECK_009"])
def test_file_existence_fixer_is_idempotent(check_id, tmp_path):
    """Second apply must not change file content (`nothing-to-do`)."""
    spec = get_fixer(check_id)
    spec.apply(tmp_path, dry_run=False, assume_yes=False)
    # Snapshot file state.
    files_before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    second = spec.apply(tmp_path, dry_run=False, assume_yes=False)
    assert second.status == "nothing-to-do"
    files_after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert files_before == files_after


# ---------- section-injection fixers ----------


def test_check_003_appends_building_info_when_missing(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text("# header\n\nno sections yet\n")
    result = get_fixer("CHECK_003").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    text = (tmp_path / "AI_AGENTS.md").read_text()
    assert "## Building info" in text


def test_check_003_idempotent_when_section_already_present(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(
        "# header\n\n## Building info\nalready here\n"
    )
    result = get_fixer("CHECK_003").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "nothing-to-do"


def test_check_003_manual_when_file_missing(tmp_path):
    """If AI_AGENTS.md doesn't exist, CHECK_003 fixer points at CHECK_002."""
    result = get_fixer("CHECK_003").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "manual"


def test_check_026_appends_both_sections_when_missing(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "CLAUDE.md").write_text("# header\n\nplaceholder\n")
    result = get_fixer("CHECK_026").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    text = (docs / "CLAUDE.md").read_text()
    assert "## Project" in text
    assert "## Commands" in text


def test_check_026_appends_only_missing_section(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    # Project is already there; only Commands needs appending.
    (docs / "CLAUDE.md").write_text("## Project\nalready written\n")
    result = get_fixer("CHECK_026").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    text = (docs / "CLAUDE.md").read_text()
    # Project section appears once (not duplicated).
    assert text.count("## Project") == 1
    assert "## Commands" in text


def test_check_027_appends_problem_and_users(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "prd.md").write_text("# PRD\n\noverview\n")
    result = get_fixer("CHECK_027").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    text = (docs / "prd.md").read_text()
    assert "## Problem" in text
    assert "## Users" in text


# ---------- Makefile fixer (special case: skip if exists but doesn't forward) ----------


def test_check_012_writes_when_no_makefile(tmp_path):
    result = get_fixer("CHECK_012").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert (tmp_path / "Makefile").is_file()


def test_check_012_refuses_when_makefile_exists_but_doesnt_forward(tmp_path):
    """If a Makefile is present but doesn't forward, it's a manual review.
    We don't want to overwrite a project's existing Makefile."""
    (tmp_path / "Makefile").write_text("dev:\n\techo hello\n")
    result = get_fixer("CHECK_012").apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "manual"


# ---------- lockfile deletion fixers ----------


@pytest.mark.parametrize("check_id, rel_path", [
    ("CHECK_032", "package-lock.json"),
    ("CHECK_033", "bun.lockb"),
    ("CHECK_034", "yarn.lock"),
])
def test_lockfile_deletion_fixers(check_id, rel_path, tmp_path):
    target = tmp_path / rel_path
    target.write_bytes(b"junk")
    assert target.exists()
    result = get_fixer(check_id).apply(tmp_path, dry_run=False, assume_yes=True)
    assert result.status == "fixed"
    assert not target.exists()


@pytest.mark.parametrize("check_id, rel_path", [
    ("CHECK_032", "package-lock.json"),
    ("CHECK_033", "bun.lockb"),
])
def test_lockfile_deletion_dry_run_keeps_file(check_id, rel_path, tmp_path):
    target = tmp_path / rel_path
    target.write_bytes(b"junk")
    result = get_fixer(check_id).apply(tmp_path, dry_run=True, assume_yes=True)
    assert result.status == "would-fix"
    assert target.exists()


@pytest.mark.parametrize("check_id, rel_path", [
    ("CHECK_032", "package-lock.json"),
    ("CHECK_033", "bun.lockb"),
])
def test_lockfile_deletion_idempotent_when_absent(check_id, rel_path, tmp_path):
    """File already absent → nothing-to-do, not error."""
    result = get_fixer(check_id).apply(tmp_path, dry_run=False, assume_yes=True)
    assert result.status == "nothing-to-do"
