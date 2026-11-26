"""v53.B — `lamill project code <domain>`: a live Claude session on a site.

The operator at the keyboard, not delegate's supervised one-shot (ADR-0031):

  1. preflight — site repo, interactive terminal, Docker up, Claude auth,
     one live session per site (refuses beside a running `code`/`delegate`
     container), dirty tree is a warning only;
  2. the `lamill-code` image (built once on first use) with the host's
     `claude` binary mounted read-only;
  3. a per-site container `lamill-code-<domain>` with the **same paths as the
     host**: the site at its real path, `HOME` at the host's home (a tmpfs)
     with `~/.claude` + `~/.claude.json` mounted into it — so Claude Code
     files this session in the same `~/.claude/projects/<encoded path>/`
     folder as a hand-started host session, and `--continue` resumes across
     both;
  4. the context pack (site docs + PRD/growth state + latest GSC and `--deep`
     numbers + fleet learnings) via `--append-system-prompt` with
     `--system-prompt-snapshot off`, so a resumed session sees today's state;
  5. `docker exec -it … claude [--continue]` with the terminal handed
     through; normal permission prompts;
  6. on exit the container is removed, the sitting's transcript is
     summarised into a dated `docs/Prompts.md` entry (v53.C), and the
     uncommitted diff + commit command are shown.

Never commits.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .data import ROOT
from .project import SITES_ROOT

IMAGE = "lamill-code"
# The image carries the toolchain (node, corepack, git) but not Claude Code:
# the host's own `claude` binary is mounted read-only, so the container runs
# exactly the host's version — same transcript format and flags as a
# hand-started host session sharing the folder, nothing to rebuild on update.
# (npm's @anthropic-ai/claude-code lagged the native build — 2.1.197 vs
# 2.1.332 on 2026-11-26 — and lacked --system-prompt-snapshot.)
DOCKERFILE = """\
FROM node:20-bookworm
ENV DISABLE_AUTOUPDATER=1
"""
CLAUDE_IN_CONTAINER = "/opt/lamill-code/claude"
CONTEXT_CAP = 20_000

Runner = Callable[..., subprocess.CompletedProcess]
Emit = Callable[[str, str], None]


class CodeRefused(Exception):
    """Operator-facing refusal; the message is printed as-is."""


def _safe(domain: str) -> str:
    return domain.lower().replace(".", "-").replace("/", "-")


def container_name(domain: str) -> str:
    return f"lamill-code-{_safe(domain)}"


def delegate_container_name(domain: str) -> str:
    return f"lamill-delegate-{_safe(domain)}"


def transcript_dir(site_dir: Path, claude_home: Path) -> Path:
    """Claude Code's per-directory session folder: the cwd with every
    non-alphanumeric character turned into `-`."""
    return claude_home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(site_dir))


def has_prior_session(site_dir: Path, claude_home: Path) -> bool:
    d = transcript_dir(site_dir, claude_home)
    return d.is_dir() and any(d.glob("*.jsonl"))


def _default_runner(args: list[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("check", False)
    return subprocess.run(args, **kw)


# ---------- v53.D: short site names ----------

_BACKUP_SUFFIXES = (".bup", ".old", ".bak")


def resolve_domain(name: str, sites_root: Path | None = None) -> str:
    """`calcengine` → `calcengine.site` when exactly one site dir has that
    first label. A full name (or any existing dir) passes through unchanged;
    an ambiguous short name (`lamill` → lamill.pics / lamill.store) is
    refused with the candidates."""
    root = sites_root or SITES_ROOT
    name = name.strip().lower().rstrip("/")
    if "." in name or (root / name).is_dir():
        return name
    try:
        hits = sorted(d.name for d in root.iterdir()
                      if d.is_dir() and "." in d.name
                      and not d.name.endswith(_BACKUP_SUFFIXES)
                      and d.name.split(".")[0].lower() == name)
    except OSError:
        hits = []
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise CodeRefused(f"✗ No site named {name!r} under {root}.\n"
                          "  Use the full domain (e.g. calcengine.site).")
    raise CodeRefused(f"✗ {name!r} matches more than one site: {', '.join(hits)}.\n"
                      "  Use the full domain.")


# ---------- preflight ----------


@dataclass
class Preflight:
    site_dir: Path
    claude_bin: Path
    dirty: list[str] = field(default_factory=list)
    resume: bool = False


def _dirty(site_dir: Path, run: Runner) -> list[str]:
    r = run(["git", "-C", str(site_dir), "status", "--porcelain"])
    if r.returncode != 0:
        return ["?? <git status unavailable>"]
    return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]


def preflight(domain: str, *, sites_root: Path | None = None,
              claude_home: Path | None = None, claude_json: Path | None = None,
              docker: list[str] | None = None, run: Runner = _default_runner,
              isatty: bool | None = None, which: Callable[[str], str | None] = shutil.which,
              ) -> Preflight:
    root = sites_root or SITES_ROOT
    claude_home = claude_home or Path.home() / ".claude"
    claude_json = claude_json or Path.home() / ".claude.json"
    docker = docker or ["docker"]
    site_dir = (root / domain).resolve()
    if not site_dir.is_dir():
        raise CodeRefused(f"✗ No site directory at {site_dir}.\n"
                          "  Check the domain spelling, or bootstrap/clone it first.")
    if not (site_dir / ".git").exists():
        raise CodeRefused(f"✗ {site_dir} is not a git repository.\n"
                          f"  Initialize it first:  git -C {site_dir} init")
    tty = sys.stdin.isatty() and sys.stdout.isatty() if isatty is None else isatty
    if not tty:
        raise CodeRefused("✗ `project code` is an interactive session and needs a terminal.\n"
                          "  Run it directly in a shell, not piped or from a script.")
    try:
        info = run(docker + ["info", "--format", "{{.ServerVersion}}"], timeout=20)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        info = None
    if info is None or info.returncode != 0:
        raise CodeRefused("✗ Docker isn't reachable — the session runs in a container.\n"
                          "  Start Docker, check with `docker info`, then re-run.")
    if not claude_home.is_dir() or not claude_json.is_file():
        missing = claude_home if not claude_home.is_dir() else claude_json
        raise CodeRefused(f"✗ Claude Code auth not found ({missing} is missing).\n"
                          "  Run `claude` on the host once and log in, then re-run.")
    found = which("claude")
    claude_bin = Path(found).resolve() if found else None
    if claude_bin is None or not claude_bin.is_file():
        raise CodeRefused("✗ Claude Code isn't installed on the host (`claude` not on PATH).\n"
                          "  The container runs the host's binary. Install it:\n"
                          "    curl -fsSL https://claude.ai/install.sh | bash")
    ps = run(docker + ["ps", "--format", "{{.Names}}"])
    names = set((ps.stdout or "").split()) if ps.returncode == 0 else set()
    for name, what in ((container_name(domain), "a `project code` session"),
                       (delegate_container_name(domain), "a `project delegate` run")):
        if name in names:
            raise CodeRefused(
                f"✗ {what} is already running on {domain} (container {name}).\n"
                "  Two agents on one working tree overwrite each other's edits.\n"
                f"  Finish that one first, or stop it:  docker rm -f {name}")
    return Preflight(site_dir=site_dir, claude_bin=claude_bin, dirty=_dirty(site_dir, run),
                     resume=has_prior_session(site_dir, claude_home))


# ---------- image ----------


def image_present(*, docker: list[str] | None = None, run: Runner = _default_runner) -> bool:
    return run((docker or ["docker"]) + ["image", "inspect", IMAGE]).returncode == 0


def build_image(*, docker: list[str] | None = None, run: Runner = _default_runner) -> None:
    """Build `lamill-code` from the inline Dockerfile. Output streams to the
    terminal (first build takes a minute or two)."""
    r = run((docker or ["docker"]) + ["build", "-t", IMAGE, "-"], input=DOCKERFILE,
            capture_output=False, text=True)
    if r.returncode != 0:
        raise CodeRefused(f"✗ Building the {IMAGE} image failed (docker exit {r.returncode}).\n"
                          "  The build output is above. Fix the cause and re-run.")


# ---------- context pack ----------

_DONE_RE = re.compile(r"^\s*(✓|✅|☑|done|shipped|dropped|complete)", re.I)


def open_prd_phases(prd_text: str, limit: int = 12) -> list[str]:
    """Phase-table rows (`| vN.X | status | feature |`) whose status isn't done."""
    out = []
    for line in prd_text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.fullmatch(r"v\d+\.[A-Z]", cells[0]):
            continue
        if _DONE_RE.match(cells[1]) or "~~" in cells[0]:
            continue
        out.append(f"{cells[0]} [{cells[1][:40]}] {cells[2][:200]}")
        if len(out) >= limit:
            break
    return out


