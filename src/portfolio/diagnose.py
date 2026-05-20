"""v7.D — `lamill project diagnose <domain>`: auto-investigate a domain's
deploy state and surface a root cause + suggested fix.

Replaces the manual dig / curl / openssl flow we use when a dashboard row
goes red and the rollup isn't enough to explain why. Probes five layers,
prints them with their raw observations, then synthesizes the most likely
root cause from a small heuristic library.

  1. DNS         — A / AAAA / CNAME / NS records via `dig`
  2. HTTP        — root + robots.txt status + Server header
  3. HTTPS / TLS — handshake outcome + cert subject (Let's Encrypt vs.
                   default platform cert vs. mismatch / no cert)
  4. Repo        — sites/<domain>/ contents + deploy config markers
  5. Inventory   — portfolio.json + GSC + most-recent live snapshot

The synthesis pass detects four classes of failure that we hit in
practice this session:

  - "Vercel custom domain attached, no project deploys there" — apex
    points at 76.76.21.21 + `x-vercel-error: DEPLOYMENT_NOT_FOUND`
    (lamill.us scenario)
  - "Namecheap parking — no real site" — apex points at
    91.195.240.x or `Server: Parking/1.0` (linkedcsi.live pre-deploy)
  - "Stale DNS pointing nowhere" — DNS resolves but TCP/TLS refuses
  - "Working" — final URL serves the expected origin

Anything outside these patterns falls back to "raw signals shown; no
single heuristic matched" rather than guessing.

Read-only by design — every probe is observation, no writes.
"""
from __future__ import annotations

import re
import socket
import ssl
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .project import SITES_ROOT


# Known platform IP signatures. Empty list elsewhere = unknown owner.
_PLATFORM_IPS = {
    "Vercel":           {"76.76.21.21"},
    "Namecheap parking": {"91.195.240.19", "192.64.119.210"},
}
_PLATFORM_CNAMES = {
    "Vercel":           ("cname.vercel-dns.com.",),
    "Cloudflare Pages": (".pages.dev.",),
    "Netlify":          (".netlify.app.",),
    "GitHub Pages":     (".github.io.",),
    "Namecheap parking": ("parkingpage.namecheap.com.",),
}

_HTTP_TIMEOUT = 5.0
_TLS_TIMEOUT = 5.0


@dataclass
class DnsLayer:
    a_records: list[str] = field(default_factory=list)
    cname: str | None = None
    nameservers: list[str] = field(default_factory=list)
    www_a: list[str] = field(default_factory=list)
    www_cname: str | None = None
    error: str | None = None

    @property
    def platform_guess(self) -> str | None:
        """Best-effort platform identification from DNS records."""
        for owner, ips in _PLATFORM_IPS.items():
            if any(ip in ips for ip in self.a_records + self.www_a):
                return owner
        for owner, suffixes in _PLATFORM_CNAMES.items():
            for cname in (self.cname, self.www_cname):
                if cname and any(cname.endswith(s) for s in suffixes):
                    return owner
        return None


@dataclass
class HttpLayer:
    apex_status: int | None = None
    apex_final_url: str | None = None
    apex_server: str | None = None
    apex_vercel_error: str | None = None     # x-vercel-error header value
    apex_body_snippet: str | None = None
    robots_status: int | None = None
    error: str | None = None


@dataclass
class TlsLayer:
    handshake_ok: bool = False
    cert_subject: str | None = None
    cert_issuer: str | None = None
    alert_code: int | None = None             # SSL alert number if handshake failed
    error: str | None = None


@dataclass
class RepoLayer:
    project_dir_exists: bool = False
    deploy_config: str | None = None          # "Vercel", "Cloudflare Workers", etc.
    git_remote: str | None = None
    inferred_intent: str | None = None        # e.g., "intent appears to be Cloudflare Workers"


@dataclass
class InventoryLayer:
    in_portfolio_json: bool = False
    portfolio_category: str | None = None
    in_recent_check: bool = False
    last_classification: str | None = None
    in_gsc: bool | None = None                # True/False if known; None if no SEO snapshot


