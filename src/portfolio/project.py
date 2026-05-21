from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .data import ROOT, load_plan

SITES_ROOT = ROOT.parent

SCHEMA_VERSION = 1

ACTIVE_MAX_DAYS = 7
QUIET_MAX_DAYS = 30
STALLED_MAX_DAYS = 90
FRESH_MAX_COMMITS = 5

PROMPTS_MD_REL = Path("docs/Prompts.md")
DATED_H2 = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b[ \t]*(.*)$")

PLATFORM_MARKERS: tuple[tuple[str, str], ...] = (
    ("cloudflare-pages", "wrangler.toml"),
    ("cloudflare-pages", "wrangler.jsonc"),
    ("cloudflare-pages", "_headers"),
    ("cloudflare-pages", "_redirects"),
    ("vercel", "vercel.json"),
    ("vercel", ".vercel/project.json"),
    ("netlify", "netlify.toml"),
)

# 2026-05-21: lamill.toml `[deploy].platform` enum → rendered string.
# `lamill_toml.PLATFORM_VALUES` uses the short forms (`cf-pages`,
# `cf-workers`); marker-based detection + downstream consumers
# (hosting.py, dashboard.py) use the long forms (`cloudflare-pages`,
# `cloudflare-workers`). detect_platform() reads lamill.toml first
# and translates so the `project check` deploy summary matches what
# the operator declared — fixing the cf-workers sites that were
# previously inferred as `cloudflare-pages` from wrangler.jsonc.
_LAMILL_PLATFORM_TO_DETECT: dict[str, str] = {
    "cf-pages": "cloudflare-pages",
    "cf-workers": "cloudflare-workers",
    "vercel": "vercel",
    "netlify": "netlify",
    "github-pages": "github-pages",
    "hostgator": "hostgator",
    "custom": "custom",
    "none": "n/a",
}


@dataclass
class ProjectResolution:
    matched: str | None
    candidates: list[str]


def resolve_project(name: str, plan: dict[str, str] | None = None) -> ProjectResolution:
    plan = plan if plan is not None else load_plan()
    name = name.strip().lower()
    if not name:
        return ProjectResolution(matched=None, candidates=[])
    if name in plan:
        return ProjectResolution(matched=name, candidates=[name])
    hits = sorted(d for d in plan if name in d)
    if len(hits) == 1:
        return ProjectResolution(matched=hits[0], candidates=hits)
    return ProjectResolution(matched=None, candidates=hits)


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode, proc.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""


def check_own_repo(project_dir: Path) -> dict:
    if not project_dir.exists():
        return {
            "pass": False,
            "reason": "dir-missing",
            "fix": f"create {project_dir}",
        }
    rc, top = _git(["rev-parse", "--show-toplevel"], cwd=project_dir)
    if rc != 0 or not top:
        return {
            "pass": False,
            "reason": "no-git",
            "fix": f"cd {project_dir} && git init && git add . && git commit -m 'init'",
        }
    top_path = Path(top).resolve()
    if top_path != project_dir.resolve():
        return {
            "pass": False,
            "reason": "tracked-by-parent",
            "toplevel": str(top_path),
            "fix": f"cd {project_dir} && git init && git add . && git commit -m 'init'",
        }
    return {"pass": True}


def fetch_first_commit_date(project_dir: Path) -> "date | None":
    """First commit date in the project's git repo. Used as a proxy for
    "when did this site launch" — accurate enough for the dashboard's
    site-age column. Returns None if not a git repo or no commits.
    """
    from datetime import date as _date, datetime as _datetime
    if not (project_dir / ".git").exists():
        return None
    rc, out = _git(
        ["log", "--reverse", "--format=%aI", "--max-count=1"],
        cwd=project_dir,
    )
    if rc != 0 or not out:
        return None
    try:
        return _datetime.fromisoformat(out.strip()).date()
    except ValueError:
        try:
            return _date.fromisoformat(out.strip()[:10])
        except ValueError:
            return None


