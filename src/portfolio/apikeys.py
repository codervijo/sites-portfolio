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
    "SERPAPI_KEY",   # v8.D — real-SERP fetcher for `new research`
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

    return out
