"""v27.E — stack-aware checks read [stack] + CHECK_151 stack-drift.

Three groups:
  1. `declared_stack` + `foreign_config_markers` helpers.
  2. CHECK_035/036/037 skip-by-declaration on wordpress/static/none,
     and fall through to the heuristic when [stack] is absent.
  3. CHECK_151 stack-drift: primary mismatch, foreign config (the
     lamillrentals two-config case), clean pass, and the additive-
     optional skips.
"""
from __future__ import annotations

import json
from pathlib import Path

from portfolio.checks.stack import declared_stack, foreign_config_markers
from portfolio.checks.stack.check_035_vite_version_ok import run as run_035
from portfolio.checks.stack.check_036_astro_version_ok import run as run_036
from portfolio.checks.stack.check_037_build_dev_scripts import run as run_037
from portfolio.checks.stack.check_151_stack_drift import run as run_151


_DEPLOY = 'schema = "lamill-toml-v1"\n[deploy]\nplatform = "cf-pages"\n'


def _toml(project_dir: Path, body: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "lamill.toml").write_text(body)


def _stack(framework: str) -> str:
    return _DEPLOY + f'[stack]\nframework = "{framework}"\n'


def _pkg(project_dir: Path, deps: dict, scripts: dict | None = None) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"dependencies": deps}
    if scripts is not None:
        payload["scripts"] = scripts
    (project_dir / "package.json").write_text(json.dumps(payload))


def _config(project_dir: Path, name: str) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / name).write_text("export default {}")


# ---- declared_stack + foreign_config_markers ------------------------


def test_declared_stack_reads_framework(tmp_path: Path):
    _toml(tmp_path, _stack("astro"))
    assert declared_stack(str(tmp_path)) == "astro"


def test_declared_stack_none_when_no_toml(tmp_path: Path):
    assert declared_stack(str(tmp_path)) is None


def test_declared_stack_none_when_no_stack_table(tmp_path: Path):
    _toml(tmp_path, _DEPLOY)
    assert declared_stack(str(tmp_path)) is None


def test_declared_stack_swallows_parse_error(tmp_path: Path):
    _toml(tmp_path, _DEPLOY + '[stack]\nframework = "not-a-real-fw"\n')
    assert declared_stack(str(tmp_path)) is None


def test_foreign_config_vite_on_astro(tmp_path: Path):
    (tmp_path / "vite.config.ts").write_text("export default {}")
    assert foreign_config_markers(tmp_path, "astro") == ["vite.config.ts"]


def test_foreign_config_vite_ok_on_vite_react(tmp_path: Path):
    (tmp_path / "vite.config.ts").write_text("export default {}")
    assert foreign_config_markers(tmp_path, "vite-react") == []


def test_foreign_config_vite_ok_on_tanstack(tmp_path: Path):
    (tmp_path / "vite.config.ts").write_text("export default {}")
    assert foreign_config_markers(tmp_path, "tanstack") == []


def test_foreign_config_astro_on_nextjs(tmp_path: Path):
    (tmp_path / "astro.config.mjs").write_text("export default {}")
    assert foreign_config_markers(tmp_path, "nextjs") == ["astro.config.mjs"]


def test_foreign_config_clean(tmp_path: Path):
    (tmp_path / "astro.config.mjs").write_text("export default {}")
    assert foreign_config_markers(tmp_path, "astro") == []


# ---- CHECK_035/036/037 skip-by-declaration --------------------------


def test_check_035_skips_on_wordpress(tmp_path: Path):
    # Stray vite.config + bad vite dep would normally fail; the
    # wordpress declaration short-circuits before the heuristic runs.
    _toml(tmp_path, _stack("wordpress"))
    _config(tmp_path, "vite.config.ts")
    _pkg(tmp_path, {"vite": "^5.0.0"})
    r = run_035(str(tmp_path))
    assert r.status == "warn"
    assert "wordpress" in r.message


