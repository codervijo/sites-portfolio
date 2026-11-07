"""v48.C — `lamill new site`: one guided command from domain + Lovable design to live.

Composition only (v48.A): every step calls an existing command as-is —
`fleet sync`, `new bootstrap`, `new deploy`, `project check` run as
subprocesses so their prompts and output reach the operator unchanged.
What lives here is only what those commands don't do: picking the domain,
discovering the Lovable repo via `gh`, the in-container build, and the
wait-until-live loop with exponential backoff.
"""
from __future__ import annotations

import csv
import difflib
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from .console import console
from .data import ROOT as DATA_ROOT
from .project import SITES_ROOT

PORKBUN_CSV = DATA_ROOT / "data" / "domains" / "porkbun.csv"
LEDGER = DATA_ROOT / "data" / "new_site.json"
BUILD_IMAGE = "node:20-bookworm"  # same image as `project delegate`'s sandbox

# Wait-until-live defaults (v48.A — design defaults to tune from real runs).
BACKOFF_FIRST_S = 30
BACKOFF_FACTOR = 2
BACKOFF_CAP_S = 600
BUDGET_FIRST_DEPLOY_MIN = 120
BUDGET_REDEPLOY_MIN = 30

LOVABLE_MARKERS = ("@lovable.dev/", "lovable-tagger")
REPO_LOOKBACK_DAYS = 90
REPO_FINGERPRINT_LIMIT = 30

Runner = Callable[[list[str]], int]


class NewSiteError(Exception):
    """Operator-facing failure; message carries the remediation."""


# ---------------------------------------------------------------- subprocess


def lamill_argv(*args: str) -> list[str]:
    """argv that runs this same lamill install (no PATH lookup)."""
    return [sys.executable, "-m", "portfolio", *args]


def run_inherit(argv: list[str]) -> int:
    """Run with the operator's TTY attached (prompts + live output pass through)."""
    return subprocess.call(argv)


# ---------------------------------------------------------------- domain


def site_state(domain: str, sites_root: Path = SITES_ROOT) -> str:
    return "bootstrapped" if (sites_root / domain / "lamill.toml").is_file() else "not bootstrapped"


def newest_porkbun_domain(csv_path: Path = PORKBUN_CSV) -> tuple[str, str] | None:
    """(domain, create_date) of the most recent Porkbun registration."""
    if not csv_path.is_file():
        return None
    best: tuple[str, str] | None = None
    with csv_path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            d = (row.get("DOMAIN") or "").strip().lower()
            created = (row.get("CREATE DATE") or "").strip()
            if d and created and (best is None or created > best[1]):
                best = (d, created)
    return best


def resolve_domain(
    domain: str | None, *, interactive: bool,
    confirm: Callable[[str], bool], prompt: Callable[[str], str],
    sync: Callable[[], None], newest: Callable[[], tuple[str, str] | None],
) -> str:
    """CLI arg → newest Porkbun registration → ask → error (v48.A)."""
    if domain:
        return domain.strip().lower()
    sync()
    cand = newest()
    if cand:
        d, created = cand
        msg = f"Use [cyan]{d}[/] (registered {created[:10]}, {site_state(d)})?"
        if not interactive:
            raise NewSiteError(
                f"no domain given (newest Porkbun registration is {d}). "
                f"Run `lamill new site {d}` or `lamill new site <domain>`."
            )
        if confirm(msg):
            return d
    if interactive:
        typed = (prompt("Domain to publish (Enter to quit)") or "").strip().lower()
        if typed:
            return typed
    raise NewSiteError(
        "no domain to publish. Usage: `lamill new site <domain>` — or buy one "
        "at Porkbun and run `lamill fleet sync --refresh` so it's picked up."
    )


# ---------------------------------------------------------------- lovable repo


