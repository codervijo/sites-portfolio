"""CHECK_167 — unknown paths return 404 on a static multi-page site (v46.G–I).

Cloudflare's `assets.not_found_handling: "single-page-application"` answers
every unknown URL with the homepage (HTTP 200) — a soft-404 on a static Astro
site. Fleet probe 2026-11-25: 16 live sites answered `/zz-no-such-page` with
200; 14 were Astro on Cloudflare with the SPA value, written by `new
bootstrap` itself until v46.I.

  pass  — static site: `not_found_handling` is "404-page", a 404 page exists,
          and (when the site is reachable) a random path answers 404.
  fail  — static site with the SPA value / no value, no 404 page, or a live
          random path answering 200.
  warn  — repo fixed but the live site still answers 200 (not deployed yet),
          or the live probe couldn't reach the site.

Not applicable: non-domain dirs, backups, archived, no `wrangler.jsonc`
(not on Cloudflare), and client-rendered SPA stacks (`[stack] framework`
vite-react / tanstack / …) — their router needs the fallback; fixing them
means prerendering first (v46.G (b)).

Severity `warn` while the fleet backfill (v46.I) is pending — the v46
fix-first posture; promote to `error` once the fleet is clean.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

from portfolio.fix_helpers import FixerSpec, FixResult

from ..result import CheckResult

CHECK_ID = "CHECK_167"
CHECK_NAME = "unknown-path-404"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Static (Astro) site on Cloudflare answers unknown paths with a real 404: "
    "wrangler.jsonc not_found_handling = \"404-page\" + a 404 page, and a live "
    "random path returns 404 (not the homepage)."
)

_DOMAIN_RE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")
_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def _stack(base: Path) -> str | None:
    try:
        from portfolio import lamill_toml
        doc = lamill_toml.load(base)
        if doc is not None and doc.stack is not None:
            return doc.stack.framework
    except Exception:  # noqa: BLE001 — additive-optional: absent/invalid → heuristics
        pass
    return None


def _not_applicable(base: Path) -> str | None:
    from portfolio.not_found import wants_spa_fallback
    domain = base.name.lower()
    if not _DOMAIN_RE.match(domain):
        return "not a domain-shaped dir"
    if domain.endswith((".bup", ".old", ".bak")):
        return "backup copy of a site dir"
    try:
        from portfolio.fleet_repos import _archived_reason
        if _archived_reason(base) is not None:
            return "archived"
    except Exception:  # noqa: BLE001
        pass
    if not (base / "wrangler.jsonc").is_file():
        return "not on Cloudflare (no wrangler.jsonc)"
    stack = _stack(base)
    if wants_spa_fallback(stack, base):
        return (f"client-rendered SPA ({stack or 'no Astro config'}) — needs the "
                "SPA fallback until it's prerendered")
    return None


def _live_status(domain: str, client=None) -> int | None:
    """HTTP status for a random path on the live site; None when unreachable."""
    import httpx
    url = f"https://{domain}/zz-lamill-404-probe-{secrets.token_hex(4)}"
    try:
        if client is not None:
            return client.get(url).status_code
        with httpx.Client(timeout=10.0, follow_redirects=True,
                          headers={"User-Agent": _UA}) as c:
            return c.get(url).status_code
    except httpx.HTTPError:
        return None


def _repo_problems(base: Path) -> list[str]:
    from portfolio.not_found import STATIC_VALUE, has_404_page, not_found_value
    problems = []
    value = not_found_value((base / "wrangler.jsonc").read_text())
    if value != STATIC_VALUE:
        problems.append(f'wrangler.jsonc not_found_handling is '
                        f'{repr(value) if value else "unset"}, should be "{STATIC_VALUE}"')
    if not has_404_page(base):
        problems.append("no 404 page (src/pages/404.astro)")
    return problems


def run(repo_path: str, *, live: bool = True, client=None) -> CheckResult:
    base = Path(repo_path).resolve()
    reason = _not_applicable(base)
    if reason:
        return CheckResult(status="pass", message=f"n/a — {reason}")
    problems = _repo_problems(base)
    if problems:
        return CheckResult(status="fail",
                           message="; ".join(problems) + " — unknown URLs serve the "
                                   "homepage (soft-404). Fix: `lamill project fix "
                                   f"{base.name} --rule {CHECK_ID} --apply`, then "
                                   "commit + push the site.")
    if not live:
        return CheckResult(status="pass", message="repo answers unknown paths with 404")
    code = _live_status(base.name.lower(), client)
    if code is None:
        return CheckResult(status="warn",
                           message="repo is correct; live probe couldn't reach the site")
    if code == 404:
        return CheckResult(status="pass", message="unknown paths answer 404 (live)")
    if code == 200:
        return CheckResult(status="warn",
                           message="repo is correct but the live site still answers 200 "
                                   "for an unknown path — commit + push to deploy the fix")
    return CheckResult(status="warn",
                       message=f"repo is correct; live random path answered HTTP {code}")


def _apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    from portfolio.not_found import (STATIC_VALUE, ensure_astro_404, has_404_page,
                                     not_found_value, set_not_found_value)
    base = project_dir.resolve()
    reason = _not_applicable(base)
    if reason:
        return FixResult(status="nothing-to-do", summary=f"n/a — {reason}", files_touched=[])
    wrangler = base / "wrangler.jsonc"
    text = wrangler.read_text()
    steps = []
    if not_found_value(text) != STATIC_VALUE:
        steps.append(f'set wrangler.jsonc not_found_handling = "{STATIC_VALUE}"')
    if not has_404_page(base):
        steps.append("add src/pages/404.astro")
    if not steps:
        return FixResult(status="nothing-to-do", summary="already answers unknown paths with 404",
                         files_touched=[])
    if dry_run:
        return FixResult(status="would-fix", summary="would " + "; ".join(steps), files_touched=[])
    touched: list[Path] = []
    if not_found_value(text) != STATIC_VALUE:
        try:
            wrangler.write_text(set_not_found_value(text, STATIC_VALUE))
        except ValueError as e:
            return FixResult(status="manual", summary=f"{e} — set assets.not_found_handling "
                             f'to "{STATIC_VALUE}" by hand', files_touched=[])
        touched.append(wrangler)
    if ensure_astro_404(base, base.name.lower()):
        touched.append(base / "src" / "pages" / "404.astro")
    return FixResult(status="fixed", summary="; ".join(steps) + " — commit + push to deploy",
                     files_touched=touched)


fix_tier_1 = FixerSpec(
    check_id="",   # registry rewrites at discovery time
    tier=1,
    summary='static site: wrangler.jsonc not_found_handling "404-page" + a 404 page',
    apply=_apply,
    edits_source=True,   # adds src/pages/404.astro → v50.D build check runs after --apply
)
