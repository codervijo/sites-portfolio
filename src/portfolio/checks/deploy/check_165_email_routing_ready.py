"""CHECK_165 — `hello@<site>` can receive mail (v50.C).

Every operator-owned site gets `hello@<site>`, forwarded by Cloudflare
Email Routing to `hello@lamill.io` (or `lamill.toml [email] forward_to`).
Operator decision 2026-11-10: email for every own site, retroactive.

  pass  — mail is handled by another provider (MX not Cloudflare's;
          never touched), or routing is on, the rule exists and the
          destination is verified.
  warn  — fixable (routing off / rule missing), destination not yet
          verified (click the link), zone pending, or SPF/rule conflict.

Not applicable: non-domain dirs, archived, dark sites, HostGator sites,
client-owned sites (client email is undecided — v50.A (b)).

The fixer calls the CF API (as CHECK_150's does); it writes no files.
"""
from __future__ import annotations

import re
from pathlib import Path

from portfolio.fix_helpers import FixerSpec, FixResult

from ..result import CheckResult

CHECK_ID = "CHECK_165"
CHECK_NAME = "email-routing-ready"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "hello@<site> receives mail: Cloudflare Email Routing forwards it to "
    "hello@lamill.io (or [email] forward_to), or another provider handles "
    "the domain's mail (v50.C)."
)

_DOMAIN_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$"
)


def _not_applicable(base: Path) -> str | None:
    domain = base.name.lower()
    if not _DOMAIN_RE.match(domain):
        return "not a domain-shaped dir"
    if domain.endswith((".bup", ".old", ".bak")):
        return "backup copy of a site dir"
    try:
        from portfolio.fleet_repos import _archived_reason
        if _archived_reason(base) is not None:
            return "archived"
    except Exception:
        pass
    try:
        from ..config import load_config
        if domain in {s.lower() for s in load_config().dark_sites}:
            return "dark site"
    except Exception:
        pass
    try:
        from portfolio import lamill_toml
        doc = lamill_toml.load(base)
        if doc is not None and doc.deploy is not None and doc.deploy.platform == "hostgator":
            return "HostGator site (mail on the host)"
    except Exception:
        pass
    try:
        from portfolio.data import load_domains
        row = next((d for d in load_domains() if d.name.lower() == domain), None)
        if row is not None and row.is_client:
            return "client-owned site (client email undecided)"
    except Exception:
        pass
    return None


def _inspect(base: Path):
    from portfolio import email_routing as er
    return er.inspect(base.name.lower(), forward_to=er.forward_to_for(base))


def run(repo_path: str) -> CheckResult:
    from portfolio import email_routing as er

    base = Path(repo_path).resolve()
    reason = _not_applicable(base)
    if reason:
        return CheckResult(status="pass", message=f"{reason} — n/a")
    try:
        st = _inspect(base)
    except er.EmailRoutingError as e:
        return CheckResult(status="warn", message=f"can't read email setup: {e}")
    except Exception as e:  # network / DNS — say so, don't pretend
        return CheckResult(status="warn",
                           message=f"can't read email setup ({type(e).__name__}: {e})")

    if st.other_provider:
        return CheckResult(status="pass",
                           message=f"mail handled by {st.other_provider} — left alone")
    if st.ready():
        return CheckResult(status="pass",
                           message=f"{', '.join(st.addresses)} → {st.forward_to} (routing on, verified)")
    steps, blockers = er.plan(st)
    if blockers:
        return CheckResult(status="warn", message="; ".join(blockers))
    if steps:
        return CheckResult(status="warn",
                           message="no working hello@ — `project fix` will: " + "; ".join(steps))
    if not st.dest_verified:
        extra = (f", then `project fix` adds {', '.join(st.missing_rules())}"
                 if st.missing_rules() else "")
        return CheckResult(status="warn",
                           message=f"waiting on verification: click the link Cloudflare "
                                   f"emailed to {st.forward_to}{extra}")
    if st.routing_status == "misconfigured":
        return CheckResult(status="warn",
                           message="Email Routing is 'misconfigured' — its MX/SPF records were "
                                   "changed or removed, so hello@ bounces. Restore them in the "
                                   "Cloudflare dashboard (Email → Email Routing → Settings).")
    return CheckResult(status="warn",
                       message=f"Email Routing status {st.routing_status!r} — re-check shortly")


def _apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    from portfolio import email_routing as er

    base = project_dir.resolve()
    reason = _not_applicable(base)
    if reason:
        return FixResult(status="nothing-to-do", summary=f"{reason} — n/a", files_touched=[])
    fwd = er.forward_to_for(base)
    try:
        st = er.inspect(base.name.lower(), forward_to=fwd)
    except er.EmailRoutingError as e:
        return FixResult(status="error", summary=str(e), files_touched=[])
    if st.other_provider:
        return FixResult(status="nothing-to-do",
                         summary=f"mail handled by {st.other_provider} — not touched",
                         files_touched=[])
    steps, blockers = er.plan(st)
    if blockers:
        return FixResult(status="manual", summary="; ".join(blockers), files_touched=[])
    if not steps and er.waiting_on_verification(st):
        return FixResult(status="manual",
                         summary=f"waiting on you: click the verification link Cloudflare "
                                 f"emailed to {fwd}, then re-run this fix to add "
                                 f"{', '.join(st.missing_rules())}", files_touched=[])
    if not steps:
        if st.dest_verified:
            return FixResult(status="nothing-to-do",
                             summary=f"{', '.join(st.addresses)} → {fwd} already set up",
                             files_touched=[])
        return FixResult(status="manual",
                         summary=f"set up; waiting on you: click the verification link "
                                 f"Cloudflare emailed to {fwd}", files_touched=[])
    if dry_run:
        return FixResult(status="would-fix", summary="would " + "; ".join(steps),
                         files_touched=[])
    try:
        res = er.ensure(base.name.lower(), forward_to=fwd)
    except er.EmailRoutingError as e:
        return FixResult(status="error", summary=str(e), files_touched=[])
    summary = "; ".join(res.changed) or "no change"
    if res.pending:
        summary += " — ↷ " + "; ".join(res.pending)
    return FixResult(status="fixed", summary=summary, files_touched=[])


fix_tier_1 = FixerSpec(
    check_id="",   # registry rewrites at discovery time
    tier=1,
    summary="forward hello@<site> via Cloudflare Email Routing (never touches other providers)",
    apply=_apply,
)
