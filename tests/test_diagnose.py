"""Tests for diagnose.py — synthesis heuristics across the failure
patterns we hit in real-world use this session.

Pure heuristic-layer tests; we build synthetic Diagnosis objects with
known signal combinations and verify the right root-cause classification
fires. Live probes (DNS/HTTP/TLS/repo/inventory) are exercised by hand
+ smoke-tested in real fleet runs.
"""
from __future__ import annotations

from pathlib import Path

from portfolio.diagnose import (
    Diagnosis,
    DnsLayer,
    HttpLayer,
    InventoryLayer,
    RepoLayer,
    TlsLayer,
    synthesize,
)


def _stub_diagnosis(**kwargs) -> Diagnosis:
    """Build a Diagnosis with sensible defaults and per-layer overrides."""
    defaults = dict(
        domain="x.com",
        dns=DnsLayer(),
        http=HttpLayer(),
        tls=TlsLayer(),
        repo=RepoLayer(),
        inventory=InventoryLayer(),
    )
    defaults.update(kwargs)
    return Diagnosis(**defaults)


# ---------- H1: Vercel deployment-not-found ----------


def test_h1_vercel_deployment_not_found():
    """lamill.us pattern — Vercel IP + 404 + DEPLOYMENT_NOT_FOUND header."""
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["76.76.21.21"]),
        http=HttpLayer(apex_status=404, apex_server="Vercel",
                       apex_vercel_error="DEPLOYMENT_NOT_FOUND"),
    )
    synthesize(d)
    assert "Vercel-side" in d.root_cause or "DEPLOYMENT_NOT_FOUND" in d.root_cause.upper()
    assert any("76.76.21.21" in step or "Vercel" in step for step in d.fix_steps)


# ---------- H2: Namecheap parking ----------


def test_h2_namecheap_parking_via_cname():
    d = _stub_diagnosis(
        dns=DnsLayer(www_cname="parkingpage.namecheap.com."),
    )
    synthesize(d)
    assert "parking" in d.root_cause.lower()


def test_h2_namecheap_parking_via_ip():
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["91.195.240.19"]),
    )
    synthesize(d)
    assert "parking" in d.root_cause.lower()


def test_h2_namecheap_parking_via_server_header():
    """No DNS smoking gun, but server header gives it away."""
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["1.2.3.4"]),  # not a known parking IP
        http=HttpLayer(apex_status=200, apex_server="Parking/1.0"),
    )
    synthesize(d)
    assert "parking" in d.root_cause.lower()


# ---------- H3: Working but intent-vs-actual mismatch ----------


def test_h3_intent_actual_mismatch_vercel_serving_wrangler_intent():
    """lamill.io pattern — Vercel serves, but repo has wrangler.jsonc."""
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["76.76.21.21"]),
        http=HttpLayer(apex_status=200, apex_server="Vercel"),
        repo=RepoLayer(project_dir_exists=True,
                       deploy_config="Cloudflare Workers"),
    )
    synthesize(d)
    assert "don't match" in d.root_cause or "doesn't match" in d.root_cause.lower()
    # Fix mentions both platforms — user has to pick one
    fix_text = " ".join(d.fix_steps)
    assert "Vercel" in fix_text and "Cloudflare Workers" in fix_text


def test_h3b_clean_vercel_working_without_repo_disagreement():
    """Working Vercel site with no conflicting repo config → just 'site up'."""
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["76.76.21.21"]),
        http=HttpLayer(apex_status=200, apex_server="Vercel"),
        repo=RepoLayer(project_dir_exists=True, deploy_config="Vercel"),
    )
    synthesize(d)
    assert "serves through Vercel" in d.root_cause
    assert "No action" in d.fix_steps[0]


# ---------- H4: TLS rejected on intended platform ----------


