"""Tests for v33.N — CHECK_156 astro-cache-gitignored + CHECK_157 pnpm-lock-tracked."""
from __future__ import annotations

import subprocess
from pathlib import Path

from portfolio.checks.stack import check_156_astro_cache_gitignored as c156
from portfolio.checks.stack import check_157_pnpm_lock_tracked as c157


def _astro_site(tmp_path: Path, *, gitignore: str | None) -> Path:
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "astro.config.mjs").write_text("export default {}\n")
    if gitignore is not None:
        (tmp_path / ".gitignore").write_text(gitignore)
    return tmp_path


# ---------- CHECK_156 astro-cache-gitignored ----------


def test_156_pass_when_astro_gitignored(tmp_path):
    _astro_site(tmp_path, gitignore="node_modules/\n.astro/\ndist/\n")
    assert c156.run(str(tmp_path)).status == "pass"


def test_156_fail_when_astro_not_gitignored(tmp_path):
    _astro_site(tmp_path, gitignore="node_modules/\ndist/\n")
    r = c156.run(str(tmp_path))
    assert r.status == "fail"
    assert ".astro/" in r.message


def test_156_skips_non_astro_web_project(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}')
    (tmp_path / "vite.config.ts").write_text("export default {}\n")
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    assert c156.run(str(tmp_path)).status == "warn"   # not Astro → skipped


def test_156_skips_declared_non_js_stack(tmp_path):
    _astro_site(tmp_path, gitignore="x\n")
    (tmp_path / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n[deploy]\nplatform = "cf-pages"\n'
        '[stack]\nframework = "wordpress"\n')
    assert c156.run(str(tmp_path)).status == "warn"


def test_156_fix_appends_astro_block(tmp_path):
    site = _astro_site(tmp_path, gitignore="node_modules/\ndist/\n")
    # dry-run announces, doesn't write
    assert c156.fix_tier_1.apply(site, True, True).status == "would-fix"
    assert ".astro/" not in (site / ".gitignore").read_text()
    # real run appends + check now passes
    assert c156.fix_tier_1.apply(site, False, True).status == "fixed"
    assert ".astro/" in (site / ".gitignore").read_text()
    assert c156.run(str(site)).status == "pass"


def test_156_fix_idempotent(tmp_path):
    site = _astro_site(tmp_path, gitignore="node_modules/\n.astro/\n")
    assert c156.fix_tier_1.apply(site, False, True).status == "nothing-to-do"


def test_156_fix_writes_full_gitignore_when_absent(tmp_path):
    site = _astro_site(tmp_path, gitignore=None)   # no .gitignore at all
    assert c156.fix_tier_1.apply(site, False, True).status == "fixed"
    gi = (site / ".gitignore").read_text()
    assert ".astro/" in gi and "node_modules/" in gi   # full standard template


# ---------- CHECK_157 pnpm-lock-tracked ----------


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def _git_site(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text('{"name":"x"}')
    _git(["init"], tmp_path)
    _git(["config", "user.email", "t@t.t"], tmp_path)
    _git(["config", "user.name", "t"], tmp_path)
    (tmp_path / "README.md").write_text("hi\n")
    _git(["add", "README.md"], tmp_path)
    _git(["commit", "-m", "init"], tmp_path)
    return tmp_path


def test_157_pass_when_lock_tracked(tmp_path):
    site = _git_site(tmp_path)
    (site / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")
    _git(["add", "pnpm-lock.yaml"], site)
    _git(["commit", "-m", "lock"], site)
    assert c157.run(str(site)).status == "pass"


def test_157_fail_when_lock_present_but_untracked(tmp_path):
    site = _git_site(tmp_path)
    (site / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n")  # not added
    r = c157.run(str(site))
    assert r.status == "fail"
    assert "git add pnpm-lock.yaml" in r.message


def test_157_pass_when_no_lockfile(tmp_path):
    site = _git_site(tmp_path)
    assert c157.run(str(site)).status == "pass"   # n/a — CHECK_031's domain


def test_157_skips_non_web_project(tmp_path):
    assert c157.run(str(tmp_path)).status == "warn"   # no package.json