@dataclass(frozen=True)
class RepoCandidate:
    full_name: str
    url: str
    pushed_at: str
    score: float


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def name_similarity(repo_name: str, domain: str) -> float:
    a, b = _norm(repo_name), _norm(domain)
    stem = _norm(domain.rsplit(".", 1)[0])
    return max(difflib.SequenceMatcher(None, a, b).ratio(),
               difflib.SequenceMatcher(None, a, stem).ratio())


def _origin_repo(path: Path) -> str | None:
    try:
        url = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
    except OSError:
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    return m.group(1).lower() if m else None


def load_ledger(path: Path = LEDGER) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def record_ledger(domain: str, repo_full_name: str, path: Path = LEDGER) -> None:
    data = load_ledger(path)
    data[domain] = repo_full_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(data.items())), indent=2) + "\n")


def used_repos(sites_root: Path = SITES_ROOT, ledger: Path = LEDGER) -> set[str]:
    """Repos already behind a site: each site's own origin, its genai/ origin,
    and the new-site ledger. Lowercase `owner/name`."""
    used = {v.lower() for v in load_ledger(ledger).values()}
    if sites_root.is_dir():
        for d in sites_root.iterdir():
            if not d.is_dir():
                continue
            for p in (d, d / "genai"):
                if (p / ".git").exists():
                    r = _origin_repo(p)
                    if r:
                        used.add(r)
    return used


def _gh_json(args: list[str]) -> object:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        raise NewSiteError(f"`gh {' '.join(args[:2])}` failed: {r.stderr.strip()[:200]} "
                           "— run `gh auth status`.")
    return json.loads(r.stdout or "null")


def _is_lovable(full_name: str) -> bool:
    r = subprocess.run(
        ["gh", "api", f"repos/{full_name}/contents/package.json", "--jq", ".content"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        return False
    import base64
    try:
        pkg = base64.b64decode(r.stdout.strip()).decode("utf-8", "replace")
    except ValueError:
        return False
    return any(m in pkg for m in LOVABLE_MARKERS)


def rank_candidates(repos: Iterable[dict], domain: str, used: set[str],
                    is_lovable: Callable[[str], bool], *, now: datetime | None = None
                    ) -> list[RepoCandidate]:
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=REPO_LOOKBACK_DAYS)).isoformat()
    recent = sorted(
        (r for r in repos if (r.get("pushedAt") or "") >= cutoff[:19]),
        key=lambda r: r.get("pushedAt") or "", reverse=True,
    )
    out: list[RepoCandidate] = []
    checked = 0
    for r in recent:
        full = f"{r['owner']['login']}/{r['name']}"
        if full.lower() in used:
            continue
        if checked >= REPO_FINGERPRINT_LIMIT:
            break
        checked += 1
        if not is_lovable(full):
            continue
        out.append(RepoCandidate(full, r.get("url") or f"https://github.com/{full}",
                                 r.get("pushedAt") or "", name_similarity(r["name"], domain)))
    # Name similarity first, then most recently pushed.
    return sorted(out, key=lambda c: (round(c.score, 2), c.pushed_at), reverse=True)


def discover_lovable_repo(domain: str) -> list[RepoCandidate]:
    repos = _gh_json(["repo", "list", "--limit", "300", "--json", "name,owner,pushedAt,url"])
    return rank_candidates(repos or [], domain, used_repos(), _is_lovable)


def pick_repo(cands: list[RepoCandidate], domain: str, *, interactive: bool,
              confirm: Callable[[str], bool], prompt: Callable[[str], str]) -> RepoCandidate | None | str:
    """Returns a candidate, a typed URL (str), or None (blank Astro scaffold)."""
    if not cands:
        if not interactive:
            return None
        typed = (prompt("No unused Lovable repo found. Git URL (Enter = blank Astro site)") or "").strip()
        return typed or None
    top = cands[0]
    clear = len(cands) == 1 or (top.score >= 0.6 and top.score - cands[1].score >= 0.2)
    if not interactive:
        return top if clear else None
    if clear and confirm(f"Use Lovable repo [cyan]{top.full_name}[/] → {domain}?"):
        return top
    for i, c in enumerate(cands, 1):
        console.print(f"  {i}. {c.full_name}  [dim](pushed {c.pushed_at[:10]})[/]")
    typed = (prompt("Pick a number, paste a git URL, or Enter for a blank Astro site") or "").strip()
    if not typed:
        return None
    if typed.isdigit() and 1 <= int(typed) <= len(cands):
        return cands[int(typed) - 1]
    return typed


