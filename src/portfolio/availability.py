"""Domain availability + price (v2.B).

Default backend: Porkbun `domain/checkAvailability` (returns available + price in
one call). Falls back to RDAP when Porkbun keys are absent (availability only).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .data import ROOT

PORKBUN_URL = "https://api.porkbun.com/api/json/v3/domain/checkAvailability"
PORKBUN_TIMEOUT = 10.0

RDAP_TIMEOUT = 8.0
RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
RDAP_CACHE_PATH = ROOT / "data" / "cache" / "rdap_endpoints.json"
RDAP_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

DEFAULT_RATE_DELAY_S = 0.3


@dataclass
class AvailResult:
    available: bool | None
    price: float | None
    backend: str
    error: str | None = None


def _money_from_str(s) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def porkbun_check(domain: str, api_key: str, secret_key: str) -> AvailResult:
    """Single Porkbun checkAvailability call. Returns AvailResult."""
    payload = {"secretapikey": secret_key, "apikey": api_key, "domain": domain}
    try:
        r = requests.post(PORKBUN_URL, json=payload, timeout=PORKBUN_TIMEOUT)
        body = r.json()
    except Exception as e:
        return AvailResult(available=None, price=None, backend="porkbun", error=f"{type(e).__name__}: {e}")
    resp = body.get("response", {}) if isinstance(body, dict) else {}
    if body.get("status") == "ERROR":
        return AvailResult(available=None, price=None, backend="porkbun", error=body.get("message", "porkbun error"))
    avail_str = (resp.get("avail") or "").lower()
    available = True if avail_str == "yes" else (False if avail_str == "no" else None)
    price = _money_from_str(resp.get("price"))
    return AvailResult(available=available, price=price, backend="porkbun")


def _load_rdap_endpoints() -> dict[str, list[str]]:
    """Map of TLD (no dot) -> list of RDAP base URLs. Cached on disk."""
    if RDAP_CACHE_PATH.exists():
        try:
            payload = json.loads(RDAP_CACHE_PATH.read_text())
            if (time.time() - payload.get("cached_at", 0)) <= RDAP_CACHE_TTL_SECONDS:
                return payload.get("services", {})
        except (OSError, json.JSONDecodeError):
            pass
    try:
        r = requests.get(RDAP_BOOTSTRAP_URL, timeout=RDAP_TIMEOUT)
        r.raise_for_status()
        services_raw = r.json().get("services", [])
    except Exception:
        return {}
    services: dict[str, list[str]] = {}
    for entry in services_raw:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        tlds, urls = entry[0], entry[1]
        for tld in tlds:
            services[tld.lower()] = list(urls)
    RDAP_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RDAP_CACHE_PATH.write_text(json.dumps({"cached_at": time.time(), "services": services}))
    return services


def rdap_check(domain: str) -> AvailResult:
    """Free availability check via RDAP. Returns AvailResult (price always None)."""
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""
    services = _load_rdap_endpoints()
    urls = services.get(tld, [])
    if not urls:
        return AvailResult(available=None, price=None, backend="rdap", error=f"no RDAP endpoint for .{tld}")
    base = urls[0].rstrip("/")
    try:
        r = requests.get(f"{base}/domain/{domain}", timeout=RDAP_TIMEOUT)
    except Exception as e:
        return AvailResult(available=None, price=None, backend="rdap", error=f"{type(e).__name__}: {e}")
    if r.status_code == 404:
        return AvailResult(available=True, price=None, backend="rdap")
    if r.status_code == 200:
        return AvailResult(available=False, price=None, backend="rdap")
    return AvailResult(available=None, price=None, backend="rdap", error=f"RDAP HTTP {r.status_code}")


class AvailabilityChecker:
    """Stateful checker: picks Porkbun or RDAP based on env, rate-limits between calls."""

    def __init__(
        self,
        porkbun_api_key: str | None = None,
        porkbun_secret_key: str | None = None,
        rate_delay_s: float = DEFAULT_RATE_DELAY_S,
    ):
        self.porkbun_api_key = porkbun_api_key or None
        self.porkbun_secret_key = porkbun_secret_key or None
        self.rate_delay_s = rate_delay_s
        self._last_call_at = 0.0

    @property
    def backend(self) -> str:
        return "porkbun" if (self.porkbun_api_key and self.porkbun_secret_key) else "rdap"

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call_at
        if elapsed < self.rate_delay_s:
            time.sleep(self.rate_delay_s - elapsed)
        self._last_call_at = time.time()

    def check(self, domain: str) -> AvailResult:
        self._rate_limit()
        if self.backend == "porkbun":
            return porkbun_check(domain, self.porkbun_api_key, self.porkbun_secret_key)
        return rdap_check(domain)

    def make_check_callable(self):
        """Return a `(domain) -> (available, price)` callable for suggest.render_options()."""
        def _f(domain: str) -> tuple[bool | None, float | None]:
            res = self.check(domain)
            return res.available, res.price
        return _f
