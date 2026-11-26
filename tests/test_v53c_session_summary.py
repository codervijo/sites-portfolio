"""v53.C — session transcript → summary → docs/Prompts.md (ADR-0031 § 7)."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from portfolio import project_code as pc

T0 = 1_790_000_000.0          # session start (epoch)


def _iso(t: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _user(text, t=T0 + 10, **kw):
    return {"type": "user", "timestamp": _iso(t), "message": {"role": "user", "content": text}, **kw}


def _asst(blocks, t=T0 + 20, **kw):
    return {"type": "assistant", "timestamp": _iso(t),
            "message": {"role": "assistant", "content": blocks}, **kw}


def _write(path: Path, recs: list, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) if not isinstance(r, str) else r for r in recs) + "\n")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def site(tmp_path):
    s = tmp_path / "sites" / "example.com"
    (s / "docs").mkdir(parents=True)
    return s


@pytest.fixture
def claude_home(tmp_path):
    return tmp_path / ".claude"


SESSION = [
    {"type": "mode", "x": 1},
    _user("old question from an earlier sitting", t=T0 - 3600),
    _asst([{"type": "text", "text": "old answer"}], t=T0 - 3500),
    _user("<command-name>/project-context</command-name>"),
    _user("<local-command-stdout>noise</local-command-stdout>"),
    _user("add a pricing FAQ to the homepage"),
    _asst([{"type": "text", "text": "Added three FAQs."},
           {"type": "tool_use", "name": "Edit", "input": {"file_path": "/s/src/pages/index.astro"}},
           {"type": "tool_use", "name": "Write", "input": {"file_path": "/s/src/data/faq.ts"}},
           {"type": "tool_use", "name": "Edit", "input": {"file_path": "/s/src/pages/index.astro"}},
           {"type": "tool_use", "name": "Bash", "input": {"command": "pnpm build"}}]),
    _user([{"type": "tool_result", "content": "ok"}]),
    _asst([{"type": "text", "text": "subagent chatter"}], isSidechain=True),
    "not json at all",
]


# ---------- find ----------

def test_find_transcript_picks_newest_since_start(site, claude_home):
    d = pc.transcript_dir(site, claude_home)
    _write(d / "old.jsonl", [], mtime=T0 - 100)
    _write(d / "a.jsonl", [], mtime=T0 + 5)
    _write(d / "b.jsonl", [], mtime=T0 + 50)
    assert pc.find_transcript(site, claude_home, T0).name == "b.jsonl"


def test_find_transcript_none_since_start_is_loud(site, claude_home):
    _write(pc.transcript_dir(site, claude_home) / "old.jsonl", [], mtime=T0 - 100)
    with pytest.raises(pc.TranscriptError, match="no session transcript"):
        pc.find_transcript(site, claude_home, T0)


def test_find_transcript_no_folder(site, claude_home):
    with pytest.raises(pc.TranscriptError):
        pc.find_transcript(site, claude_home, T0)


# ---------- extract ----------

def test_extract_session(tmp_path):
    ex = pc.extract_session(_write(tmp_path / "s.jsonl", SESSION), T0)
    assert ex.prompts == 2                                   # /project-context + the ask
    assert "OPERATOR: /project-context" in ex.text
    assert "OPERATOR: add a pricing FAQ" in ex.text
    assert "CLAUDE: Added three FAQs." in ex.text and "CLAUDE ran: pnpm build" in ex.text
    assert "old question" not in ex.text and "subagent" not in ex.text
    assert "noise" not in ex.text
    assert ex.files == ["/s/src/pages/index.astro", "/s/src/data/faq.ts"]


def test_extract_unrecognised_format_is_loud(tmp_path):
    p = _write(tmp_path / "s.jsonl", [{"kind": "msg", "body": "hi"}])
    with pytest.raises(pc.TranscriptError, match="format may have changed"):
        pc.extract_session(p, T0)


def test_extract_caps_text(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "TRANSCRIPT_TEXT_CAP", 300)
    recs = [_user(f"prompt {i} " + "x" * 100) for i in range(20)]
    ex = pc.extract_session(_write(tmp_path / "s.jsonl", recs), T0)
    assert "middle of session omitted" in ex.text and len(ex.text) < 400
    assert "prompt 0" in ex.text and "prompt 19" in ex.text


# ---------- summarize ----------

def _ex():
    return pc.SessionExtract(path=Path("x"), prompts=1, text="OPERATOR: hi", files=["a.astro"])


def test_summarize_call_shape():
    seen = {}

    def run(args, **kw):
        seen["args"], seen["kw"] = args, kw
        return subprocess.CompletedProcess(args, 0, json.dumps({"result": "- **Asked:** hi"}), "")
    out = pc.summarize("example.com", _ex(), run=run, claude="/bin/claude")
    assert out == "- **Asked:** hi"
    a = seen["args"]
    assert a[0] == "/bin/claude" and "-p" in a and "--no-session-persistence" in a
    assert "OPERATOR: hi" in seen["kw"]["input"] and "a.astro" in seen["kw"]["input"]
    assert "example.com" not in Path(seen["kw"]["cwd"]).name      # scratch dir, not the site


@pytest.mark.parametrize("rc,out,err", [
    (1, "", "auth expired"),
    (0, json.dumps({"is_error": True, "result": "budget exceeded"}), ""),
    (0, json.dumps({"result": ""}), ""),
    (0, "not json", ""),
])
def test_summarize_failures_are_loud(rc, out, err):
    run = lambda args, **kw: subprocess.CompletedProcess(args, rc, out, err)  # noqa: E731
    with pytest.raises(pc.TranscriptError, match="summary call failed"):
        pc.summarize("example.com", _ex(), run=run)


# ---------- Prompts.md ----------

def test_append_creates_with_header(site):
    p = pc.append_prompts_entry(site, "example.com", "- **Asked:** x", "2026-11-26")
    t = p.read_text()
    assert t.startswith("# Prompt History — example.com")
    assert t.endswith("\n## 2026-11-26 — code session\n- **Asked:** x\n")


def test_append_appends(site):
    (site / "docs" / "Prompts.md").write_text("# existing\n")
    pc.append_prompts_entry(site, "example.com", "S", "2026-11-26")
    assert (site / "docs" / "Prompts.md").read_text() == "# existing\n\n## 2026-11-26 — code session\nS\n"


# ---------- log_session ----------

def _log(site, claude_home, run, marks):
    return pc.log_session("example.com", site, claude_home, T0,
                          emit=lambda m, t: marks.append((m, t)), run=run, today="2026-11-26")


def test_log_session_happy(site, claude_home):
    _write(pc.transcript_dir(site, claude_home) / "s.jsonl", SESSION, mtime=T0 + 60)
    run = lambda args, **kw: subprocess.CompletedProcess(  # noqa: E731
        args, 0, json.dumps({"result": "- **Asked:** FAQ"}), "")
    marks: list = []
    assert _log(site, claude_home, run, marks) is True
    assert "## 2026-11-26 — code session\n- **Asked:** FAQ" in (site / "docs" / "Prompts.md").read_text()
    assert [m for m, _ in marks] == ["✓", "✓"]


def test_log_session_nothing_asked(site, claude_home):
    _write(pc.transcript_dir(site, claude_home) / "s.jsonl", [_asst([])], mtime=T0 + 60)
    marks: list = []
    assert _log(site, claude_home, None, marks) is True
    assert marks[0][0] == "↷" and not (site / "docs" / "Prompts.md").exists()


def test_log_session_missing_transcript(site, claude_home):
    marks: list = []
    assert _log(site, claude_home, None, marks) is False
    assert marks[0][0] == "✗" and "not logged" in marks[0][1]


def test_log_session_summary_failure(site, claude_home):
    _write(pc.transcript_dir(site, claude_home) / "s.jsonl", SESSION, mtime=T0 + 60)
    run = lambda args, **kw: subprocess.CompletedProcess(args, 1, "", "boom")  # noqa: E731
    marks: list = []
    assert _log(site, claude_home, run, marks) is False
    assert marks[-1][0] == "✗" and not (site / "docs" / "Prompts.md").exists()


# ---------- diff ----------

def test_show_diff(site, capsys):
    def run(args, **kw):
        if "status" in args:
            return subprocess.CompletedProcess(args, 0, " M a\n?? b\n", "")
        return subprocess.CompletedProcess(args, 0, " a | 2 +-\n 1 file changed\n", "")
    marks: list = []
    pc.show_diff(site, emit=lambda m, t: marks.append((m, t)), run=run)
    assert marks == [("↷", "2 uncommitted path(s) — 1 file changed, 1 untracked")]
    assert "git commit" in capsys.readouterr().out


def test_show_diff_clean(site):
    marks: list = []
    pc.show_diff(site, emit=lambda m, t: marks.append((m, t)),
                 run=lambda a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    assert marks[0][0] == "✓"


def test_real_transcript_parses_if_present():
    """Guard against format drift: parse a real transcript on this machine."""
    d = Path.home() / ".claude" / "projects"
    files = sorted(d.glob("*/*.jsonl"), key=lambda f: f.stat().st_mtime)[-1:] if d.is_dir() else []
    if not files:
        pytest.skip("no local Claude Code transcripts")
    ex = pc.extract_session(files[0], 0)
    assert ex.prompts > 0
