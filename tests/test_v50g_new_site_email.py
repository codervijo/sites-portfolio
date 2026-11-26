"""v50.G — every new site gets email: bootstrap footer link + `new deploy` step 6.8."""
from __future__ import annotations

import subprocess

import pytest

import portfolio.email_routing as er
from portfolio import cli
from portfolio.bootstrap import bootstrap, email_footer_for_new_site
from portfolio.checks.deploy import check_165_email_routing_ready as c165
from portfolio.checks.deploy import check_166_email_footer_link as c166
from portfolio.fix_helpers import FixResult

D = "mailnew.dev"


def _norm(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


# ---------------------------------------------------------------- bootstrap


@pytest.mark.parametrize("stack, rel", [("astro", "src/pages/index.astro"),
                                        ("vite", "src/App.jsx")])
def test_bootstrap_ships_footer_link_in_initial_commit(tmp_path, stack, rel):
    res = bootstrap(D, stack=stack, sites_root=tmp_path)
    base = tmp_path / D
    assert res.email_footer and res.email_footer[0] == "ok"
    assert f'mailto:hello@{D}' in (base / rel).read_text()
    assert c166.run(str(base)).status == "pass"
    committed = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=base,
                               capture_output=True, text=True, check=True).stdout
    assert f"mailto:hello@{D}" in committed


def test_footer_step_skips_client_sites(tmp_path, monkeypatch):
    base = tmp_path / D
    base.mkdir()
    monkeypatch.setattr(c165, "_not_applicable", lambda b: "client-owned site (client email undecided)")
    kind, msg = email_footer_for_new_site(base)
    assert kind == "skip" and "client-owned" in msg


def test_footer_step_never_raises(tmp_path, monkeypatch):
    base = tmp_path / D
    base.mkdir()
    monkeypatch.setattr(c166, "add_footer_link", lambda *a, **k: 1 / 0)
    kind, msg = email_footer_for_new_site(base)
    assert kind == "skip" and "ZeroDivisionError" in msg


# ---------------------------------------------------------------- new deploy 6.8


def _st(**kw) -> er.EmailState:
    st = er.EmailState(domain=D, forward_to="hello@lamill.io", addresses=[f"hello@{D}"],
                       on_cloudflare=True, zone_status="active")
    for k, v in kw.items():
        setattr(st, k, v)
    return st


@pytest.fixture
def site(tmp_path, monkeypatch):
    base = tmp_path / D
    base.mkdir()
    monkeypatch.setattr(c165, "_not_applicable", lambda b: None)
    return base


def _no_apply(*a, **k):
    pytest.fail("CHECK_165 fixer ran when it shouldn't")


def test_deploy_zone_pending_is_soft_skip(site, monkeypatch, capsys):
    monkeypatch.setattr(er, "inspect", lambda *a, **k: _st(zone_status="pending"))
    monkeypatch.setattr(c165, "_apply", _no_apply)
    cli._deploy_step_email_routing(domain=D, project_dir=site, dry_run=False)
    out = _norm(capsys)
    assert "↷" in out and "pending" in out and "when the zone is active" in out


def test_deploy_ready_is_idempotent_noop(site, monkeypatch, capsys):
    ready = _st(routing_enabled=True, routing_status="ready",
                rules={f"hello@{D}": ["hello@lamill.io"]}, dest_exists=True, dest_verified=True)
    monkeypatch.setattr(er, "inspect", lambda *a, **k: ready)
    monkeypatch.setattr(c165, "_apply", _no_apply)
    cli._deploy_step_email_routing(domain=D, project_dir=site, dry_run=False)
    assert "already set up" in _norm(capsys)


def test_deploy_other_provider_left_alone(site, monkeypatch, capsys):
    monkeypatch.setattr(er, "inspect", lambda *a, **k: _st(other_provider="Zoho"))
    monkeypatch.setattr(c165, "_apply", _no_apply)
    cli._deploy_step_email_routing(domain=D, project_dir=site, dry_run=False)
    assert "left alone" in _norm(capsys)


def test_deploy_active_zone_runs_fixer_and_reports_pending(site, monkeypatch, capsys):
    monkeypatch.setattr(er, "inspect", lambda *a, **k: _st())
    monkeypatch.setattr(c165, "_apply", lambda b, dry_run, assume_yes: FixResult(
        "fixed", "Email Routing enabled — ↷ click the verification link", []))
    cli._deploy_step_email_routing(domain=D, project_dir=site, dry_run=False)
    out = _norm(capsys)
    assert "↷ Email Routing enabled" in out and "verification link" in out


def test_deploy_read_failure_never_blocks(site, capsys):
    # conftest makes inspect raise EmailRoutingError
    cli._deploy_step_email_routing(domain=D, project_dir=site, dry_run=False)
    out = _norm(capsys)
    assert "↷" in out and "re-run" in out


def test_deploy_dry_run_writes_nothing(site, monkeypatch, capsys):
    monkeypatch.setattr(er, "inspect", lambda *a, **k: pytest.fail("probed in dry run"))
    cli._deploy_step_email_routing(domain=D, project_dir=site, dry_run=True)
    assert "would" in _norm(capsys)


def test_deploy_client_site_skipped(tmp_path, monkeypatch, capsys):
    base = tmp_path / D
    base.mkdir()
    monkeypatch.setattr(c165, "_not_applicable", lambda b: "client-owned site (client email undecided)")
    monkeypatch.setattr(er, "inspect", lambda *a, **k: pytest.fail("probed a client site"))
    cli._deploy_step_email_routing(domain=D, project_dir=base, dry_run=False)
    assert "client-owned" in _norm(capsys)
