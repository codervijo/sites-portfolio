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


# v27.E — re-export the pure classifier helpers so the stack checks have
# one import source for both detection (`foreign_config_markers`) and the
# non-JS framework set.
from ...stack_classifier import NON_JS_FRAMEWORKS, foreign_config_markers  # noqa: E402,F401


def declared_stack(repo_path: str) -> str | None:
    """Return `[stack].framework` from `<repo_path>/lamill.toml`, or None.

    None when the file is absent, has no `[stack]` table, or fails to
    parse. Per the additive-optional invariant (docs/CLAUDE.md), a
    missing declaration is the baseline — callers fall back to the
    file-system heuristic rather than warning. Parse errors are swallowed
    to None here so this helper never raises into a check's hot path;
    CHECK_151 surfaces parse errors itself via its own `load()`.
    """
    from ...lamill_toml import ParseError, load
    try:
        doc = load(Path(repo_path))
    except ParseError:
        return None
    if doc is None or doc.stack is None:
        return None
    return doc.stack.framework
