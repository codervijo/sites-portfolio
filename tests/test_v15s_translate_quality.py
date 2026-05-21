"""Tests for v15.S — translate output quality.

Four fixes, all in `stack_translate.py`, motivated by the
disclosur.dev port-to-Astro run (2026-05-20) that surfaced:
  1. Validator didn't catch `@import "tailwindcss"` referenced
     from src/styles/ without a matching dep in package.json.
  2. Claude's atomic-write tmp files (`*.tmp.<pid>.<hex>`) leaked
     into src/pages/ and broke Astro dev server.
  3. Translation prompt didn't explicitly instruct porting CSS
     toolchain deps from genai/package.json.
  4. pnpm v11's interactive approve-builds flow wrote a stub
     pnpm-workspace.yaml with placeholder text that overrode the
     parent sites/pnpm-workspace.yaml — silently ignoring
     `onlyBuiltDependencies: [esbuild, sharp]`.
"""
from __future__ import annotations

import json
from pathlib import Path

from portfolio.stack_translate import (
    _build_port_prompt,
    _build_translation_prompt,
    _detect_tailwind_usage,
    StackDetection,
    STACK_TANSTACK,
    sweep_tmp_artifacts,
    validate_translation,
    write_pnpm_workspace_yaml,
)


# ---- Fix 1: validator catches missing tailwindcss dep ----


def _scaffold_minimal_astro_project(
    project_dir: Path,
    *,
    deps: dict[str, str] | None = None,
) -> None:
    """Write the minimum file shape that passes the pre-existing
    `validate_translation` checks (astro dep, astro.config, src/pages/),
    so v15.S checks are what's exercised."""
    deps = deps if deps is not None else {"astro": "^5.0.0"}
    pkg = {"name": "test-site", "type": "module", "dependencies": deps}
    (project_dir / "package.json").write_text(json.dumps(pkg))
    (project_dir / "astro.config.mjs").write_text(
        "export default { output: 'static' };"
    )
    (project_dir / "src" / "pages").mkdir(parents=True)
    (project_dir / "src" / "pages" / "index.astro").write_text("<p>hi</p>")
    (project_dir / "src" / "styles").mkdir(parents=True)


def test_validator_passes_when_no_tailwind_usage(tmp_path):
    """Baseline: no tailwind anywhere → validator passes."""
    _scaffold_minimal_astro_project(tmp_path)
    (tmp_path / "src" / "styles" / "globals.css").write_text(
        "body { margin: 0; }"
    )
    result = validate_translation(tmp_path)
    assert result.ok, result.issues


def test_validator_flags_tailwind_v4_import_without_dep(tmp_path):
    """The disclosur.dev case: `@import "tailwindcss"` in CSS but no
    tailwindcss dep in package.json → validator must reject."""
    _scaffold_minimal_astro_project(tmp_path)
    (tmp_path / "src" / "styles" / "globals.css").write_text(
        '@import "tailwindcss" source(none);\n'
        "body { margin: 0; }"
    )
    result = validate_translation(tmp_path)
    assert not result.ok
    # Both issues fire: tailwindcss + @tailwindcss/vite missing.
    text = " | ".join(result.issues)
    assert "tailwindcss" in text
    assert "@tailwindcss/vite" in text
    assert "globals.css" in text  # evidence path surfaced


def test_validator_flags_tailwind_v3_directive_without_dep(tmp_path):
    """Tailwind v3 syntax (`@tailwind base;`) without dep → reject.
    Doesn't require @tailwindcss/vite (v3 uses postcss plugin)."""
    _scaffold_minimal_astro_project(tmp_path)
    (tmp_path / "src" / "styles" / "globals.css").write_text(
        "@tailwind base;\n@tailwind components;\n@tailwind utilities;"
    )
    result = validate_translation(tmp_path)
    assert not result.ok
    text = " | ".join(result.issues)
    assert "tailwindcss" in text
    assert "@tailwindcss/vite" not in text  # v3 doesn't need it


def test_validator_passes_when_tailwind_v4_dep_present(tmp_path):
    """Tailwind v4 import + matching deps → validator passes."""
    _scaffold_minimal_astro_project(
        tmp_path,
        deps={
            "astro": "^5.0.0",
            "tailwindcss": "^4.2.1",
            "@tailwindcss/vite": "^4.2.1",
        },
    )
    (tmp_path / "src" / "styles" / "globals.css").write_text(
        '@import "tailwindcss";'
    )
    result = validate_translation(tmp_path)
    assert result.ok, result.issues


def test_detect_tailwind_usage_signals(tmp_path):
    """Direct test of the detector — keeps validator wiring trivial."""
    src = tmp_path / "src"
    (src / "styles").mkdir(parents=True)
    # No file: no signal.
    assert _detect_tailwind_usage(src) == {
        "any": False, "v4_import": False, "evidence": "",
    }
    # v3 directive only.
    (src / "styles" / "a.css").write_text("@tailwind base;")
    out = _detect_tailwind_usage(src)
    assert out["any"] is True
    assert out["v4_import"] is False
    assert "a.css" in str(out["evidence"])
    # v4 import wins (more specific).
    (src / "styles" / "b.css").write_text('@import "tailwindcss";')
    out2 = _detect_tailwind_usage(src)
    assert out2["v4_import"] is True


# ---- Fix 2: sweep_tmp_artifacts removes Claude atomic-write leftovers ----