def open_growth_entries(growth_text: str, limit: int = 5) -> list[str]:
    """Dated `## YYYY-MM-DD — …` entries whose Status is active / testing."""
    entries = re.split(r"(?m)^(?=## \d{4}-\d{2}-\d{2})", growth_text)
    out = []
    for e in entries:
        if not re.match(r"## \d{4}-\d{2}-\d{2}", e):
            continue
        m = re.search(r"Status:\**\s*(\w+)", e)
        if m and m.group(1).lower() in ("active", "testing"):
            out.append(e.strip()[:1200])
    return out[-limit:]


def _latest_json(folder: Path) -> tuple[str, dict] | None:
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for f in reversed(files):
        try:
            return f.stem, json.loads(f.read_text())
        except (OSError, ValueError):
            continue
    return None


def gsc_summary(domain: str, data_root: Path) -> str:
    latest = _latest_json(data_root / "seo")
    if not latest:
        return ""
    day, snap = latest
    row = next((r for r in snap.get("rows", []) if r.get("domain") == domain), None)
    if not row or row.get("gsc_status") != "ok":
        return ""
    days = snap.get("days", "?")
    pos = row.get("gsc_position")
    return (f"GSC, last {days} days (snapshot {day}): {row.get('gsc_impressions')} impressions, "
            f"{row.get('gsc_clicks')} clicks, avg position "
            f"{f'{pos:.1f}' if isinstance(pos, (int, float)) else '—'}; "
            f"homepage last crawled {row.get('gsc_last_crawl') or '—'}; "
            f"sitemap URLs {row.get('sitemap_url_count') or '—'}.")


