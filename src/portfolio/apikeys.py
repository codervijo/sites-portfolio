"""v7.A — `settings apikeys` (list/set/delete) for portfolio.env credentials.

Replaces manual editing of portfolio.env with a CLI surface that:
  - lists known keys with set/not-set status + connectivity tick
  - sets a key with strict validation against a known-keys list
    (--force to bypass for arbitrary names)
  - deletes a key (with confirm; --yes to skip)

Env file is edited atomically: read → mutate in memory → tmpfile →
rename. Preserves comments, blank lines, and ordering of unchanged
keys. If a key already exists, the existing line is updated; new keys
get appended at the end.

Connectivity tests live next to the env IO since they're the
"is this credential actually working?" half of the same UX. Each
provider has a small probe that returns OK / failed / not-testable.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx

from .suggest import PORTFOLIO_ENV, ensure_portfolio_env


# Keys we actively support. Used by `set` for strict validation;
# `list` always shows these (set or not).
KNOWN_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "PORKBUN_API_KEY",
    "PORKBUN_SECRET_API_KEY",
    "CF_API_TOKEN",
    "CF_ACCOUNT_ID",
    "CRUX_API_KEY",
    "SERPAPI_KEY",   # v8.D — real-SERP fetcher for `new validate`
    "VERCEL_TOKEN",  # v11.A — Vercel provider walker for `fleet hosting`
    # v11.A — per-account HostGator API tokens + cPanel usernames.
    # cPanel API tokens are account-scoped; one token per HG account
    # in the fleet. The env-var suffix `GATOR3164` encodes the server
    # hostname (used to build `https://gator3164.hostgator.com:2083`).
    # The cPanel username on that server is a SEPARATE value — for
    # unmanaged HG shared hosting it's often the same as the hostname,
    # but for accounts with a custom username (e.g. `foundervijo` on
    # server `gator3164`) it differs. Resolution 11.L originally
    # assumed username==hostname; patched 2026-05-19 to decouple them
    # after the operator's curl returned `Current User: foundervijo`.
    # Add more when a third HG account appears.
    "HOSTGATOR_TOKEN_GATOR3164",
    "HOSTGATOR_USER_GATOR3164",
    "HOSTGATOR_TOKEN_GATOR4216",
    "HOSTGATOR_USER_GATOR4216",
    "GITHUB_TOKEN",  # v15.I — REST API for repo create via `POST /user/repos`
                     # (per ADR-0012). Falls back to `gh` CLI when unset; both
                     # paths exit `new deploy` with a clear error when neither
                     # is available.
    "GA4_ACCOUNT_ID",  # v18.D — parent account ID for `ga4_admin.create_property`
                       # (e.g. "123456789"). Visible in the GA4 admin URL or via
                       # `GET /v1beta/accounts`. Operator's GA4 organization is
                       # usually one account; set once via `lamill settings
                       # apikeys set GA4_ACCOUNT_ID <id>`. Bootstrap soft-skips
                       # GA4 property creation when unset.
)


# ---------- env file IO ----------


def _read_env_lines() -> list[str]:
    """Return portfolio.env's lines (creates it from template if absent)."""
    ensure_portfolio_env()
    return PORTFOLIO_ENV.read_text().splitlines(keepends=True)


