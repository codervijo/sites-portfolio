"""Stack-category checks: package.json shape, lockfile discipline (pnpm-only),
Vite/Astro version compatibility with deploy targets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_package_json(repo_path: str) -> dict[str, Any] | None:
    """Returns the parsed package.json or None if missing/invalid."""
    p = Path(repo_path) / "package.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _is_web_project(repo_path: str) -> bool:
    """A web project has package.json at root."""
    return (Path(repo_path) / "package.json").is_file()


def _has_vite_config(repo_path: str) -> bool:
    base = Path(repo_path)
    return any((base / f"vite.config.{ext}").is_file()
               for ext in ("ts", "js", "mjs", "cjs"))


def _has_astro_config(repo_path: str) -> bool:
    base = Path(repo_path)
    return any((base / f"astro.config.{ext}").is_file()
               for ext in ("ts", "js", "mjs", "cjs"))


def _parse_semver_min(version_spec: str) -> int | None:
    """Extract the minimum major version from a semver-style spec like
    "^6.1.0" or "~5", returning the int or None if unparseable."""
    import re
    m = re.search(r"\d+", version_spec)
    if not m:
        return None
    try:
        return int(m.group(0))
    except ValueError:
        return None