def test_sweep_removes_tmp_artifacts(tmp_path):
    """The disclosur.dev case: three `.astro.tmp.<pid>.<hex>` files
    leaked into src/pages/dashboard/ — sweep must remove them."""
    pages = tmp_path / "src" / "pages" / "dashboard"
    pages.mkdir(parents=True)
    real = pages / "providers.astro"
    real.write_text("---\n---\n<p>ok</p>")
    leak1 = pages / "providers.astro.tmp.2394385.6e80e0ebacc8"
    leak1.write_text("partial write")
    leak2 = pages / "gaps.astro.tmp.2394385.a41f567b04bd"
    leak2.write_text("partial write")

    swept = sweep_tmp_artifacts(tmp_path)

    assert real.exists(), "must not touch real .astro files"
    assert not leak1.exists()
    assert not leak2.exists()
    assert sorted(swept) == [
        "src/pages/dashboard/gaps.astro.tmp.2394385.a41f567b04bd",
        "src/pages/dashboard/providers.astro.tmp.2394385.6e80e0ebacc8",
    ]


def test_sweep_skips_node_modules_and_genai(tmp_path):
    """Sweep must not touch vendored / reference dirs even if they
    happen to contain matching filename patterns."""
    nm = tmp_path / "node_modules" / "junk"
    nm.mkdir(parents=True)
    nm_leak = nm / "foo.tmp.123.abc"
    nm_leak.write_text("x")

    genai = tmp_path / "genai" / "src"
    genai.mkdir(parents=True)
    genai_leak = genai / "bar.tmp.456.def"
    genai_leak.write_text("x")

    swept = sweep_tmp_artifacts(tmp_path)

    assert nm_leak.exists()
    assert genai_leak.exists()
    assert swept == []


def test_sweep_empty_when_no_artifacts(tmp_path):
    """Normal post-translation case: nothing to sweep, empty list."""
    (tmp_path / "src" / "pages").mkdir(parents=True)
    (tmp_path / "src" / "pages" / "index.astro").write_text("ok")
    assert sweep_tmp_artifacts(tmp_path) == []


# ---- Fix 3: translation prompts include CSS toolchain section ----


def test_translation_prompt_includes_css_toolchain(tmp_path):
    """The full-translation prompt (`_build_translation_prompt`) must
    explicitly instruct CSS-toolchain dep porting + plugin wiring."""
    detection = StackDetection(
        stack=STACK_TANSTACK,
        signals=["dependency:@tanstack/react-start"],
    )
    prompt = _build_translation_prompt(tmp_path, detection)
    assert "CSS toolchain" in prompt
    assert "tailwindcss" in prompt
    assert "@tailwindcss/vite" in prompt
    # Wiring example must be in the prompt — the disclosur.dev
    # failure was specifically about missing plugin registration.
    assert "import tailwindcss" in prompt


def test_port_prompt_allows_package_json_for_css_deps(tmp_path):
    """The port prompt (`_build_port_prompt`) used to say "do NOT
    touch package.json" — which prevented Claude from adding the
    Tailwind dep. v15.S relaxes this for CSS toolchain deps."""
    prompt = _build_port_prompt(
        tmp_path,
        source_stack=STACK_TANSTACK,
        source_signals=["dependency:@tanstack/react-start"],
    )
    assert "CSS toolchain" in prompt
    assert "tailwindcss" in prompt
    # The relaxation: "you MAY (and often must) edit package.json".
    assert "MAY" in prompt and "package.json" in prompt
    # Wiring example present.
    assert "@tailwindcss/vite" in prompt


# ---- Fix 4: write_pnpm_workspace_yaml pre-seeds approve-builds ----


def test_write_pnpm_workspace_yaml_creates_when_absent(tmp_path):
    """Fresh project → write the pre-approved allowlist."""
    written = write_pnpm_workspace_yaml(tmp_path)
    assert written is True
    target = tmp_path / "pnpm-workspace.yaml"
    assert target.exists()
    text = target.read_text()
    assert "onlyBuiltDependencies:" in text
    assert "- esbuild" in text
    assert "- sharp" in text


def test_write_pnpm_workspace_yaml_overwrites_pnpm_stub(tmp_path):
    """The disclosur.dev case: pnpm wrote a stub with `allowBuilds:`
    placeholder text. Lamill must overwrite that with the real
    allowlist."""
    stub = tmp_path / "pnpm-workspace.yaml"
    stub.write_text(
        "allowBuilds:\n"
        "  esbuild: set this to true or false\n"
        "  sharp: set this to true or false\n"
    )

    written = write_pnpm_workspace_yaml(tmp_path)

    assert written is True
    text = stub.read_text()
    assert "set this to true or false" not in text
    assert "- esbuild" in text
    assert "- sharp" in text


def test_write_pnpm_workspace_yaml_preserves_operator_customization(tmp_path):
    """If operator has already customized the yaml, don't clobber.
    Idempotency: lamill only overwrites pnpm's placeholder stubs."""
    custom = tmp_path / "pnpm-workspace.yaml"
    custom.write_text(
        "onlyBuiltDependencies:\n"
        "  - esbuild\n"
        "  - sharp\n"
        "  - canvas\n"  # operator added their own
    )

    written = write_pnpm_workspace_yaml(tmp_path)

    assert written is False
    text = custom.read_text()
    assert "canvas" in text  # operator's customization survives
