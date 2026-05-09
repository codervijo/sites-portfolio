"""v5.A — Universal check catalog.

Public API:
  - `CheckResult` (status + message)
  - `list_checks(category=..., ids=...)` — catalog metadata
  - `get_check(id)` — one CheckSpec by ID
  - `run_check(id, repo_path)` — single check against a repo
  - `run_checks(repo_path, category=..., ids=..., skip_checks=...)` — many

Add a new check by dropping `check_NNN_<slug>.py` into the right category
directory (e.g. `portfolio/checks/scaffold/`). The registry auto-discovers.
"""
from .config import CheckConfig, load_config
from .registry import (
    CheckSpec,
    get_check,
    list_checks,
    reset_cache,
    run_check,
    run_checks,
)
from .result import CheckResult

__all__ = [
    "CheckConfig",
    "CheckResult",
    "CheckSpec",
    "get_check",
    "list_checks",
    "load_config",
    "reset_cache",
    "run_check",
    "run_checks",
]