def _parse_assignment(line: str) -> tuple[str, str] | None:
    """Parse `KEY=VALUE` from a non-comment line. Returns (key, value)
    or None if the line isn't an assignment. Quotes around value are
    stripped if symmetric."""
    m = re.match(r"^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
    if not m:
        return None
    key, val = m.group(1), m.group(2)
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        val = val[1:-1]
    return key, val


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` via tmpfile + rename for atomicity."""
    fd, tmp = tempfile.mkstemp(prefix=".portfolio_env.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        shutil.move(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_key(key: str) -> str | None:
    """Return the value of `key` in portfolio.env, or None if unset.
    Whitespace-only / empty values count as unset."""
    for line in _read_env_lines():
        parsed = _parse_assignment(line)
        if parsed and parsed[0] == key:
            value = parsed[1].strip()
            return value if value else None
    return None


def set_key(key: str, value: str) -> None:
    """Set `key` to `value` in portfolio.env. Updates the existing line
    if present; otherwise appends. Preserves all other lines / comments.
    """
    lines = _read_env_lines()
    new_line = f"{key}={value}\n"
    found = False
    out: list[str] = []
    for line in lines:
        parsed = _parse_assignment(line)
        if parsed and parsed[0] == key and not found:
            out.append(new_line)
            found = True
            continue
        out.append(line)
    if not found:
        # Append at end. Ensure file ends with a newline before append.
        if out and not out[-1].endswith("\n"):
            out[-1] = out[-1] + "\n"
        out.append(new_line)
    _atomic_write(PORTFOLIO_ENV, "".join(out))


def delete_key(key: str) -> bool:
    """Remove `key` from portfolio.env. Returns True if a line was
    removed; False if the key wasn't present."""
    lines = _read_env_lines()
    out: list[str] = []
    removed = False
    for line in lines:
        parsed = _parse_assignment(line)
        if parsed and parsed[0] == key and not removed:
            removed = True
            continue
        out.append(line)
    if removed:
        _atomic_write(PORTFOLIO_ENV, "".join(out))
    return removed


# ---------- connectivity tests ----------


ProbeStatus = Literal["valid", "invalid", "not-testable", "missing"]


@dataclass
class ProbeResult:
    """Outcome of one credential connectivity probe."""
    status: ProbeStatus
    detail: str  # short human-readable summary (or "")


def _probe_openai(key: str) -> ProbeResult:
    """Hit OpenAI's /v1/models endpoint — cheapest authenticated call."""
    if not key:
        return ProbeResult("missing", "")
    try:
        r = httpx.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        return ProbeResult("valid", "200 OK")
    if r.status_code == 401:
        return ProbeResult("invalid", "401 unauthorized")
    return ProbeResult("invalid", f"http {r.status_code}")


def _probe_crux(key: str) -> ProbeResult:
    """CrUX API — POST a query for google.com (always has data)."""
    if not key:
        return ProbeResult("missing", "")
    try:
        r = httpx.post(
            f"https://chromeuxreport.googleapis.com/v1/records:queryRecord?key={key}",
            json={"origin": "https://google.com", "formFactor": "PHONE",
                  "metrics": ["largest_contentful_paint"]},
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        return ProbeResult("valid", "200 OK")
    if r.status_code in (400, 403):
        return ProbeResult("invalid", f"http {r.status_code}")
    return ProbeResult("invalid", f"http {r.status_code}")


def _probe_porkbun(api_key: str, secret: str) -> ProbeResult:
    """Porkbun ping endpoint — auth requires both key + secret."""
    if not api_key or not secret:
        return ProbeResult("missing", "")
    try:
        r = httpx.post(
            "https://api.porkbun.com/api/json/v3/ping",
            json={"apikey": api_key, "secretapikey": secret},
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        try:
            body = r.json()
            if body.get("status") == "SUCCESS":
                return ProbeResult("valid", "200 SUCCESS")
        except (ValueError, KeyError):
            pass
        return ProbeResult("invalid", "unexpected response shape")
    return ProbeResult("invalid", f"http {r.status_code}")


def _probe_cf_token(token: str) -> ProbeResult:
    """Cloudflare /user/tokens/verify — confirms the token is valid."""
    if not token:
        return ProbeResult("missing", "")
    try:
        r = httpx.get(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {token}"},
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        try:
            body = r.json()
            if body.get("success"):
                return ProbeResult("valid", "200 success")
        except (ValueError, KeyError):
            pass
        return ProbeResult("invalid", "unexpected response shape")
    return ProbeResult("invalid", f"http {r.status_code}")


def _probe_serpapi(key: str) -> ProbeResult:
    """SerpAPI /account endpoint — cheapest authenticated call that
    doesn't burn against the search quota."""
    if not key:
        return ProbeResult("missing", "")
    try:
        r = httpx.get(
            f"https://serpapi.com/account?api_key={key}",
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        try:
            body = r.json()
            # /account returns plan name + remaining searches; both confirm
            # the key is valid + give useful context.
            plan = body.get("plan_name") or body.get("plan") or "?"
            remaining = body.get("searches_left", body.get("plan_searches_left", "?"))
            return ProbeResult("valid", f"{plan} · {remaining} left")
        except (ValueError, KeyError):
            return ProbeResult("valid", "200 OK")
    if r.status_code == 401:
        return ProbeResult("invalid", "401 unauthorized")
    return ProbeResult("invalid", f"http {r.status_code}")


def _probe_vercel(token: str) -> ProbeResult:
    """Vercel `/v2/user` — cheapest authenticated call; confirms the
    token is valid and returns the user/team identity.
    """
    if not token:
        return ProbeResult("missing", "")
    try:
        r = httpx.get(
            "https://api.vercel.com/v2/user",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        try:
            user = r.json().get("user", {})
            username = user.get("username") or user.get("email") or "?"
            return ProbeResult("valid", f"user={username}")
        except (ValueError, KeyError):
            return ProbeResult("valid", "200 OK")
    if r.status_code == 401:
        return ProbeResult("invalid", "401 unauthorized")
    return ProbeResult("invalid", f"http {r.status_code}")


HOSTGATOR_TOKEN_PREFIX = "HOSTGATOR_TOKEN_"
HOSTGATOR_USER_PREFIX = "HOSTGATOR_USER_"


def _hg_account_from_keyname(keyname: str) -> str | None:
    """Extract the cPanel account_id from a `HOSTGATOR_TOKEN_<ACCOUNT_ID>`
    env-var name. Returns None if the keyname doesn't match the
    expected pattern.
    """
    if not keyname.startswith(HOSTGATOR_TOKEN_PREFIX):
        return None
    return keyname[len(HOSTGATOR_TOKEN_PREFIX):].lower() or None


def hg_user_for_account(account_id: str) -> str:
    """Look up the cPanel username for an HG `account_id`.

    Reads `HOSTGATOR_USER_<ACCOUNT_ID>` from `portfolio.env`. Falls
    back to `account_id` itself when the env var isn't set —
    back-compat with operators where username==server-hostname (the
    default for unmanaged HG shared hosting; resolution 11.L's
    original assumption).

    Public (no leading underscore) so the walker + orchestrator in
    `hosting.py` can plumb it through without reaching into a
    private symbol.
    """
    if not account_id:
        return account_id
    keyname = f"{HOSTGATOR_USER_PREFIX}{account_id.upper()}"
    return get_key(keyname) or account_id


def _probe_hostgator(
    token: str, account_id: str, cpanel_user: str | None = None,
) -> ProbeResult:
    """HostGator cPanel UAPI — `Variables/get_user_information`.

    Auth uses cPanel's custom `cpanel <user>:<token>` scheme (NOT HTTP
    Basic). cPanel host is auto-derived from `account_id` per
    resolution 11.L: `https://<account_id>.hostgator.com:2083`.

    `cpanel_user` is the cPanel username on that server. When unset,
    falls back to `account_id` — works for shared hosting where the
    server name doubles as the username. For accounts with a custom
    username (operator set `HOSTGATOR_USER_GATOR3164=foundervijo`,
    surfaced 2026-05-19 via the 403 hand test), pass it through.

    8s timeout because cPanel is slower than CF/Vercel.
    """
    if not token:
        return ProbeResult("missing", "")
    if not account_id:
        return ProbeResult("invalid", "missing account_id")
    user = cpanel_user or account_id
    url = (
        f"https://{account_id}.hostgator.com:2083"
        f"/execute/Variables/get_user_information"
    )
    try:
        r = httpx.get(
            url,
            headers={"Authorization": f"cpanel {user}:{token}"},
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        try:
            body = r.json()
        except ValueError:
            return ProbeResult("invalid", "non-JSON response")
        # UAPI returns top-level `status` (1=success, 0=failure).
        if body.get("status") == 1:
            data = body.get("data") or {}
            user = data.get("user") or account_id
            return ProbeResult("valid", f"cPanel user={user}")
        errors = body.get("errors") or []
        first = errors[0] if errors else "unknown error"
        return ProbeResult("invalid", f"UAPI status=0: {first}")
    if r.status_code == 401:
        return ProbeResult("invalid", "401 unauthorized")
    if r.status_code == 403:
        return ProbeResult("invalid", "403 forbidden (token scope?)")
    return ProbeResult("invalid", f"http {r.status_code}")


def probe_all() -> dict[str, ProbeResult]:
    """Run connectivity probes for every known key. Returns a dict
    keyed by KEY name. Probes run sequentially (~5-10s total).

    Pairs that need both halves (Porkbun) report under each key
    individually; CF_ACCOUNT_ID is reported as not-testable on its own
    but the test for CF_API_TOKEN implicitly validates the token's
    account scope.
    """
    out: dict[str, ProbeResult] = {}

    out["OPENAI_API_KEY"] = _probe_openai(get_key("OPENAI_API_KEY") or "")
    out["CRUX_API_KEY"] = _probe_crux(get_key("CRUX_API_KEY") or "")

    pk = get_key("PORKBUN_API_KEY") or ""
    sk = get_key("PORKBUN_SECRET_API_KEY") or ""
    pb_result = _probe_porkbun(pk, sk)
    # Both keys share the same probe outcome.
    out["PORKBUN_API_KEY"] = pb_result if pk else ProbeResult("missing", "")
    out["PORKBUN_SECRET_API_KEY"] = pb_result if sk else ProbeResult("missing", "")

    out["CF_API_TOKEN"] = _probe_cf_token(get_key("CF_API_TOKEN") or "")

    if get_key("CF_ACCOUNT_ID"):
        out["CF_ACCOUNT_ID"] = ProbeResult(
            "not-testable",
            "implicitly validated by CF_API_TOKEN's scope",
        )
    else:
        out["CF_ACCOUNT_ID"] = ProbeResult("missing", "")

    out["SERPAPI_KEY"] = _probe_serpapi(get_key("SERPAPI_KEY") or "")

    # v11.A — Vercel + HostGator (one probe per HG account).
    out["VERCEL_TOKEN"] = _probe_vercel(get_key("VERCEL_TOKEN") or "")
    for hg_key in (k for k in KNOWN_KEYS if k.startswith(HOSTGATOR_TOKEN_PREFIX)):
        account_id = _hg_account_from_keyname(hg_key) or ""
        cpanel_user = hg_user_for_account(account_id)
        out[hg_key] = _probe_hostgator(
            get_key(hg_key) or "", account_id, cpanel_user,
        )
    # The HOSTGATOR_USER_* env vars don't have their own probe — they
    # piggyback on the matching HOSTGATOR_TOKEN_<...> result. Surface
    # them as not-testable when set / missing otherwise, so the
    # `apikeys list` table shows the operator at a glance whether the
    # username override is in place.
    for user_key in (k for k in KNOWN_KEYS if k.startswith(HOSTGATOR_USER_PREFIX)):
        if get_key(user_key):
            out[user_key] = ProbeResult(
                "not-testable",
                "validated via paired HOSTGATOR_TOKEN_<...> probe",
            )
        else:
            out[user_key] = ProbeResult("missing", "")

    # v15.I — GitHub REST API for repo create. Falls back to `gh` CLI
    # when token unset; pipeline pre-flight handles both.
    out["GITHUB_TOKEN"] = _probe_github(get_key("GITHUB_TOKEN") or "")

    # v18.D — GA4 account ID is set-or-missing (no remote probe;
    # validity is implicit in whether bootstrap's create_property call
    # succeeds against this account). Surface "not-testable" when set
    # so the apikeys list table shows the operator at a glance whether
    # bootstrap will attempt GA4 auto-create.
    if get_key("GA4_ACCOUNT_ID"):
        out["GA4_ACCOUNT_ID"] = ProbeResult(
            "not-testable",
            "validated implicitly by `new bootstrap` create_property",
        )
    else:
        out["GA4_ACCOUNT_ID"] = ProbeResult("missing", "")

    return out


def _probe_github(token: str) -> ProbeResult:
    """GitHub REST API token probe — `GET /user` returns the
    authenticated user's profile (40x on bad token; 200 on valid).

    Token may be missing without being an error — v15.I's `new deploy`
    falls back to the `gh` CLI when GITHUB_TOKEN is unset. The
    `list` command surfaces 'missing' so the operator sees the state.
    """
    if not token:
        return ProbeResult("missing", "")
    try:
        r = httpx.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=8.0,
        )
    except httpx.HTTPError as e:
        return ProbeResult("invalid", f"{type(e).__name__}")
    if r.status_code == 200:
        try:
            login = r.json().get("login") or "?"
        except ValueError:
            login = "?"
        return ProbeResult("valid", f"login={login}")
    if r.status_code == 401:
        return ProbeResult("invalid", "401 unauthorized")
    if r.status_code == 403:
        return ProbeResult("invalid", "403 forbidden (token scope?)")
    return ProbeResult("invalid", f"http {r.status_code}")
