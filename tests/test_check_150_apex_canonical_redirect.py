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
