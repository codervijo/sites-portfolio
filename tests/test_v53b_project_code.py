"""v53.B — `lamill project code <domain>` (ADR-0031)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from portfolio import project_code as pc


def _cp(rc: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], rc, out, err)


class FakeRun:
    """Records argv; answers docker/git calls from a small table."""

    def __init__(self, *, docker_ok=True, running=(), dirty="", image=True,
                 session_rc=0, run_rc=0):
        self.calls: list[list[str]] = []
        self.kw: list[dict] = []
        self.docker_ok, self.running, self.dirty = docker_ok, running, dirty
        self.image, self.session_rc, self.run_rc = image, session_rc, run_rc

    def __call__(self, args, **kw):
        self.calls.append(list(args))
        self.kw.append(kw)
        if args[:1] == ["git"]:
            return _cp(0, self.dirty)
        sub = args[1] if len(args) > 1 else ""
        if sub == "info":
            return _cp(0 if self.docker_ok else 1)
        if sub == "ps":
            return _cp(0, "\n".join(self.running))
        if sub == "image":
            return _cp(0 if self.image else 1)
        if sub == "run":
            return _cp(self.run_rc, "", "boom" if self.run_rc else "")
        if sub == "exec":
            return _cp(self.session_rc)
        return _cp(0)

    def subs(self) -> list[str]:
        return [c[1] if c[0] == "docker" else c[0] for c in self.calls]


@pytest.fixture
def env(tmp_path):
    sites = tmp_path / "sites"
    site = sites / "example.com"
    (site / ".git").mkdir(parents=True)
    (site / "docs").mkdir()
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude.json").write_text("{}")
    (home / "bin").mkdir()
    (home / "bin" / "claude").write_text("")
    return sites, site, home


def _which(home):
    return lambda name: str(home / "bin" / "claude")


def _pre(env, run, **kw):
    sites, _, home = env
    return pc.preflight("example.com", sites_root=sites, claude_home=home / ".claude",
                        claude_json=home / ".claude.json", run=run,
                        isatty=kw.pop("isatty", True),
                        which=kw.pop("which", _which(home)), **kw)


# ---------- paths / resume ----------

def test_transcript_dir_encodes_like_claude_code(tmp_path):
    d = pc.transcript_dir(Path("/home/v/work/sites/calcengine.site"), tmp_path)
    assert d == tmp_path / "projects" / "-home-v-work-sites-calcengine-site"


def test_has_prior_session(env):
    _, site, home = env
    assert not pc.has_prior_session(site, home / ".claude")
    d = pc.transcript_dir(site, home / ".claude")
    d.mkdir(parents=True)
    (d / "abc.jsonl").write_text("{}\n")
    assert pc.has_prior_session(site, home / ".claude")


# ---------- preflight ----------

def test_preflight_ok_resume_false(env):
    pf = _pre(env, FakeRun())
    assert pf.site_dir == env[1].resolve() and pf.resume is False and pf.dirty == []
    assert pf.claude_bin == (env[2] / "bin" / "claude").resolve()


def test_preflight_no_host_claude(env):
    with pytest.raises(pc.CodeRefused, match="isn't installed on the host"):
        _pre(env, FakeRun(), which=lambda n: None)


def test_preflight_missing_site(env):
    sites, _, home = env
    with pytest.raises(pc.CodeRefused, match="No site directory"):
        pc.preflight("nope.com", sites_root=sites, claude_home=home / ".claude",
                     claude_json=home / ".claude.json", run=FakeRun(), isatty=True,
                     which=_which(home))


def test_preflight_not_git(env):
    (env[1] / ".git").rmdir()
    with pytest.raises(pc.CodeRefused, match="not a git repository"):
        _pre(env, FakeRun())


def test_preflight_needs_tty(env):
    with pytest.raises(pc.CodeRefused, match="needs a terminal"):
        _pre(env, FakeRun(), isatty=False)


def test_preflight_docker_down(env):
    with pytest.raises(pc.CodeRefused, match="Docker isn't reachable"):
        _pre(env, FakeRun(docker_ok=False))


def test_preflight_no_auth(env):
    (env[2] / ".claude.json").unlink()
    with pytest.raises(pc.CodeRefused, match="auth not found"):
        _pre(env, FakeRun())


@pytest.mark.parametrize("name,what", [("lamill-code-example-com", "project code"),
                                       ("lamill-delegate-example-com", "project delegate")])
def test_preflight_refuses_second_session(env, name, what):
    with pytest.raises(pc.CodeRefused, match=what):
        _pre(env, FakeRun(running=["other", name]))


def test_preflight_other_site_running_is_fine(env):
    _pre(env, FakeRun(running=["lamill-code-other-com"]))


def test_preflight_dirty_is_warning_not_refusal(env):
    pf = _pre(env, FakeRun(dirty=" M src/x.astro\n?? y"))
    assert pf.dirty == [" M src/x.astro", "?? y"]


# ---------- argv ----------

def test_run_args_same_paths_as_host(tmp_path):
    home = tmp_path / "h"
    site = home / "work" / "sites" / "example.com"
    gc = home / ".gitconfig"
    gc.parent.mkdir(parents=True)
    gc.write_text("[user]\n")
    a = pc.run_args("example.com", site, home=home, claude_home=home / ".claude",
                    claude_json=home / ".claude.json", claude_bin=Path("/x/claude"),
                    gitconfig=gc)
    assert f"{site}:{site}" in a
    assert f"{home}/.claude:{home}/.claude" in a
    assert f"{home}/.claude.json:{home}/.claude.json" in a
    assert f"{gc}:{home}/.gitconfig:ro" in a
    assert f"/x/claude:{pc.CLAUDE_IN_CONTAINER}:ro" in a
    assert a[a.index("-w") + 1] == str(site)
    assert f"HOME={home}" in a and "lamill-code-example-com" in a and pc.IMAGE in a
    assert "--dangerously-skip-permissions" not in a


def test_run_args_skips_missing_gitconfig(tmp_path):
    a = pc.run_args("example.com", tmp_path, home=tmp_path, claude_home=tmp_path,
                    claude_json=tmp_path, claude_bin=tmp_path, gitconfig=tmp_path / "none")
    assert not any(".gitconfig" in x for x in a)


@pytest.mark.parametrize("resume", [True, False])
def test_exec_args(resume, tmp_path):
    a = pc.exec_args("example.com", tmp_path, home=tmp_path, uid=1000, gid=1000,
                     resume=resume, context="CTX")
    assert a[:2] == ["exec", "-it"] and "1000:1000" in a
    assert pc.CLAUDE_IN_CONTAINER in a
    assert ("--continue" in a) is resume
    assert a[a.index("--append-system-prompt") + 1] == "CTX"
    assert a[a.index("--system-prompt-snapshot") + 1] == "off"
    assert "--dangerously-skip-permissions" not in a and "-p" not in a


# ---------- context pack ----------

PRD = """
| # | Status | Feature |
|---|---|---|
| v1.A | ✓ 2026-10-05 | done thing |
| v1.B | ☑ | locked thing |
| v2.A | active | keyword research |
| v2.B | ☐ | build calculators |
| ~~v2.C~~ | dropped | gone |
"""

GROWTH = """# Growth Log
## YYYY-MM-DD — template
- **Status:** active | testing
## 2026-10-05 — pivot
- **Status:** shipped
## 2026-11-21 — recovery plan
- **Status:** testing
body
"""


def test_open_prd_phases():
    rows = pc.open_prd_phases(PRD)
    assert [r.split()[0] for r in rows] == ["v2.A", "v2.B"]


def test_open_growth_entries():
    e = pc.open_growth_entries(GROWTH)
    assert len(e) == 1 and e[0].startswith("## 2026-11-21")


def test_fleet_learnings_for():
    text = ("# Fleet learnings\n\n## Getting pages crawled\n\n- calcengine had 1/81 indexed.\n\n"
            "- other site.\n\n## Measuring\n\n- nothing here.\n")
    out = pc.fleet_learnings_for("calcengine.site", text)
    assert "Getting pages crawled; Measuring" in out
    assert "[Getting pages crawled] - calcengine had 1/81" in out
    assert "other site" not in out


def test_build_context_pack(env, tmp_path):
    _, site, _ = env
    (site / "AI_AGENTS.md").write_text("agent guide")
    (site / "docs" / "prd.md").write_text(PRD)
    (site / "docs" / "growth.md").write_text(GROWTH)
    data = tmp_path / "data"
    (data / "seo").mkdir(parents=True)
    (data / "seo" / "2026-11-26.json").write_text(json.dumps({"days": 90, "rows": [
        {"domain": "example.com", "gsc_status": "ok", "gsc_impressions": 17,
         "gsc_clicks": 0, "gsc_position": 25.76, "gsc_last_crawl": "2026-11-21",
         "sitemap_url_count": 81}]}))
    (data / "seo_deep" / "example.com").mkdir(parents=True)
    (data / "seo_deep" / "example.com" / "2026-11-25.json").write_text(json.dumps(
        {"findings": [{"tier": "likely", "impact": "high", "title": "not discovered"}]}))
    lf = tmp_path / "fl.md"
    lf.write_text("# F\n\n## Choosing a domain\n\n- example was fine.\n")
    pack = pc.build_context_pack("example.com", site, data_root=data, learnings=lf)
    for s in ("agent guide", "v2.B", "2026-11-21 — recovery plan",
              "17 impressions", "position 25.8", "[likely/high] not discovered",
              "example was fine", "docs/ contains: growth.md, prd.md"):
        assert s in pack, s


def test_context_pack_cap(env, tmp_path):
    _, site, _ = env
    (site / "AI_AGENTS.md").write_text("x" * 50_000)
    pack = pc.build_context_pack("example.com", site, data_root=tmp_path,
                                 learnings=tmp_path / "none", cap=1000)
    assert len(pack) < 1100 and pack.endswith("size cap ...]")


def test_context_pack_tolerates_nothing(env, tmp_path):
    pack = pc.build_context_pack("example.com", env[1], data_root=tmp_path,
                                 learnings=tmp_path / "none")
    assert "LAMILL SESSION CONTEXT" in pack


# ---------- run_code ----------

def _removed_after_exec(fake) -> bool:
    i = fake.subs().index("exec")
    return any(c[1:3] == ["rm", "-f"] for c in fake.calls[i + 1:])


def _run_code(env, fake, monkeypatch, **kw):
    sites, _, home = env
    monkeypatch.setattr(pc, "build_context_pack", lambda d, s: "CTX")
    monkeypatch.setattr(pc, "log_session", kw.pop("log_session", lambda *a, **k: True))
    marks: list[tuple[str, str]] = []
    rc = pc.run_code("example.com", emit=lambda m, t: marks.append((m, t)), run=fake,
                     sites_root=sites, home=home, isatty=True, which=_which(home), **kw)
    return rc, marks


def test_run_code_happy_path(env, monkeypatch):
    fake = FakeRun()
    rc, marks = _run_code(env, fake, monkeypatch)
    assert rc == 0
    subs = fake.subs()
    assert subs.index("run") < subs.index("exec") < len(subs) - 1
    assert _removed_after_exec(fake)
    exec_kw = fake.kw[subs.index("exec")]
    assert exec_kw.get("capture_output") is False        # terminal handed through



def test_run_code_builds_missing_image(env, monkeypatch):
    fake = FakeRun(image=False)
    _, marks = _run_code(env, fake, monkeypatch)
    assert "build" in fake.subs()
    assert fake.kw[fake.subs().index("build")]["input"] == pc.DOCKERFILE


def test_run_code_removes_container_when_session_fails(env, monkeypatch):
    fake = FakeRun(session_rc=3)
    rc, marks = _run_code(env, fake, monkeypatch)
    assert rc == 3 and _removed_after_exec(fake)
    assert any(m == "✗" for m, _ in marks)


def test_run_code_container_start_failure(env, monkeypatch):
    with pytest.raises(pc.CodeRefused, match="Container start failed: boom"):
        _run_code(env, FakeRun(run_rc=1), monkeypatch)


def test_run_code_warns_on_dirty_tree(env, monkeypatch):
    _, marks = _run_code(env, FakeRun(dirty=" M a"), monkeypatch)
    assert any(m == "↷" and "uncommitted" in t for m, t in marks)


def test_cli_registers_project_code():
    from typer.testing import CliRunner
    from portfolio.cli import app
    r = CliRunner().invoke(app, ["project", "code", "--help"])
    assert r.exit_code == 0 and "live Claude session" in r.output


def test_run_code_returns_1_when_logging_fails(env, monkeypatch):
    rc, _ = _run_code(env, FakeRun(), monkeypatch, log_session=lambda *a, **k: False)
    assert rc == 1


# ---------- v53.D: short names ----------

@pytest.fixture
def root(tmp_path):
    for d in ("calcengine.site", "lamill.pics", "lamill.store", "dunam.app.bup",
              "portfolio"):
        (tmp_path / d).mkdir()
    (tmp_path / "notes.txt").write_text("")
    return tmp_path


@pytest.mark.parametrize("name,want", [
    ("calcengine", "calcengine.site"),
    ("CalcEngine/", "calcengine.site"),
    ("calcengine.site", "calcengine.site"),
    ("lamill.pics", "lamill.pics"),
    ("portfolio", "portfolio"),           # existing non-domain dir passes through
    ("other.com", "other.com"),           # full names pass through; preflight judges
])
def test_resolve_domain(root, name, want):
    assert pc.resolve_domain(name, root) == want


def test_resolve_domain_ambiguous(root):
    with pytest.raises(pc.CodeRefused, match="lamill.pics, lamill.store"):
        pc.resolve_domain("lamill", root)


def test_resolve_domain_ignores_backups_and_unknown(root):
    with pytest.raises(pc.CodeRefused, match="No site named 'dunam'"):
        pc.resolve_domain("dunam", root)


def test_run_code_resolves_short_name(env, monkeypatch):
    rc, marks = _run_code_named(env, FakeRun(), monkeypatch, "example")
    assert rc == 0 and ("✓", "example → example.com") in marks


def _run_code_named(env, fake, monkeypatch, name):
    sites, _, home = env
    monkeypatch.setattr(pc, "build_context_pack", lambda d, s: "CTX")
    monkeypatch.setattr(pc, "log_session", lambda *a, **k: True)
    marks: list = []
    rc = pc.run_code(name, emit=lambda m, t: marks.append((m, t)), run=fake,
                     sites_root=sites, home=home, isatty=True, which=_which(home))
    return rc, marks


# ---------- did you mean ----------

def test_did_you_mean_short_typo(root):
    with pytest.raises(pc.CodeRefused, match=r"Did you mean calcengine\.site\?"):
        pc.resolve_domain("caclengine", root)


def test_did_you_mean_full_typo(env):
    sites, _, home = env
    with pytest.raises(pc.CodeRefused, match=r"Did you mean example\.com\?"):
        pc.preflight("exmaple.com", sites_root=sites, claude_home=home / ".claude",
                     claude_json=home / ".claude.json", run=FakeRun(), isatty=True,
                     which=_which(home))


def test_did_you_mean_lists_all_matching_sites(root):
    assert pc.did_you_mean("lamil", root) == "\n  Did you mean lamill.pics or lamill.store?"


def test_did_you_mean_nothing_close(root):
    with pytest.raises(pc.CodeRefused, match="Use the full domain"):
        pc.resolve_domain("zzzzzz", root)
