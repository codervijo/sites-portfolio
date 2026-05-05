"""Tests for src/portfolio/bootstrap.py — domain validation, template path,
genai-copy path, CF safety fixes, ingester, and git init wiring.

All file ops use tmp_path fixtures. Real `git init` is run on the temp dirs
(cheap, no remotes). No real network — `--git-url` path is exercised by
patching subprocess.run."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio import bootstrap as bs
from portfolio.bootstrap import (
    BootstrapError,
    _add_cf_headers,
    _add_wrangler_jsonc,
    _bump_vite_version,
    _ensure_pnpm_only,
    _project_name,
    _remove_legacy_wrangler_toml,
    _remove_redirects_files,
    bootstrap,
    detect_stack_from_pkg,
    validate_domain,
)


# ---------- domain validation ----------


@pytest.mark.parametrize("good", [
    "kwizicle.com",
    "iotbastion.com",
    "lamill.io",
    "co-vibe.dev",
    "abc.def.ghi",
])
def test_validate_domain_accepts_valid(good):
    assert validate_domain(good) == good.lower()


@pytest.mark.parametrize("bad", [
    "",
    " ",
    "no_dots",
    "spaces in.com",
    "trailing-.com",
    "-leading.com",
    "double..dot.com",
    "weird*chars.com",
])
def test_validate_domain_rejects_invalid(bad):
    with pytest.raises(BootstrapError):
        validate_domain(bad)


def test_validate_domain_lowercases():
    assert validate_domain("KwIziCLE.COM") == "kwizicle.com"


# ---------- template path ----------


def test_template_path_creates_dir_with_astro_default(tmp_path):
    result = bootstrap("flow.dev", sites_root=tmp_path)
    assert result.path == "template"
    assert result.stack == "astro"
    project = tmp_path / "flow.dev"
    assert project.is_dir()
    assert (project / "package.json").exists()
    assert (project / "astro.config.mjs").exists()
    assert (project / "src" / "pages" / "index.astro").exists()


def test_template_path_writes_vite_when_chosen(tmp_path):
    result = bootstrap("flow.dev", stack="vite", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    assert result.stack == "vite"
    assert (project / "vite.config.js").exists()
    assert (project / "index.html").exists()
    assert (project / "src" / "main.jsx").exists()
    assert (project / "src" / "App.jsx").exists()


def test_template_path_writes_common_files(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    for rel in ("AI_AGENTS.md", "README.md", ".gitignore", "Makefile",
                "docs/prd.md", "docs/Prompts.md"):
        assert (project / rel).exists(), f"missing {rel}"


def test_template_path_ai_agents_has_required_sections(tmp_path):
    bootstrap("flow.dev", topic="cool idea", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "AI_AGENTS.md").read_text()
    # Reformatted to match the homeloom + voltloop convention:
    # Build tooling section + Deployment section.
    assert "## Build tooling — Makefile + Docker" in text
    assert "## Deployment" in text
    assert "wrangler.jsonc" in text
    assert "public/_headers" in text
    assert "cool idea" in text  # topic injected


def test_template_path_makefile_forwards_to_parent_with_proj(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "Makefile").read_text()
    assert "PROJ := flow.dev" in text
    assert "$(MAKE) -C .." in text
    assert "proj=$(PROJ)" in text


def test_template_path_makefile_errors_without_parent(tmp_path):
    """Generated Makefile should refuse to run if ../Makefile is missing."""
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "Makefile").read_text()
    assert "wildcard ../Makefile" in text
    assert "$(error" in text


def test_template_path_refuses_existing_dir(tmp_path):
    (tmp_path / "exists.com").mkdir()
    with pytest.raises(BootstrapError, match="already exists"):
        bootstrap("exists.com", sites_root=tmp_path)


def test_template_path_unsupported_stack_errors(tmp_path):
    with pytest.raises(BootstrapError, match="unsupported"):
        bootstrap("flow.dev", stack="rails", sites_root=tmp_path)


def test_template_path_with_ingester(tmp_path):
    bootstrap("flow.dev", with_ingester=True, sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    assert (project / "scripts" / "ingest.py").exists()
    assert (project / "scripts" / "README.md").exists()


def test_template_path_git_initialized(tmp_path):
    result = bootstrap("flow.dev", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    assert result.git_initialized is True
    assert result.initial_commit_sha is not None
    assert (project / ".git").is_dir()


# ---------- from-genai path ----------


def _make_fake_lovable_export(genai_dir: Path, vite_version: str = "^4.5.0", with_redirects: bool = True):
    """Populate genai_dir with a minimal fake Lovable-style Vite/React export."""
    genai_dir.mkdir(parents=True, exist_ok=True)
    pkg = {
        "name": "lovable-export",
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"},
        "dependencies": {"react": "^18.3.0", "react-dom": "^18.3.0"},
        "devDependencies": {"vite": vite_version, "@vitejs/plugin-react": "^4.3.0"},
    }
    (genai_dir / "package.json").write_text(json.dumps(pkg, indent=2))
    (genai_dir / "vite.config.js").write_text("// vite config")
    (genai_dir / "index.html").write_text("<html></html>")
    src = genai_dir / "src"
    src.mkdir()
    (src / "App.jsx").write_text("export default () => <div/>;")
    if with_redirects:
        public = genai_dir / "public"
        public.mkdir()
        (public / "_redirects").write_text("/* /index.html 200")


def test_from_genai_copies_files_up(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", vite_version="^6.0.0", with_redirects=False)

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert result.path == "genai"
    assert (project / "package.json").exists()
    assert (project / "vite.config.js").exists()
    assert (project / "src" / "App.jsx").exists()
    assert (project / "genai").exists(), "genai/ should be left intact for the user to inspect"


def test_from_genai_detects_vite_stack_from_package_json(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai")

    result = bootstrap("kwizicle.com", from_genai=True, stack="astro", sites_root=tmp_path)
    # Should auto-detect to vite from the genai package.json — overrides --stack=astro
    assert result.stack == "vite"


def test_from_genai_bumps_old_vite(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", vite_version="^4.5.0")

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    pkg = json.loads((project / "package.json").read_text())
    assert pkg["devDependencies"]["vite"] == "^6.0.0"
    assert any("bumped vite" in fix for fix in result.cf_fixes)


def test_from_genai_leaves_modern_vite_alone(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", vite_version="^6.5.0", with_redirects=False)

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    pkg = json.loads((project / "package.json").read_text())
    assert pkg["devDependencies"]["vite"] == "^6.5.0"
    assert not any("bumped vite" in fix for fix in result.cf_fixes)


def test_from_genai_removes_redirects(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=True)

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert not (project / "_redirects").exists()
    assert not (project / "public" / "_redirects").exists()
    assert any("removed" in fix and "_redirects" in fix for fix in result.cf_fixes)


def test_from_genai_adds_wrangler_jsonc(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert (project / "wrangler.jsonc").exists()
    text = (project / "wrangler.jsonc").read_text()
    parsed = json.loads(text)
    assert parsed["name"] == "kwizicle"  # base only — TLD dropped
    assert parsed["assets"]["directory"] == "./dist"
    assert parsed["assets"]["not_found_handling"] == "single-page-application"
    assert any("wrangler.jsonc" in fix for fix in result.cf_fixes)


def test_from_genai_adds_cf_headers(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    headers_path = project / "public" / "_headers"
    assert headers_path.exists()
    text = headers_path.read_text()
    assert "Cache-Control" in text
    assert "X-Frame-Options" in text
    assert any("public/_headers" in fix for fix in result.cf_fixes)


def test_from_genai_removes_legacy_wrangler_toml(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)
    # Simulate a legacy wrangler.toml left over from the older bootstrap.
    (project / "wrangler.toml").write_text('name = "x"\n[site]\nbucket = "./dist"\n')

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert not (project / "wrangler.toml").exists()
    assert any("legacy wrangler.toml" in fix for fix in result.cf_fixes)


def test_template_path_also_gets_cf_config(tmp_path):
    """All bootstrapped projects ship with wrangler.jsonc + public/_headers,
    not just the genai-copy ones."""
    bootstrap("flow.dev", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    assert (project / "wrangler.jsonc").exists()
    assert (project / "public" / "_headers").exists()


def test_from_genai_preserves_existing_common_files(tmp_path):
    """If genai brings its own README.md/.gitignore, don't overwrite them."""
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)
    (project / "genai" / "README.md").write_text("# Lovable's README")
    (project / "genai" / ".gitignore").write_text("custom\n")

    bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert (project / "README.md").read_text() == "# Lovable's README"
    assert (project / ".gitignore").read_text() == "custom\n"


