"""v35.F incr 11 — neutral repo-walk leaf, extracted from cli.py so both
cli.py (fleet check) and fix_cli.py (fix engine) depend on it instead of on
each other (breaks the would-be cli <-> fix_cli cycle). Pure stdlib.
"""
from __future__ import annotations


def _is_likely_repo(path) -> bool:
    """Heuristic: an immediate child of repos_dir counts as a repo if it's
    a directory and not a hidden/special name. We don't require .git to
    exist (a project can be missing its repo and we still want to report)."""
    from pathlib import Path
    p = Path(path)
    if not p.is_dir():
        return False
    name = p.name
    if name.startswith(".") or name in ("node_modules", "tarball", "__pycache__"):
        return False
    return True


def _iterate_repos(repos_dir, ignore: list[str] | None = None):
    """List immediate-child directories of `repos_dir` that look like repos.
    Sorted alphabetically for stable output. If `ignore` is given, drop
    repos whose name matches (case-insensitive) — the portfolio CLI repo
    itself is filtered by default via config (see `DEFAULT_IGNORE_REPOS`)."""
    from pathlib import Path
    base = Path(repos_dir)
    if not base.is_dir():
        return []
    skip_names = {n.lower() for n in (ignore or [])}
    return sorted(
        [p for p in base.iterdir()
         if _is_likely_repo(p) and p.name.lower() not in skip_names],
        key=lambda p: p.name.lower(),
    )
