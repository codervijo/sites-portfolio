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

`--switch-old` (v49.F) turns step 1's ↷ deferred into a clean switch: a
fresh LaMill Sites property, the old ID replaced in lamill.toml / index.html /
src/, and hosting env vars that would override it (Vercel `PUBLIC_GA_ID` /
`VITE_GA_ID`) deleted after the build passes, before the push.

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
SWITCH_MSG = "GA4: switch {old} → {ga} (lamill fleet ga --switch-old, v49.F)"
_ENV_KEYS = {"PUBLIC_GA_ID", "VITE_GA_ID"}
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


def _undo_build_side_effects(base: Path, dirty_before: set[str], touched: list[Path]) -> None:
    """Builds can regenerate committed files (voltloop rewrites
    `public/sitemap.xml`). Restore tracked files the build changed that were
    clean before and that this run didn't write, so the repo is left as found."""
    ours = {str(p.relative_to(base)) for p in touched}
    tracked = set(_git(base, "ls-files").stdout.splitlines())
    stray = sorted((_dirty(base) - dirty_before - ours) & tracked)
    if stray:
        _git(base, "checkout", "--", *stray)


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


def commit_and_push(base: Path, files: list[Path], ga: str, msg: str | None = None) -> tuple[bool, str]:
    rels = [str(p.relative_to(base)) for p in files]
    for step in (["add", "--", *rels],
                 ["commit", "-m", msg or COMMIT_MSG.format(ga=ga), "--", *rels]):
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
             account_of: Callable[[str], tuple[str, str] | None] = _account_of,
             switch_old: bool = False,
             new_property: Callable[[str], str] | None = None,
             drop_env: Callable[[str, bool], list[str]] | None = None,
             other_account_id: Callable[[str], str | None] | None = None) -> SiteResult:
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
        old = c162._GA_ID.search(p162.summary)
        if deferred and switch_old and old:
            return _switch(domain, base, old.group(0), p162.summary.split(" — ")[0], apply=apply, confirm=confirm,
                           build=build, new_property=new_property, drop_env=drop_env)
        _step("skip" if deferred else "err", "id", p162.summary)
        return SiteResult(domain, "deferred" if deferred else "failed", p162.summary)
    if p162.status == "error":
        _step("err", "id", p162.summary)
        return SiteResult(domain, "failed", p162.summary)
    ga = c162.recorded_id(base)
    src_ids = c163.source_ids(base)
    existing = ga or (next(iter(src_ids)) if len(src_ids) == 1 else None)
    if switch_old and not existing:
        # A re-run after a reverted switch: the new fleet property exists, so
        # CHECK_162 "reuses" it — but the old ID (other account) may still sit
        # in a local .env / hosting env var. Finish the switch.
        old = (other_account_id or _other_account_id)(domain)
        if old:
            return _switch(domain, base, old, f"{old} is in another account", apply=apply,
                           confirm=confirm, build=build, new_property=new_property, drop_env=drop_env)
    if existing:
        # v49.A (g): IDs living outside the fleet account go last (moved first).
        from . import apikeys
        acct = account_of(existing)
        fleet = (apikeys.get_key("GA4_ACCOUNT_ID") or "").strip()
        if acct is not None and fleet and acct[0] != fleet:
            msg = f"{existing} is in {acct[1]} — move it to the fleet account first"
            if switch_old:
                return _switch(domain, base, existing, f"{existing} is in {acct[1]}", apply=apply,
                               confirm=confirm, build=build, new_property=new_property, drop_env=drop_env)
            _step("skip", "id", msg)
            return SiteResult(domain, "deferred", msg)
    _step("ok" if ga else "skip", "id", ga or p162.summary)

    found = c162._GA_ID.search(p162.summary) if p162.status == "would-fix" else None
    plan_id = existing or (found.group(0) if found else "G-(new)")
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

    return _finish(domain, base, ga, touched, snap, dirty_before, build, c164)