@dataclass
class HostingLayer:
    """v11.K — joined from `data/hosting/<date>.json` snapshot.

    Reads-only — never re-walks the provider APIs during diagnose
    (snapshot freshness is the operator's call via
    `lamill fleet hosting --refresh`). Carries one row per matching
    walker entry; cross-walker conflicts (resolution 11.F) expose
    via `>= 2` rows.
    """
    snapshot_path: str | None = None  # filename, for the "Sources:" footer parity
    rows: list = field(default_factory=list)  # list[HostingRow] — kept loose to avoid circular import


@dataclass
class Diagnosis:
    domain: str
    dns: DnsLayer
    http: HttpLayer
    tls: TlsLayer
    repo: RepoLayer
    inventory: InventoryLayer
    hosting: HostingLayer = field(default_factory=HostingLayer)
    root_cause: str = ""
    fix_steps: list[str] = field(default_factory=list)


# ---------- Layer 1: DNS ----------


def _dig(name: str, rtype: str) -> list[str]:
    try:
        r = subprocess.run(
            ["dig", "+short", "+timeout=3", name, rtype],
            capture_output=True, text=True, check=False, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines()
            if line.strip() and not line.startswith(";;")]


def probe_dns(domain: str) -> DnsLayer:
    out = DnsLayer()
    out.a_records = _dig(domain, "A")
    cnames = _dig(domain, "CNAME")
    out.cname = cnames[0] if cnames else None
    out.nameservers = _dig(domain, "NS")
    out.www_a = _dig(f"www.{domain}", "A")
    www_cnames = _dig(f"www.{domain}", "CNAME")
    out.www_cname = www_cnames[0] if www_cnames else None
    if not (out.a_records or out.www_a or out.cname or out.www_cname):
        out.error = "no DNS records returned"
    return out


# ---------- Layer 2: HTTP ----------


def probe_http(domain: str) -> HttpLayer:
    out = HttpLayer()
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True,
                          verify=False,   # raw connectivity check
                          headers={"User-Agent": "lamill-diagnose/1"}) as c:
            try:
                r = c.get(f"https://{domain}/")
                out.apex_status = r.status_code
                out.apex_final_url = str(r.url)
                out.apex_server = r.headers.get("server")
                out.apex_vercel_error = r.headers.get("x-vercel-error")
                # First 200 chars of body, only if it's HTML.
                ctype = r.headers.get("content-type", "")
                if "html" in ctype and r.text:
                    out.apex_body_snippet = r.text[:200].replace("\n", " ").strip()
            except httpx.HTTPError as e:
                out.error = f"{type(e).__name__}: {e}"
            try:
                r = c.get(f"https://{domain}/robots.txt")
                out.robots_status = r.status_code
            except httpx.HTTPError:
                pass
    except Exception as e:
        out.error = f"{type(e).__name__}: {e}"
    return out


# ---------- Layer 3: TLS ----------


def probe_tls(domain: str) -> TlsLayer:
    out = TlsLayer()
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, 443), timeout=_TLS_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                out.handshake_ok = True
                subject = dict(x[0] for x in cert.get("subject", ()))
                issuer = dict(x[0] for x in cert.get("issuer", ()))
                out.cert_subject = subject.get("commonName")
                out.cert_issuer = issuer.get("commonName") or issuer.get("organizationName")
    except ssl.SSLError as e:
        # Try to extract the TLS alert code from the error message.
        # OpenSSL surfaces e.g. "tlsv1 unrecognized name" → alert 112.
        msg = str(e).lower()
        if "unrecognized name" in msg:
            out.alert_code = 112
        out.error = f"SSLError: {e}"
    except (socket.timeout, OSError) as e:
        out.error = f"{type(e).__name__}: {e}"
    except Exception as e:
        out.error = f"{type(e).__name__}: {e}"
    return out


# ---------- Layer 4: Repo ----------


