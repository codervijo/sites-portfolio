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


def has_makefile_with_targets(project_dir: Path, *targets: str) -> bool:
    mf = project_dir / "Makefile"
    if not mf.exists():
        return False
    text = mf.read_text(errors="replace")
    return all(re.search(rf"^{re.escape(t)}\s*:", text, re.MULTILINE) for t in targets)


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

    if own_repo["pass"]:
        _ok("own-git-repo")
    else:
        entry = {"reason": own_repo.get("reason")}
        if "toplevel" in own_repo:
            entry["toplevel"] = own_repo["toplevel"]
        if own_repo.get("fix"):
            entry["fix"] = own_repo["fix"]
        _fail("own-git-repo", **entry)

    if plan_category:
        _ok("has-category")
    else:
        _fail("has-category", reason="domain has no category set in portfolio.json")

    if not project_dir.exists():
        for r in ("has-prompts-md", "prompts-md-format", "has-makefile", "has-ai-agents-md", "has-growth-log", "platform-declared", "live-site"):
            _skip(r, "dir does not exist")
    else:
        if prompts["exists"]:
            _ok("has-prompts-md")
            if prompts["format_ok"]:
                _ok("prompts-md-format")
            else:
                _fail("prompts-md-format", reason=prompts["format_warning"] or "no dated H2")
        else:
            _fail("has-prompts-md", reason="docs/Prompts.md not found",
                  fix=f"create {project_dir}/docs/Prompts.md with `## YYYY-MM-DD` heading")
            _skip("prompts-md-format", "Prompts.md does not exist")

        if has_makefile_with_targets(project_dir, "run", "build"):
            _ok("has-makefile")
        else:
            _fail("has-makefile", reason="missing Makefile or `run`/`build` targets")

        if (project_dir / "AI_AGENTS.md").exists():
            _ok("has-ai-agents-md")
        else:
            _fail("has-ai-agents-md", reason="AI_AGENTS.md not found")

        if (project_dir / "docs" / "growth.md").exists():
            _ok("has-growth-log")
        else:
            _fail("has-growth-log",
                  reason="docs/growth.md not found — per-project growth-experiment log",
                  fix=f"`portfolio bootstrap` scaffolds it; for existing projects, add docs/growth.md with a dated H2 entry per experiment (see template)")

        if deployment["platform"] == "n/a":
            _ok("platform-declared")
            _skip("live-site", f"{deployment['kind']} project does not deploy")
        elif deployment["platform"] == "unknown":
            _fail("platform-declared",
                  reason="web project but no platform marker (wrangler.toml / vercel.json / netlify.toml)")
            if deployment["live"]:
                cls = deployment["live"]["classification"]
                if cls == "live-site":
                    _ok("live-site")
                else:
                    _fail("live-site", reason=f"classification is {cls!r}")
            else:
                _skip("live-site", "no check snapshot covers this domain")
        else:
            _ok("platform-declared")
            if deployment["live"]:
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
