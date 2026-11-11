"""v50.B/C — Cloudflare Email Routing client + CHECK_165."""
from __future__ import annotations

import json

import httpx
import pytest

import portfolio.email_routing as er_mod

# conftest stubs `inspect` / `public_mx`; grab the real ones at import time.
from portfolio.email_routing import inspect as real_inspect  # noqa: E402

D = "example.com"
Z = "zone1"
A = "acct1"


class FakeCF:
    """In-memory Cloudflare: zone, DNS records, routing settings, rules, addresses."""

    def __init__(self, *, mx=(), spf=None, enabled=False, rules=None,
                 dest=None, status="active", on_cf=True):
        self.mx, self.spf, self.enabled = list(mx), spf, enabled
        self.rules = rules or []
        self.dest = dest            # None | {"email":..., "verified": ...}
        self.status, self.on_cf = status, on_cf
        self.writes: list[str] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        p, m = req.url.path, req.method
        ok = lambda res: httpx.Response(200, json={"success": True, "result": res})  # noqa: E731
        if p == "/client/v4/zones" or p == "/zones":
            return ok([{"id": Z, "status": self.status, "account": {"id": A}}] if self.on_cf else [])
        if p.endswith(f"/zones/{Z}/dns_records"):
            recs = [{"type": "MX", "name": D, "content": h} for h in self.mx]
            if self.spf:
                recs.append({"type": "TXT", "name": D, "content": self.spf})
            return ok(recs)
        if p.endswith(f"/zones/{Z}/email/routing") and m == "GET":
            return ok({"enabled": self.enabled, "status": "ready" if self.enabled else "unconfigured"})
        if p.endswith(f"/zones/{Z}/email/routing/dns") and m == "POST":
            self.writes.append("enable"); self.enabled = True
            self.mx = ["route1.mx.cloudflare.net"]
            return ok({})
        if p.endswith(f"/zones/{Z}/email/routing/rules"):
            if m == "POST":
                self.writes.append("rule"); self.rules.append(json.loads(req.content))
                return ok({})
            return ok(self.rules)
        if p.endswith(f"/accounts/{A}/email/routing/addresses"):
            if m == "POST":
                self.writes.append("dest")
                self.dest = {"email": json.loads(req.content)["email"], "verified": None}
                return ok(self.dest)
            return ok([self.dest] if self.dest else [])
        return httpx.Response(404, json={"success": False, "errors": [{"code": 0, "message": p}]})

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="https://api.cloudflare.com/client/v4",
                            transport=httpx.MockTransport(self.handler))


def _rule(addr, to):
    return {"enabled": True, "matchers": [{"type": "literal", "field": "to", "value": addr}],
            "actions": [{"type": "forward", "value": [to]}]}


@pytest.fixture(autouse=True)
def _real_inspect(monkeypatch):
    monkeypatch.setattr(er_mod, "inspect", real_inspect)


def test_fresh_zone_plans_dest_and_enable_rule_waits():
    st = er_mod.inspect(D, client=FakeCF().client())
    steps, blockers = er_mod.plan(st)
    assert not blockers and len(steps) == 2  # rule waits for verification


def test_ensure_two_passes_around_verification_then_idempotent():
    cf = FakeCF()
    r = er_mod.ensure(D, client=cf.client())
    # CF rejects a rule to an unverified destination (code 2054) — don't try.
    assert cf.writes == ["dest", "enable"]
    assert any("verification" in p and "re-run" in p for p in r.pending)
    cf.dest["verified"] = "2026-11-10T00:00:00Z"
    cf.writes.clear()
    r2 = er_mod.ensure(D, client=cf.client())
    assert cf.writes == ["rule"] and r2.pending == [] and r2.state.ready()
    cf.writes.clear()
    r3 = er_mod.ensure(D, client=cf.client())
    assert cf.writes == [] and r3.changed == []


def test_other_provider_mx_is_never_touched():
    cf = FakeCF(mx=["aspmx.l.google.com"])
    r = er_mod.ensure(D, client=cf.client())
    assert cf.writes == [] and r.state.other_provider == "Google"


