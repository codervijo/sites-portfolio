"""v48.C — `lamill new site` orchestrator (all external effects injected)."""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone

import pytest

from portfolio import new_site as ns
from portfolio.new_site import LiveState, Options, RepoCandidate


# ------------------------------------------------------------ domain


def _no(_m):  # confirm → no
    return False


def _yes(_m):
    return True


def test_domain_from_cli_wins():
    assert ns.resolve_domain("Foo.COM", interactive=True, confirm=_no, prompt=lambda m: "",
                             sync=lambda: pytest.fail("no sync"), newest=lambda: None) == "foo.com"


def test_domain_newest_porkbun_accepted():
    synced = []
    d = ns.resolve_domain(None, interactive=True, confirm=_yes, prompt=lambda m: "",
                          sync=lambda: synced.append(1), newest=lambda: ("lamill.store", "2026-11-07 09:01"))
    assert d == "lamill.store" and synced


def test_domain_declined_then_typed():
    d = ns.resolve_domain(None, interactive=True, confirm=_no, prompt=lambda m: "other.dev",
                          sync=lambda: None, newest=lambda: ("lamill.store", "2026-11-07"))
    assert d == "other.dev"


def test_domain_nothing_errors_with_usage():
    with pytest.raises(ns.NewSiteError, match="lamill new site <domain>"):
        ns.resolve_domain(None, interactive=True, confirm=_no, prompt=lambda m: "",
                          sync=lambda: None, newest=lambda: None)


def test_domain_non_interactive_never_guesses():
    with pytest.raises(ns.NewSiteError, match="lamill new site lamill.store"):
        ns.resolve_domain(None, interactive=False, confirm=_yes, prompt=lambda m: "",
                          sync=lambda: None, newest=lambda: ("lamill.store", "2026-11-07"))


def test_newest_porkbun_domain(tmp_path):
    p = tmp_path / "porkbun.csv"
    p.write_text("DOMAIN,TLD,STATUSES,CREATE DATE\n"
                 "old.com,com,ACTIVE,2026-04-24 21:10:06\n"
                 "lamill.store,store,ACTIVE,2026-11-07 09:01:59\n")
    assert ns.newest_porkbun_domain(p) == ("lamill.store", "2026-11-07 09:01:59")


# ------------------------------------------------------------ lovable repos


def _repo(name, pushed):
    return {"name": name, "owner": {"login": "codervijo"}, "pushedAt": pushed,
            "url": f"https://github.com/codervijo/{name}"}


NOW = datetime(2026, 11, 7, tzinfo=timezone.utc)


def test_rank_excludes_used_and_non_lovable_and_prefers_name_match():
    repos = [_repo("lamill-storefronts", "2026-11-07T10:00:00Z"),
             _repo("engine-reliability-insights", "2026-11-07T11:00:00Z"),
             _repo("lamill.pics", "2026-11-07T12:00:00Z"),       # used
             _repo("plain-astro", "2026-11-07T13:00:00Z"),       # not lovable
             _repo("ancient-lovable", "2025-01-01T00:00:00Z")]   # too old
    lovable = {"codervijo/lamill-storefronts", "codervijo/engine-reliability-insights",
               "codervijo/lamill.pics", "codervijo/ancient-lovable"}
    out = ns.rank_candidates(repos, "lamill.store", {"codervijo/lamill.pics"},
                             lambda f: f in lovable, now=NOW)
    assert [c.full_name for c in out] == ["codervijo/lamill-storefronts",
                                          "codervijo/engine-reliability-insights"]


def test_pick_clear_match_confirms():
    c = [RepoCandidate("o/lamill-storefronts", "u1", "2026-11-07", 0.9),
         RepoCandidate("o/other", "u2", "2026-11-06", 0.2)]
    assert ns.pick_repo(c, "lamill.store", interactive=True, confirm=_yes, prompt=lambda m: "") is c[0]


def test_pick_ambiguous_numbered():
    c = [RepoCandidate("o/a", "u1", "2026-11-07", 0.3), RepoCandidate("o/b", "u2", "2026-11-06", 0.3)]
    assert ns.pick_repo(c, "x.com", interactive=True, confirm=_yes, prompt=lambda m: "2") is c[1]


def test_pick_none_blank_scaffold():
    assert ns.pick_repo([], "x.com", interactive=True, confirm=_yes, prompt=lambda m: "") is None


def test_ledger_roundtrip_and_used(tmp_path):
    led = tmp_path / "new_site.json"
    ns.record_ledger("lamill.store", "codervijo/lamill-storefronts", led)
    assert json.loads(led.read_text()) == {"lamill.store": "codervijo/lamill-storefronts"}
    assert "codervijo/lamill-storefronts" in ns.used_repos(tmp_path / "nosites", led)


# ------------------------------------------------------------ wait


def test_backoff_schedule():
    assert list(itertools.islice(ns.backoff_delays(), 7)) == [30, 60, 120, 240, 480, 600, 600]


def _clock():
    t = {"now": 0.0}
    return (lambda s: t.__setitem__("now", t["now"] + s)), (lambda: t["now"])


def test_wait_goes_live():
    seq = iter([LiveState("pending", "queued", False, "000"),
                LiveState("active", "success", True, "200")])
    sleep, mono = _clock()
    assert ns.wait_until_live("x.com", budget_s=600, probe=lambda: next(seq),
                              sleep=sleep, monotonic=mono) == "live"