def deep_summary(domain: str, data_root: Path) -> str:
    latest = _latest_json(data_root / "seo_deep" / domain)
    if not latest:
        return ""
    day, rep = latest
    lines = [f"`lamill project seo {domain} --deep` report of {day}:"]
    for f in rep.get("findings", [])[:6]:
        lines.append(f"- [{f.get('tier')}/{f.get('impact')}] {f.get('title')}")
        if f.get("fix"):
            lines.append(f"  fix: {str(f['fix'])[:300]}")
    return "\n".join(lines)


def fleet_learnings_for(domain: str, text: str, max_chars: int = 4000) -> str:
    """Paragraphs/bullets of fleet-learnings.md that name this site, under
    their section heading, plus the list of sections."""
    stem = domain.split(".")[0].lower()
    heads = [ln[3:].strip() for ln in text.splitlines() if ln.startswith("## ")]
    picked: list[str] = []
    section = ""
    for block in re.split(r"\n\s*\n", text):
        h = re.findall(r"(?m)^## (.+)$", block)
        if h:
            section = h[-1].strip()
        if stem in block.lower() and not block.lstrip().startswith("# "):
            picked.append(f"[{section}] {block.strip()}")
    body = "\n\n".join(picked)
    if len(body) > max_chars:
        body = body[:max_chars] + "\n[... truncated ...]"
    out = ["Fleet learnings (lessons across all LaMill sites; the full file is "
           "portfolio/docs/fleet-learnings.md on the host, not mounted here). "
           "Sections: " + "; ".join(heads) + "."]
    if body:
        out.append("Lines about this site:\n" + body)
    return "\n".join(out)