def test_spf_without_cf_include_blocks():
    cf = FakeCF(spf="v=spf1 include:zoho.com ~all")
    with pytest.raises(er_mod.EmailRoutingError, match="SPF"):
        er_mod.ensure(D, client=cf.client())
    assert cf.writes == []


def test_existing_rule_elsewhere_is_not_overwritten():
    cf = FakeCF(enabled=True, mx=["route1.mx.cloudflare.net"],
                rules=[_rule(f"hello@{D}", "someone@else.com")],
                dest={"email": "hello@lamill.io", "verified": "x"})
    with pytest.raises(er_mod.EmailRoutingError, match="already forwards"):
        er_mod.ensure(D, client=cf.client())
    assert cf.writes == []


def test_pending_zone_blocks():
    cf = FakeCF(status="pending")
    with pytest.raises(er_mod.EmailRoutingError, match="pending"):
        er_mod.ensure(D, client=cf.client())


def test_permission_error_is_plain_words():
    def h(req):
        return httpx.Response(403, json={"success": False, "errors": [{"code": 10000}]})
    c = httpx.Client(base_url="https://x", transport=httpx.MockTransport(h))
    with pytest.raises(er_mod.EmailRoutingError, match="Email Routing Rules: Edit"):
        er_mod.inspect(D, client=c)


def test_forward_to_override(tmp_path):
    (tmp_path / "lamill.toml").write_text('[email]\nforward_to = "x@y.com"\n')
    assert er_mod.forward_to_for(tmp_path) == "x@y.com"
    (tmp_path / "lamill.toml").write_text('schema = "lamill-toml-v1"\n')
    assert er_mod.forward_to_for(tmp_path) == er_mod.DEFAULT_FORWARD_TO


def test_provider_names():
    assert er_mod.provider_name(["mx.zoho.com"]) == "Zoho"
    assert er_mod.provider_name(["eforward1.registrar-servers.com"]) == "Namecheap forwarding"


# ---- CHECK_165 ------------------------------------------------------------

def _site(tmp_path, name=D):
    d = tmp_path / name
    d.mkdir()
    return d


def test_check_na_for_non_domain_dir(tmp_path):
    from portfolio.checks.deploy import check_165_email_routing_ready as c
    assert "n/a" in c.run(str(_site(tmp_path, "portfolio"))).message


@pytest.mark.parametrize("kw,status,needle", [
    ({"mx": ["mx.zoho.com"]}, "pass", "Zoho"),
    ({}, "warn", "project fix"),
    ({"enabled": True, "mx": ["route1.mx.cloudflare.net"],
      "rules": [_rule(f"hello@{D}", "hello@lamill.io")],
      "dest": {"email": "hello@lamill.io", "verified": "x"}}, "pass", "verified"),
    ({"enabled": True, "mx": ["route1.mx.cloudflare.net"],
      "rules": [_rule(f"hello@{D}", "hello@lamill.io")],
      "dest": {"email": "hello@lamill.io", "verified": None}}, "warn", "click the link"),
])
def test_check_states(tmp_path, monkeypatch, kw, status, needle):
    from portfolio.checks.deploy import check_165_email_routing_ready as c
    cf = FakeCF(**kw)
    monkeypatch.setattr(c, "_not_applicable", lambda b: None)
    monkeypatch.setattr(c, "_inspect", lambda b: real_inspect(D, client=cf.client()))
    r = c.run(str(_site(tmp_path)))
    assert r.status == status and needle in r.message


def test_check_reports_unreadable_setup_not_silently(tmp_path, monkeypatch):
    from portfolio.checks.deploy import check_165_email_routing_ready as c
    monkeypatch.setattr(c, "_not_applicable", lambda b: None)
    r = c.run(str(_site(tmp_path)))  # conftest stub raises
    assert r.status == "warn" and "can't read email setup" in r.message