def fetch_last_commit(project_dir: Path) -> dict | None:
    rc, out = _git(
        ["log", "-1", "--format=%H%x1f%h%x1f%aI%x1f%an%x1f%s"],
        cwd=project_dir,
    )
    if rc != 0 or not out:
        return None
    parts = out.split("\x1f")
    if len(parts) < 5:
        return None
    sha, short, iso_date, author, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
    try:
        commit_dt = datetime.fromisoformat(iso_date)
    except ValueError:
        return None
    age_days = (datetime.now(commit_dt.tzinfo) - commit_dt).days
    return {
        "sha": sha,
        "short_sha": short,
        "date": commit_dt.isoformat(),
        "age_days": age_days,
        "author": author,
        "subject": subject,
    }


def fetch_git_pulse(project_dir: Path) -> dict:
    rc, branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=project_dir)
    branch_name = branch if rc == 0 and branch else None

    rc, status_out = _git(["status", "--porcelain"], cwd=project_dir)
    modified = untracked = 0
    if rc == 0:
        for line in status_out.splitlines():
            if line.startswith("??"):
                untracked += 1
            elif line.strip():
                modified += 1

    rc, total_out = _git(["rev-list", "--count", "HEAD"], cwd=project_dir)
    total_commits = int(total_out) if rc == 0 and total_out.isdigit() else None

    today = date.today()
    rc, c7_out = _git(
        ["rev-list", "--count", f"--since={(today - timedelta(days=7)).isoformat()}", "HEAD"],
        cwd=project_dir,
    )
    commits_7d = int(c7_out) if rc == 0 and c7_out.isdigit() else None

    rc, c30_out = _git(
        ["rev-list", "--count", f"--since={(today - timedelta(days=30)).isoformat()}", "HEAD"],
        cwd=project_dir,
    )
    commits_30d = int(c30_out) if rc == 0 and c30_out.isdigit() else None

    return {
        "branch": branch_name,
        "clean": modified == 0 and untracked == 0,
        "modified_count": modified,
        "untracked_count": untracked,
        "total_commits": total_commits,
        "commits_7d": commits_7d,
        "commits_30d": commits_30d,
    }


def parse_prompts_md(project_dir: Path) -> dict:
    path = project_dir / PROMPTS_MD_REL
    if not path.exists():
        return {"exists": False, "format_ok": False, "last_entry": None, "format_warning": None}

    text = path.read_text(errors="replace")
    lines = text.splitlines()

    matches: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = DATED_H2.match(line)
        if m:
            matches.append((i, m.group(1), m.group(2).strip().lstrip("—-").strip()))

    if matches:
        idx, date_str, title = matches[-1]
        body_lines: list[str] = []
        for j in range(idx + 1, len(lines)):
            if DATED_H2.match(lines[j]):
                break
            body_lines.append(lines[j])
        body = "\n".join(body_lines).strip()
        summary = body[:300] + ("…" if len(body) > 300 else "")
        return {
            "exists": True,
            "format_ok": True,
            "last_entry": {"date": date_str, "title": title or None, "body": body, "summary": summary},
            "format_warning": None,
        }

    mtime = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    body = text.strip()
    summary = body[:300] + ("…" if len(body) > 300 else "")
    return {
        "exists": True,
        "format_ok": False,
        "last_entry": ({"date": mtime, "title": None, "body": body, "summary": summary} if body else None),
        "format_warning": "no dated H2 headings found; using file mtime",
    }


