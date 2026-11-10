"""CHECK_162 — the site's GA4 measurement ID is recorded in
`lamill.toml [analytics] ga4_id` (v49.B).

The fix is the idempotent "ensure GA4 property" step, in order:

  1. `lamill.toml` already has an ID → nothing to do.
  2. The site source already loads exactly one real `G-` ID → adopt it
     (records the ID; no API call). Covers the hand-wired sites.
  3. A property for the domain exists in the fleet GA4 account
     (`GA4_ACCOUNT_ID`) → reuse it.
  4. It exists only in another GA4 account → manual: move it first
     (v49.A (g) — the pre-existing properties go last).
  5. Nothing exists → create property + web stream (14-month retention).

`warn` severity so it never blocks the v48.D pre-deploy gate. Not
applicable to non-web projects, HostGator sites, dark sites, and
client-owned sites (per-client GA4 accounts are out of v49's scope).
"""
from __future__ import annotations

import re
from pathlib import Path

from portfolio import lamill_toml
from portfolio.fix_helpers import FixerSpec, FixResult
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

from ..result import CheckResult

CHECK_ID = "CHECK_162"
CHECK_NAME = "ga4-id-recorded"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "GA4 measurement ID recorded in lamill.toml [analytics] ga4_id "
    "(`project fix` adopts it from source, reuses or creates the property — v49.B)."
)

_GA_ID = re.compile(r"\bG-[A-Z0-9]{6,12}\b")
_SRC_EXT = (".astro", ".tsx", ".ts", ".jsx", ".js", ".html", ".vue", ".svelte")
_SKIP_DIRS = {"node_modules", "dist", "build", ".astro", ".output", ".vercel",
              ".wrangler", ".next", ".git", "genai", "docs", "tests", "__tests__",
              "rankmill-output"}


def _not_applicable(base: Path) -> str | None:
    """Reason the check doesn't apply to this repo, else None."""
    if not (base / "package.json").is_file():
        return "not a web project"
    if not (base / LAMILL_TOML_FILENAME).is_file():
        return "no lamill.toml"
    try:
        doc = lamill_toml.load(base)
    except Exception:  # unparseable → CHECK_059's job, not ours
        return "lamill.toml unparseable (see CHECK_059)"
    if doc is not None and doc.deploy is not None and doc.deploy.platform == "hostgator":
        return "HostGator site"
    try:
        from ..config import load_config
        if base.name.lower() in {s.lower() for s in load_config().dark_sites}:
            return "dark site"
    except Exception:  # config unreadable → don't block the check on it
        pass
    try:
        from portfolio.data import load_domains
        row = next((d for d in load_domains() if d.name.lower() == base.name.lower()), None)
        if row is not None and row.is_client:
            return "client-owned site (per-client GA4 account)"
    except Exception:
        pass
    return None


def recorded_id(base: Path) -> str | None:
    doc = lamill_toml.load(base)
    if doc is None or doc.analytics is None:
        return None
    return doc.analytics.ga4_id or None


def source_ids(base: Path) -> set[str]:
    """Real `G-` IDs referenced in the site's source (placeholders like
    `G-XXXXXXXXXX` excluded)."""
    found: set[str] = set()
    candidates = [base / "index.html"]
    src = base / "src"
    if src.is_dir():
        for p in src.rglob("*"):
            if p.suffix in _SRC_EXT and not (_SKIP_DIRS & set(p.relative_to(base).parts)):
                candidates.append(p)
    for p in candidates:
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for m in _GA_ID.findall(text):
            if set(m[2:]) != {"X"}:
                found.add(m)
    return found


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    reason = _not_applicable(base)
    if reason:
        return CheckResult(status="pass", message=f"{reason} — n/a")
    ga = recorded_id(base)
    if ga:
        return CheckResult(status="pass", message=f"GA4 ID recorded: {ga}")
    return CheckResult(
        status="warn",
        message="no GA4 ID in lamill.toml [analytics] — `project fix` to adopt/reuse/create",
    )


_INDEX: list | None = None  # one GA4 stream index per process (fleet runs)


def _write(base: Path, ga_id: str) -> Path:
    from portfolio import lamill_toml_edit
    lamill_toml_edit.set_table(base, "analytics", {"ga4_id": ga_id})
    return base / LAMILL_TOML_FILENAME


def _fix(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    global _INDEX
    base = Path(project_dir)
    reason = _not_applicable(base)
    if reason:
        return FixResult("nothing-to-do", f"{reason} — n/a", [])
    if recorded_id(base):
        return FixResult("nothing-to-do", "GA4 ID already recorded", [])

    ids = source_ids(base)
    if len(ids) > 1:
        return FixResult("manual", f"source loads several GA4 IDs ({', '.join(sorted(ids))}) — pick one", [])
    if len(ids) == 1:
        (ga,) = ids
        if dry_run:
            return FixResult("would-fix", f"adopt {ga} from source", [])
        return FixResult("fixed", f"adopted {ga} from source", [_write(base, ga)])

    from portfolio import apikeys, ga4_admin
    if not ga4_admin.has_token():
        return FixResult("manual", "GA4 sign-in missing — run `lamill settings ga4 auth`", [])
    account_id = apikeys.get_key("GA4_ACCOUNT_ID")
    if not account_id:
        return FixResult("manual", "GA4_ACCOUNT_ID not set — `lamill settings apikeys set GA4_ACCOUNT_ID <id>`", [])
    try:
        if _INDEX is None:
            _INDEX = ga4_admin.stream_index()
        out = ga4_admin.ensure_property(base.name, account_id, index=_INDEX, dry_run=dry_run)
    except ga4_admin.GA4TransientError as e:
        return FixResult("error", f"transient GA4 failure ({e}) — retry later", [])
    except ga4_admin.GA4AdminError as e:
        return FixResult("error", str(e)[:300], [])

    if out.status == "would-create":
        return FixResult("would-fix", f"create GA4 property {base.name} in account {account_id}", [])
    if out.status == "elsewhere":
        return FixResult("manual", f"GA4 property exists in {out.detail} ({out.measurement_id}) — move it to the fleet account first", [])
    if out.status == "ambiguous":
        return FixResult("manual", f"several fleet-account properties match ({out.detail}) — keep one", [])
    if dry_run:  # "found" on a dry run
        return FixResult("would-fix", f"record existing {out.measurement_id}", [])
    verb = "created" if out.status == "created" else "reused"
    return FixResult("fixed", f"{verb} GA4 property → {out.measurement_id}", [_write(base, out.measurement_id)])


fix_tier_1 = FixerSpec(
    check_id="",
    tier=1,
    summary="record GA4 ID (adopt from source / reuse / create property)",
    apply=_fix,
)