def probe_repo(domain: str) -> RepoLayer:
    out = RepoLayer()
    site_dir = SITES_ROOT / domain
    if not site_dir.exists():
        return out
    out.project_dir_exists = True

    # Deploy config markers in priority order. First match wins.
    config_markers = [
        ("Cloudflare Workers", "wrangler.jsonc"),
        ("Cloudflare Workers", "wrangler.toml"),
        ("Vercel",             "vercel.json"),
        ("Netlify",            "netlify.toml"),
    ]
    for platform, fname in config_markers:
        if (site_dir / fname).exists():
            out.deploy_config = platform
            out.inferred_intent = (
                f"intent appears to be {platform} (per {fname})"
            )
            break

    # Git remote, if any.
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=site_dir, capture_output=True, text=True,
            check=False, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            out.git_remote = r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return out


# ---------- Layer 5: Inventory ----------


def probe_inventory(domain: str) -> InventoryLayer:
    out = InventoryLayer()
    # Portfolio.json membership + category.
    try:
        from .data import load_domains
        for d in load_domains():
            if d.name.lower() == domain.lower():
                out.in_portfolio_json = True
                out.portfolio_category = d.category
                break
    except Exception:
        pass

    # Most-recent live snapshot row for this domain.
    try:
        from .check import best_per_domain, latest_snapshot, load_snapshot
        snap = latest_snapshot()
        if snap is not None:
            snapshot = load_snapshot(snap)
            row = best_per_domain(snapshot).get(domain.lower())
            if row:
                out.in_recent_check = True
                out.last_classification = row.get("classification")
    except Exception:
        pass

    # GSC presence (via the most recent SEO snapshot — read-only).
    try:
        from .seo_cache import latest_snapshot as seo_latest, load_snapshot, rows_from_snapshot
        snap = seo_latest()
        if snap is not None:
            rows = rows_from_snapshot(load_snapshot(snap))
            for r in rows:
                if r.domain.lower() == domain.lower():
                    # gsc_status is "ok" when the property exists and we got data.
                    out.in_gsc = (r.gsc_status == "ok")
                    break
    except Exception:
        pass
    return out


def probe_hosting(domain: str) -> HostingLayer:
    """v11.K — pull every walker row matching `domain` from the
    latest `data/hosting/<date>.json` snapshot.

    Read-only — diagnose never triggers a fresh walk (snapshot
    freshness is the operator's responsibility via
    `lamill fleet hosting --refresh`). Returns a `HostingLayer`
    with one row per matching walker entry; cross-walker conflicts
    (resolution 11.F) expose naturally as `len(rows) >= 2`.
    """
    out = HostingLayer()
    try:
        from . import hosting_cache

        snap = hosting_cache.latest_snapshot()
        if snap is None:
            return out
        out.snapshot_path = snap.name
        data = hosting_cache.load_snapshot(snap)
        result = hosting_cache.result_from_snapshot(data)
        for r in result.rows:
            if r.domain.lower() == domain.lower():
                out.rows.append(r)
    except Exception:
        pass
    return out


# ---------- Synthesis ----------


