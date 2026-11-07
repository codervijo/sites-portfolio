"""CHECK_054 — wrangler.jsonc `name` matches the project directory slug."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _read_jsonc


def _expected_slug(dir_name: str) -> str:
    """`<domain>` → CF Pages project name. We strip TLDs to keep the slug short."""
    base = dir_name.split(".", 1)[0]
    # CF project names: lowercase alphanumeric + hyphens.
    return "".join(c if c.isalnum() else "-" for c in base.lower()).strip("-")


CHECK_ID = "CHECK_054"
CHECK_NAME = "wrangler-name-matches-slug"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = "wrangler.jsonc `name` matches the project slug — full domain with hyphens (`lamill-store`), or the legacy TLD-dropped form (`kwizicle`)."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / "wrangler.jsonc"
    if not p.is_file():
        return CheckResult(status="warn", message="not a CF Pages project — skipped")
    cfg = _read_jsonc(p)
    if cfg is None:
        return CheckResult(status="warn", message="wrangler.jsonc unreadable — skipped")
    from ...cf_slug import new_project_name
    declared = cfg.get("name")
    dir_name = Path(repo_path).name
    # BUG-103: new bootstraps keep the TLD (`lamill-store`); pre-BUG-103
    # sites keep their TLD-dropped slug (`kwizicle`). Both are conformant.
    expected = new_project_name(dir_name)
    if declared in (expected, _expected_slug(dir_name)):
        return CheckResult(status="pass", message=f'name="{declared}"')
    return CheckResult(status="warn",
                       message=f'name="{declared}", expected "{expected}" (from dir slug)')
