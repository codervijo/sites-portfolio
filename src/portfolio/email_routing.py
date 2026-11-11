"""v50.B — idempotent Cloudflare Email Routing client + preflight.

Forwards `hello@<site>` to the operator's mailbox (`hello@lamill.io` by
default, `lamill.toml [email] forward_to` overrides). Used by CHECK_165
(`email-routing-ready`); there is no CLI verb of its own (operator,
2026-11-10: delivery through check + fix).

Ground rules (operator brief 2026-11-10):
  * **Never touch a zone whose mail is handled by another provider.** Any
    MX that isn't Cloudflare's `route*.mx.cloudflare.net` → "managed
    elsewhere", read-only.
  * **Never overwrite an existing rule.** A rule for the address that
    forwards somewhere else is reported, not replaced.
  * An apex SPF TXT that lacks Cloudflare's include → manual (merge by
    hand), never replaced.
  * Probe before act; every write is skipped when state already matches
    (ADR-0015).

`inspect()` is read-only and returns an `EmailState`; `ensure()` makes
the writes. The CF API endpoints used:
  GET  /zones/{z}/email/routing                 settings (enabled/status)
  POST /zones/{z}/email/routing/dns             enable (CF adds MX + SPF)
  GET  /zones/{z}/email/routing/rules           rules
  POST /zones/{z}/email/routing/rules           create rule
  GET  /accounts/{a}/email/routing/addresses    destination addresses
  POST /accounts/{a}/email/routing/addresses    create (CF mails a link)
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import _httpapi
from . import cloudflare as cf

DEFAULT_FORWARD_TO = "hello@lamill.io"   # operator-owned sites only (v50.A (b))
DEFAULT_LOCAL_PARTS = ("hello",)         # every own site gets hello@ (v50.A)
CF_MX_SUFFIX = ".mx.cloudflare.net"
CF_SPF_INCLUDE = "include:_spf.mx.cloudflare.net"
DOH_URL = "https://cloudflare-dns.com/dns-query"

_PERM_HINT = (
    "The CF token needs Zone → Email Routing Rules: Edit and "
    "Account → Email Routing Addresses: Edit. Edit the lamill token at "
    "https://dash.cloudflare.com/profile/api-tokens, then re-run."
)


class EmailRoutingError(RuntimeError):
    """Operator-facing failure: plain-words cause + fix."""


# ---------------------------------------------------------------- state


@dataclass
class EmailState:
    domain: str
    forward_to: str
    addresses: list[str]                    # full addresses, e.g. hello@x.com
    on_cloudflare: bool = False
    zone_id: str | None = None
    account_id: str | None = None
    zone_status: str | None = None          # active / pending / …
    mx_hosts: list[str] = field(default_factory=list)
    other_provider: str | None = None       # set when MX is not Cloudflare's
    spf: str | None = None                  # apex v=spf1 TXT, if any
    routing_enabled: bool = False
    routing_status: str | None = None       # ready / unconfigured / misconfigured …
    rules: dict[str, list[str]] = field(default_factory=dict)  # addr → forward targets
    dest_exists: bool = False
    dest_verified: bool = False

    # -- derived -------------------------------------------------------
    @property
    def spf_conflict(self) -> bool:
        return bool(self.spf) and CF_SPF_INCLUDE not in (self.spf or "")

    def missing_rules(self) -> list[str]:
        return [a for a in self.addresses if a not in self.rules]

    def conflicting_rules(self) -> dict[str, list[str]]:
        """Rules for our addresses that forward somewhere else."""
        return {a: t for a, t in self.rules.items()
                if a in self.addresses and self.forward_to not in t}

    def ready(self) -> bool:
        # Status matters, not just the switch: deleting CF's MX/SPF leaves
        # routing "enabled" but `misconfigured`, and mail bounces.
        return (self.routing_enabled and self.routing_status == "ready"
                and not self.missing_rules()
                and not self.conflicting_rules() and self.dest_verified)


# ---------------------------------------------------------------- config


def forward_to_for(base: Path) -> str:
    """`lamill.toml [email] forward_to`, else the fleet default. Read raw so
    the optional table needs no schema change (ADR-0017)."""
    try:
        doc = tomllib.loads((base / "lamill.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return DEFAULT_FORWARD_TO
    email = doc.get("email")
    if isinstance(email, dict):
        v = email.get("forward_to")
        if isinstance(v, str) and "@" in v:
            return v.strip()
    return DEFAULT_FORWARD_TO


# ---------------------------------------------------------------- DNS (public)


def public_mx(domain: str, *, client: httpx.Client | None = None) -> list[str]:
    """MX hosts as the world sees them (DNS-over-HTTPS; no dependency)."""
    def factory() -> httpx.Client:
        return httpx.Client(timeout=8.0, headers={"accept": "application/dns-json"})
    with _httpapi.managed_client(client, factory) as c:
        r = c.get(DOH_URL, params={"name": domain, "type": "MX"})
    r.raise_for_status()
    out = []
    for a in r.json().get("Answer") or []:
        if a.get("type") == 15:
            parts = str(a.get("data", "")).split()
            if parts:
                out.append(parts[-1].rstrip(".").lower())
    return out


def provider_name(mx_hosts: list[str]) -> str:
    joined = " ".join(mx_hosts)
    for needle, name in (("google", "Google"), ("zoho", "Zoho"),
                         ("protonmail", "Proton"), ("outlook", "Microsoft 365"),
                         ("registrar-servers", "Namecheap forwarding"),
                         ("improvmx", "ImprovMX"), ("forwardemail", "Forward Email")):
        if needle in joined:
            return name
    return f"own mail server ({mx_hosts[0]})" if mx_hosts else "unknown"


def _is_cf_mx(host: str) -> bool:
    return host.rstrip(".").lower().endswith(CF_MX_SUFFIX)


# ---------------------------------------------------------------- CF calls


def _ok(resp: httpx.Response, what: str) -> dict:
    if resp.status_code in (401, 403):
        raise EmailRoutingError(f"{what}: Cloudflare refused (HTTP {resp.status_code}). {_PERM_HINT}")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if resp.status_code >= 400 or not body.get("success", False):
        errs = body.get("errors") or resp.text[:200]
        codes = {e.get("code") for e in errs} if isinstance(errs, list) else set()
        if 10000 in codes:  # CF's "Authentication error" = missing permission
            raise EmailRoutingError(f"{what}: Cloudflare says the token lacks permission. {_PERM_HINT}")
        raise EmailRoutingError(f"{what}: Cloudflare error (HTTP {resp.status_code}): {errs}")
    return body


def _zone(c: httpx.Client, domain: str) -> dict | None:
    body = _ok(c.get("/zones", params={"name": domain}), f"look up zone {domain}")
    res = body.get("result") or []
    return res[0] if res else None


def _rules(c: httpx.Client, zone_id: str) -> dict[str, list[str]]:
    body = _ok(c.get(f"/zones/{zone_id}/email/routing/rules", params={"per_page": 50}),
               "read routing rules")
    out: dict[str, list[str]] = {}
    for r in body.get("result") or []:
        if not r.get("enabled", True):
            continue
        for m in r.get("matchers") or []:
            if m.get("type") == "literal" and m.get("field") == "to":
                targets: list[str] = []
                for a in r.get("actions") or []:
                    if a.get("type") == "forward":
                        targets += [str(v).lower() for v in a.get("value") or []]
                out.setdefault(str(m.get("value", "")).lower(), []).extend(targets)
    return out


def _dest(c: httpx.Client, account_id: str, email: str) -> dict | None:
    body = _ok(c.get(f"/accounts/{account_id}/email/routing/addresses",
                     params={"per_page": 50}), "read destination addresses")
    for a in body.get("result") or []:
        if str(a.get("email", "")).lower() == email.lower():
            return a
    return None


# ---------------------------------------------------------------- inspect / ensure


def inspect(domain: str, *, forward_to: str = DEFAULT_FORWARD_TO,
            local_parts: tuple[str, ...] = DEFAULT_LOCAL_PARTS,
            client: httpx.Client | None = None,
            dns_client: httpx.Client | None = None) -> EmailState:
    """Read-only snapshot of the domain's mail setup. Raises
    EmailRoutingError (plain words) when Cloudflare can't be read."""
    domain = domain.lower()
    st = EmailState(domain=domain, forward_to=forward_to.lower(),
                    addresses=[f"{p}@{domain}" for p in local_parts])
    with _httpapi.managed_client(client, cf._client) as c:
        z = _zone(c, domain)
        if z is None:  # not on this CF account → public DNS only
            st.mx_hosts = public_mx(domain, client=dns_client)
            if st.mx_hosts:
                st.other_provider = provider_name(st.mx_hosts)
            return st
        st.on_cloudflare = True
        st.zone_id = z["id"]
        st.account_id = (z.get("account") or {}).get("id")
        st.zone_status = z.get("status")
        recs = _ok(c.get(f"/zones/{st.zone_id}/dns_records", params={"per_page": 100}),
                   "read DNS records").get("result") or []
        for r in recs:
            if r.get("name", "").lower() != domain:
                continue
            if r.get("type") == "MX":
                st.mx_hosts.append(str(r.get("content", "")).rstrip(".").lower())
            elif r.get("type") == "TXT" and "v=spf1" in str(r.get("content", "")):
                st.spf = str(r.get("content", "")).strip('"')
        foreign = [h for h in st.mx_hosts if not _is_cf_mx(h)]
        if foreign:
            st.other_provider = provider_name(foreign)
            return st  # never look further / never touch
        s = _ok(c.get(f"/zones/{st.zone_id}/email/routing"), "read Email Routing settings")
        res = s.get("result") or {}
        st.routing_enabled = bool(res.get("enabled"))
        st.routing_status = res.get("status")
        st.rules = _rules(c, st.zone_id)
        if st.account_id:
            d = _dest(c, st.account_id, forward_to)
            st.dest_exists = d is not None
            st.dest_verified = bool(d and d.get("verified"))
    return st