def detect_platform(project_dir: Path) -> dict:
    if not project_dir.exists():
        return {"platform": "n/a", "evidence": [], "kind": "missing"}

    pkg_path = project_dir / "package.json"
    has_pkg = pkg_path.exists()
    has_pyproject = (project_dir / "pyproject.toml").exists()
    has_gomod = (project_dir / "go.mod").exists()

    pkg_data: dict = {}
    if has_pkg:
        try:
            pkg_data = json.loads(pkg_path.read_text())
        except (json.JSONDecodeError, OSError):
            pkg_data = {}

    if has_pkg:
        scripts = pkg_data.get("scripts", {})
        kind = "web" if "build" in scripts else "library"
    elif has_pyproject or has_gomod:
        kind = "cli"
    else:
        kind = "scaffold"

    if kind in ("cli", "library"):
        return {"platform": "n/a", "evidence": [], "kind": kind}

    evidence: list[str] = []
    platform: str | None = None

    # 2026-05-21 — lamill.toml [deploy].platform is the OPERATOR's
    # declaration; trust it over marker inference. Without this, cf-
    # workers sites (which still carry a wrangler.jsonc for local
    # `wrangler dev`) were rendered as cloudflare-pages because the
    # marker map only knew that file from the CFP era. Fall through
    # to marker detection only if lamill.toml is missing / malformed
    # / declares `none`.
    try:
        from .lamill_toml import load as _load_lamill_toml, ParseError
        lt = _load_lamill_toml(project_dir)
    except Exception:
        lt = None
    if lt is not None:
        declared = _LAMILL_PLATFORM_TO_DETECT.get(lt.deploy.platform)
        if declared is not None and declared != "n/a":
            platform = declared
            evidence.append("lamill.toml:[deploy].platform")

    if platform is None:
        for plat, marker in PLATFORM_MARKERS:
            if (project_dir / marker).exists():
                evidence.append(marker)
                if platform is None:
                    platform = plat

    if platform is None and pkg_data:
        deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
        scripts_map = pkg_data.get("scripts", {})
        if "wrangler" in deps or any("wrangler" in str(v) for v in scripts_map.values()):
            platform = "cloudflare-pages"
            evidence.append("package.json:wrangler")

    return {"platform": platform or "unknown", "evidence": evidence, "kind": kind}


def fetch_live_status(domain: str) -> dict | None:
    from .check import best_per_domain, latest_snapshot, load_snapshot

    snap_path = latest_snapshot()
    if not snap_path:
        return None
    try:
        snap = load_snapshot(snap_path)
    except (OSError, json.JSONDecodeError):
        return None
    best = best_per_domain(snap)
    r = best.get(domain)
    if not r:
        return None
    return {
        "snapshot": snap_path.name,
        "classification": r["classification"],
        "http_status": r.get("status"),
        "response_time_ms": r.get("response_time_ms"),
        "final_url": r.get("final_url"),
    }


def compute_verdict(
    own_repo_pass: bool,
    last_commit: dict | None,
    total_commits: int | None,
) -> str:
    if not own_repo_pass:
        return "Misconfigured"
    if last_commit is None:
        return "Fresh"
    if total_commits is not None and total_commits < FRESH_MAX_COMMITS:
        return "Fresh"
    age = last_commit["age_days"]
    if age <= ACTIVE_MAX_DAYS:
        return "Active"
    if age <= QUIET_MAX_DAYS:
        return "Quiet"
    if age <= STALLED_MAX_DAYS:
        return "Stalled"
    return "Dormant"


