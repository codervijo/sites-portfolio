"""Tests for the `[fleet] dark_sites` config field (2026-05-27).

Closes the csinorcal.church incident: pre-fix, `fleet fix --rule
CHECK_150 --apply` toggled `always_use_https` on csinorcal.church
because the dark-site classification existed only in memory, not in
config. Post-fix, `load_config()` exposes `dark_sites` with a default
(csinorcal.church) and a `[fleet] dark_sites = [...]` override.
"""
from __future__ import annotations

from portfolio.checks.config import (
    DEFAULT_DARK_SITES,
    CheckConfig,
    load_config,
)


def _write_config(tmp_path, body: str):
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_default_dark_sites_includes_csinorcal():
    """The default list must include the historically known dark site,
    so a fresh operator install doesn't auto-toggle settings on it."""
    assert "csinorcal.church" in DEFAULT_DARK_SITES


def test_load_config_missing_file_returns_defaults(tmp_path):
    """Missing config.toml — CheckConfig defaults apply, including
    dark_sites=DEFAULT_DARK_SITES."""
    cfg = load_config(tmp_path / "does-not-exist.toml")
    assert cfg.dark_sites == [s.lower() for s in DEFAULT_DARK_SITES]


def test_load_config_no_fleet_section_returns_default_dark_sites(tmp_path):
    """A config.toml with only [git] (no [fleet]) keeps the default
    dark_sites — operator hasn't opted out."""
    p = _write_config(tmp_path, '[git]\nrepos_dir = "~/x"\n')
    cfg = load_config(p)
    assert cfg.dark_sites == [s.lower() for s in DEFAULT_DARK_SITES]


def test_load_config_explicit_dark_sites_overrides_default(tmp_path):
    """[fleet] dark_sites = [...] replaces the default entirely (mirrors
    ignore_repos semantics — explicit list, not append)."""
    p = _write_config(tmp_path, (
        '[fleet]\n'
        'dark_sites = ["intranet.example", "private.test"]\n'
    ))
    cfg = load_config(p)
    assert cfg.dark_sites == ["intranet.example", "private.test"]
    # csinorcal.church is NOT in the override → operator explicitly opted out.
    assert "csinorcal.church" not in cfg.dark_sites


def test_load_config_empty_dark_sites_disables_filter(tmp_path):
    """Empty list = operator explicitly says 'no dark sites' → filter
    becomes a no-op. Distinct from 'unset' (which uses defaults)."""
    p = _write_config(tmp_path, '[fleet]\ndark_sites = []\n')
    cfg = load_config(p)
    assert cfg.dark_sites == []


def test_load_config_dark_sites_lowercased(tmp_path):
    """Comparison is case-insensitive on the eligibility side; the
    loader normalizes input to lowercase up-front so comparisons stay
    consistent."""
    p = _write_config(tmp_path, (
        '[fleet]\n'
        'dark_sites = ["Internal.SITE", "MixedCase.example"]\n'
    ))
    cfg = load_config(p)
    assert cfg.dark_sites == ["internal.site", "mixedcase.example"]


def test_check_config_default_factory_returns_fresh_list():
    """The default_factory pattern prevents the dataclass-default-
    mutable-arg footgun — each CheckConfig instance gets its own list."""
    a = CheckConfig()
    b = CheckConfig()
    a.dark_sites.append("mutated.example")
    assert "mutated.example" not in b.dark_sites