def _finish(domain: str, base: Path, ga: str, touched: list[Path], snap: Snapshot,
            dirty_before: set[str], build, c164, *, msg: str | None = None,
            pre_push: Callable[[], tuple[bool, str]] | None = None) -> SiteResult:
    """Shared apply tail: dirty-file guard → build gate → (pre_push) →
    commit touched files + push → live state."""
    clash = sorted(str(p.relative_to(base)) for p in touched if str(p.relative_to(base)) in dirty_before)
    if clash:
        snap.restore(touched)
        m = f"uncommitted edits in {', '.join(clash)} — commit or stash them, then re-run"
        _step("err", "git", m)
        return SiteResult(domain, "failed", m)

    source_changed = any(p.name != "lamill.toml" for p in touched)
    if source_changed:
        ok, detail = build(base)
        _undo_build_side_effects(base, dirty_before, touched)
        if not ok or not built_output_has(base, ga):
            snap.restore(touched)
            m = detail if not ok else f"built output doesn't contain {ga}"
            _step("err", "build", f"{m} — changes reverted")
            return SiteResult(domain, "failed", m)
        _step("ok", "build", f"{detail}; output contains {ga}")

    if pre_push is not None:
        ok, detail = pre_push()
        if not ok:
            snap.restore(touched)
            _step("err", "env", f"{detail} — changes reverted")
            return SiteResult(domain, "failed", detail)

    ok, detail = commit_and_push(base, touched, ga, msg)
    if not ok:
        _step("err", "push", detail)
        return SiteResult(domain, "failed", detail, [str(p.relative_to(base)) for p in touched])
    _step("ok", "push", f"{detail} ({len(touched)} file(s))")
    res = _live_step(domain, base, c164, "changed")
    res.touched = [str(p.relative_to(base)) for p in touched]
    return res


def _new_fleet_property(domain: str) -> str:
    """Find-or-create `domain`'s property in the fleet account, ignoring
    properties elsewhere (v49.F). Returns the new measurement ID."""
    from . import apikeys, ga4_admin
    from .checks.seo import check_162_ga4_id_recorded as c162
    account_id = (apikeys.get_key("GA4_ACCOUNT_ID") or "").strip()
    if c162._INDEX is None:
        c162._INDEX = ga4_admin.stream_index()
    out = ga4_admin.ensure_property(domain, account_id, index=c162._INDEX, ignore_other_accounts=True)
    if out.status not in ("found", "created") or not out.measurement_id:
        raise ga4_admin.GA4AdminError(f"ensure_property({domain}) → {out.status} {out.detail}".strip())
    return out.measurement_id


def _other_account_id(domain: str) -> str | None:
    """Measurement ID of `domain`'s property in a non-fleet account, if any."""
    from . import apikeys, ga4_admin
    from .checks.seo import check_162_ga4_id_recorded as c162
    fleet = (apikeys.get_key("GA4_ACCOUNT_ID") or "").strip()
    try:
        if c162._INDEX is None:
            if not ga4_admin.has_token():
                return None
            c162._INDEX = ga4_admin.stream_index()
    except ga4_admin.GA4AdminError:
        return None
    hit = next((h for h in ga4_admin.find_for_domain(domain, c162._INDEX)
                if h.account_id != fleet and h.measurement_id), None)
    return hit.measurement_id if hit else None


def _drop_host_env(base: Path, dry_run: bool) -> list[str]:
    """Delete hosting env vars that would override the committed ID (Vercel
    only; other platforms → [])."""
    from . import lamill_toml, vercel
    try:
        lt = lamill_toml.load(base)
    except lamill_toml.ParseError:
        lt = None
    platform = lt.deploy.platform if lt else None
    if platform != "vercel":
        return []
    proj = vercel.find_project_by_domain(base.name)
    return vercel.delete_env_keys(proj.project_id, _ENV_KEYS, dry_run=dry_run)


def _replace_id(base: Path, files, old: str, new: str) -> list[Path]:
    out = []
    for p in files:
        if p.name == "lamill.toml" or not p.is_file():
            continue
        try:
            text = p.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if old in text:
            p.write_text(text.replace(old, new))
            out.append(p)
    return out