def test_wait_build_failure_fails_fast():
    sleep, mono = _clock()
    assert ns.wait_until_live("x.com", budget_s=600, probe=lambda: LiveState("active", "failed", False, "522"),
                              sleep=sleep, monotonic=mono) == "build_failed"


def test_wait_times_out_within_budget():
    sleep, mono = _clock()
    r = ns.wait_until_live("x.com", budget_s=200, probe=lambda: LiveState("pending", "success", False, "000"),
                           sleep=sleep, monotonic=mono)
    assert r == "timeout" and mono() == 200  # 30 + 60 + 110 (clamped to budget)


# ------------------------------------------------------------ orchestrator


class Harness:
    def __init__(self, tmp_path, *, bootstrapped=False, build_ok=True, deploy_rc=0, wait="live",
                 zone_active=False, confirms=None):
        self.sites = tmp_path / "sites"
        self.sites.mkdir()
        self.ledger = tmp_path / "new_site.json"
        if bootstrapped:
            (self.sites / "x.com").mkdir()
            (self.sites / "x.com" / "lamill.toml").write_text("")
        self.calls: list[list[str]] = []
        self.build_ok, self.deploy_rc, self.wait_result = build_ok, deploy_rc, wait
        self.zone = zone_active
        self.confirms = confirms
        self.budget = None

    def runner(self, argv):
        self.calls.append(argv[3:])  # strip `python -m portfolio`
        if argv[3:5] == ["new", "bootstrap"]:
            (self.sites / argv[5]).mkdir(exist_ok=True)
            (self.sites / argv[5] / "lamill.toml").write_text("")
        if argv[3:5] == ["new", "deploy"]:
            return self.deploy_rc
        return 0

    def wait(self, domain, *, budget_s, probe):
        self.budget = budget_s
        return self.wait_result

    def run(self, domain="x.com", **opts):
        confirm = self.confirms if self.confirms is not None else _yes
        return ns.run_new_site(
            domain, Options(**opts), runner=self.runner, ask_confirm=confirm,
            ask_prompt=lambda m: "", owned=lambda d: True,
            discover=lambda d: [RepoCandidate("codervijo/x-site", "https://github.com/codervijo/x-site",
                                              "2026-11-07", 0.9)],
            build=lambda d: (self.build_ok, "build OK" if self.build_ok else "build failed (exit 1)"),
            is_zone_active=lambda d: self.zone, probe_factory=lambda d, s: (lambda: None),
            wait=self.wait, sites_root=self.sites, ledger=self.ledger, newest=lambda: None)

    def cmds(self):
        return [c[:2] for c in self.calls]


def test_full_run_order_ledger_and_first_deploy_budget(tmp_path):
    h = Harness(tmp_path)
    assert h.run(yes=True) == 0
    assert h.cmds() == [["new", "bootstrap"], ["new", "deploy"], ["project", "check"]]
    assert h.calls[0] == ["new", "bootstrap", "x.com", "--git-url", "https://github.com/codervijo/x-site"]
    assert "--yes" in h.calls[1]
    assert json.loads(h.ledger.read_text()) == {"x.com": "codervijo/x-site"}
    assert h.budget == ns.BUDGET_FIRST_DEPLOY_MIN * 60


def test_resume_skips_bootstrap_and_uses_redeploy_budget(tmp_path):
    h = Harness(tmp_path, bootstrapped=True, zone_active=True)
    assert h.run(yes=True) == 0
    assert ["new", "bootstrap"] not in h.cmds()
    assert h.budget == ns.BUDGET_REDEPLOY_MIN * 60


def test_declining_a_step_stops_cleanly(tmp_path):
    h = Harness(tmp_path, bootstrapped=True, confirms=lambda m: "Deploy" not in m)
    assert h.run() == 0
    assert ["new", "deploy"] not in h.cmds()


def test_build_failure_stops_before_deploy(tmp_path):
    h = Harness(tmp_path, bootstrapped=True, build_ok=False)
    assert h.run(yes=True) == 2
    assert ["new", "deploy"] not in h.cmds()


def test_deploy_failure_is_red(tmp_path):
    h = Harness(tmp_path, bootstrapped=True, deploy_rc=8)
    assert h.run(yes=True) == 2
    assert ["project", "check"] not in h.cmds()


def test_timeout_is_soft_and_skips_check(tmp_path):
    h = Harness(tmp_path, bootstrapped=True, wait="timeout")
    assert h.run(yes=True) == 0
    assert ["project", "check"] not in h.cmds()


def test_no_wait_and_timeout_override(tmp_path):
    h = Harness(tmp_path, bootstrapped=True)
    h.run(yes=True, no_wait=True)
    assert h.budget is None
    (tmp_path / "b").mkdir()
    h2 = Harness(tmp_path / "b", bootstrapped=True)
    h2.run(yes=True, timeout_min=7)
    assert h2.budget == 7 * 60


def test_explicit_git_url_and_owner_pass_through(tmp_path):
    h = Harness(tmp_path)
    h.run(yes=True, git_url="git@github.com:codervijo/foo.git", owner="Derek Hoyt", private=True)
    assert h.calls[0] == ["new", "bootstrap", "x.com", "--git-url", "git@github.com:codervijo/foo.git",
                          "--owner", "Derek Hoyt"]
    assert "--private" in h.calls[1]
    assert json.loads(h.ledger.read_text()) == {"x.com": "codervijo/foo"}
