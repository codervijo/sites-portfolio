"""Tests for v26.B `CHECK_150_apex_canonical_redirect`.

Covers every distinct probe-response pattern the fleet audit
2026-05-25 surfaced (buckets A-E in `docs/bugs.md`), plus the
edge cases the spec calls out:

  - apex=200, www=NXDOMAIN, http=308→https  → pass (CF Pages shape)
  - apex=200, www=308→apex, http=308→https  → pass
  - apex=307→www (Vercel default, homeloom.app pattern) → fail
  - apex=308→www (lamill.io pattern — wrong direction, but 308) → fail
  - apex=200, www=200 (split canonical) → fail
  - apex=200, www=307 (temp redirect — Google holds signals) → fail
  - http=200 (no HTTPS upgrade — Bucket D) → fail
  - http=302 (temp redirect — Bucket-D-with-temp variant) → fail
  - apex unreachable → warn (skipped — flaky network shouldn't grade)
  - non-domain-shaped repo dir → warn (skipped — for sibling CLI tools)
  - archived site → warn (skipped — same posture as CHECK_042)

HTTP stubbed via `httpx.MockTransport`. Connection-failure cases
monkeypatch the module-level `_probe` to return `_Probe(None, "")`
since `MockTransport` always responds.
"""
from __future__ import annotations

import httpx
import pytest

from portfolio.checks.seo import check_150_apex_canonical_redirect as mod


# ---------- helpers ----------


def _client_for(responses: dict[str, httpx.Response]) -> httpx.Client:
    """Build an httpx.Client that returns canned responses keyed by URL.

    `responses` maps the literal request URL (e.g. `"https://example.com/"`)
    to the `httpx.Response` to serve. Unknown URLs raise to make missed
    setups loud."""
    def handler(req: httpx.Request) -> httpx.Response:
        key = str(req.url)
        if key not in responses:
            raise AssertionError(f"unexpected probe URL: {key}")
        return responses[key]

    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport)


def _redirect(status: int, location: str) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location})


def _ok() -> httpx.Response:
    return httpx.Response(200)


# ---------- happy paths ----------