def test_fixer_dry_run_and_apply(tmp_path, monkeypatch):
    from portfolio.checks.deploy import check_165_email_routing_ready as c
    cf = FakeCF()
    monkeypatch.setattr(c, "_not_applicable", lambda b: None)
    monkeypatch.setattr(er_mod, "inspect",
                        lambda d, **k: real_inspect(D, client=cf.client(),
                                                    **{x: v for x, v in k.items() if x != "client"}))
    monkeypatch.setattr(er_mod.cf, "_client", lambda: cf.client())
    site = _site(tmp_path)
    r = c._apply(site, True, False)
    assert r.status == "would-fix" and cf.writes == []
    r = c._apply(site, False, False)
    assert r.status == "fixed" and cf.writes == ["dest", "enable"]
    assert "verification" in r.summary
    r = c._apply(site, False, False)  # still unverified → waits, no writes
    assert r.status == "manual" and "click the verification link" in r.summary
    assert cf.writes == ["dest", "enable"]


def test_misconfigured_routing_is_not_ready(tmp_path, monkeypatch):
    from portfolio.checks.deploy import check_165_email_routing_ready as c
    cf = FakeCF(enabled=True, mx=[],
                rules=[_rule(f"hello@{D}", "hello@lamill.io")],
                dest={"email": "hello@lamill.io", "verified": "x"})
    orig = cf.handler
    def h(req):
        if req.url.path.endswith(f"/zones/{Z}/email/routing") and req.method == "GET":
            return httpx.Response(200, json={"success": True,
                                             "result": {"enabled": True, "status": "misconfigured"}})
        return orig(req)
    cf.handler = h
    monkeypatch.setattr(c, "_not_applicable", lambda b: None)
    monkeypatch.setattr(c, "_inspect", lambda b: real_inspect(D, client=cf.client()))
    r = c.run(str(_site(tmp_path)))
    assert r.status == "warn" and "misconfigured" in r.message


def test_fleet_fix_plans_warn_fixers_like_project_fix(tmp_path, monkeypatch, capsys):
    """fleet fix used to plan only `fail`; warn-severity fixers showed 'nothing to fix'."""
    from portfolio import fix_cli
    from portfolio.checks.result import CheckResult
    site = _site(tmp_path, "dropaudit.co")
    monkeypatch.setattr(fix_cli, "_list_fleet_eligible_projects",
                        lambda: [("dropaudit.co", site)])
    import portfolio.checks as checks
    monkeypatch.setattr(checks, "run_checks", lambda d: {
        "CHECK_165": CheckResult(status="warn", message="no working hello@"),
        "CHECK_150": CheckResult(status="warn", message="apex unreachable — skipped"),
    })
    fix_cli._run_project_fix_all(apply_changes=False, rule_filter=["CHECK_165"],
                                 assume_yes=False, use_ai=False)
    out = capsys.readouterr().out
    assert "1×T1" in out and "nothing to fix" not in out


@pytest.mark.parametrize("name", ["iotbastion.com.bup", "thoralox.com.old"])
def test_backup_dirs_are_na(tmp_path, name):
    from portfolio.checks.deploy import check_165_email_routing_ready as c
    assert "backup copy" in c.run(str(_site(tmp_path, name))).message


def test_extra_addresses_from_toml(tmp_path):
    (tmp_path / "lamill.toml").write_text(
        '[email]\naddresses = ["security", "Hello", "bad addr", "ops@x.com", 3]\n')
    assert er_mod.local_parts_for(tmp_path) == ("hello", "security", "ops")
    (tmp_path / "lamill.toml").write_text('schema = "lamill-toml-v1"\n')
    assert er_mod.local_parts_for(tmp_path) == ("hello",)


def test_extra_address_gets_its_own_rule_and_hello_is_kept():
    cf = FakeCF(dest={"email": er_mod.DEFAULT_FORWARD_TO, "verified": "2026-11-10T00:00:00Z"})
    er_mod.ensure(D, client=cf.client())
    st = er_mod.inspect(D, client=cf.client(), local_parts=("hello", "security"))
    assert st.missing_rules() == [f"security@{D}"]
    cf.writes.clear()
    r = er_mod.ensure(D, client=cf.client(), local_parts=("hello", "security"))
    assert cf.writes == ["rule"] and r.state.ready()