def test_from_genai_writes_missing_common_files(tmp_path):
    """Files genai doesn't ship still get written."""
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)

    bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert (project / "AI_AGENTS.md").exists()
    assert (project / "docs" / "prd.md").exists()
    assert (project / "docs" / "Prompts.md").exists()


def test_from_genai_requires_existing_dir(tmp_path):
    with pytest.raises(BootstrapError, match="to already exist"):
        bootstrap("absent.com", from_genai=True, sites_root=tmp_path)


def test_from_genai_requires_genai_subdir(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    with pytest.raises(BootstrapError, match="genai/"):
        bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)


def test_from_genai_requires_genai_package_json(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    (project / "genai").mkdir()
    with pytest.raises(BootstrapError, match="package.json"):
        bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)


def test_from_genai_skips_node_modules_and_pnpm_store(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)
    (project / "genai" / "node_modules").mkdir()
    (project / "genai" / "node_modules" / "huge.txt").write_text("x")

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert not (project / "node_modules").exists()
    assert any("node_modules" in w for w in result.warnings)


# ---------- git-url path ----------


def test_git_url_path_invokes_clone_then_genai_logic(tmp_path):
    """Patch git clone to populate the target dir; then bootstrap should proceed
    as if from_genai were passed."""
    real_run = subprocess.run

    def fake_clone_then_real(args, *kwargs_args, **kwargs):
        if args[:2] == ["git", "clone"]:
            target = Path(args[-1])
            target.mkdir(parents=True, exist_ok=True)
            _make_fake_lovable_export(target, vite_version="^4.0.0", with_redirects=True)
            class _R:
                returncode = 0
                stdout = ""
                stderr = ""
            return _R()
        return real_run(args, *kwargs_args, **kwargs)

    with patch("portfolio.bootstrap.subprocess.run", side_effect=fake_clone_then_real):
        result = bootstrap(
            "kwizicle.com",
            git_url="https://github.com/fake/repo.git",
            sites_root=tmp_path,
        )

    project = tmp_path / "kwizicle.com"
    assert result.path == "git-url"
    assert result.stack == "vite"  # auto-detected from cloned package.json
    # Files copied up from genai/
    assert (project / "package.json").exists()
    # CF fixes applied
    pkg = json.loads((project / "package.json").read_text())
    assert pkg["devDependencies"]["vite"] == "^6.0.0"
    assert (project / "wrangler.jsonc").exists()
    assert (project / "public" / "_headers").exists()