# ---------------------------------------------------------------- build


def build_in_container(site_dir: Path, *, runner: Callable[[list[str]], int] = run_inherit) -> tuple[bool, str]:
    """Build with `project delegate`'s build command in a disposable container
    (never host pnpm). Runs as root, like `make buildsh` — the documented build
    — because sites already built that way have root-owned node_modules/dist
    that a host-user build can't overwrite (found on lamill.store, 2026-11-07)."""
    from .delegate import _detect_build
    cmd, info = _detect_build(site_dir)
    if cmd is None:
        return True, f"nothing to build ({info})"
    argv = ["docker", "run", "--rm", "--network=host", "-e", "HOME=/tmp",
            "-v", f"{site_dir}:/work", "-w", "/work", BUILD_IMAGE, "sh", "-lc", cmd]
    rc = runner(argv)
    return rc == 0, "build OK" if rc == 0 else f"build failed (exit {rc})"


# ---------------------------------------------------------------- wait


def backoff_delays(first: int = BACKOFF_FIRST_S, factor: int = BACKOFF_FACTOR,
                   cap: int = BACKOFF_CAP_S):
    d = first
    while True:
        yield d
        d = min(d * factor, cap)


@dataclass
class LiveState:
    zone: str
    build: str
    live_ok: bool
    live: str

    @property
    def done(self) -> bool:
        return self.zone == "active" and self.build in ("success", "n/a") and self.live_ok


def probe_state(domain: str, slug: str) -> LiveState:
    """The three probes `new deploy --watch` uses, called as-is."""
    from . import apikeys, cloudflare
    from .cli import _probe_apex_live
    acct = (apikeys.get_key("CF_ACCOUNT_ID") or "").strip()
    try:
        zone = cloudflare.get_zone(cloudflare.resolve_zone_id(domain)).status
    except cloudflare.CloudflareAPIError:
        zone = "?"
    try:
        if cloudflare.get_pages_project(slug, account_id=acct) is None:
            build = "n/a"  # Workers Service: no public build-status API
        else:
            stage, status, _ = cloudflare.latest_deployment_status(slug, account_id=acct)
            build = {"success": "success", "failure": "failed"}.get(
                status or "", f"{(stage or 'queued')[:8]}/{(status or '?')[:8]}")
    except cloudflare.CloudflareAPIError:
        build = "?"
    ok, token, detail = _probe_apex_live(domain, head=True)
    return LiveState(zone, build, ok, f"{token}→{detail}" if detail else token)


def zone_active(domain: str) -> bool:
    from . import cloudflare
    try:
        return cloudflare.get_zone(cloudflare.resolve_zone_id(domain)).status == "active"
    except cloudflare.CloudflareAPIError:
        return False


def wait_until_live(domain: str, *, budget_s: int, probe: Callable[[], LiveState],
                    sleep: Callable[[float], None] = time.sleep,
                    monotonic: Callable[[], float] = time.monotonic) -> str:
    """Returns "live" | "build_failed" | "timeout"."""
    start = monotonic()
    delays = backoff_delays()
    while True:
        st = probe()
        el = int(monotonic() - start)
        if st.done:
            console.print(f"  [green]✓[/] live [dim](zone active · build {st.build} · "
                          f"HTTP {st.live} · {el // 60}m{el % 60:02d}s)[/]")
            return "live"
        if st.build == "failed":
            console.print("  [red]✗[/] CF build failed — open the build log in the CF dashboard.")
            return "build_failed"
        remaining = budget_s - el
        if remaining <= 0:
            return "timeout"
        nxt = min(next(delays), remaining)
        console.print(f"  [yellow]↷[/] zone={st.zone} · build={st.build} · live={st.live} "
                      f"· next check in {_fmt(nxt)} [dim]({el // 60}m elapsed)[/]")
        sleep(nxt)


