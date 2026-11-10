"""v49.E — `lamill fleet ga`: GA4 rollout across the fleet (ADR-0029).

One idempotent pass per in-scope site, each step probing before acting and
printing ✓ / ✗ / ↷:

  0. live?    — homepage answers < 400, else ↷ not live (v49.A (h)); a
                transport error (e.g. TLS blocked locally) continues with ↷.
  1. ID       — CHECK_162 fixer: recorded → adopt from source → reuse → create.
                Property — or the ID the source already loads — in another
                GA4 account → ↷ deferred (v49.A (g)).
  2. tag      — CHECK_163 fixer (per-stack injection + privacy sentence).
                Different `G-` in source / non-site-wide loader → ✗.
  3. build    — container build; built output must contain the ID, else
                every file this run touched is restored → ✗.
  4. commit   — only the files this run touched, then `git push`.
  5. live     — CHECK_164 `live_state`: ✓ live, ↷ deploying (no waiting).

Dry run by default (plan only — no API writes, no file writes). `--apply`
confirms per site; `--yes` skips the confirmation. A file this run would
touch that already has uncommitted edits stops that site (✗) — operator
work is never mixed into the GA4 commit.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .console import console

COMMIT_MSG = "GA4: tag {ga} (lamill fleet ga, ADR-0029)"
_BUILD_DIRS = ("dist", ".output", "build", ".vercel/output")
_SCAN_EXT = {".html", ".js", ".mjs"}


@dataclass
class SiteResult:
    domain: str
    outcome: str  # done | changed | deferred | skipped | failed | planned
    detail: str = ""
    touched: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- scope


def in_scope_sites(only: list[str] | None = None) -> list[tuple[str, Path]]:
    """Fleet-eligible repos (ignore_repos, delete-category, dark sites out),
    minus `*.bup` / `*.old` and whatever CHECK_162 deems not applicable
    (non-web, HostGator, client-owned, unparseable lamill.toml)."""
    from .checks.seo.check_162_ga4_id_recorded import _not_applicable
    from .fix_cli import _list_fleet_eligible_projects
    wanted = {o.lower() for o in only or []}
    out = []
    for name, path in _list_fleet_eligible_projects():
        if name.endswith((".bup", ".old")):
            continue
        if wanted and name.lower() not in wanted:
            continue
        if _not_applicable(path):
            continue
        out.append((name, path))
    return out


# ---------------------------------------------------------------- git / fs


def _git(base: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(base), capture_output=True, text=True, check=False)


def _dirty(base: Path) -> set[str]:
    out = _git(base, "status", "--porcelain", "--untracked-files=all").stdout
    return {line[3:].split(" -> ")[-1].strip('"') for line in out.splitlines() if line.strip()}


class Snapshot:
    """In-memory copy of every file a fixer could touch, so a failed build
    restores exactly the pre-run bytes (and removes files the run created)."""

    def __init__(self, base: Path):
        self.base = base
        self.files: dict[Path, bytes] = {}
        roots = [base / "lamill.toml", base / "index.html"]
        src = base / "src"
        paths = list(src.rglob("*")) if src.is_dir() else []
        for p in roots + paths:
            if p.is_file() and "node_modules" not in p.parts:
                self.files[p] = p.read_bytes()

    def restore(self, touched: list[Path]) -> None:
        for p in touched:
            if p in self.files:
                p.write_bytes(self.files[p])
            elif p.exists():
                p.unlink()


def built_output_has(base: Path, ga: str) -> bool:
    for d in _BUILD_DIRS:
        root = base / d
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.suffix in _SCAN_EXT and p.is_file():
                try:
                    if ga in p.read_text(errors="ignore"):
                        return True
                except OSError:
                    continue
    return False


def commit_and_push(base: Path, files: list[Path], ga: str) -> tuple[bool, str]:
    rels = [str(p.relative_to(base)) for p in files]
    for step in (["add", "--", *rels],
                 ["commit", "-m", COMMIT_MSG.format(ga=ga), "--", *rels]):
        r = _git(base, *step)
        if r.returncode != 0:
            return False, f"git {step[0]}: {(r.stderr or r.stdout).strip()[:200]}"
    sha = _git(base, "rev-parse", "--short", "HEAD").stdout.strip()
    r = _git(base, "push")
    if r.returncode != 0:
        return False, f"committed {sha}, push failed: {r.stderr.strip()[:200]} — `git pull --rebase && git push` in {base.name}"
    return True, sha


# ---------------------------------------------------------------- runner


def _mark(kind: str) -> str:
    return {"ok": "[green]✓[/]", "skip": "[yellow]↷[/]", "err": "[red]✗[/]"}[kind]


def _step(kind: str, label: str, msg: str) -> None:
    console.print(f"  {_mark(kind)} {label:<7} {msg}", highlight=False)


def _is_live(domain: str, base: Path) -> tuple[bool, str]:
    from .checks.seo._live import LiveFetchError, fetch_response_status, resolve_live_url
    origin = resolve_live_url(str(base)) or f"https://{domain}"
    try:
        code = fetch_response_status(origin + "/")
    except LiveFetchError as e:
        # Transport failure ≠ not live: a local network filter can break TLS
        # to whole TLDs (seen on every .xyz site, 2026-11-09). Carry on.
        return None, str(e)
    return code < 400, f"HTTP {code}"


def _account_of(ga: str) -> tuple[str, str] | None:
    """(account_id, account_name) holding measurement ID `ga`, from the
    shared CHECK_162 stream index; None when unknown / API unavailable."""
    from . import ga4_admin
    from .checks.seo import check_162_ga4_id_recorded as c162
    try:
        if c162._INDEX is None:
            if not ga4_admin.has_token():
                return None
            c162._INDEX = ga4_admin.stream_index()
    except ga4_admin.GA4AdminError:
        return None
    hit = next((h for h in c162._INDEX if h.measurement_id == ga), None)
    return (hit.account_id, hit.account_name) if hit else ("?", "an account foundervijo@ can't see")


def run_site(domain: str, base: Path, *, apply: bool, confirm: Callable[[str], bool],
             build: Callable[[Path], tuple[bool, str]],
             is_live: Callable[[str, Path], tuple[bool | None, str]] = _is_live,
             account_of: Callable[[str], tuple[str, str] | None] = _account_of) -> SiteResult:
    from .checks.seo import check_162_ga4_id_recorded as c162
    from .checks.seo import check_163_ga4_tag_in_source as c163
    from .checks.seo import check_164_ga4_live_tag as c164
    from .fix_helpers import FixResult

    console.print(f"[bold]{domain}[/]")
    live, why = is_live(domain, base)
    if live is False:
        _step("skip", "live", f"not live ({why}) — skipped")
        return SiteResult(domain, "skipped", f"not live ({why})")
    if live is None:
        _step("skip", "live", f"can't reach it from here ({why}) — continuing; live check will ↷")

    # ---- plan (no writes)
    p162 = c162._fix(base, dry_run=True, assume_yes=True)
    if p162.status == "manual":
        deferred = "move it" in p162.summary
        _step("skip" if deferred else "err", "id", p162.summary)
        return SiteResult(domain, "deferred" if deferred else "failed", p162.summary)
    if p162.status == "error":
        _step("err", "id", p162.summary)
        return SiteResult(domain, "failed", p162.summary)
    ga = c162.recorded_id(base)
    src_ids = c163.source_ids(base)
    existing = ga or (next(iter(src_ids)) if len(src_ids) == 1 else None)
    if existing:
        # v49.A (g): IDs living outside the fleet account go last (moved first).
        from . import apikeys
        acct = account_of(existing)
        fleet = (apikeys.get_key("GA4_ACCOUNT_ID") or "").strip()
        if acct is not None and fleet and acct[0] != fleet:
            msg = f"{existing} is in {acct[1]} — move it to the fleet account first"
            _step("skip", "id", msg)
            return SiteResult(domain, "deferred", msg)
    _step("ok" if ga else "skip", "id", ga or p162.summary)

    plan_id = existing or "G-(new)"
    tag_plan = c163._plan_tag(base, plan_id)
    if isinstance(tag_plan, FixResult):
        _step("err", "tag", tag_plan.summary)
        return SiteResult(domain, "failed", tag_plan.summary)
    tag_summary, tag_writes = tag_plan
    priv, priv_file = c163.privacy_state(base)
    if tag_writes:
        _step("skip", "tag", tag_summary)
    else:
        _step("ok", "tag", f"source loads {ga}")
    if priv == "missing" and priv_file is not None:
        _step("skip", "privacy", f"add GA sentence → {priv_file.relative_to(base)}")
    elif priv == "conflict":
        msg = (f"{priv_file.relative_to(base)} talks about analytics without naming Google Analytics "
               "(e.g. \"No analytics\") — rewrite it first; GA4 would make it false")
        _step("err", "privacy", msg)
        return SiteResult(domain, "failed", msg)
    elif priv == "missing":
        _step("err", "privacy", "privacy page has no <p> to append to — add the GA sentence by hand")

    will_privacy = priv == "missing" and priv_file is not None
    nothing_to_do = ga and not tag_writes and not will_privacy
    if nothing_to_do:
        return _live_step(domain, base, c164, "done")

    if not apply:
        return SiteResult(domain, "planned", tag_summary or "record ID")
    if not confirm(f"Apply GA4 to {domain}?"):
        _step("skip", "apply", "declined")
        return SiteResult(domain, "skipped", "declined")

    # ---- apply
    dirty_before = _dirty(base)
    snap = Snapshot(base)
    touched: list[Path] = []

    r162 = c162._fix(base, dry_run=False, assume_yes=True)
    if r162.status == "fixed":
        touched += [Path(p) for p in r162.files_touched]
        _step("ok", "id", r162.summary)
    elif r162.status != "nothing-to-do":
        _step("err", "id", r162.summary)
        return SiteResult(domain, "failed", r162.summary)
    ga = c162.recorded_id(base)

    r163 = c163._fix(base, dry_run=False, assume_yes=True)
    if r163.status == "fixed":
        touched += [Path(p) for p in r163.files_touched]
        _step("ok", "tag", r163.summary)
    elif r163.status != "nothing-to-do":
        snap.restore(touched)
        _step("err", "tag", r163.summary)
        return SiteResult(domain, "failed", r163.summary)

    clash = sorted(str(p.relative_to(base)) for p in touched if str(p.relative_to(base)) in dirty_before)
    if clash:
        snap.restore(touched)
        msg = f"uncommitted edits in {', '.join(clash)} — commit or stash them, then re-run"
        _step("err", "git", msg)
        return SiteResult(domain, "failed", msg)

    source_changed = any(p.name != "lamill.toml" for p in touched)
    if source_changed:
        ok, detail = build(base)
        if not ok or not built_output_has(base, ga):
            snap.restore(touched)
            msg = detail if not ok else f"built output doesn't contain {ga}"
            _step("err", "build", f"{msg} — changes reverted")
            return SiteResult(domain, "failed", msg)
        _step("ok", "build", f"{detail}; output contains {ga}")

    ok, detail = commit_and_push(base, touched, ga)
    if not ok:
        _step("err", "push", detail)
        return SiteResult(domain, "failed", detail, [str(p.relative_to(base)) for p in touched])
    _step("ok", "push", f"{detail} ({len(touched)} file(s))")
    res = _live_step(domain, base, c164, "changed")
    res.touched = [str(p.relative_to(base)) for p in touched]
    return res


def _live_step(domain: str, base: Path, c164, outcome: str) -> SiteResult:
    from .checks.seo import _live
    _live.clear_cache()
    state, detail = c164.live_state(base)
    if state == "live":
        _step("ok", "live", detail)
    elif state == "mismatch":
        _step("err", "live", detail)
        return SiteResult(domain, "failed", detail)
    else:
        _step("skip", "live", f"deploying — {detail}; re-run to confirm")
    return SiteResult(domain, outcome, detail)


def run(*, apply: bool, assume_yes: bool, only: list[str] | None = None,
        build: Callable[[Path], tuple[bool, str]] | None = None,
        confirm: Callable[[str], bool] | None = None) -> list[SiteResult]:
    import typer

    from .checks.seo import check_162_ga4_id_recorded as c162
    from .new_site import build_in_container

    c162._INDEX = None
    build = build or (lambda b: build_in_container(b))
    confirm = confirm or (lambda q: True if assume_yes else typer.confirm(q, default=False))
    sites = in_scope_sites(only)
    if not sites:
        console.print("[yellow]No in-scope sites.[/]")
        return []
    console.print(f"[dim]{'APPLY' if apply else 'DRY RUN'} — {len(sites)} site(s)[/]")
    results = []
    for name, path in sites:
        results.append(run_site(name, path, apply=apply, confirm=confirm, build=build))

    counts: dict[str, list[str]] = {}
    for r in results:
        counts.setdefault(r.outcome, []).append(r.domain)
    console.print()
    for outcome, kind in (("done", "ok"), ("changed", "ok"), ("planned", "skip"),
                          ("deferred", "skip"), ("skipped", "skip"), ("failed", "err")):
        if outcome in counts:
            names = counts[outcome]
            console.print(f"{_mark(kind)} {outcome:<8} {len(names):>3}  [dim]{', '.join(names)}[/]", highlight=False)
    if not apply and "planned" in counts:
        console.print("[dim]Dry run — `lamill fleet ga --apply` to execute (confirms per site).[/]")
    return results
