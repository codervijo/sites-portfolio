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
                "docs/prd.md", "docs/Prompts.md", "docs/growth.md"):
        assert (project / rel).exists(), f"missing {rel}"


def test_template_path_growth_log_is_self_sustaining(tmp_path):
    """docs/growth.md must embed the workflow so the user doesn't need to
    remember it. Specifically: lifecycle steps, format guide, where to get
    GSC numbers, and a first entry already filled in with a concrete review
    date."""
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "docs" / "growth.md").read_text()
    # Workflow guide present
    assert "How to use this" in text
    assert "Lifecycle of one entry" in text
    # Format spec present
    assert "Status:" in text and "KPI:" in text and "Baseline:" in text
    # Where-to-get-numbers
    assert "gsc sync" in text
    # First entry pre-populated with status=active and a concrete review date
    assert "Status:** active" in text
    # Review date should be a specific YYYY-MM-DD, not the literal placeholder
    import re
    match = re.search(r"review (\d{4}-\d{2}-\d{2})", text)
    assert match is not None, "first entry must include a concrete review date"


def test_template_path_seo_files_present(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    for rel in ("public/robots.txt", "public/sitemap.xml", "public/favicon.svg",
                "vitest.config.js", "src/__tests__/smoke.test.js"):
        assert (project / rel).exists(), f"missing {rel}"
    # robots references the sitemap URL
    assert "Sitemap: https://flow.dev/sitemap.xml" in (project / "public" / "robots.txt").read_text()
    # sitemap is valid-looking XML with the home page
    sitemap = (project / "public" / "sitemap.xml").read_text()
    assert "https://flow.dev/" in sitemap
    assert "<urlset" in sitemap


def test_template_path_vite_index_has_meta_tags_and_jsonld(tmp_path):
    bootstrap("flow.dev", stack="vite", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "index.html").read_text()
    # Standard SEO meta
    assert '<meta name="description"' in text
    assert '<link rel="canonical" href="https://flow.dev"' in text
    assert '<link rel="icon" type="image/svg+xml" href="/favicon.svg"' in text
    # OG / Twitter
    assert '<meta property="og:title"' in text
    assert '<meta property="og:url" content="https://flow.dev"' in text
    assert '<meta name="twitter:card"' in text
    # JSON-LD structured data
    assert '<script type="application/ld+json">' in text
    assert '"@type": "Organization"' in text
    assert '"@type": "WebSite"' in text
    assert '"https://flow.dev/#organization"' in text


def test_template_path_astro_index_has_meta_tags_and_jsonld(tmp_path):
    bootstrap("flow.dev", stack="astro", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "src" / "pages" / "index.astro").read_text()
    # Astro frontmatter has site/title/description
    assert 'const site = "https://flow.dev"' in text
    assert 'const title = "flow.dev"' in text
    # Meta + OG + Twitter + JSON-LD
    assert "og:title" in text
    assert "twitter:card" in text
    assert "application/ld+json" in text
    assert '"@type": "Organization"' in text


def test_favicon_svg_renders_initial_and_color(tmp_path):
    bootstrap("kwizicle.com", sites_root=tmp_path)
    svg = (tmp_path / "kwizicle.com" / "public" / "favicon.svg").read_text()
    # Valid SVG envelope
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    # Uses viewBox + a rect background + a centered text
    assert 'viewBox="0 0 64 64"' in svg
    assert "<rect" in svg
    assert "<text" in svg
    # Initial = first letter of base name, uppercase
    assert ">K<" in svg
    # Has a fill color from the palette (any 6-digit hex)
    import re
    assert re.search(r'fill="#[0-9a-f]{6}"', svg) is not None


def test_favicon_color_deterministic(tmp_path):
    """Same domain → same color forever (so favicon doesn't drift between rebuilds)."""
    from portfolio.bootstrap import _favicon_color
    assert _favicon_color("kwizicle.com") == _favicon_color("kwizicle.com")
    # Different domains usually pick different colors (palette has 12 entries)
    colors = {_favicon_color(d) for d in
              ("flow.dev", "kwizicle.com", "lamill.io", "homeloom.app", "voltloop.site")}
    assert len(colors) >= 2  # at least some variation across these 5


# ---------- v3.B.2: sitemap generator + SEO regression test ----------


def test_vite_path_writes_sitemap_script(tmp_path):
    bootstrap("flow.dev", stack="vite", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    script = project / "scripts" / "generate-sitemap.mjs"
    assert script.exists()
    text = script.read_text()
    # Scans dist/ for HTML files and writes dist/sitemap.xml
    assert "import { readdirSync, statSync, writeFileSync }" in text
    assert "dist/sitemap.xml" in text or "DIST" in text
    # Default site URL falls through to the domain at scaffold time
    assert "https://flow.dev" in text


def test_vite_path_build_script_chains_sitemap_generator(tmp_path):
    bootstrap("flow.dev", stack="vite", sites_root=tmp_path)
    pkg = json.loads((tmp_path / "flow.dev" / "package.json").read_text())
    assert pkg["scripts"]["build"] == "vite build && node scripts/generate-sitemap.mjs"


def test_astro_path_uses_sitemap_integration(tmp_path):
    bootstrap("flow.dev", stack="astro", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    config = (project / "astro.config.mjs").read_text()
    assert "@astrojs/sitemap" in config
    assert "integrations: [sitemap()]" in config
    assert "site: 'https://flow.dev'" in config
    pkg = json.loads((project / "package.json").read_text())
    assert "@astrojs/sitemap" in pkg["dependencies"]


def test_vite_path_seo_test_present_and_asserts_baseline(tmp_path):
    bootstrap("flow.dev", stack="vite", sites_root=tmp_path)
    seo_test = (tmp_path / "flow.dev" / "src" / "__tests__" / "seo.test.js").read_text()
    # Reads the right file
    assert "index.html" in seo_test
    # Asserts the v3.B baseline pieces
    for assertion in ("title", "meta", "description", "canonical",
                      "og:title", "twitter:card", "favicon", "Organization", "WebSite"):
        assert assertion in seo_test, f"SEO test missing assertion for {assertion!r}"
    # Domain-specific canonical check
    assert "flow.dev" in seo_test


def test_astro_path_seo_test_present_and_strips_frontmatter(tmp_path):
    bootstrap("flow.dev", stack="astro", sites_root=tmp_path)
    seo_test = (tmp_path / "flow.dev" / "src" / "__tests__" / "seo.test.js").read_text()
    # Reads the .astro source
    assert "index.astro" in seo_test
    # Strips the frontmatter block
    assert "frontmatter" in seo_test.lower() or "---[" in seo_test
    # Asserts core baseline
    for assertion in ("title", "description", "canonical", "favicon", "Organization"):
        assert assertion in seo_test, f"SEO test missing assertion for {assertion!r}"


def test_both_stacks_have_test_seo_npm_script(tmp_path):
    bootstrap("a.com", stack="vite", sites_root=tmp_path)
    bootstrap("b.com", stack="astro", sites_root=tmp_path)
    pkg_a = json.loads((tmp_path / "a.com" / "package.json").read_text())
    pkg_b = json.loads((tmp_path / "b.com" / "package.json").read_text())
    assert pkg_a["scripts"]["test:seo"] == "vitest run src/__tests__/seo.test.js"
    assert pkg_b["scripts"]["test:seo"] == "vitest run src/__tests__/seo.test.js"


def test_template_path_ai_agents_has_post_deploy_checklist(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "AI_AGENTS.md").read_text()
    # Post-deploy checklist with GSC verification
    assert "Post-deploy checklist" in text
    assert "search.google.com/search-console" in text
    assert "sc-domain:flow.dev" in text


def test_template_path_ai_agents_has_conformance_section(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "AI_AGENTS.md").read_text()
    assert "How this project is checked" in text
    # v7.A renamed `portfolio info status` → `portfolio project check`.
    assert "portfolio project check" in text
    # Lists CHECK_* IDs from the catalog (v5.E migrated rule names).
    for cid in ("CHECK_020", "CHECK_002", "CHECK_007", "CHECK_008"):
        assert cid in text, f"check {cid} not surfaced in AI_AGENTS"


def test_template_path_passes_day_zero_catalog(tmp_path):
    """v6.A.1 — every catalog check that's testable on a freshly-
    bootstrapped project must pass (or skip), not fail. Locks in the
    bootstrap↔catalog reconciliation so future drift fails CI."""
    from portfolio.checks import list_checks, run_check

    bootstrap("flow.dev", sites_root=tmp_path)
    project_dir = str(tmp_path / "flow.dev")

    # Skip checks that depend on git history beyond the initial commit
    # or post-deploy state (transient — closes after `make deps` /
    # actual deploy).
    transient = {
        "CHECK_021",  # last-commit-30d (initial commit is fresh)
        "CHECK_022",  # clean-tree (true post-bootstrap; just be safe)
        "CHECK_023",  # on-main-branch (already pass; defensive)
        "CHECK_028",  # last-deploy-date (no deploy yet)
        "CHECK_031",  # has-pnpm-lock (user runs `make deps` after)
        "CHECK_041",  # dir-matches-portfolio-entry (user runs `lamill
                      # fleet sync` to rebuild inventory after
                      # the new dir exists)
        "CHECK_042",  # live-final-url-matches-domain (no live snapshot
                      # covers a freshly-scaffolded dir; closes after
                      # first `lamill fleet live` post-deploy)
    }

    fails = []
    for spec in list_checks():
        if spec.id in transient:
            continue
        r = run_check(spec.id, project_dir)
        if r.status == "fail":
            fails.append((spec.id, spec.name, r.message))

    assert not fails, (
        "Day-zero catalog failures on bootstrap output:\n" +
        "\n".join(f"  ✗ {cid} {name} — {msg}" for cid, name, msg in fails)
    )


def test_template_path_ai_agents_has_ship_fast_reminder(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "AI_AGENTS.md").read_text()
    # Some recognizable form of the workspace ship-fast strategy
    assert "ship" in text.lower()
    assert "30-site" in text or "30 commercial" in text or "30-site SEO" in text


def test_template_path_ai_agents_has_required_sections(tmp_path):
    bootstrap("flow.dev", topic="cool idea", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "AI_AGENTS.md").read_text()
    # v6.A.1 renamed to match catalog headings (CHECK_003 + CHECK_004
    # look for these literal strings).
    assert "## Building info" in text
    assert "## Deployment info" in text
    assert "wrangler.jsonc" in text
    assert "public/_headers" in text
    assert "cool idea" in text  # topic injected


def test_template_path_ai_agents_has_versioning_section(tmp_path):
    """Bootstrapped projects must surface the canonical sites/* versioning
    convention so agents/users entering the project know about vN / vN.X."""
    bootstrap("flow.dev", sites_root=tmp_path)
    text = (tmp_path / "flow.dev" / "AI_AGENTS.md").read_text()
    assert "## Versioning" in text
    assert "vN" in text and "vN.X" in text
    assert "sites/portfolio/AI_AGENTS.md" in text  # points at the canonical source
    assert "v0.A" in text  # bootstrap phase notation


def test_template_path_prd_references_versioning_convention(tmp_path):
    bootstrap("flow.dev", sites_root=tmp_path)
    prd = (tmp_path / "flow.dev" / "docs" / "prd.md").read_text()
    assert "v0" in prd and "v0.A" in prd  # initial scaffold phase notation
    assert "v1" in prd  # first-real-version placeholder
    assert "sites/portfolio/AI_AGENTS.md" in prd  # canonical reference


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
    """Populate genai_dir with a minimal fake Lovable-style Vite/React export.

    v15.H note (ADR-0013): the v15.H stack-translation hook detects
    non-Astro repos and translates via Claude subprocess. To keep
    legacy `--from-genai` tests testing the `_copy_from_genai` + CF
    safety fix behaviors (rather than the translation path), this
    fixture includes `astro` in dependencies so `detect_stack` routes
    through the direct-copy path. The underlying behaviors tested
    (vite version bumping, lockfile cleanup, CF headers/wrangler) are
    stack-agnostic and apply to any sites/* project.
    """
    genai_dir.mkdir(parents=True, exist_ok=True)
    pkg = {
        "name": "lovable-export",
        "type": "module",
        "scripts": {"dev": "vite", "build": "vite build"},
        "dependencies": {
            "react": "^18.3.0",
            "react-dom": "^18.3.0",
            "astro": "^5.0.0",  # v15.H: routes detection to Astro path
        },
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


def test_from_genai_detects_astro_stack_from_package_json(tmp_path):
    """v15.H (ADR-0013): `--from-genai` auto-detects stack via the
    new `detect_stack` helper. Fixtures now include `astro` dep, so
    detection routes through the direct-copy path with stack='astro'.
    The previous v3.A behavior asserted stack='vite'; that's now
    deprecated under the Astro-only policy."""
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    _make_fake_lovable_export(project / "genai")

    result = bootstrap("kwizicle.com", from_genai=True, stack="astro", sites_root=tmp_path)
    assert result.stack == "astro"


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
    # v15.H (ADR-0013): fixture includes `astro` dep → detect_stack
    # routes through direct-copy path with stack='astro'.
    assert result.stack == "astro"
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


# ---------- v10.C — lamill.toml writing as part of scaffolding ----------


def test_bootstrap_writes_lamill_toml_with_cf_pages_default(tmp_path):
    """Template path with default --stack astro → lamill.toml has
    platform=cf-pages (per resolution 10.C — CF Pages stays the
    current bootstrap default until the next 3-4 sites all ship
    on Vercel)."""
    from portfolio.lamill_toml import load
    bootstrap("flow.dev", sites_root=tmp_path)
    project = tmp_path / "flow.dev"
    assert (project / "lamill.toml").exists()
    payload = load(project)
    assert payload is not None
    assert payload.deploy.platform == "cf-pages"


def test_bootstrap_lamill_toml_sets_custom_domains_to_domain(tmp_path):
    from portfolio.lamill_toml import load
    bootstrap("calcengine.site", sites_root=tmp_path)
    payload = load(tmp_path / "calcengine.site")
    assert payload.deploy.custom_domains == ["calcengine.site"]


def test_bootstrap_vite_stack_also_defaults_to_cf_pages(tmp_path):
    from portfolio.lamill_toml import load
    bootstrap("kwizicle.com", stack="vite", sites_root=tmp_path)
    payload = load(tmp_path / "kwizicle.com")
    assert payload.deploy.platform == "cf-pages"


def test_bootstrap_platform_flag_overrides_default(tmp_path):
    from portfolio.lamill_toml import load
    bootstrap("airsucks.com", sites_root=tmp_path, platform="vercel")
    payload = load(tmp_path / "airsucks.com")
    assert payload.deploy.platform == "vercel"


def test_bootstrap_platform_flag_accepts_non_hosting_platforms(tmp_path):
    """Every PLATFORM_VALUES entry except `hostgator` / `custom` is
    accepted via --platform. The two hosting-required platforms reject
    at bootstrap (see test_bootstrap_platform_flag_rejects_hostgator)
    because bootstrap doesn't prompt for cpanel + FTP breadcrumbs."""
    from portfolio.lamill_toml import (
        HOSTING_REQUIRED_PLATFORMS, PLATFORM_VALUES, load,
    )
    for i, platform in enumerate(PLATFORM_VALUES):
        if platform in HOSTING_REQUIRED_PLATFORMS:
            continue
        domain = f"test{i}.example"
        bootstrap(domain, sites_root=tmp_path, platform=platform)
        payload = load(tmp_path / domain)
        assert payload.deploy.platform == platform


@pytest.mark.parametrize("platform", ("hostgator", "custom"))
def test_bootstrap_platform_flag_rejects_hosting_required(tmp_path, platform):
    """`--platform hostgator|custom` rejects at bootstrap with a
    pointer to `settings deploy set` (the only command that
    knows how to prompt for the required hosting fields)."""
    with pytest.raises(BootstrapError, match="can't be set at bootstrap"):
        bootstrap(
            f"hg-{platform}.example",
            sites_root=tmp_path,
            platform=platform,
        )


def test_bootstrap_platform_flag_rejects_invalid(tmp_path):
    with pytest.raises(BootstrapError, match="unsupported --platform"):
        bootstrap("invalid.example", sites_root=tmp_path, platform="fly-io")
    # Project dir gets created earlier in bootstrap; the failure is
    # mid-flight. That's the existing behavior (--stack 'bogus' also
    # fails after `mkdir`); document but don't try to clean it up.


def test_bootstrap_lamill_toml_round_trips_through_load(tmp_path):
    """The file bootstrap writes must satisfy the v10.A parser
    (strict-on-read). If load() ever raises ParseError here, that's
    drift between the writer and the parser."""
    from portfolio.lamill_toml import load
    bootstrap("flow.dev", sites_root=tmp_path)
    payload = load(tmp_path / "flow.dev")  # raises on malformed
    assert payload is not None
    assert payload.deploy.platform == "cf-pages"
    assert payload.deploy.production_branch == "main"


def test_bootstrap_doesnt_clobber_existing_lamill_toml(tmp_path):
    """If a `lamill.toml` somehow already exists in the project dir
    before bootstrap (uncommon but possible if --from-genai brought
    one along), bootstrap leaves it alone."""
    from portfolio.lamill_toml import (
        BackendBlock, DeployBlock, LamillToml, load, write,
    )
    project_dir = tmp_path / "flow.dev"
    project_dir.mkdir(parents=True)
    # Pre-seed a vercel + backend payload so the bootstrap path
    # would normally overwrite with cf-pages.
    preexisting = LamillToml(
        deploy=DeployBlock(platform="vercel", account="team-prod"),
        backend=BackendBlock(db="postgres", framework="fastapi",
                             hosting="fly.io"),
    )
    write(project_dir, preexisting)
    # Bootstrap normally rejects existing project_dir on template
    # path; use --from-genai instead. Pre-seed an empty genai dir
    # with an Astro package.json so v15.H detect_stack routes through
    # the direct-copy path (otherwise UNKNOWN stack bails with
    # BootstrapError).
    (project_dir / "genai").mkdir()
    (project_dir / "genai" / "package.json").write_text(
        '{"name": "flow", "scripts": {"build": "echo build"}, '
        '"dependencies": {"astro": "^5.0.0"}}'
    )
    bootstrap("flow.dev", from_genai=True, sites_root=tmp_path)
    # The pre-existing lamill.toml survives untouched.
    payload = load(project_dir)
    assert payload.deploy.platform == "vercel"
    assert payload.deploy.account == "team-prod"
    assert payload.backend is not None
    assert payload.backend.db == "postgres"


def test_bootstrap_passes_day_zero_catalog_with_lamill_toml(tmp_path):
    """v10.C addendum to the v6.B day-zero catalog regression — adding
    a lamill.toml to the scaffold output mustn't break any check. If
    a check fails because the bootstrap now writes an extra file,
    that check is a regression introduced by v10.C."""
    from portfolio.checks import list_checks, run_check
    bootstrap("flow.dev", sites_root=tmp_path)
    project_dir = str(tmp_path / "flow.dev")
    transient = {
        "CHECK_021", "CHECK_022", "CHECK_023", "CHECK_028",
        "CHECK_031", "CHECK_041", "CHECK_042",
    }
    failed = []
    for spec in list_checks():
        if spec.id in transient:
            continue
        result = run_check(spec.id, project_dir)
        if result.status == "fail":
            failed.append(f"{spec.id}: {result.message}")
    assert not failed, "checks failed on freshly-bootstrapped output:\n" + "\n".join(failed)