def _fmt(s: int) -> str:
    return f"{s}s" if s < 60 else f"{s // 60}m{s % 60:02d}s" if s % 60 else f"{s // 60}m"


# ---------------------------------------------------------------- orchestrator


class Stopped(Exception):
    """Operator declined a step confirm — clean exit, re-run resumes."""


@dataclass
class Options:
    git_url: str = ""
    owner: str = ""
    yes: bool = False
    non_interactive: bool = False
    private: bool = False
    timeout_min: int | None = None
    no_wait: bool = False


def _repo_full_name(url: str) -> str | None:
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url.strip())
    return m.group(1) if m else None


def run_new_site(
    domain: str | None, opts: Options, *,
    runner: Runner = run_inherit,
    ask_confirm: Callable[[str], bool] | None = None,
    ask_prompt: Callable[[str], str] | None = None,
    owned: Callable[[str], bool] | None = None,
    discover: Callable[[str], list[RepoCandidate]] = discover_lovable_repo,
    build: Callable[[Path], tuple[bool, str]] | None = None,
    is_zone_active: Callable[[str], bool] = zone_active,
    probe_factory: Callable[[str, str], Callable[[], LiveState]] | None = None,
    wait: Callable[..., str] = wait_until_live,
    sites_root: Path = SITES_ROOT,
    ledger: Path = LEDGER,
    newest: Callable[[], tuple[str, str] | None] = newest_porkbun_domain,
) -> int:
    """Run the guided flow. Returns the process exit code."""
    import typer

    from .cf_slug import resolve_slug
    from .data import OWNER_SELF, normalize_owner

    interactive = not opts.non_interactive
    _confirm = ask_confirm or (lambda m: typer.confirm(m, default=True))
    _prompt = ask_prompt or (lambda m: typer.prompt(m, default="", show_default=False))
    auto = opts.yes or opts.non_interactive

    def pick_confirm(msg: str) -> bool:
        return True if opts.yes else _confirm(msg)

    def step(n: int, title: str) -> None:
        console.print(f"\n[bold]{n}. {title}[/]")
        if not auto and not _confirm(f"Next: {title} — continue?"):
            raise Stopped(title)

    if owned is None:
        from .bootstrap import validate_owned_domain
        owned = lambda d: validate_owned_domain(d).found  # noqa: E731

    def sync() -> None:
        console.print("[dim]Refreshing inventory (fleet sync --refresh)…[/]")
        runner(lamill_argv("fleet", "sync", "--refresh"))

    try:
        domain = resolve_domain(domain, interactive=interactive, confirm=pick_confirm,
                                prompt=_prompt, sync=sync, newest=newest)
        console.print(f"[bold]v48 — New site[/] [cyan]{domain}[/]")
        site_dir = sites_root / domain
        is_client = normalize_owner(opts.owner) != OWNER_SELF

        # 1. inventory
        console.print("\n[bold]1. Domain inventory[/]")
        if is_client:
            console.print(f"  [green]✓[/] client domain (owner={normalize_owner(opts.owner)}) — not in your registrar inventory by design")
        elif owned(domain):
            console.print("  [green]✓[/] in owned-domains inventory")
        else:
            sync()
            if not owned(domain):
                raise NewSiteError(
                    f"{domain} isn't in your owned-domains inventory even after "
                    f"`fleet sync --refresh`. Check the spelling, or pass "
                    f"`--owner <client>` if a client owns it."
                )
            console.print("  [green]✓[/] in owned-domains inventory (after sync)")

        # 2. bootstrap
        if (site_dir / "lamill.toml").is_file():
            console.print("\n[bold]2. Bootstrap[/]\n  [green]✓[/] already bootstrapped — skipping")
        else:
            git_url, repo_name = opts.git_url.strip(), None
            if git_url:
                repo_name = _repo_full_name(git_url)
            else:
                console.print("\n[dim]Looking for your Lovable repo on GitHub (gh)…[/]")
                choice = pick_repo(discover(domain), domain, interactive=interactive,
                                   confirm=pick_confirm, prompt=_prompt)
                if isinstance(choice, RepoCandidate):
                    git_url, repo_name = choice.url, choice.full_name
                elif isinstance(choice, str):
                    git_url, repo_name = choice, _repo_full_name(choice)
            step(2, "Bootstrap" + (f" from {repo_name or git_url}" if git_url else " (blank Astro)"))
            argv = lamill_argv("new", "bootstrap", domain)
            if git_url:
                argv += ["--git-url", git_url]
            if opts.owner:
                argv += ["--owner", opts.owner]
            if opts.non_interactive:
                argv.append("--non-interactive")
            rc = runner(argv)
            if rc != 0:
                raise NewSiteError(f"`new bootstrap` exited {rc} — fix the error above, then re-run `lamill new site {domain}`.")
            if repo_name:
                record_ledger(domain, repo_name, ledger)
            console.print("  [green]✓[/] bootstrapped")

        # 3. build
        step(3, "Build (in Docker)")
        ok, detail = (build or build_in_container)(site_dir)
        if not ok:
            raise NewSiteError(f"{detail} — fix the build in sites/{domain}/, then re-run `lamill new site {domain}`.")
        console.print(f"  [green]✓[/] {detail}")

        # 4. deploy
        first_deploy = not is_zone_active(domain)
        step(4, "Deploy" + (" (first deploy)" if first_deploy else ""))
        argv = lamill_argv("new", "deploy", domain)
        if opts.yes:
            argv.append("--yes")
        if opts.private:
            argv.append("--private")
        rc = runner(argv)
        if rc != 0:
            raise NewSiteError(f"`new deploy` exited {rc} — fix the error above, then re-run `lamill new site {domain}` (deploy is safe to re-run).")
        console.print("  [green]✓[/] deploy pipeline finished")

        # 5. wait until live
        console.print("\n[bold]5. Wait until live[/]")
        if opts.no_wait:
            console.print(f"  [yellow]↷[/] skipped (--no-wait) — re-run `lamill new site {domain}` to wait")
        else:
            budget_min = opts.timeout_min or (BUDGET_FIRST_DEPLOY_MIN if first_deploy else BUDGET_REDEPLOY_MIN)
            console.print(f"  [dim]up to {budget_min} min · backoff {BACKOFF_FIRST_S}s ×{BACKOFF_FACTOR} "
                          f"(cap {BACKOFF_CAP_S // 60}m) · Ctrl-C is safe[/]")
            slug = resolve_slug(site_dir, domain)
            probe = (probe_factory or (lambda d, s: (lambda: probe_state(d, s))))(domain, slug)
            result = wait(domain, budget_s=budget_min * 60, probe=probe)
            if result == "build_failed":
                return 1
            if result == "timeout":
                console.print(f"  [yellow]↷[/] not live after {budget_min} min — usually NS propagation. "
                              f"Re-run `lamill new site {domain}` later; it resumes here.")
                return 0

        # 6. check
        step(6, "Project check")
        rc = runner(lamill_argv("project", "check", domain))
        console.print("  [green]✓[/] project check clean" if rc == 0
                      else f"  [red]✗[/] project check reported failures (exit {rc}) — see above")
        console.print(f"\n[bold green]✓ {domain}[/] — https://{domain}/")
        return 0 if rc == 0 else 1
    except Stopped as s:
        console.print(f"  [yellow]↷[/] stopped before “{s}”. Re-run `lamill new site {domain or ''}`".rstrip()
                      + " to resume.")
        return 0
    except NewSiteError as e:
        console.print(f"  [red]✗[/] {e}")
        return 2