def synthesize(d: Diagnosis) -> None:
    """Run heuristics; populate root_cause + fix_steps on `d` in place.

    Heuristic order matters — most-specific first. If nothing matches we
    leave root_cause empty so the rendered output makes clear no single
    cause was identified.
    """
    # H1: Vercel custom-domain orphan (lamill.us pattern)
    if (d.http.apex_server == "Vercel"
            and d.http.apex_vercel_error == "DEPLOYMENT_NOT_FOUND"):
        d.root_cause = (
            "Vercel-side: a custom-domain entry exists for this domain on Vercel's "
            "edge, but no project / deployment is wired to it. Either the project "
            "was deleted, the production deployment was removed, or DNS still "
            "points here from a never-completed setup."
        )
        d.fix_steps = [
            "Decide intent: redeploy on Vercel (add custom domain + push) OR "
            "remove the Vercel A/CNAME records and point DNS elsewhere.",
            "Check your registrar (likely GoDaddy/Namecheap) DNS panel for the "
            "lingering A record 76.76.21.21 — that's Vercel's anycast IP.",
        ]
        return

    # H2: Namecheap parking — well-known parking page
    is_namecheap_parking = (
        (d.dns.cname and "parkingpage.namecheap.com" in d.dns.cname)
        or (d.dns.www_cname and "parkingpage.namecheap.com" in d.dns.www_cname)
        or any(ip in {"91.195.240.19", "192.64.119.210"}
               for ip in d.dns.a_records + d.dns.www_a)
        or d.http.apex_server == "Parking/1.0"
    )
    if is_namecheap_parking:
        d.root_cause = (
            "Domain DNS is set to Namecheap's parking page. No real site has "
            "been deployed (or DNS was never pointed at a deploy target). The "
            "TLS handshake fails because Namecheap's parking server doesn't "
            "provision certs for parked domains."
        )
        fix_lines = [
            "If you intend to deploy this: bootstrap + deploy a real site, "
            "then in Namecheap DNS replace the parking records with the deploy "
            "platform's CNAME/A records.",
        ]
        if d.repo.deploy_config:
            fix_lines.insert(
                0,
                f"Project repo already has a {d.repo.deploy_config} config — "
                f"this looks like an unfinished setup. Finish the deploy "
                f"and point DNS at it."
            )
        d.fix_steps = fix_lines
        return

    # H3: Working but intent-vs-actual mismatch. Site IS serving, but the
    # repo's deploy config (wrangler.jsonc / vercel.json / netlify.toml)
    # disagrees with the platform actually doing the serving. This is the
    # lamill.io case from earlier this session — wrangler.jsonc says CF
    # Workers, but DNS points to Vercel and the cert is Vercel's.
    actual_platform = d.dns.platform_guess
    intent = d.repo.deploy_config
    if (d.http.apex_status and 200 <= d.http.apex_status < 300
            and actual_platform and intent
            and actual_platform != intent):
        d.root_cause = (
            f"Site is serving (HTTP {d.http.apex_status}) on {actual_platform} — "
            f"but the repo's deploy config indicates {intent}. The live deploy "
            f"and the repo's intent don't match. Common cause: an earlier deploy "
            f"setup on the actual platform that was never cleaned up after a "
            f"migration to the intended one (or vice versa)."
        )
        d.fix_steps = [
            f"Decide canonical: keep serving on {actual_platform} OR migrate "
            f"to {intent} as intended.",
            (f"If keeping {actual_platform}: remove the {intent} config files "
             f"so the repo reflects reality."),
            (f"If migrating to {intent}: complete that deploy and update DNS "
             f"at the registrar away from {actual_platform}."),
        ]
        return

    # H3b: Bare apex points to Vercel IP, working, intent agrees (or none)
    if "76.76.21.21" in d.dns.a_records and not d.http.apex_vercel_error:
        if d.http.apex_status and 200 <= d.http.apex_status < 300:
            d.root_cause = (
                "Domain serves through Vercel correctly. Probably the live "
                "site itself — no further diagnosis needed."
            )
            d.fix_steps = ["No action — site is up."]
            return

    # H4: TLS handshake fails on a domain whose intended platform we know
    if (not d.tls.handshake_ok and d.tls.alert_code == 112
            and d.repo.deploy_config):
        d.root_cause = (
            f"TLS handshake rejected with `unrecognized_name` (alert 112). "
            f"The server has no certificate for this hostname. Project intent "
            f"is {d.repo.deploy_config}, so the deploy hasn't been wired up "
            f"to provision the cert."
        )
        d.fix_steps = [
            f"Verify the domain is added as a custom-domain in {d.repo.deploy_config}.",
            "Trigger a fresh deploy so the platform provisions the cert.",
            "Wait ~5-10 min after deploy completes for cert issuance.",
        ]
        return

    # H5: No DNS records at all
    if d.dns.error == "no DNS records returned":
        d.root_cause = (
            "No DNS records found for this domain. Either the nameservers "
            "have nothing configured, or the domain isn't actually registered "
            "(check `lamill new domain` to verify availability)."
        )
        d.fix_steps = [
            "Confirm the domain exists in your registrar inventory.",
            "Set up A/CNAME records at the registrar pointing to your "
            "deploy platform.",
        ]
        return

    # H6: HTTP works, classification says live-site
    if (d.http.apex_status and 200 <= d.http.apex_status < 300
            and d.inventory.last_classification == "live-site"):
        d.root_cause = (
            "Live and serving HTTP 200. Classification confirms live-site. "
            "No fault detected — diagnosis run was probably defensive."
        )
        d.fix_steps = ["No action — site is up."]
        return

    # H7: HTTP works but classification = forwarder/parked
    if d.inventory.last_classification in ("forwarder", "parked"):
        d.root_cause = (
            f"Domain reachable but classified `{d.inventory.last_classification}` — "
            "it points somewhere other than serving its own content. Decide "
            "whether to build a site here, retire the domain, or accept the "
            "current state."
        )
        d.fix_steps = [
            "If retiring: drop a TOMBSTONE.md in the project dir to suppress "
            "fleet repos / focus signals.",
            "If building: `lamill new bootstrap <domain>` to scaffold, then "
            "update DNS once deployed.",
        ]
        return

    # Fallback — no heuristic matched.
    d.root_cause = (
        "No single heuristic matched the observed signals. Review the layers "
        "above for context. Common patterns this diagnoser handles: Vercel "
        "deployment-not-found, Namecheap parking, missing-cert on intended "
        "platform, no-DNS-at-all, normal live site."
    )