def _switch(domain: str, base: Path, old: str, why: str, *, apply: bool, confirm, build,
            new_property=None, drop_env=None) -> SiteResult:
    """v49.F clean switch: fresh fleet property replaces `old` everywhere."""
    from .checks.seo import check_162_ga4_id_recorded as c162
    from .checks.seo import check_163_ga4_tag_in_source as c163
    from .checks.seo import check_164_ga4_live_tag as c164
    from .fix_helpers import FixResult
    new_property = new_property or _new_fleet_property
    drop_env = drop_env or _drop_host_env

    _step("skip", "id", f"{why} → switch to a new LaMill Sites property")
    tag_plan = c163._plan_tag(base, old)  # replacing old→new is textual, so plan against old
    if isinstance(tag_plan, FixResult):
        _step("err", "tag", tag_plan.summary)
        return SiteResult(domain, "failed", tag_plan.summary)
    tag_summary, tag_writes = tag_plan
    _step("skip" if tag_writes else "ok", "tag", tag_summary.replace(old, "new ID") if tag_writes else f"source loads {old} → replace")
    priv, priv_file = c163.privacy_state(base)
    if priv == "conflict":
        m = f"{priv_file.relative_to(base)} contradicts GA — rewrite it first"
        _step("err", "privacy", m)
        return SiteResult(domain, "failed", m)
    if priv == "missing" and priv_file is not None:
        _step("skip", "privacy", f"add GA sentence → {priv_file.relative_to(base)}")
    try:
        env_keys = drop_env(base, True)
    except Exception as e:
        _step("err", "env", f"can't read hosting env vars: {e}"[:300])
        return SiteResult(domain, "failed", str(e)[:300])
    if env_keys:
        _step("skip", "env", f"delete {', '.join(env_keys)} after the build passes")

    if not apply:
        return SiteResult(domain, "planned", f"switch {old} → new")
    if not confirm(f"Switch {domain} from {old} to a new LaMill Sites property?"):
        _step("skip", "apply", "declined")
        return SiteResult(domain, "skipped", "declined")

    dirty_before = _dirty(base)
    snap = Snapshot(base)
    try:
        ga = new_property(domain)
    except Exception as e:
        _step("err", "id", f"property create failed: {e}"[:300])
        return SiteResult(domain, "failed", str(e)[:300])
    _step("ok", "id", f"LaMill Sites property → {ga}")

    # Gitignored local env files (calcengine `.env`: PUBLIC_GA_ID=<old>) would
    # make the build gate see the old ID; update them too, never commit them.
    env_files = [p for p in base.glob(".env*") if p.is_file() and p.name != ".env.example"
                 and _git(base, "check-ignore", "-q", p.name).returncode == 0]
    env_snap = {p: p.read_bytes() for p in env_files}
    local_env = _replace_id(base, env_files, old, ga)
    if local_env:
        _step("ok", "env", f"{old} → {ga} in local {', '.join(p.name for p in local_env)} (gitignored, not committed)")
    touched = [c162._write(base, ga)]
    touched += _replace_id(base, list(snap.files), old, ga)
    r163 = c163._fix(base, dry_run=False, assume_yes=True)
    if r163.status == "fixed":
        touched += [Path(p) for p in r163.files_touched if Path(p) not in touched]
        _step("ok", "tag", r163.summary)
    elif r163.status != "nothing-to-do":
        snap.restore(touched)
        for p, b in env_snap.items():
            p.write_bytes(b)
        _step("err", "tag", r163.summary)
        return SiteResult(domain, "failed", r163.summary)
    else:
        _step("ok", "tag", f"{old} → {ga} in {len(touched) - 1} source file(s)")

    def pre_push() -> tuple[bool, str]:
        if not env_keys:
            return True, ""
        try:
            gone = drop_env(base, False)
        except Exception as e:
            return False, f"env delete failed: {e}"[:300]
        _step("ok", "env", f"deleted {', '.join(gone) or 'nothing'}")
        return True, ""

    res = _finish(domain, base, ga, touched, snap, dirty_before, build, c164,
                  msg=SWITCH_MSG.format(old=old, ga=ga), pre_push=pre_push)
    if res.outcome == "failed" and not res.touched:  # reverted before commit
        for p, b in env_snap.items():
            p.write_bytes(b)
    return res


def _live_step(domain: str, base: Path, c164, outcome: str) -> SiteResult:
    from .checks.seo import _live
    _live.clear_cache()
    state, detail = c164.live_state(base)
    if state == "live":
        _step("ok", "live", detail)
    elif state == "mismatch" and outcome == "changed":
        # Just pushed: the old build (old ID) is still served until the deploy lands.
        _step("skip", "live", f"deploying — {detail}; re-run to confirm")
    elif state == "mismatch":
        _step("err", "live", detail)
        return SiteResult(domain, "failed", detail)
    else:
        _step("skip", "live", f"deploying — {detail}; re-run to confirm")
    return SiteResult(domain, outcome, detail)


def run(*, apply: bool, assume_yes: bool, only: list[str] | None = None, switch_old: bool = False,
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
        results.append(run_site(name, path, apply=apply, confirm=confirm, build=build, switch_old=switch_old))

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