def test_h4_tls_alert_112_with_intent_platform():
    d = _stub_diagnosis(
        tls=TlsLayer(handshake_ok=False, alert_code=112,
                     error="SSLError: tlsv1 unrecognized name"),
        repo=RepoLayer(project_dir_exists=True,
                       deploy_config="Cloudflare Workers"),
    )
    synthesize(d)
    assert "TLS handshake rejected" in d.root_cause
    assert "Cloudflare Workers" in d.root_cause
    # Fix mentions cert provisioning
    assert any("cert" in s.lower() for s in d.fix_steps)


# ---------- H5: No DNS ----------


def test_h5_no_dns_at_all():
    d = _stub_diagnosis(
        dns=DnsLayer(error="no DNS records returned"),
    )
    synthesize(d)
    assert "No DNS records found" in d.root_cause
    assert any("registrar" in s.lower() for s in d.fix_steps)


# ---------- H6: Normal working site ----------


def test_h6_working_live_site():
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["1.2.3.4"]),
        http=HttpLayer(apex_status=200, apex_server="Cloudflare"),
        inventory=InventoryLayer(last_classification="live-site"),
    )
    synthesize(d)
    assert "Live and serving" in d.root_cause
    assert "No action" in d.fix_steps[0]


# ---------- H7: Forwarder / parked decision item ----------


def test_h7_forwarder_decision():
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["1.2.3.4"]),
        http=HttpLayer(apex_status=200),
        inventory=InventoryLayer(last_classification="forwarder"),
    )
    synthesize(d)
    assert "forwarder" in d.root_cause.lower()
    fix_text = " ".join(d.fix_steps)
    assert "TOMBSTONE" in fix_text
    assert "bootstrap" in fix_text.lower()


def test_h7_parked_decision():
    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["1.2.3.4"]),
        http=HttpLayer(apex_status=200),
        inventory=InventoryLayer(last_classification="parked"),
    )
    synthesize(d)
    assert "parked" in d.root_cause.lower()


# ---------- Fallback when no heuristic matches ----------


def test_fallback_when_nothing_matches():
    """Bare diagnosis with no useful signals → fallback message."""
    d = _stub_diagnosis()
    synthesize(d)
    assert "No single heuristic matched" in d.root_cause
    # No definitive fix — the user has to interpret the layers themselves
    assert d.fix_steps == []


# ---------- Renderer doesn't crash ----------


def test_render_does_not_crash():
    """Smoke — the renderer handles any combination of layers without raising."""
    from io import StringIO
    from rich.console import Console
    from portfolio.diagnose import render

    d = _stub_diagnosis(
        dns=DnsLayer(a_records=["76.76.21.21"]),
        http=HttpLayer(apex_status=404, apex_server="Vercel",
                       apex_vercel_error="DEPLOYMENT_NOT_FOUND"),
        tls=TlsLayer(handshake_ok=True, cert_subject="x.com", cert_issuer="LE"),
        repo=RepoLayer(project_dir_exists=True, deploy_config="Vercel"),
        inventory=InventoryLayer(in_portfolio_json=True,
                                 portfolio_category="My brand"),
    )
    synthesize(d)
    sink = Console(file=StringIO(), force_terminal=False)
    # Should not raise.
    render(d, sink)


# ---------- Platform-guess from DNS ----------


def test_dns_platform_guess_vercel_via_ip():
    dns = DnsLayer(a_records=["76.76.21.21"])
    assert dns.platform_guess == "Vercel"


def test_dns_platform_guess_cf_pages_via_cname():
    dns = DnsLayer(cname="x.pages.dev.")
    assert dns.platform_guess == "Cloudflare Pages"


def test_dns_platform_guess_netlify_via_cname():
    dns = DnsLayer(www_cname="something.netlify.app.")
    assert dns.platform_guess == "Netlify"


def test_dns_platform_guess_none_when_nothing_known():
    dns = DnsLayer(a_records=["1.2.3.4"])
    assert dns.platform_guess is None