# ---------- Driver ----------


def diagnose(domain: str) -> Diagnosis:
    """Run all probes + the synthesis pass. Read-only.

    Five live probes (DNS / HTTP / TLS / Repo / Inventory) plus a
    sixth snapshot-read layer (Hosting, v11.K) that joins
    `data/hosting/<date>.json` without re-walking provider APIs.
    """
    d = Diagnosis(
        domain=domain,
        dns=probe_dns(domain),
        http=probe_http(domain),
        tls=probe_tls(domain),
        repo=probe_repo(domain),
        inventory=probe_inventory(domain),
        hosting=probe_hosting(domain),
    )
    synthesize(d)
    return d


# ---------- Rendering ----------


def render(d: Diagnosis, console) -> None:
    """Pretty-print the diagnosis to a Rich console."""
    console.print(f"\n[bold]{d.domain}[/]  [dim]diagnosis[/]\n")

    # DNS
    a = ", ".join(d.dns.a_records) if d.dns.a_records else "[dim]none[/]"
    cname = d.dns.cname or "[dim]none[/]"
    www_a = ", ".join(d.dns.www_a) if d.dns.www_a else "[dim]none[/]"
    www_cname = d.dns.www_cname or "[dim]none[/]"
    ns = ", ".join(d.dns.nameservers[:2]) if d.dns.nameservers else "[dim]none[/]"
    platform = d.dns.platform_guess
    platform_tag = f"  [yellow]→ {platform}[/]" if platform else ""
    console.print(f"  [cyan]DNS[/]        apex A: {a}{platform_tag}")
    if d.dns.cname:
        console.print(f"             apex CNAME: {cname}")
    if d.dns.www_a or d.dns.www_cname:
        console.print(f"             www  A: {www_a}")
        if d.dns.www_cname:
            console.print(f"             www  CNAME: {www_cname}")
    console.print(f"             NS: {ns}")

    # HTTP
    if d.http.error and d.http.apex_status is None:
        console.print(f"  [cyan]HTTP[/]       [red]error:[/] {d.http.error}")
    else:
        status_color = "green" if (d.http.apex_status and 200 <= d.http.apex_status < 300) else "red"
        server = d.http.apex_server or "?"
        line = f"  [cyan]HTTP[/]       [{status_color}]{d.http.apex_status}[/]  Server: {server}"
        if d.http.apex_vercel_error:
            line += f"  [red]x-vercel-error: {d.http.apex_vercel_error}[/]"
        console.print(line)
        if d.http.apex_final_url and d.http.apex_final_url != f"https://{d.domain}/":
            console.print(f"             final → {d.http.apex_final_url}")
        if d.http.robots_status:
            rcolor = "green" if d.http.robots_status == 200 else "red"
            console.print(f"             robots.txt: [{rcolor}]{d.http.robots_status}[/]")

    # TLS
    if d.tls.handshake_ok:
        cn = d.tls.cert_subject or "?"
        issuer = d.tls.cert_issuer or "?"
        console.print(f"  [cyan]TLS[/]        [green]ok[/]  cert: {cn}  issued by: {issuer}")
    else:
        alert = f"  alert={d.tls.alert_code}" if d.tls.alert_code else ""
        console.print(f"  [cyan]TLS[/]        [red]failed[/]  {d.tls.error or ''}{alert}")

    # Repo
    if d.repo.project_dir_exists:
        intent = f"  [dim]({d.repo.inferred_intent})[/]" if d.repo.inferred_intent else ""
        remote = d.repo.git_remote or "[dim]no remote[/]"
        console.print(f"  [cyan]Repo[/]       sites/{d.domain}/ exists  ·  remote: {remote}{intent}")
    else:
        console.print(f"  [cyan]Repo[/]       sites/{d.domain}/  [dim]not found[/]")

    # Inventory
    inv = d.inventory
    in_portfolio = "[green]✓[/]" if inv.in_portfolio_json else "[red]✗[/]"
    cat = f" ({inv.portfolio_category})" if inv.portfolio_category else ""
    cls = inv.last_classification or "[dim]no snapshot[/]"
    gsc = ("[green]in GSC[/]" if inv.in_gsc
           else "[red]not in GSC[/]" if inv.in_gsc is False
           else "[dim]GSC unknown[/]")
    console.print(
        f"  [cyan]Inventory[/]  portfolio.json {in_portfolio}{cat}  ·  "
        f"live class: {cls}  ·  {gsc}"
    )

    # Hosting (v11.K) — sixth layer, snapshot-read only.
    host = d.hosting
    if host.snapshot_path is None:
        console.print(
            f"  [cyan]Hosting[/]    [dim]no snapshot — run `lamill fleet "
            f"hosting --refresh`[/]"
        )
    elif not host.rows:
        console.print(
            f"  [cyan]Hosting[/]    [dim]no row for {d.domain} in "
            f"{host.snapshot_path}[/]"
        )
    else:
        for i, r in enumerate(host.rows):
            prefix = "  [cyan]Hosting[/]   " if i == 0 else "             "
            conflict = " [yellow]🤐 conflict[/]" if r.provider_conflict else ""
            extras: list[str] = []
            if r.project_slug:
                extras.append(f"project={r.project_slug}")
            if r.hg_account_id:
                extras.append(f"acct={r.hg_account_id}")
            if r.latest_deploy_status:
                extras.append(f"status={r.latest_deploy_status}")
            if r.last_successful_deploy_at:
                extras.append(f"last_ok={r.last_successful_deploy_at[:10]}")
            if r.consecutive_failures:
                extras.append(f"failures={r.consecutive_failures}")
            if r.disk_used_mb is not None:
                extras.append(f"disk={r.disk_used_mb}MB")
            if r.wp_version:
                extras.append(f"WP={r.wp_version}")
            if r.error:
                extras.append(f"[red]err={r.error}[/]")
            tail = "  ·  ".join(extras) if extras else ""
            console.print(
                f"{prefix} provider={r.provider or '—'}{conflict}"
                + (f"  ·  {tail}" if tail else "")
            )

    # Verdict
    console.print(f"\n[bold]Root cause:[/]")
    console.print(f"  {d.root_cause}\n")
    if d.fix_steps:
        console.print(f"[bold]Fix:[/]")
        for i, step in enumerate(d.fix_steps, 1):
            console.print(f"  {i}. {step}")
        console.print()
