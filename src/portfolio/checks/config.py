"""v5.A — `~/.config/portfolio/config.toml` loader.

Layout:
  [git]
  repos_dir = "~/work/projects/sites"   # where to scan for repos
  github_token = ""                      # optional, enables CHECK_025-027
  skip_checks = []                       # e.g. ["CHECK_025", "CHECK_026"]
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH_DEFAULT = Path.home() / ".config" / "portfolio" / "config.toml"


@dataclass
class CheckConfig:
    """Resolved config for catalog runs. All fields have defaults so missing
    config.toml is tolerated (each load returns a CheckConfig with defaults).
    """
    repos_dir: Path = field(default_factory=lambda: Path.home() / "work" / "projects" / "sites")
    github_token: str = ""
    skip_checks: list[str] = field(default_factory=list)


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
    repos_dir_raw = git.get("repos_dir") or ""
    if repos_dir_raw:
        repos_dir = Path(os.path.expanduser(str(repos_dir_raw)))
    else:
        repos_dir = CheckConfig().repos_dir
    return CheckConfig(
        repos_dir=repos_dir,
        github_token=str(git.get("github_token") or ""),
        skip_checks=[str(s) for s in git.get("skip_checks", []) or []],
    )
