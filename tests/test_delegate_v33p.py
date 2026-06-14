"""v33.P — delegate quota-aware self-healing on the 5-hour cap.

Pins the contract: a rate-limited run is detected, the partial diff is
reverted, the loop waits out the reset (countdown ticks), retries, and
completes — with no real time or docker (sleep/now/backend injected).
`--no-wait` (and non-TTY, which the CLI maps to it) fails fast with the
reset time + a clean tree; `--max-wait`/`--max-retries` bound the loop.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from portfolio.delegate import (
    QuotaStatus,
    ResilientConfig,
    parse_resets_at,
    probe_quota_host,
    quota_from_rate_limit,
    result_quota,
    run_delegate_resilient,
)


def _git(args, cwd):
    subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, check=False)


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "sites"
    d = root / "example.com"
    d.mkdir(parents=True)
    _git(["init"], d)
    _git(["config", "user.email", "t@t.t"], d)
    _git(["config", "user.name", "t"], d)
    (d / "README.md").write_text("hi\n")
    _git(["add", "-A"], d)
    _git(["commit", "-m", "init"], d)
    return d


class _FakeTime:
    """Controllable clock: `sleep` advances `now`, so countdown loops run
    instantly + deterministically."""
    def __init__(self, start: datetime):
        self.t = start

    def now(self) -> datetime:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += timedelta(seconds=s)


class _ScriptedBackend:
    def __init__(self, lines, *, side_effect=None):
        self.lines = lines
        self.side_effect = side_effect
        self.killed = 0

    def start(self, site_dir):
        self.sd = site_dir

    def stream(self, prompt, system_prompt=None):
        if self.side_effect:
            self.side_effect(self.sd)
        for ln in self.lines:
            yield ln

    def kill(self):
        self.killed += 1


def _rate_limit_line(resets_at: datetime) -> str:
    return (
        '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected",'
        f'"resetsAt":"{resets_at.isoformat()}","overageStatus":"rejected",'
        '"overageDisabledReason":"org_level_disabled"}}')


_RESULT_OK = '{"type":"result","is_error":false,"total_cost_usd":0.05}'


# ---------- parsing ----------


def test_parse_resets_at_iso_and_epoch():
    assert parse_resets_at("2026-06-13T20:00:00Z") == datetime(
        2026, 6, 13, 20, 0, tzinfo=timezone.utc)
    assert parse_resets_at(1_800_000_000).tzinfo is timezone.utc
    assert parse_resets_at("garbage") is None
    assert parse_resets_at(None) is None


def test_quota_from_rate_limit():
    q = quota_from_rate_limit({"status": "rejected", "overage_status": "rejected",
                               "resets_at": "2026-06-13T20:00:00Z",
                               "overage_disabled_reason": "org_level_disabled"})
    assert q.capped and q.reason == "org_level_disabled"
    assert quota_from_rate_limit({"status": "allowed"}) is None
    assert quota_from_rate_limit(None) is None


# ---------- the self-healing loop ----------


def test_dod_resume_preserves_partial_wait_retry_complete(site):
    """The headline: rate-limited run #1 → **keep** the partial → wait
    countdown → retry **continues from it** → complete. No flags. (Resume-on-
    cap: the retry runs with force so the dirty tree is the starting point.)"""
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=5)

    def _make_partial(sd):
        (sd / "PARTIAL.txt").write_text("half-done\n")

    b1 = _ScriptedBackend([_rate_limit_line(resets)], side_effect=_make_partial)
    b2 = _ScriptedBackend([_RESULT_OK])
    backends = iter([b1, b2])
    ticks: list[float] = []

    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: next(backends),
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=2),
        sites_root=site.parent,
        on_wait=lambda remaining, target: ticks.append(remaining),
        sleep=ft.sleep, now_fn=ft.now)

    assert res.status == "done"                    # retry succeeded past the dirty tree
    assert ticks                                   # countdown actually ran
    assert (site / "PARTIAL.txt").exists()         # PRESERVED — not thrown away
    assert b1.killed == 1 and b2.killed == 1


def test_give_up_after_max_retries_preserves_progress(site):
    """Exhausting --max-retries keeps the accumulated work (re-run to continue),
    rather than discarding it."""
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=2)

    def _make_partial(sd):
        (sd / "PARTIAL.txt").write_text("some progress\n")

    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: _ScriptedBackend([_rate_limit_line(resets)],
                                                  side_effect=_make_partial),
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=1),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "error"
    assert "kept in the tree" in res.reason
    assert (site / "PARTIAL.txt").exists()         # kept, not reverted


def test_no_wait_fails_fast_keeps_partial_in_tree(site):
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(hours=2)

    def _make_partial(sd):
        (sd / "PARTIAL.txt").write_text("half\n")

    b1 = _ScriptedBackend([_rate_limit_line(resets)], side_effect=_make_partial)
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: b1,
        config=ResilientConfig(wait=False),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)

    assert res.status == "error"
    assert "rate-limited until" in res.reason
    assert "overage" in res.reason                 # the real-fix note
    # v33.P resume: --no-wait no longer hard-discards — the partial stays in
    # the tree (with a recovery hint), never thrown away.
    assert (site / "PARTIAL.txt").exists()
    assert "kept in the tree" in res.reason


def test_empty_diff_cap_hard_reverts(site):
    """The one case that DOES hard-revert: a cap with no progress (empty diff)
    → clean tree, retry from scratch."""
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=2)
    # No side_effect → the rate-limited run leaves nothing.
    b1 = _ScriptedBackend([_rate_limit_line(resets)])
    b2 = _ScriptedBackend([_RESULT_OK])
    backends = iter([b1, b2])
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: next(backends),
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=2),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "done"


def test_max_retries_bounds_the_loop(site):
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=2)
    # Makes PROGRESS each window (growing diff) but still caps → bounded by
    # max_retries (not the no-progress bail).
    n = {"i": 0}

    def factory():
        n["i"] += 1
        idx = n["i"]

        def se(sd):
            (sd / f"progress{idx}.txt").write_text("more\n")   # diff grows each window
        return _ScriptedBackend([_rate_limit_line(resets)], side_effect=se)

    res = run_delegate_resilient(
        "example.com", "do x", backend_factory=factory,
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=2),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "error"
    assert "--max-retries reached" in res.reason
    assert res.capped_out is True


def test_no_progress_window_bails_early_as_capped_out(site):
    """v33.R — a resumed window that caps again WITHOUT growing the diff bails
    early (before max_retries) with capped_out=True → signals 'too big, split'."""
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=2)

    def factory():
        def se(sd):
            (sd / "stuck.txt").write_text("same\n")   # SAME content every window
        return _ScriptedBackend([_rate_limit_line(resets)], side_effect=se)

    res = run_delegate_resilient(
        "example.com", "do x", backend_factory=factory,
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=9),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "error"
    assert res.capped_out is True
    assert "no net progress" in res.reason.lower()
    assert "--max-retries" not in res.reason            # bailed early, not at the cap


def test_max_wait_exceeded_fails(site):
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(hours=10)        # far past max_wait
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: _ScriptedBackend([_rate_limit_line(resets)]),
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=2),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "error"
    assert "exceeds --max-wait" in res.reason


def test_checkpoint_backs_up_tracked_progress_and_keeps_tree(site):
    """A cap with tracked progress: the partial stays in the tree AND a
    recoverable labeled backup stash is created."""
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=2)

    def _edit_tracked(sd):
        (sd / "README.md").write_text("agent progress\n")   # README.md is tracked

    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: _ScriptedBackend([_rate_limit_line(resets)],
                                                  side_effect=_edit_tracked),
        config=ResilientConfig(wait=True, max_wait_s=3600, max_retries=0),
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)

    assert res.status == "error"
    assert "agent progress" in (site / "README.md").read_text()   # kept in tree
    stash = subprocess.run(["git", "stash", "list"], cwd=str(site),
                           capture_output=True, text=True)
    assert "delegate-wip" in stash.stdout                          # recoverable


def test_preflight_probe_capped_waits_then_runs(site):
    ft = _FakeTime(datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc))
    resets = ft.now() + timedelta(seconds=3)
    probe = QuotaStatus(capped=True, resets_at=resets, reason="org_level_disabled")
    b = _ScriptedBackend([_RESULT_OK])
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: b,
        config=ResilientConfig(wait=True, max_wait_s=3600),
        preflight_probe=lambda: probe,
        sites_root=site.parent, sleep=ft.sleep, now_fn=ft.now)
    assert res.status == "done"
    assert ft.now() >= resets                       # we actually waited


def test_clean_run_no_rate_limit_passes_through(site):
    b = _ScriptedBackend([_RESULT_OK])
    res = run_delegate_resilient(
        "example.com", "do x",
        backend_factory=lambda: b,
        config=ResilientConfig(wait=True),
        sites_root=site.parent)
    assert res.status == "done"


# ---------- host-side pre-flight probe ----------


def test_probe_quota_host_detects_cap():
    resets = "2026-06-13T20:00:00Z"
    out = _rate_limit_line(parse_resets_at(resets)) + "\n"

    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
    q = probe_quota_host(runner=runner)
    assert q and q.capped and q.resets_at == parse_resets_at(resets)


def test_probe_quota_host_not_capped_returns_none():
    def runner(cmd):
        return subprocess.CompletedProcess(cmd, 0,
                                           stdout=_RESULT_OK + "\n", stderr="")
    assert probe_quota_host(runner=runner) is None


def test_probe_quota_host_no_claude_returns_none():
    def runner(cmd):
        raise FileNotFoundError("claude")
    assert probe_quota_host(runner=runner) is None
