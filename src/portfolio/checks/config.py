"""v5.A — `~/.config/portfolio/config.toml` loader.

Layout:
  [git]
  repos_dir = "~/work/projects/sites"   # where to scan for repos
  github_token = ""                      # optional
  skip_checks = []                       # e.g. ["CHECK_011"] (skip a check globally)
  ignore_repos = ["portfolio", "rankmill"]   # repos to exclude from `check --git`

  [fleet]
  dark_sites = ["csinorcal.church"]      # 2026-05-27 — domains excluded from
                                          # fleet-wide auto-remediation (`fleet fix`).
                                          # Internal/private sites that shouldn't
                                          # receive auto-toggles like `always_use_https`.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH_DEFAULT = Path.home() / ".config" / "portfolio" / "config.toml"

# Repos that are always excluded from `check --git` even without explicit
# config — these are sibling Python-CLI tools, not website projects, so the
# catalog's stack/deploy/SEO checks would all skip and create noise. Users
# can override by listing the repo in [git] ignore_repos = []  (empty list =
# no defaults).
DEFAULT_IGNORE_REPOS = ["portfolio", "rankmill"]

# 2026-05-27 — Domains excluded from fleet-wide auto-remediation walks
# (`fleet fix`). Dark sites are internal/private projects where automatic
# write-actions (always_use_https toggles, redirect normalizations) aren't
# desired — operator manages those manually. Per CLAUDE.md global memory:
# "Dark sites — not for public SEO; csinorcal.church is internal; ignore
# its SEO failures." User overrides by listing in [fleet] dark_sites = [].
DEFAULT_DARK_SITES = ["csinorcal.church"]


@dataclass
class CheckConfig:
    """Resolved config for catalog runs. All fields have defaults so missing
    config.toml is tolerated (each load returns a CheckConfig with defaults).
    """
    repos_dir: Path = field(default_factory=lambda: Path.home() / "work" / "projects" / "sites")
    github_token: str = ""
    skip_checks: list[str] = field(default_factory=list)
    ignore_repos: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_REPOS))
    dark_sites: list[str] = field(default_factory=lambda: list(DEFAULT_DARK_SITES))


def load_config(path: Path | None = None) -> CheckConfig:
    """Read config.toml from `path` (default `~/.config/portfolio/config.toml`).
    Returns a CheckConfig with defaults filled in for any missing fields.
    Missing file → all defaults; never raises on missing file."""
    p = path or CONFIG_PATH_DEFAULT
    if not p.exists():
        return CheckConfig()
    try:
        data = tomllib.loads(p.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return CheckConfig()
    git = data.get("git", {}) if isinstance(data.get("git"), dict) else {}
    fleet = data.get("fleet", {}) if isinstance(data.get("fleet"), dict) else {}
    repos_dir_raw = git.get("repos_dir") or ""
    if repos_dir_raw:
        repos_dir = Path(os.path.expanduser(str(repos_dir_raw)))
    else:
        repos_dir = CheckConfig().repos_dir
    if "ignore_repos" in git:
        # User explicitly set the list (possibly empty) — honor it as-is.
        ignore_repos = [str(s) for s in git.get("ignore_repos") or []]
    else:
        ignore_repos = list(DEFAULT_IGNORE_REPOS)
    if "dark_sites" in fleet:
        # User explicitly set the list (possibly empty) — honor it as-is.
        dark_sites = [str(s).lower() for s in fleet.get("dark_sites") or []]
    else:
        dark_sites = [s.lower() for s in DEFAULT_DARK_SITES]
    return CheckConfig(
        repos_dir=repos_dir,
        github_token=str(git.get("github_token") or ""),
        skip_checks=[str(s) for s in git.get("skip_checks", []) or []],
        ignore_repos=ignore_repos,
        dark_sites=dark_sites,
    )
