"""v5.E — `portfolio project status <name>` is now driven by the catalog.

Verifies the conformance section's rule names migrated from legacy
short names ("own-git-repo", "has-prompts-md", ...) to CHECK_* IDs,
while keeping `has-category` and `live-site` as ad-hoc rules (no
catalog equivalent).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from portfolio import project as project_module


def _git_init(path: Path) -> None:
    """Bare-bones repo so CHECK_020 (own-git-repo) and friends pass."""
    import os
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "t@e.com"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env)
    (path / "README.md").write_text("# repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "initial"],
                   cwd=path, check=True, env=env)


def _mk_project(tmp_path: Path, domain: str = "example.com") -> Path:
    """Build a minimal sites/<domain>/ scaffold that passes a few catalog
    checks and fails others."""
    sites = tmp_path / "sites"
    sites.mkdir()
    project = sites / domain
    project.mkdir()
    _git_init(project)
    (project / "AI_AGENTS.md").write_text(
        "## Building info\nsee parent\n## Deployment info\ncf pages\n"
    )
    (project / "package.json").write_text(json.dumps({
        "name": "x", "scripts": {"build": "vite build", "dev": "vite"},
    }))
    (project / "pnpm-lock.yaml").write_text("lockfileVersion: 9")
    (project / ".gitignore").write_text("node_modules/\ndist/\n")
    return project


def _patch_paths(monkeypatch, tmp_path: Path, domain: str,
                 plan_category: str = "My brand") -> None:
    """Point project_module at the temp sites dir + a stub plan."""
    monkeypatch.setattr(project_module, "SITES_ROOT", tmp_path / "sites")
    monkeypatch.setattr(project_module, "load_plan",
                        lambda: {domain: plan_category})


def test_build_status_uses_catalog_rule_names(tmp_path, monkeypatch):
    domain = "example.com"
    _mk_project(tmp_path, domain)
    _patch_paths(monkeypatch, tmp_path, domain)

    result = project_module.build_status(domain)
    conf = result["conformance"]

    # Every passed catalog rule should be a CHECK_xxx ID (4-digit numeric
    # tail). Two ad-hoc rules — has-category, live-site — are exempt.
    legacy_allowed = {"has-category", "live-site"}
    for rule in conf["passed"]:
        assert (
            rule.startswith("CHECK_") or rule in legacy_allowed
        ), f"unexpected legacy rule name in passed: {rule!r}"
    # And the catalog rules we definitely expect to pass.
    for cid in ("CHECK_001", "CHECK_002", "CHECK_009", "CHECK_020",
                "CHECK_030", "CHECK_031"):
        assert cid in conf["passed"], f"expected {cid} in passed"


def test_build_status_failed_entries_carry_check_name(tmp_path, monkeypatch):
    """Failed conformance entries should include the catalog `name` field
    so the renderer can show e.g. `CHECK_006 has-docs-claude — ...`."""
    domain = "example.com"
    _mk_project(tmp_path, domain)
    _patch_paths(monkeypatch, tmp_path, domain)

    result = project_module.build_status(domain)
    fails = result["conformance"]["failed"]
    # No docs/CLAUDE.md was created → CHECK_006 fails.
    check_006 = next((f for f in fails if f["rule"] == "CHECK_006"), None)
    assert check_006 is not None
    assert check_006["name"] == "has-docs-claude"
    assert "missing" in check_006["reason"].lower()


def test_build_status_keeps_has_category_and_live_site(tmp_path, monkeypatch):
    """Ad-hoc rules without catalog equivalents must still appear."""
    domain = "example.com"
    _mk_project(tmp_path, domain)
    _patch_paths(monkeypatch, tmp_path, domain, plan_category="My brand")

    result = project_module.build_status(domain)
    all_rules = (
        list(result["conformance"]["passed"])
        + [f["rule"] for f in result["conformance"]["failed"]]
        + [s["rule"] for s in result["conformance"]["skipped"]]
    )
    assert "has-category" in all_rules
    assert "live-site" in all_rules


def test_build_status_no_dir_skips_everything_with_synthetic_marker(
    tmp_path, monkeypatch
):
    """When sites/<domain>/ doesn't exist, we don't run catalog checks
    against a missing path — instead we emit `project-dir-missing` as a
    skip so the renderer's `(missing)` header is the canonical signal."""
    monkeypatch.setattr(project_module, "SITES_ROOT", tmp_path / "sites")
    monkeypatch.setattr(project_module, "load_plan",
                        lambda: {"vanished.com": "My brand"})

    result = project_module.build_status("vanished.com")
    skipped_rules = [s["rule"] for s in result["conformance"]["skipped"]]
    assert "project-dir-missing" in skipped_rules
    # And no CHECK_* rules ran.
    assert not any(
        r.startswith("CHECK_") for r in result["conformance"]["passed"]
    )