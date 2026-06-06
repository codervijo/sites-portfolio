"""Tests for `_deploy_watch_loop` — the optional `--watch` mode that
blocks polling until a fresh-domain deploy is fully live (zone active +
build success + 200 HTTP).

Covers four outcomes the loop is designed to return:
  - "live"         — all three probes green
  - "timeout"      — budget exhausted, soft-skip
  - "build_failed" — CF deployment returned `failure`; fail fast
  - "cancelled"    — operator pressed Ctrl-C

Time is mocked via injected `sleep` + `monotonic` callables so tests
run instantly. CF + HTTP probes mocked via monkeypatch.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio import cloudflare
from portfolio.cli import _deploy_watch_loop
from portfolio.cloudflare import ZoneInfo


def _zone_info(status: str) -> ZoneInfo:
    return ZoneInfo(
        zone_id="z1", name="example.com",
        name_servers=["a.ns.cloudflare.com", "b.ns.cloudflare.com"],
        status=status, created=False,
    )


def test_watch_returns_live_when_all_three_green(monkeypatch):
    """Happy path: zone active, build success, live 200 on first poll."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone_info("active"))
    monkeypatch.setattr(
        cloudflare, "latest_deployment_status",
        # Return signature: (stage_name, stage_status, deployment_id)
        lambda slug, **kw: ("deploy", "success", "dep1"),
    )

    class _OK:
        status_code = 200
        url = "https://example.com/"
    monkeypatch.setattr("httpx.head", lambda url, **kw: _OK())

    sleeps: list[int] = []
    t = {"now": 0.0}

    def _mono():
        return t["now"]

    def _sleep(s):
        sleeps.append(s)
        t["now"] += s

    result = _deploy_watch_loop(
        domain="example.com", zone_id="z1", slug="example",
        cf_account="acct1", cf_surface="pages",
        timeout_s=60, interval_s=5,
        sleep=_sleep, monotonic=_mono,
    )
    assert result == "live"
    assert sleeps == []  # no waits needed; first poll was green


def test_watch_transitions_pending_to_active_then_live(monkeypatch):
    """Zone goes pending → active over two polls; build success arrives
    on the second; live 200 on the second. Single sleep happens between."""
    zone_states = iter(["pending", "active"])
    monkeypatch.setattr(
        cloudflare, "get_zone",
        lambda zid: _zone_info(next(zone_states)),
    )
    # Return signature: (stage_name, stage_status, deployment_id)
    build_states = iter([
        ("build", "active", "id0"),     # in-progress
        ("deploy", "success", "id1"),   # done
    ])
    monkeypatch.setattr(
        cloudflare, "latest_deployment_status",
        lambda slug, **kw: next(build_states),
    )

    live_codes = iter([404, 200])
    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.url = "https://example.com/"
    monkeypatch.setattr(
        "httpx.head",
        lambda url, **kw: _Resp(next(live_codes)),
    )

    sleeps: list[int] = []
    t = {"now": 0.0}

    def _mono(): return t["now"]
    def _sleep(s):
        sleeps.append(s)
        t["now"] += s

    result = _deploy_watch_loop(
        domain="example.com", zone_id="z1", slug="example",
        cf_account="acct1", cf_surface="pages",
        timeout_s=120, interval_s=10,
        sleep=_sleep, monotonic=_mono,
    )
    assert result == "live"
    assert sleeps == [10]  # one wait between two polls


def test_watch_returns_build_failed_fast(monkeypatch):
    """CF deployment status = failure → fail fast without exhausting budget."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone_info("active"))
    monkeypatch.setattr(
        cloudflare, "latest_deployment_status",
        # Return signature: (stage_name, stage_status, deployment_id)
        lambda slug, **kw: ("build", "failure", "depX"),
    )

    class _Conn:
        status_code = 404
        url = "https://example.com/"
    monkeypatch.setattr("httpx.head", lambda url, **kw: _Conn())

    sleeps: list[int] = []
    t = {"now": 0.0}

    def _mono(): return t["now"]
    def _sleep(s):
        sleeps.append(s)
        t["now"] += s

    result = _deploy_watch_loop(
        domain="example.com", zone_id="z1", slug="example",
        cf_account="acct1", cf_surface="pages",
        timeout_s=300, interval_s=5,
        sleep=_sleep, monotonic=_mono,
    )
    assert result == "build_failed"
    assert sleeps == []  # bailed on first poll


def test_watch_returns_timeout_when_budget_exhausted(monkeypatch):
    """Zone never activates; loop exhausts the budget and returns
    timeout (soft-skip, not failure)."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone_info("pending"))
    monkeypatch.setattr(
        cloudflare, "latest_deployment_status",
        lambda slug, **kw: ("", "", ""),  # no deployment yet
    )
    monkeypatch.setattr(
        "httpx.head",
        lambda url, **kw: (_ for _ in ()).throw(httpx.ConnectError("dns fail")),
    )

    sleeps: list[int] = []
    t = {"now": 0.0}

    def _mono(): return t["now"]
    def _sleep(s):
        sleeps.append(s)
        t["now"] += s

    result = _deploy_watch_loop(
        domain="example.com", zone_id="z1", slug="example",
        cf_account="acct1", cf_surface="pages",
        timeout_s=30, interval_s=10,
        sleep=_sleep, monotonic=_mono,
    )
    assert result == "timeout"
    # Should have slept 10s three times before exceeding the 30s budget.
    assert sleeps == [10, 10, 10]


def test_watch_workers_surface_treats_build_as_na(monkeypatch):
    """For cf_surface='workers', build status is 'n/a' (no public API);
    loop returns live when zone active + 200 (build_ok always true)."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone_info("active"))

    # latest_deployment_status should NOT be called when cf_surface=workers.
    # Raise to make that explicit.
    def _should_not_be_called(*a, **kw):
        raise AssertionError("latest_deployment_status called for workers surface")
    monkeypatch.setattr(cloudflare, "latest_deployment_status", _should_not_be_called)

    class _OK:
        status_code = 200
        url = "https://example.com/"
    monkeypatch.setattr("httpx.head", lambda url, **kw: _OK())

    result = _deploy_watch_loop(
        domain="example.com", zone_id="z1", slug="example",
        cf_account="acct1", cf_surface="workers",
        timeout_s=60, interval_s=5,
        sleep=lambda s: None,
        monotonic=lambda: 0.0,
    )
    assert result == "live"


def test_watch_keyboard_interrupt_returns_cancelled(monkeypatch):
    """Ctrl-C during a sleep cycle → cleanly returns 'cancelled'."""
    monkeypatch.setattr(cloudflare, "get_zone", lambda zid: _zone_info("pending"))
    monkeypatch.setattr(
        cloudflare, "latest_deployment_status",
        lambda slug, **kw: ("", "", ""),
    )

    class _Resp:
        status_code = 404
        url = "https://example.com/"
    monkeypatch.setattr("httpx.head", lambda url, **kw: _Resp())

    def _sleep_raises(s):
        raise KeyboardInterrupt()

    result = _deploy_watch_loop(
        domain="example.com", zone_id="z1", slug="example",
        cf_account="acct1", cf_surface="pages",
        timeout_s=300, interval_s=5,
        sleep=_sleep_raises,
        monotonic=lambda: 0.0,
    )
    assert result == "cancelled"
