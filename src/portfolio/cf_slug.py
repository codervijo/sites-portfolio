"""Cloudflare project slug resolution + fleet collision guard (BUG-103).

A site's CF project name is persisted in its `wrangler.jsonc` `name` at
bootstrap. Deploy reads it back from there instead of recomputing it, so a
naming-rule change never renames an existing site's project. Sites without
a `wrangler.jsonc` keep the legacy TLD-dropping rule.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CF_PLATFORMS = ("cf-pages", "cf-workers")


def new_project_name(domain: str) -> str:
    """Slug for a NEW bootstrap: the full domain, dots → hyphens.

    `lamill.store` → `lamill-store`, `app.foo.io` → `app-foo-io`. Keeping
    the TLD makes same-stem domains (`lamill.store` / `lamill.pics`)
    distinct (BUG-098 / BUG-103).
    """
    base = re.sub(r"[^a-z0-9-]", "-", domain.lower()).strip("-")
    return re.sub(r"-{2,}", "-", base)


def legacy_project_name(domain: str) -> str:
    """Pre-BUG-103 rule: drop the TLD. Only for sites with no wrangler.jsonc."""
    base = domain.lower().rsplit(".", 1)[0]
    base = re.sub(r"[^a-z0-9-]", "-", base).strip("-")
    return base or domain.lower().replace(".", "-")


def wrangler_name(project_dir: Path) -> str | None:
    """`name` from `<project_dir>/wrangler.jsonc`, or None if absent/unreadable."""
    from .deploy import _strip_jsonc_comments

    path = Path(project_dir) / "wrangler.jsonc"
    if not path.is_file():
        return None
    try:
        name = json.loads(_strip_jsonc_comments(path.read_text())).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    return name.strip() if isinstance(name, str) and name.strip() else None


def resolve_slug(project_dir: Path, domain: str) -> str:
    """The CF project slug deploy must use for this site."""
    return wrangler_name(project_dir) or legacy_project_name(domain)


def _is_cf_site(site_dir: Path) -> bool:
    from . import lamill_toml
    try:
        doc = lamill_toml.load(site_dir)
    except Exception:  # unparseable lamill.toml → not ours to judge here
        return False
    return bool(doc and doc.deploy and doc.deploy.platform in CF_PLATFORMS)


def find_slug_collisions(domain: str, slug: str, sites_root: Path) -> list[str]:
    """Other CF-deployed sites under `sites_root` that resolve to `slug`."""
    hits: list[str] = []
    if not Path(sites_root).is_dir():
        return hits
    for site_dir in sorted(Path(sites_root).iterdir()):
        if not site_dir.is_dir() or site_dir.name.lower() == domain.lower():
            continue
        if not (site_dir / "lamill.toml").is_file() or not _is_cf_site(site_dir):
            continue
        if resolve_slug(site_dir, site_dir.name) == slug:
            hits.append(site_dir.name)
    return hits