def test_pass_apex_200_www_nxdomain_http_308():
    """The cleanest pass: apex serves 200, www has no DNS, HTTP 308→HTTPS.
    The CF Pages default fleetwide pattern."""
    client = _client_for({
        "https://example.com/": _ok(),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    # Patch _probe so www returns None-status (NXDOMAIN simulation —
    # MockTransport doesn't support raising ConnectError naturally).
    real_probe = mod._probe
    def fake_probe(c, url):
        if url == "https://www.example.com/":
            return mod._Probe(status=None, location="")
        return real_probe(c, url)

    import unittest.mock as um
    with um.patch.object(mod, "_probe", fake_probe):
        result = mod._classify("example.com", client)
    assert result.status == "pass", result.message
    assert "apex 200" in result.message
    assert "NXDOMAIN" in result.message


def test_pass_apex_200_www_308_http_308():
    """Equally valid: www serves 308→apex (no NXDOMAIN, but redirects clean)."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _redirect(308, "https://example.com/"),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "pass", result.message


def test_pass_accepts_301_as_permanent():
    """301 is functionally equivalent to 308 for SEO signal transfer."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _redirect(301, "https://example.com/"),
        "http://example.com/": _redirect(301, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "pass", result.message


# ---------- failures ----------


def test_fail_apex_307_to_www_homeloom_pattern():
    """Bucket A: apex 307→www. SEO-blocking — Google holds signals."""
    client = _client_for({
        "https://example.com/": _redirect(307, "https://www.example.com/"),
        "https://www.example.com/": _ok(),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "TEMP" in result.message
    assert "307" in result.message


def test_fail_apex_308_to_www_wrong_direction():
    """Bucket B: apex 308→www. Permanent redirect (so Google DOES
    consolidate), but onto www instead of apex — non-conforming
    with the fleet's apex-as-canonical convention."""
    client = _client_for({
        "https://example.com/": _redirect(308, "https://www.example.com/"),
        "https://www.example.com/": _ok(),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "apex 308" in result.message
    assert "isn't the canonical" in result.message


def test_fail_www_returns_200_split_canonical():
    """Both apex and www serve 200. No redirect → Google sees two
    canonicals → splits ranking signals."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _ok(),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "second canonical" in result.message


def test_fail_www_307_temporary():
    """www is 307→apex. The direction is right but the temp status
    means Google never consolidates to apex either."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _redirect(307, "https://example.com/"),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "www 307" in result.message


def test_fail_http_returns_200_no_https_upgrade():
    """Bucket D: HTTP 200, no upgrade. apex + www clean otherwise."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _redirect(308, "https://example.com/"),
        "http://example.com/": _ok(),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "http=200" in result.message
    assert "no HTTPS upgrade" in result.message


def test_fail_http_302_temporary_to_https():
    """HTTP 302 (TEMP) → HTTPS — Google won't consolidate the upgrade."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _redirect(308, "https://example.com/"),
        "http://example.com/": _redirect(302, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "http 302" in result.message
    assert "TEMP" in result.message


def test_fail_www_308_to_unrelated_target():
    """www 308 to some-other-domain → not apex → fail."""
    client = _client_for({
        "https://example.com/": _ok(),
        "https://www.example.com/": _redirect(308, "https://other.com/"),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "www 308" in result.message
    assert "not apex" in result.message


def test_fail_apex_returns_unexpected_status():
    """apex 500 / 404 / etc. doesn't fit any redirect category."""
    client = _client_for({
        "https://example.com/": httpx.Response(500),
        "https://www.example.com/": _redirect(308, "https://example.com/"),
        "http://example.com/": _redirect(308, "https://example.com/"),
    })
    result = mod._classify("example.com", client)
    assert result.status == "fail"
    assert "apex returned 500" in result.message


# ---------- network-error paths ----------


def test_warn_apex_unreachable_skips_grade(monkeypatch):
    """apex DNS / TLS / connrefused → warn (skipped). Flaky network
    shouldn't fail-grade a check."""
    def all_unreachable(c, url):
        return mod._Probe(status=None, location="")
    monkeypatch.setattr(mod, "_probe", all_unreachable)
    # _classify needs a client but won't use it (patched _probe).
    client = httpx.Client()
    result = mod._classify("example.com", client)
    assert result.status == "warn"
    assert "apex unreachable" in result.message


# ---------- skip paths ----------


def test_warn_non_domain_dir_skipped(tmp_path):
    """`sites/portfolio/` or `sites/rankmill/` — dir name isn't a
    domain → check skips, doesn't try to probe anything."""
    (tmp_path / "portfolio").mkdir()
    result = mod.run(str(tmp_path / "portfolio"))
    assert result.status == "warn"
    assert "not a domain-shaped dir" in result.message


def test_warn_archived_site_skipped(tmp_path, monkeypatch):
    """Mirrors CHECK_042 posture — archived sites skip with warn."""
    (tmp_path / "example.com").mkdir()
    # Inject a fake fleet_repos._archived_reason that flags this path.
    import portfolio.fleet_repos as fr
    monkeypatch.setattr(fr, "_archived_reason",
                        lambda p: "archived 2024-01-01")
    result = mod.run(str(tmp_path / "example.com"))
    assert result.status == "warn"
    assert "archived" in result.message


def test_metadata_constants():
    """Sanity — the registry contract attributes exist + have the
    expected values for v26.B's `warn`-soak ship."""
    assert mod.CHECK_ID == "CHECK_150"
    assert mod.CHECK_NAME == "apex-canonical-redirect"
    assert mod.CATEGORY == "seo"
    assert mod.SEVERITY == "warn"
    assert "apex" in mod.DESCRIPTION.lower()


# ============================================================================
# v26.C — fix_tier_1 dispatch + Cloudflare fixer
# ============================================================================


def _write_lamill_toml(project_dir, platform: str) -> None:
    """Drop a minimal lamill.toml declaring `[deploy].platform`.

    `hostgator` and `custom` require a `[hosting]` section per the
    lamill_toml schema — the helper adds an empty one so the parser
    accepts the file."""
    body = f'[deploy]\nplatform = "{platform}"\n'
    if platform in ("hostgator", "custom"):
        body += '\n[hosting]\n'
    (project_dir / "lamill.toml").write_text(body)


def test_fix_dispatch_no_lamill_toml_returns_manual(tmp_path):
    """Missing lamill.toml → can't dispatch; surface manual + hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    result = mod.fix_tier_1.apply(site, dry_run=True, assume_yes=False)
    assert result.status == "manual"
    assert "lamill.toml" in result.summary


def test_fix_dispatch_non_domain_dir_skips(tmp_path):
    """Dir name not a domain (e.g. `portfolio/`) → nothing-to-do."""
    site = tmp_path / "not-a-domain"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    result = mod.fix_tier_1.apply(site, dry_run=True, assume_yes=False)
    assert result.status == "nothing-to-do"
    assert "not a domain-shaped dir" in result.summary


def test_fix_dispatch_hostgator_returns_manual_with_hint(tmp_path):
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "hostgator")
    result = mod.fix_tier_1.apply(site, dry_run=True, assume_yes=False)
    assert result.status == "manual"
    assert ".htaccess" in result.summary


# ---------- CF branch: nothing-to-do / would-fix / fixed / error paths ----------


def _stub_cloudflare(monkeypatch, *,
                     zone_id="ZONE123",
                     current_setting="off",
                     patch_raises=None,
                     post_write_http_status=308):
    """Patch the cloudflare.* calls + the post-write http probe to
    cover one CF branch scenario per test.

    `post_write_http_status` can be a single int (returned for every
    probe attempt) or a list of ints (returned in sequence — last value
    repeats once the list is exhausted). The list form simulates CF
    edge propagation: e.g. `[200, 200, 308]` flips to redirect on the
    3rd attempt."""
    import portfolio.cloudflare as cf

    monkeypatch.setattr(cf, "resolve_zone_id",
                        lambda d, client=None: zone_id)
    monkeypatch.setattr(cf, "get_zone_setting",
                        lambda zid, sid, client=None: current_setting)

    def fake_set(zid, sid, val, client=None):
        if patch_raises is not None:
            raise patch_raises
        return None
    monkeypatch.setattr(cf, "set_zone_setting", fake_set)

    if isinstance(post_write_http_status, list):
        seq = iter(post_write_http_status)
        last = [post_write_http_status[-1]]
        def fake_probe(domain):
            try:
                last[0] = next(seq)
            except StopIteration:
                pass
            return last[0]
        monkeypatch.setattr(mod, "_http_status", fake_probe)
    else:
        monkeypatch.setattr(mod, "_http_status",
                            lambda domain: post_write_http_status)

    # No-op sleep so backoff-poll tests don't actually wait.
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)


def test_fix_cf_already_on_returns_nothing_to_do(tmp_path, monkeypatch):
    """always_use_https already 'on' → no API write; skip silently."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    _stub_cloudflare(monkeypatch, current_setting="on")
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "nothing-to-do"
    assert "already on" in result.summary


def test_fix_cf_dry_run_returns_would_fix(tmp_path, monkeypatch):
    """Off + dry-run → would-fix with current value annotated; no write."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    # If set_zone_setting is called in dry-run mode, the test fails loud.
    import portfolio.cloudflare as cf
    monkeypatch.setattr(cf, "set_zone_setting",
                        lambda *a, **k: pytest.fail("set fired in dry-run!"))
    monkeypatch.setattr(cf, "resolve_zone_id", lambda d, client=None: "Z")
    monkeypatch.setattr(cf, "get_zone_setting",
                        lambda z, s, client=None: "off")
    result = mod.fix_tier_1.apply(site, dry_run=True, assume_yes=False)
    assert result.status == "would-fix"
    assert "would set always_use_https" in result.summary


def test_fix_cf_apply_and_verify_returns_fixed(tmp_path, monkeypatch):
    """Off + apply + post-write probe shows 308 → fixed."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    _stub_cloudflare(monkeypatch, post_write_http_status=308)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert "now returns 308" in result.summary


def test_fix_cf_workers_uses_same_branch(tmp_path, monkeypatch):
    """cf-workers takes the same branch as cf-pages (same toggle)."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-workers")
    _stub_cloudflare(monkeypatch, post_write_http_status=301)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert "now returns 301" in result.summary


def test_fix_cf_apply_post_write_still_200_returns_error(tmp_path, monkeypatch):
    """Toggle PATCH succeeded but http stays 200 across the full backoff
    window → genuine error (conflicting Page Rule / stuck cache)."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    _stub_cloudflare(monkeypatch, post_write_http_status=200)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "error"
    assert "still returns 200" in result.summary
    assert "probes" in result.summary
    assert "Page Rules" in result.summary


def test_fix_cf_apply_post_write_eventually_settles_returns_fixed(tmp_path, monkeypatch):
    """Backoff verify — http returns 200 on early attempts, then 308
    on a later attempt (simulates CF edge propagation kicking in).
    Should return fixed without leaking the early-200 noise."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    # 200, 200, 308 — propagation kicks in on the 3rd probe.
    _stub_cloudflare(monkeypatch,
                     post_write_http_status=[200, 200, 308])
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert "now returns 308" in result.summary


def test_fix_cf_post_write_probe_unreachable_still_marks_fixed(tmp_path, monkeypatch):
    """Toggle PATCH succeeded but the post-write probe couldn't reach
    the host (None) — the API write itself succeeded; mark fixed but
    annotate that the operator should verify manually."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    _stub_cloudflare(monkeypatch, post_write_http_status=None)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert "verify manually" in result.summary


def test_fix_cf_api_patch_error_returns_error_with_hint(tmp_path, monkeypatch):
    """PATCH 403 (token lacks Zone Settings:Edit) → error + token hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    import portfolio.cloudflare as cf
    _stub_cloudflare(monkeypatch,
                     patch_raises=cf.CloudflareAPIError("HTTP 403: forbidden"))
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "error"
    assert "PATCH always_use_https failed" in result.summary
    assert "Zone Settings:Edit" in result.summary


def test_fix_cf_missing_credentials_returns_actionable_error(tmp_path, monkeypatch):
    """CF token unset → error with `settings apikeys set` hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    import portfolio.cloudflare as cf
    def raise_missing(d, client=None):
        raise cf.MissingCredentialsError("CF_API_TOKEN not set")
    monkeypatch.setattr(cf, "resolve_zone_id", raise_missing)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "error"
    assert "CF_API_TOKEN" in result.summary
    assert "settings apikeys set" in result.summary


def test_fix_cf_zone_resolution_api_error_returns_error(tmp_path, monkeypatch):
    """`resolve_zone_id` raises CloudflareAPIError → error + diagnose hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "cf-pages")
    import portfolio.cloudflare as cf
    def raise_api(d, client=None):
        raise cf.CloudflareAPIError("zone not in account")
    monkeypatch.setattr(cf, "resolve_zone_id", raise_api)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "error"
    assert "resolve zone failed" in result.summary
    assert "check-token" in result.summary


def test_fix_tier_1_metadata():
    """The FixerSpec attaches correctly + the registry can discover it."""
    assert mod.fix_tier_1.tier == 1
    assert "https" in mod.fix_tier_1.summary.lower()
    assert callable(mod.fix_tier_1.apply)


def test_fix_tier_1_registered_under_check_150():
    """Once discovered by the fix_registry, the fixer's `check_id`
    should be CHECK_150 (the registry rewrites it from the module's
    CHECK_ID at discovery time)."""
    from portfolio import fix_registry
    fix_registry.reset_cache()
    spec = fix_registry.get_tier_1("CHECK_150")
    assert spec is not None
    assert spec.check_id == "CHECK_150"


# ============================================================================
# v26.D — Vercel branch tests
# ============================================================================
#
# The Vercel branch is mocked at the `portfolio.vercel` module level:
# `find_project_by_domain`, `get_project_domain`,
# `update_domain_redirect`, `add_domain_to_project`. This isolates the
# branch logic from the actual API client (which has its own
# `tests/test_vercel.py` coverage).


def _stub_vercel(monkeypatch, *,
                 project_id="proj_homeloom",
                 project_name="homeloom",
                 apex_cfg=None,
                 www_cfg=None,
                 find_raises=None,
                 read_raises=None,
                 write_raises=None,
                 post_apply_apex_status=200,
                 post_apply_www_status=308):
    """Patch the vercel.* calls + the verification probe to cover one
    Vercel-branch scenario per test. Pass DomainConfig instances (or
    None for unattached) for apex_cfg / www_cfg."""
    import portfolio.vercel as v

    if find_raises is not None:
        def fake_find(d, client=None, page_size=100, max_pages=20):
            raise find_raises
        monkeypatch.setattr(v, "find_project_by_domain", fake_find)
    else:
        monkeypatch.setattr(v, "find_project_by_domain",
                            lambda d, client=None, page_size=100, max_pages=20:
                            v.ProjectRef(project_id=project_id, name=project_name))

    def fake_get(pid, domain, client=None):
        if read_raises is not None:
            raise read_raises
        return apex_cfg if domain.count(".") == 1 else www_cfg
    monkeypatch.setattr(v, "get_project_domain", fake_get)

    write_calls: list[tuple[str, str, str, dict]] = []

    def fake_update(pid, domain, *, redirect_to, status_code=308, client=None):
        if write_raises is not None:
            raise write_raises
        write_calls.append(("PATCH", pid, domain,
                             {"redirect_to": redirect_to, "status_code": status_code}))
    monkeypatch.setattr(v, "update_domain_redirect", fake_update)

    def fake_add(pid, name, *, redirect_to=None, status_code=308, client=None):
        if write_raises is not None:
            raise write_raises
        write_calls.append(("POST", pid, name,
                             {"redirect_to": redirect_to, "status_code": status_code}))
    monkeypatch.setattr(v, "add_domain_to_project", fake_add)

    def fake_probe(url):
        return post_apply_apex_status if "/www." not in url else post_apply_www_status
    monkeypatch.setattr(mod, "_probe_status", fake_probe)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    return write_calls


def _domain_cfg(name: str, *, redirect=None, status=None) -> object:
    """Build a portfolio.vercel.DomainConfig — lazy import so the
    fixture file doesn't depend on portfolio.vercel being importable
    at module collection time."""
    from portfolio.vercel import DomainConfig
    return DomainConfig(name=name, redirect=redirect,
                        redirect_status_code=status, verified=True)


def test_fix_vercel_missing_token_returns_error(tmp_path, monkeypatch):
    """VERCEL_TOKEN unset → error with `settings apikeys set` hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    import portfolio.vercel as v
    def raise_missing(d, **kw):
        raise v.MissingCredentialsError("VERCEL_TOKEN not set")
    monkeypatch.setattr(v, "find_project_by_domain", raise_missing)
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "error"
    assert "Vercel token missing" in result.summary


def test_fix_vercel_project_not_found_returns_manual(tmp_path, monkeypatch):
    """find_project_by_domain raises VercelAPIError ("no project
    attaches X") → surface as manual so operator investigates project
    ownership / TOML drift."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    import portfolio.vercel as v
    _stub_vercel(monkeypatch,
                 find_raises=v.VercelAPIError("no Vercel project attaches example.com"))
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "manual"
    assert "not found" in result.summary


def test_fix_vercel_already_clean_returns_nothing_to_do(tmp_path, monkeypatch):
    """apex serves directly + www→apex 308 already → no writes; skip."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    calls = _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com", redirect=None, status=None),
        www_cfg=_domain_cfg("www.example.com", redirect="example.com", status=308),
    )
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "nothing-to-do"
    assert "already 308" in result.summary
    assert calls == []   # no writes fired


def test_fix_vercel_apex_inverted_homeloom_pattern_dry_run(tmp_path, monkeypatch):
    """The homeloom.app shape: apex redirects to www (307 or 308), www
    serves directly. Dry-run shows the plan with both changes."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    calls = _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com",
                              redirect="www.example.com", status=308),
        www_cfg=_domain_cfg("www.example.com", redirect=None, status=None),
    )
    result = mod.fix_tier_1.apply(site, dry_run=True, assume_yes=False)
    assert result.status == "would-fix"
    assert "clear redirect on example.com" in result.summary
    assert "www.example.com redirect" in result.summary
    assert calls == []   # dry-run — no writes


def test_fix_vercel_apex_inverted_apply_writes_and_verifies(tmp_path, monkeypatch):
    """Same shape as above — apply commits the writes; verification
    probe shows apex=200 + www=308 → fixed."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    calls = _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com",
                              redirect="www.example.com", status=308),
        www_cfg=_domain_cfg("www.example.com", redirect=None, status=None),
        post_apply_apex_status=200,
        post_apply_www_status=308,
    )
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    # Two PATCH calls expected — apex (clear) + www (set redirect).
    assert len(calls) == 2
    verbs = [c[0] for c in calls]
    assert verbs == ["PATCH", "PATCH"]
    apex_call = next(c for c in calls if c[2] == "example.com")
    assert apex_call[3]["redirect_to"] is None
    www_call = next(c for c in calls if c[2] == "www.example.com")
    assert www_call[3]["redirect_to"] == "example.com"
    assert www_call[3]["status_code"] == 308


def test_fix_vercel_www_not_attached_uses_post(tmp_path, monkeypatch):
    """Apex serves direct + www isn't in the project's domain list →
    POST to add www with the 308 redirect already baked in."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    calls = _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com", redirect=None, status=None),
        www_cfg=None,
        post_apply_apex_status=200,
        post_apply_www_status=308,
    )
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert len(calls) == 1
    verb, _, name, body = calls[0]
    assert verb == "POST"
    assert name == "www.example.com"
    assert body["redirect_to"] == "example.com"
    assert body["status_code"] == 308


def test_fix_vercel_www_has_wrong_status_code_307(tmp_path, monkeypatch):
    """www redirects to apex but with statusCode=307 (temp) → fix
    needs to flip to 308."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    calls = _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com", redirect=None, status=None),
        www_cfg=_domain_cfg("www.example.com", redirect="example.com", status=307),
    )
    result = mod.fix_tier_1.apply(site, dry_run=True, assume_yes=False)
    assert result.status == "would-fix"
    assert "www.example.com redirect" in result.summary
    assert calls == []


def test_fix_vercel_apex_not_attached_returns_manual(tmp_path, monkeypatch):
    """find_project_by_domain returned a project, but `get_project_domain`
    for the apex returns None (apex isn't attached). Odd shape — route
    manual so operator investigates the dashboard."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    _stub_vercel(
        monkeypatch,
        apex_cfg=None,
        www_cfg=_domain_cfg("www.example.com", redirect=None, status=None),
    )
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "manual"
    assert "isn't attached" in result.summary


def test_fix_vercel_api_error_mid_write_returns_error(tmp_path, monkeypatch):
    """One of the PATCH/POST calls 5xxs mid-fix → partial state; surface
    as error with re-run hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    import portfolio.vercel as v
    _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com",
                              redirect="www.example.com", status=308),
        www_cfg=_domain_cfg("www.example.com", redirect=None, status=None),
        write_raises=v.VercelAPIError("HTTP 500: server error"),
    )
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "error"
    assert "API write failed" in result.summary
    assert "idempotent" in result.summary


def test_fix_vercel_verify_doesnt_settle_returns_fixed_with_caveat(tmp_path, monkeypatch):
    """Writes succeed but the post-write probe doesn't show apex=200 +
    www=308 within the backoff window — Vercel can take longer than CF
    for edge propagation. Mark fixed with the manual re-probe hint."""
    site = tmp_path / "example.com"
    site.mkdir()
    _write_lamill_toml(site, "vercel")
    _stub_vercel(
        monkeypatch,
        apex_cfg=_domain_cfg("example.com",
                              redirect="www.example.com", status=308),
        www_cfg=_domain_cfg("www.example.com", redirect=None, status=None),
        post_apply_apex_status=200,   # apex flipped
        post_apply_www_status=200,    # www hasn't propagated yet
    )
    result = mod.fix_tier_1.apply(site, dry_run=False, assume_yes=False)
    assert result.status == "fixed"
    assert "Re-probe in" in result.summary
    assert "www=200" in result.summary