@dataclass
class EnsureResult:
    changed: list[str]       # what was written, plain words
    pending: list[str]       # what's waiting on someone/something
    state: EmailState


def plan(st: EmailState) -> tuple[list[str], list[str]]:
    """(would-do steps, blockers). Blockers mean: don't write anything."""
    blockers: list[str] = []
    if not st.on_cloudflare:
        blockers.append("DNS isn't on Cloudflare — set up mail at the DNS host by hand"
                        if not st.other_provider else "")
    elif st.zone_status != "active":
        blockers.append(f"Cloudflare zone is {st.zone_status!r}, not active — "
                        "re-run once the nameservers point at Cloudflare")
    if st.other_provider:
        return [], []  # managed elsewhere: nothing to do, nothing blocked
    if st.spf_conflict:
        blockers.append(f"apex already has an SPF record ({st.spf!r}) without "
                        f"{CF_SPF_INCLUDE} — merge it by hand, lamill won't replace it")
    for a, t in st.conflicting_rules().items():
        blockers.append(f"{a} already forwards to {', '.join(t)} — "
                        "left alone; change it in the dashboard if intended")
    blockers = [b for b in blockers if b]
    steps: list[str] = []
    if not st.dest_exists:
        steps.append(f"add destination {st.forward_to} (Cloudflare emails it a verification link)")
    if not st.routing_enabled:
        steps.append("enable Email Routing (Cloudflare adds its MX + SPF records)")
    for a in st.missing_rules():
        # Cloudflare rejects a rule to an unverified destination (code 2054,
        # seen in the v50.E pilot), so the rule waits for the click.
        if st.dest_verified:
            steps.append(f"add rule {a} → {st.forward_to}")
    return steps, blockers