def test_git_url_path_refuses_existing_dir(tmp_path):
    (tmp_path / "exists.com").mkdir()
    with pytest.raises(BootstrapError, match="already exists"):
        bootstrap("exists.com", git_url="https://x/y.git", sites_root=tmp_path)


def test_git_url_path_handles_clone_failure(tmp_path):
    def fake_clone_failure(args, *kwargs_args, **kwargs):
        if args[:2] == ["git", "clone"]:
            raise subprocess.CalledProcessError(128, args, output="", stderr="repo not found")
        return subprocess.run(args, *kwargs_args, **kwargs)

    with patch("portfolio.bootstrap.subprocess.run", side_effect=fake_clone_failure):
        with pytest.raises(BootstrapError, match="git clone failed"):
            bootstrap("flow.dev", git_url="https://bad/url.git", sites_root=tmp_path)


# ---------- helpers ----------


def test_bump_vite_version_no_op_when_modern(tmp_path):
    pkg_path = tmp_path / "package.json"
    pkg_path.write_text(json.dumps({"devDependencies": {"vite": "^6.5.0"}}))
    msg = _bump_vite_version(pkg_path)
    assert msg is None


def test_bump_vite_version_bumps_old(tmp_path):
    pkg_path = tmp_path / "package.json"
    pkg_path.write_text(json.dumps({"devDependencies": {"vite": "^4.5.0"}}))
    msg = _bump_vite_version(pkg_path)
    assert msg is not None
    pkg = json.loads(pkg_path.read_text())
    assert pkg["devDependencies"]["vite"] == "^6.0.0"


def test_bump_vite_version_works_in_dependencies(tmp_path):
    pkg_path = tmp_path / "package.json"
    pkg_path.write_text(json.dumps({"dependencies": {"vite": "5.0.0"}}))
    msg = _bump_vite_version(pkg_path)
    assert msg is not None
    pkg = json.loads(pkg_path.read_text())
    assert pkg["dependencies"]["vite"] == "^6.0.0"


def test_remove_redirects_files(tmp_path):
    (tmp_path / "_redirects").write_text("/* /index.html 200")
    public = tmp_path / "public"
    public.mkdir()
    (public / "_redirects").write_text("/api/* /api/proxy 200")
    removed = _remove_redirects_files(tmp_path)
    assert "_redirects" in removed
    assert "public/_redirects" in removed
    assert not (tmp_path / "_redirects").exists()
    assert not (public / "_redirects").exists()


def test_add_wrangler_jsonc(tmp_path):
    assert _add_wrangler_jsonc(tmp_path, "kwizicle.com", "2026-05-04") is True
    assert (tmp_path / "wrangler.jsonc").exists()
    parsed = json.loads((tmp_path / "wrangler.jsonc").read_text())
    # Name drops the TLD entirely (matches user's preferred form after kwizicle iteration).
    assert parsed["name"] == "kwizicle"
    assert parsed["compatibility_date"] == "2026-05-04"
    assert parsed["assets"]["not_found_handling"] == "single-page-application"
    # Idempotent: second call returns False, doesn't overwrite.
    assert _add_wrangler_jsonc(tmp_path, "kwizicle.com", "2026-05-04") is False