def _read(path: Path, cap: int) -> str:
    try:
        t = path.read_text(errors="replace")
    except OSError:
        return ""
    return t if len(t) <= cap else t[:cap] + "\n[... truncated ...]"


def build_context_pack(domain: str, site_dir: Path, *, data_root: Path | None = None,
                       learnings: Path | None = None, cap: int = CONTEXT_CAP) -> str:
    data_root = data_root or ROOT / "data"
    learnings = learnings or ROOT / "docs" / "fleet-learnings.md"
    parts = [
        f"=== LAMILL SESSION CONTEXT — {domain} (assembled by `lamill project code`) ===",
        "You are working interactively with the operator on this site. It runs in a "
        "container whose paths match the host's. Do not commit unless the operator "
        "asks. lamill writes docs/Prompts.md after the session — do not edit it.",
    ]
    ai = _read(site_dir / "AI_AGENTS.md", 4000)
    if ai:
        parts += ["", "=== AI_AGENTS.md ===", ai]
    prd = site_dir / "docs" / "prd.md"
    if prd.is_file():
        rows = open_prd_phases(_read(prd, 400_000))
        parts += ["", "=== docs/prd.md — open phases ===",
                  "\n".join(rows) if rows else "(no open phase rows parsed — read docs/prd.md)"]
    growth = site_dir / "docs" / "growth.md"
    if growth.is_file():
        entries = open_growth_entries(_read(growth, 400_000))
        if entries:
            parts += ["", "=== docs/growth.md — active / testing entries ===",
                      "\n\n".join(entries)]
    gsc = gsc_summary(domain, data_root)
    if gsc:
        parts += ["", "=== Search Console ===", gsc]
    deep = deep_summary(domain, data_root)
    if deep:
        parts += ["", "=== Indexing diagnosis ===", deep]
    if learnings.is_file():
        parts += ["", "=== Fleet learnings ===",
                  fleet_learnings_for(domain, _read(learnings, 400_000))]
    docs = site_dir / "docs"
    if docs.is_dir():
        names = sorted(p.name for p in docs.iterdir()
                       if p.is_file() and not p.name.startswith("."))
        if names:
            parts += ["", "=== docs/ map ===", "docs/ contains: " + ", ".join(names)
                      + ". Read what's relevant before changing things."]
    pack = "\n".join(parts)
    if len(pack) > cap:
        pack = pack[:cap] + "\n[... context pack truncated at the size cap ...]"
    return pack


# ---------- container ----------


def run_args(domain: str, site_dir: Path, *, home: Path, claude_home: Path,
             claude_json: Path, claude_bin: Path, gitconfig: Path | None) -> list[str]:
    """`docker run` argv for the per-site container (same paths as the host)."""
    args = ["run", "-d", "--name", container_name(domain), "--network=host",
            "--tmpfs", f"{home}:rw,exec,mode=1777",
            "-v", f"{site_dir}:{site_dir}",
            "-v", f"{claude_home}:{home}/.claude",
            "-v", f"{claude_json}:{home}/.claude.json",
            "-v", f"{claude_bin}:{CLAUDE_IN_CONTAINER}:ro"]
    if gitconfig is not None and gitconfig.is_file():
        args += ["-v", f"{gitconfig}:{home}/.gitconfig:ro"]
    args += ["-e", f"HOME={home}", "-w", str(site_dir), IMAGE, "sleep", "infinity"]
    return args


