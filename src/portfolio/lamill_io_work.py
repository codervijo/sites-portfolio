"""Add a lamill.io /work entry for a site, so the studio hub links to every
project it ships.

Writes `sites/lamill.io/src/content/work/<slug>.ts` as a DRAFT (hidden from
lamill.io's public /work listing + sitemap until reviewed; still previewable
by URL). lamill.io auto-collects the file via `import.meta.glob` — no index
to touch.

Left UNCOMMITTED in the lamill.io repo for review (never auto-commits into a
sibling repo; lamill.io redeploys on push and draft status keeps it unlisted
regardless). Idempotent: skips if the entry already exists (no clobber).

Used by the standalone `lamill new work <domain>` command and automatically
at the end of `lamill new deploy`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from .project import SITES_ROOT

LAMILL_IO = "lamill.io"
_WORK_REL = "src/content/work"

# lamill.toml [stack].framework -> lamill.io "stack" chips. Unknown/absent
# framework -> no chips (human fills them in the draft).
_STACK_CHIPS: dict[str, list[str]] = {
    "astro": ["Astro"],
    "vite-react": ["React", "Vite"],
    "tanstack-start": ["TanStack Start"],
    "tanstack": ["TanStack Start"],
    "next": ["Next.js"],
}


@dataclass
class WorkEntryResult:
    status: str            # "created" | "exists" | "no-lamill-io" | "dry-run"
    slug: str
    path: Path | None
    message: str


def slug_for(domain: str) -> str:
    """`drdebug.dev` -> `drdebug`; `cottagefoodmap.com` -> `cottagefoodmap`.

    Matches lamill.io's existing work-entry slugs (the registrable label,
    kebab-case)."""
    first = domain.strip().lower().lstrip("/").split("/")[0].split(".")[0]
    return re.sub(r"[^a-z0-9-]+", "-", first).strip("-")


def _today_iso() -> str:
    return _date.today().isoformat()


def _ts_str(s: str) -> str:
    """Escape for a double-quoted TS string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _derive_stack(domain: str) -> list[str]:
    """Map the site's declared [stack].framework to lamill.io stack chips."""
    from . import lamill_toml
    try:
        doc = lamill_toml.load(SITES_ROOT / domain)
    except Exception:
        doc = None
    fw = (
        doc.stack.framework.strip().lower()
        if doc and doc.stack and doc.stack.framework
        else ""
    )
    return list(_STACK_CHIPS.get(fw, []))


def render_entry(*, slug: str, title: str, url: str, date: str,
                 summary: str, description: str,
                 tags: list[str], stack: list[str]) -> str:
    def arr(xs: list[str]) -> str:
        return "[" + ", ".join(f'"{_ts_str(x)}"' for x in xs) + "]"

    return (
        'import type { WorkEntry } from "@/lib/content";\n\n'
        "// Auto-generated DRAFT (`lamill new work` / `new deploy`). Hidden from\n"
        "// the public /work listing + sitemap until you fill in the copy and\n"
        '// flip status to "published".\n'
        "const entry: WorkEntry = {\n"
        f'  slug: "{_ts_str(slug)}",\n'
        f'  title: "{_ts_str(title)}",\n'
        f'  url: "{_ts_str(url)}",\n'
        f'  summary: "{_ts_str(summary)}",\n'
        f'  description: "{_ts_str(description)}",\n'
        f'  date: "{date}",\n'
        f"  tags: {arr(tags)},\n"
        f"  stack: {arr(stack)},\n"
        '  status: "draft",\n'
        "  body: [],\n"
        "};\n\nexport default entry;\n"
    )


def add_work_entry(domain: str, *, date: str | None = None,
                   title: str | None = None,
                   dry_run: bool = False) -> WorkEntryResult:
    """Create the lamill.io work-entry draft for `domain`. Idempotent."""
    slug = slug_for(domain)
    lamill_dir = SITES_ROOT / LAMILL_IO
    if not lamill_dir.is_dir():
        return WorkEntryResult("no-lamill-io", slug, None,
                               f"{LAMILL_IO}/ not present — skipped")
    target = lamill_dir / _WORK_REL / f"{slug}.ts"
    if target.exists():
        return WorkEntryResult("exists", slug, target,
                               f"work/{slug}.ts already exists — skipped (no clobber)")

    ttl = title or slug
    entry = render_entry(
        slug=slug, title=ttl, url=f"https://{domain}/",
        date=date or _today_iso(),
        summary="TODO — one-line summary of what this site does.",
        description=f"{ttl} — TODO: SEO description for the case study.",
        tags=[], stack=_derive_stack(domain),
    )
    if dry_run:
        return WorkEntryResult("dry-run", slug, target,
                               f"would write draft work/{slug}.ts ({len(entry)} bytes)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(entry)
    return WorkEntryResult(
        "created", slug, target,
        f"wrote DRAFT work/{slug}.ts — uncommitted; review + set status:\"published\"",
    )