@pytest.mark.parametrize("domain,expected", [
    ("kwizicle.com", "kwizicle"),
    ("homeloom.app", "homeloom"),
    ("voltloop.site", "voltloop"),
    ("foo.bar.io", "foo-bar"),
    ("multi-word.com", "multi-word"),
])
def test_project_name_munging(domain, expected):
    assert _project_name(domain) == expected


def test_ensure_pnpm_only_removes_bun_lockfile(tmp_path):
    (tmp_path / "bun.lockb").write_bytes(b"bun lock binary")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    fixes = _ensure_pnpm_only(tmp_path)
    assert not (tmp_path / "bun.lockb").exists()
    assert (tmp_path / "pnpm-lock.yaml").exists()  # pnpm preserved
    assert any("bun.lockb" in f for f in fixes)


def test_ensure_pnpm_only_removes_npm_lockfile(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")
    fixes = _ensure_pnpm_only(tmp_path)
    assert not (tmp_path / "package-lock.json").exists()
    assert any("package-lock.json" in f for f in fixes)


def test_ensure_pnpm_only_removes_yarn_lock(tmp_path):
    (tmp_path / "yarn.lock").write_text("# yarn lock\n")
    fixes = _ensure_pnpm_only(tmp_path)
    assert not (tmp_path / "yarn.lock").exists()
    assert any("yarn.lock" in f for f in fixes)


def test_ensure_pnpm_only_normalizes_package_manager_field(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x",
        "packageManager": "bun@1.0.0",
    }))
    fixes = _ensure_pnpm_only(tmp_path)
    pkg = json.loads((tmp_path / "package.json").read_text())
    assert pkg["packageManager"].startswith("pnpm")
    assert any("packageManager" in f for f in fixes)


def test_ensure_pnpm_only_leaves_pnpm_package_manager_alone(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x",
        "packageManager": "pnpm@9.5.0",
    }))
    fixes = _ensure_pnpm_only(tmp_path)
    pkg = json.loads((tmp_path / "package.json").read_text())
    assert pkg["packageManager"] == "pnpm@9.5.0"
    assert not any("packageManager" in f for f in fixes)


def test_ensure_pnpm_only_no_op_when_clean(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    fixes = _ensure_pnpm_only(tmp_path)
    assert fixes == []


def test_from_genai_strips_bun_lockfile(tmp_path):
    """Lovable exports ship bun.lockb + package-lock.json + pnpm-lock.yaml.
    All three lockfiles confused CF Pages; only pnpm-lock.yaml should remain."""
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai", with_redirects=False)
    # Add the multi-lockfile situation Lovable produces.
    (project / "genai" / "bun.lockb").write_bytes(b"bun")
    (project / "genai" / "package-lock.json").write_text("{}")
    (project / "genai" / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")

    result = bootstrap("kwizicle.com", from_genai=True, sites_root=tmp_path)
    assert not (project / "bun.lockb").exists(), "bun.lockb should be removed"
    assert not (project / "package-lock.json").exists(), "package-lock.json should be removed"
    assert (project / "pnpm-lock.yaml").exists(), "pnpm-lock.yaml should be preserved"
    assert any("bun.lockb" in f for f in result.cf_fixes)
    assert any("package-lock.json" in f for f in result.cf_fixes)


def test_add_cf_headers(tmp_path):
    assert _add_cf_headers(tmp_path) is True
    headers = (tmp_path / "public" / "_headers").read_text()
    assert "Cache-Control" in headers
    assert "X-Content-Type-Options: nosniff" in headers
    # Idempotent
    assert _add_cf_headers(tmp_path) is False


def test_remove_legacy_wrangler_toml(tmp_path):
    (tmp_path / "wrangler.toml").write_text("name = 'x'\n")
    assert _remove_legacy_wrangler_toml(tmp_path) is True
    assert not (tmp_path / "wrangler.toml").exists()
    # Idempotent — returns False when not present.
    assert _remove_legacy_wrangler_toml(tmp_path) is False


def test_detect_stack_from_pkg_astro(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"astro": "^5.0.0"}}))
    assert detect_stack_from_pkg(tmp_path) == "astro"


def test_detect_stack_from_pkg_vite(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"devDependencies": {"vite": "^6.0.0"}}))
    assert detect_stack_from_pkg(tmp_path) == "vite"


def test_detect_stack_from_pkg_react_only(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    assert detect_stack_from_pkg(tmp_path) == "vite"  # React → vite default


def test_detect_stack_from_pkg_unknown(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lodash": "*"}}))
    assert detect_stack_from_pkg(tmp_path) == "unknown"


def test_detect_stack_from_pkg_missing_returns_default(tmp_path):
    assert detect_stack_from_pkg(tmp_path) == "vite"