def build_status(name: str) -> dict:
    plan = load_plan()
    res = resolve_project(name, plan=plan)

    if res.matched is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "input": name,
            "resolved": None,
            "candidates": res.candidates,
            "error": "ambiguous" if res.candidates else "not-found",
        }

    domain = res.matched
    project_dir = SITES_ROOT / domain
    own_repo = check_own_repo(project_dir)

    last_commit = fetch_last_commit(project_dir) if own_repo["pass"] else None
    git_pulse = fetch_git_pulse(project_dir) if own_repo["pass"] else None

    prompts = parse_prompts_md(project_dir) if project_dir.exists() else {
        "exists": False, "format_ok": False, "last_entry": None, "format_warning": None,
    }
    deployment = detect_platform(project_dir)
    deployment["live"] = fetch_live_status(domain)

    plan_category = plan.get(domain)

    passed: list[str] = []
    failed: list[dict] = []
    skipped: list[dict] = []

    def _ok(rule: str) -> None:
        passed.append(rule)

    def _fail(rule: str, **kwargs) -> None:
        failed.append({"rule": rule, **kwargs})

    def _skip(rule: str, reason: str) -> None:
        skipped.append({"rule": rule, "reason": reason})

    # v5.E: catalog-driven conformance.
    #
    # Run every applicable check from the registry against the project dir
    # and translate the registry's (status, message) shape into the legacy
    # (passed/failed/skipped) buckets that downstream consumers + the JSON
    # schema expect:
    #   - pass                                    → passed
    #   - fail                                    → failed (reason = message)
    #   - warn whose message contains "skipped"   → skipped (these are
    #         stack-aware "not a Vite project — skipped"-style returns)
    #   - warn (genuine, e.g. info-severity gaps) → failed (info severity
    #         flagged as such in the JSON for downstream filtering)
    if project_dir.exists():
        from .checks import list_checks, run_checks
        # Skip categories that don't make sense for `project status`:
        #  - `seo` runtime checks need HTTP fetch (they live under v5.D).
        # File-system + git-log categories are all in scope.
        applicable_categories = {
            "scaffold", "docs", "git", "ci", "stack", "deploy", "seo",
            "content",
        }
        spec_by_id = {s.id: s for s in list_checks() if s.category in applicable_categories}
        results = run_checks(str(project_dir), ids=list(spec_by_id.keys()))
        for cid in sorted(results):
            r = results[cid]
            spec = spec_by_id.get(cid)
            if r.status == "pass":
                _ok(cid)
            elif r.status == "fail":
                _fail(cid, reason=r.message,
                      severity=spec.severity if spec else "warn",
                      name=spec.name if spec else None)
            else:  # "warn"
                if "skipped" in r.message:
                    _skip(cid, r.message)
                else:
                    _fail(cid, reason=r.message,
                          severity=spec.severity if spec else "warn",
                          name=spec.name if spec else None)
    else:
        # Project dir doesn't exist yet — record one synthetic skip per
        # category so downstream renderers know to surface the underlying
        # cause (the "Dir: ... (missing)" header) instead of N green checks.
        _skip("project-dir-missing", f"{project_dir} does not exist")

    # ---------- ad-hoc rules with no catalog equivalent ----------
    # has-category: domain has a category in portfolio.json. Data-side, not
    # file-system; doesn't fit the catalog's `run(repo_path)` shape.
    if plan_category:
        _ok("has-category")
    else:
        _fail("has-category", reason="domain has no category set in portfolio.json")

    # live-site: deployed and classified live by the latest check snapshot.
    # Runtime signal — could become a future runtime CHECK_xxx but isn't yet.
    if not project_dir.exists():
        _skip("live-site", "project dir does not exist")
    elif deployment["platform"] == "n/a":
        _skip("live-site", f"{deployment['kind']} project does not deploy")
    elif deployment["live"]:
        cls = deployment["live"]["classification"]
        if cls == "live-site":
            _ok("live-site")
        else:
            _fail("live-site", reason=f"classification is {cls!r}")
    else:
        _skip("live-site", "no check snapshot covers this domain")

    return {
        "schema_version": SCHEMA_VERSION,
        "input": name,
        "resolved": domain,
        "dir": str(project_dir),
        "dir_exists": project_dir.exists(),
        "plan_category": plan_category,
        "verdict": compute_verdict(
            own_repo["pass"],
            last_commit,
            git_pulse["total_commits"] if git_pulse else None,
        ),
        "git": {
            "own_repo_pass": own_repo["pass"],
            "branch": git_pulse["branch"] if git_pulse else None,
            "clean": git_pulse["clean"] if git_pulse else None,
            "modified_count": git_pulse["modified_count"] if git_pulse else None,
            "untracked_count": git_pulse["untracked_count"] if git_pulse else None,
            "total_commits": git_pulse["total_commits"] if git_pulse else None,
            "commits_7d": git_pulse["commits_7d"] if git_pulse else None,
            "commits_30d": git_pulse["commits_30d"] if git_pulse else None,
            "last_commit": last_commit,
        },
        "prompts_md": prompts,
        "deployment": deployment,
        "conformance": {
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        },
    }