def test_check_036_skips_on_static(tmp_path: Path):
    _toml(tmp_path, _stack("static"))
    _config(tmp_path, "astro.config.mjs")
    _pkg(tmp_path, {"astro": "^4.0.0"})  # astro 4 would normally fail
    r = run_036(str(tmp_path))
    assert r.status == "warn"
    assert "static" in r.message


def test_check_037_skips_on_none(tmp_path: Path):
    _toml(tmp_path, _stack("none"))
    _pkg(tmp_path, {}, scripts={})  # no build/dev would normally fail
    r = run_037(str(tmp_path))
    assert r.status == "warn"
    assert "none" in r.message


def test_check_035_falls_through_when_no_declaration(tmp_path: Path):
    # No lamill.toml → existing heuristic runs. Vite 5 + vite.config
    # still fails (needs a config file for the check to engage).
    _config(tmp_path, "vite.config.ts")
    _pkg(tmp_path, {"vite": "^5.0.0"})
    r = run_035(str(tmp_path))
    assert r.status == "fail"


def test_check_035_passes_on_astro_declaration_with_good_vite(tmp_path: Path):
    # astro is a JS framework → NOT short-circuited; heuristic runs.
    _toml(tmp_path, _stack("astro"))
    _config(tmp_path, "vite.config.ts")
    _pkg(tmp_path, {"vite": "^6.0.0", "astro": "^5.0.0"})
    r = run_035(str(tmp_path))
    assert r.status == "pass"


def test_check_037_falls_through_when_no_declaration(tmp_path: Path):
    _pkg(tmp_path, {}, scripts={})  # missing build/dev
    r = run_037(str(tmp_path))
    assert r.status == "fail"


# ---- CHECK_151 stack-drift ------------------------------------------


def test_drift_warn_no_toml(tmp_path: Path):
    r = run_151(str(tmp_path))
    assert r.status == "warn"
    assert "no lamill.toml" in r.message


def test_drift_warn_no_stack_table(tmp_path: Path):
    _toml(tmp_path, _DEPLOY)
    r = run_151(str(tmp_path))
    assert r.status == "warn"
    assert "[stack]" in r.message


def test_drift_warn_on_parse_error(tmp_path: Path):
    _toml(tmp_path, _DEPLOY + '[stack]\nframework = "bogus-fw"\n')
    r = run_151(str(tmp_path))
    assert r.status == "warn"
    assert "CHECK_059" in r.message


def test_drift_pass_clean_astro(tmp_path: Path):
    _toml(tmp_path, _stack("astro"))
    _pkg(tmp_path, {"astro": "^5.0.0"})
    (tmp_path / "astro.config.mjs").write_text("export default {}")
    r = run_151(str(tmp_path))
    assert r.status == "pass"


def test_drift_fail_primary_mismatch(tmp_path: Path):
    # Declared astro, but package.json has next → primary mismatch.
    _toml(tmp_path, _stack("astro"))
    _pkg(tmp_path, {"next": "^14.0.0"})
    r = run_151(str(tmp_path))
    assert r.status == "fail"
    assert "nextjs" in r.message


def test_drift_fail_foreign_config_lamillrentals(tmp_path: Path):
    # The lamillrentals case: astro declared + detected, stray root
    # vite.config.ts lingers from the migration.
    _toml(tmp_path, _stack("astro"))
    _pkg(tmp_path, {"astro": "^5.0.0"})
    (tmp_path / "vite.config.ts").write_text("export default {}")
    r = run_151(str(tmp_path))
    assert r.status == "fail"
    assert "vite.config.ts" in r.message


def test_drift_pass_when_detection_inconclusive(tmp_path: Path):
    # Declared astro but no package.json → classify returns None →
    # nothing to compare → pass (don't fail on absence).
    _toml(tmp_path, _stack("astro"))
    r = run_151(str(tmp_path))
    assert r.status == "pass"