def waiting_on_verification(st: EmailState) -> bool:
    """Rules are missing only because the destination isn't verified yet."""
    return bool(st.missing_rules()) and not st.dest_verified and st.dest_exists


def ensure(domain: str, *, forward_to: str = DEFAULT_FORWARD_TO,
           local_parts: tuple[str, ...] = DEFAULT_LOCAL_PARTS,
           client: httpx.Client | None = None,
           dns_client: httpx.Client | None = None) -> EnsureResult:
    """Make the writes `plan()` lists. Idempotent: a done domain writes
    nothing. Raises EmailRoutingError on blockers or API failure."""
    with _httpapi.managed_client(client, cf._client) as c:
        st = inspect(domain, forward_to=forward_to, local_parts=local_parts,
                     client=c, dns_client=dns_client)
        steps, blockers = plan(st)
        if blockers:
            raise EmailRoutingError("; ".join(blockers))
        if st.on_cloudflare and not st.other_provider and not st.account_id:
            raise EmailRoutingError(
                f"Cloudflare didn't return the account for zone {st.zone_id} — "
                "can't manage destination addresses. Check the token's account access.")
        changed: list[str] = []
        if st.other_provider:
            return EnsureResult(changed, [], st)
        if not st.dest_exists:
            _ok(c.post(f"/accounts/{st.account_id}/email/routing/addresses",
                       json={"email": st.forward_to}), f"add destination {st.forward_to}")
            changed.append(f"destination {st.forward_to} added — verification email sent")
        if not st.routing_enabled:
            r = c.post(f"/zones/{st.zone_id}/email/routing/dns", json={})
            if r.status_code in (404, 405):  # older API shape
                r = c.post(f"/zones/{st.zone_id}/email/routing/enable", json={})
            _ok(r, "enable Email Routing")
            changed.append("Email Routing enabled (MX + SPF added by Cloudflare)")
        rule_addrs = st.missing_rules() if st.dest_verified else []
        for a in rule_addrs:
            _ok(c.post(f"/zones/{st.zone_id}/email/routing/rules", json={
                "name": f"lamill: {a} → {st.forward_to}",
                "enabled": True,
                "matchers": [{"type": "literal", "field": "to", "value": a}],
                "actions": [{"type": "forward", "value": [st.forward_to]}],
            }), f"add rule {a}")
            changed.append(f"rule {a} → {st.forward_to} added")
        after = inspect(domain, forward_to=forward_to, local_parts=local_parts,
                        client=c, dns_client=dns_client)
    pending: list[str] = []
    if not after.dest_verified:
        pending.append(f"click the verification link Cloudflare emailed to {after.forward_to}, "
                       f"then re-run `lamill project fix {domain} --rule CHECK_165 --apply` "
                       f"to add {', '.join(after.missing_rules()) or 'the rule'}")
    if not after.routing_enabled or after.routing_status not in (None, "ready"):
        pending.append(f"Email Routing status is {after.routing_status!r} — "
                       "Cloudflare may still be adding DNS records; re-run the check")
    if after.missing_rules() and after.dest_verified:
        pending.append(f"rules still missing after write: {', '.join(after.missing_rules())}")
    return EnsureResult(changed, pending, after)