def exec_args(domain: str, site_dir: Path, *, home: Path, uid: int, gid: int,
              resume: bool, context: str) -> list[str]:
    """`docker exec -it … claude` argv. Normal permission prompts (ADR-0031)."""
    env = ["-e", f"HOME={home}", "-e", "DISABLE_AUTOUPDATER=1"]
    for k in ("TERM", "COLORTERM", "LANG"):
        if os.environ.get(k):
            env += ["-e", f"{k}={os.environ[k]}"]
    cmd = ["exec", "-it", "--user", f"{uid}:{gid}", *env, "-w", str(site_dir),
           container_name(domain), CLAUDE_IN_CONTAINER]
    if resume:
        cmd.append("--continue")
    cmd += ["--append-system-prompt", context, "--system-prompt-snapshot", "off"]
    return cmd


# ---------- v53.C: transcript → summary → Prompts.md ----------
#
# Claude Code's transcript (`~/.claude/projects/<encoded cwd>/<id>.jsonl`) is
# an internal format that can change on any upgrade (ADR-0031). Everything
# that reads it lives here, and every way it can fail ends in a plain ✗ —
# never a silently skipped log entry.

TRANSCRIPT_TEXT_CAP = 60_000
_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


class TranscriptError(Exception):
    """The transcript is missing or unreadable — logged as ✗."""


@dataclass
class SessionExtract:
    path: Path
    prompts: int
    text: str
    files: list[str]


def find_transcript(site_dir: Path, claude_home: Path, started: float) -> Path:
    """The site's transcript written during this sitting: the newest
    `*.jsonl` in its project folder modified since the session started."""
    d = transcript_dir(site_dir, claude_home)
    files = [f for f in d.glob("*.jsonl") if f.stat().st_mtime >= started - 1] \
        if d.is_dir() else []
    if not files:
        raise TranscriptError(
            f"no session transcript written to {d} during this session. Claude Code "
            "may have changed where it saves sessions — re-check after upgrades.")
    return max(files, key=lambda f: f.stat().st_mtime)


def _ts(rec: dict) -> float | None:
    from datetime import datetime
    t = rec.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _user_text(content) -> str:
    if isinstance(content, list):     # tool results / pasted images: text blocks only
        content = "\n".join(b.get("text", "") for b in content
                            if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return ""
    t = content.strip()
    m = re.search(r"<command-name>(.*?)</command-name>", t)
    if m:
        return m.group(1).strip()
    if t.startswith(("<local-command", "Caveat:", "<system-reminder>")):
        return ""
    return t


def extract_session(path: Path, started: float) -> SessionExtract:
    """Operator prompts, Claude's replies and edited files since `started`
    (a resumed session's earlier sittings are left out)."""
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError as e:
        raise TranscriptError(f"can't read {path}: {e}") from e
    turns: list[str] = []
    files: list[str] = []
    prompts = recognised = 0
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("type") not in ("user", "assistant"):
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            continue
        recognised += 1
        ts = _ts(rec)
        if rec.get("isSidechain") or (ts is not None and ts < started - 1):
            continue
        if rec["type"] == "user":
            t = _user_text(msg.get("content"))
            if t:
                prompts += 1
                turns.append(f"OPERATOR: {t[:3000]}")
            continue
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and b.get("text", "").strip():
                turns.append(f"CLAUDE: {b['text'].strip()[:1500]}")
            elif b.get("type") == "tool_use":
                inp = b.get("input") or {}
                if b.get("name") in _EDIT_TOOLS:
                    fp = inp.get("file_path") or inp.get("notebook_path")
                    if fp and fp not in files:
                        files.append(fp)
                elif b.get("name") == "Bash" and inp.get("command"):
                    turns.append(f"CLAUDE ran: {str(inp['command'])[:160]}")
    if lines and not recognised:
        raise TranscriptError(f"{path.name}: no user/assistant records recognised — the "
                              "transcript format may have changed in a Claude Code update.")
    text = "\n\n".join(turns)
    if len(text) > TRANSCRIPT_TEXT_CAP:
        head = TRANSCRIPT_TEXT_CAP // 3
        text = (text[:head] + "\n\n[... middle of session omitted ...]\n\n"
                + text[-(TRANSCRIPT_TEXT_CAP - head):])
    return SessionExtract(path=path, prompts=prompts, text=text, files=files)


SUMMARY_PROMPT = """Summarise this interactive Claude Code session on the website \
{domain} for the site's prompt log. Write exactly four markdown bullets and nothing else:

- **Asked:** what the operator wanted
- **Changed:** what was actually changed (files, content) — "nothing" if nothing
- **Decided:** decisions or conclusions reached — "none" if none
- **Open:** follow-ups left open — "none" if none

Plain words, at most 120 words in total. Use only what the transcript shows; \
don't invent. Files edited: {files}.

TRANSCRIPT
{text}
"""


def summarize(domain: str, ex: SessionExtract, *, run: Runner = _default_runner,
              claude: str = "claude") -> str:
    """`claude -p` on the host, prompt on stdin. Runs from a scratch dir with
    `--no-session-persistence` so the summariser's own conversation never
    lands in the site's folder (it would become the next `--continue`)."""
    import tempfile
    prompt = SUMMARY_PROMPT.format(domain=domain, text=ex.text,
                                   files=", ".join(ex.files) or "none")
    with tempfile.TemporaryDirectory(prefix="lamill-code-summary-") as tmp:
        try:
            r = run([claude, "-p", "--no-session-persistence", "--output-format", "json",
                     "--allowedTools", "", "--max-budget-usd", "0.50"],
                    input=prompt, cwd=tmp, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise TranscriptError(f"summary call failed: {e}") from e
    try:
        out = json.loads(r.stdout or "")
    except ValueError:
        out = {}
    text = (out.get("result") or "").strip() if isinstance(out, dict) else ""
    if r.returncode != 0 or out.get("is_error") or not text:
        why = text or (r.stderr or r.stdout or "").strip()[-300:] or f"exit {r.returncode}"
        raise TranscriptError(f"summary call failed: {why}")
    return text


def append_prompts_entry(site_dir: Path, domain: str, summary: str, today: str) -> Path:
    """Dated `## YYYY-MM-DD — code session` entry (v33.H shape)."""
    from .delegate import _PROMPTS_MD_HEADER
    prompts = site_dir / "docs" / "Prompts.md"
    entry = f"\n## {today} — code session\n{summary.strip()}\n"
    if prompts.exists():
        with prompts.open("a", encoding="utf-8") as fh:
            fh.write(entry)
    else:
        prompts.parent.mkdir(parents=True, exist_ok=True)
        prompts.write_text(_PROMPTS_MD_HEADER.format(domain=domain) + entry,
                           encoding="utf-8")
    return prompts


def log_session(domain: str, site_dir: Path, claude_home: Path, started: float, *,
                emit: Emit, run: Runner = _default_runner, today: str | None = None,
                claude: str = "claude") -> bool:
    """Find → extract → summarise → append. Returns False when logging failed
    (✗ printed); True when logged or when there was nothing to log (↷)."""
    from datetime import date
    try:
        path = find_transcript(site_dir, claude_home, started)
        ex = extract_session(path, started)
        if ex.prompts == 0:
            emit("↷", "no prompts this session — nothing logged to Prompts.md")
            return True
        emit("✓", f"transcript {path.name} — {ex.prompts} prompt(s), "
                  f"{len(ex.files)} file(s) edited")
        summary = summarize(domain, ex, run=run, claude=claude)
        prompts = append_prompts_entry(site_dir, domain, summary,
                                       today or date.today().isoformat())
    except TranscriptError as e:
        emit("✗", f"session not logged to docs/Prompts.md — {e}")
        return False
    except OSError as e:
        emit("✗", f"session not logged — couldn't write docs/Prompts.md: {e}")
        return False
    emit("✓", f"summary → {prompts.relative_to(site_dir)}")
    print(summary, flush=True)
    return True


def show_diff(site_dir: Path, *, emit: Emit, run: Runner = _default_runner) -> None:
    """Uncommitted state + the commit command. lamill never commits."""
    st = run(["git", "-C", str(site_dir), "status", "--porcelain"])
    changed = [ln for ln in (st.stdout or "").splitlines() if ln.strip()]
    if not changed:
        emit("✓", "working tree clean — nothing to commit")
        return
    stat = run(["git", "-C", str(site_dir), "diff", "--stat", "HEAD"])
    last = [ln for ln in (stat.stdout or "").splitlines() if ln.strip()]
    untracked = sum(1 for ln in changed if ln.startswith("??"))
    emit("↷", f"{len(changed)} uncommitted path(s)"
              + (f" — {last[-1].strip()}" if last else "")
              + (f", {untracked} untracked" if untracked else ""))
    print(f"  review + commit:  cd {site_dir} && git status && git add -A && git commit",
          flush=True)


def _print_emit(mark: str, text: str) -> None:
    print(f"{mark} {text}", flush=True)


def run_code(domain: str, *, emit: Emit = _print_emit, run: Runner = _default_runner,
             docker: list[str] | None = None, sites_root: Path | None = None,
             home: Path | None = None, isatty: bool | None = None,
             which: Callable[[str], str | None] = shutil.which) -> int:
    """The whole session. Returns claude's exit code; raises CodeRefused."""
    docker = docker or ["docker"]
    home = home or Path.home()
    claude_home, claude_json = home / ".claude", home / ".claude.json"
    full = resolve_domain(domain, sites_root)
    if full != domain:
        emit("✓", f"{domain} → {full}")
    domain = full
    pf = preflight(domain, sites_root=sites_root, claude_home=claude_home,
                   claude_json=claude_json, docker=docker, run=run, isatty=isatty,
                   which=which)
    emit("✓", f"site {pf.site_dir}")
    if pf.dirty:
        emit("↷", f"working tree has {len(pf.dirty)} uncommitted change(s) — "
                  "they'll mix with this session's edits in the diff")
    if image_present(docker=docker, run=run):
        emit("✓", f"image {IMAGE}")
    else:
        emit("↷", f"image {IMAGE} not found — building it (first run only)")
        build_image(docker=docker, run=run)
        emit("✓", f"image {IMAGE} built")
    context = build_context_pack(domain, pf.site_dir)
    emit("✓", f"context pack {len(context):,} chars")
    name = container_name(domain)
    run(docker + ["rm", "-f", name])
    r = run(docker + run_args(domain, pf.site_dir, home=home, claude_home=claude_home,
                              claude_json=claude_json, claude_bin=pf.claude_bin,
                              gitconfig=home / ".gitconfig"))
    if r.returncode != 0:
        raise CodeRefused(f"✗ Container start failed: {(r.stderr or '').strip()}")
    try:
        emit("✓", f"container {name}")
        started = time.time()
        emit("✓", "resuming this site's last session (/clear starts fresh)" if pf.resume
             else "no earlier session for this site — starting fresh")
        # Ctrl-C belongs to Claude (interrupt), not to lamill. A Python-level
        # no-op handler (unlike SIG_IGN) resets to default in the child on exec.
        prev = signal.signal(signal.SIGINT, lambda *_: None)
        try:
            session = run(docker + exec_args(domain, pf.site_dir, home=home,
                                             uid=os.getuid(), gid=os.getgid(),
                                             resume=pf.resume, context=context),
                          capture_output=False)
        finally:
            signal.signal(signal.SIGINT, prev)
        code = session.returncode
    finally:
        run(docker + ["rm", "-f", name])
    emit("✓" if code == 0 else "✗", f"session ended (claude exit {code}); container removed")
    logged = log_session(domain, pf.site_dir, claude_home, started, emit=emit, run=run,
                         claude=str(pf.claude_bin))
    show_diff(pf.site_dir, emit=emit, run=run)
    return code if code != 0 or logged else 1
