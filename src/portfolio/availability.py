"""Domain availability + price (v2.B, fixed 2026-05-06).

Two independent layers — kept separate because Porkbun's previous
`/domain/checkAvailability` endpoint is dead (returns 404). The current
working layout:

  - **Availability**: RDAP. IANA bootstrap → per-TLD endpoint → GET
    `/domain/<name>`. 404 = available; 200 = taken; anything else =
    unknown (per-TLD coverage gaps for `.io / .co / .tech` etc.).

  - **Price**: Porkbun's `/api/json/v3/pricing/get` — public, no auth
    required, returns prices for every TLD they sell. Cached locally
    for 7 days.

`AvailabilityChecker` composes both: RDAP for the bool, Porkbun pricing
for the dollars. Retries 1× with 1s backoff on transient network errors.
Distinguishes `error` (retried, still failed) from `unknown` (RDAP has no
endpoint for that TLD).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .data import ROOT

PORKBUN_PRICING_URL = "https://api.porkbun.com/api/json/v3/pricing/get"
PORKBUN_TIMEOUT = 30.0
PORKBUN_PRICING_CACHE_PATH = ROOT / "data" / "cache" / "porkbun_pricing.json"
PORKBUN_PRICING_TTL_SECONDS = 7 * 24 * 60 * 60
PORKBUN_PRICING_RETRIES = 2
PORKBUN_PRICING_RETRY_BACKOFF_S = 2.0

RDAP_TIMEOUT = 8.0
RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
RDAP_CACHE_PATH = ROOT / "data" / "cache" / "rdap_endpoints.json"
RDAP_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

DEFAULT_RATE_DELAY_S = 0.3
DEFAULT_RETRIES = 1
DEFAULT_RETRY_BACKOFF_S = 1.0

# DoH (DNS-over-HTTPS) fallback for availability when RDAP fails.
#
# Background: some networks (Charter/Spectrum + Cujo, others) intercept
# `rdap.radix.host` at the L4 layer, returning malformed TLS bytes. The same
# networks often hijack plain DNS too (NXDOMAIN forging). DoH bypasses both
# because the query is encrypted to the public resolver. We query NS records
# (set by every registrar at registration time) — a registered domain has
# `Status: 0` plus an `Answer` array; an unregistered one returns `Status: 3`
# (NXDOMAIN). False-positive cases (registered but no NS configured) are rare
# and the user re-verifies at registrar checkout anyway.
DOH_GOOGLE_URL = "https://dns.google/resolve"
DOH_CLOUDFLARE_URL = "https://cloudflare-dns.com/dns-query"
DOH_TIMEOUT = 8.0


@dataclass
class AvailResult:
    """One check result.

    `available`:
      - True   → confirmed available
      - False  → confirmed taken
      - None   → unknown (RDAP gap, no error)

    `error` is set when the check actually failed (timeout, 5xx, parse
    failure) after retries — distinct from None-without-error which is
    "the registry just doesn't expose RDAP for this TLD."
    """
    available: bool | None
    price: float | None
    backend: str
    error: str | None = None


# ---------- pricing (Porkbun /pricing/get; public, no auth) ----------


def _money_from_str(s) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _fetch_porkbun_pricing() -> dict[str, dict] | None:
    """Hit /pricing/get with retries. Returns the `pricing` dict (TLD without
    leading dot → {registration, renewal, transfer, coupons}). Returns None
    on persistent failure (so callers fall back to no-price gracefully)."""
    for attempt in range(PORKBUN_PRICING_RETRIES + 1):
        try:
            r = requests.get(PORKBUN_PRICING_URL, timeout=PORKBUN_TIMEOUT)
        except Exception:
            if attempt < PORKBUN_PRICING_RETRIES:
                time.sleep(PORKBUN_PRICING_RETRY_BACKOFF_S * (attempt + 1))
                continue
            return None
        if r.status_code != 200:
            if 500 <= r.status_code < 600 and attempt < PORKBUN_PRICING_RETRIES:
                time.sleep(PORKBUN_PRICING_RETRY_BACKOFF_S * (attempt + 1))
                continue
            return None
        try:
            body = r.json()
        except Exception:
            return None
        if body.get("status") != "SUCCESS":
            return None
        pricing = body.get("pricing")
        if not isinstance(pricing, dict):
            return None
        return pricing
    return None


def load_porkbun_pricing() -> dict[str, dict]:
    """Get the Porkbun pricing dict, refreshing the cache if stale.

    Returns {} if the cache is stale and the fetch fails — callers should
    treat empty pricing as "no price available" (price=None per lookup).
    """
    if PORKBUN_PRICING_CACHE_PATH.exists():
        try:
            payload = json.loads(PORKBUN_PRICING_CACHE_PATH.read_text())
            if (time.time() - payload.get("cached_at", 0)) <= PORKBUN_PRICING_TTL_SECONDS:
                return payload.get("pricing", {})
        except (OSError, json.JSONDecodeError):
            pass
    pricing = _fetch_porkbun_pricing()
    if pricing is None:
        return {}
    PORKBUN_PRICING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PORKBUN_PRICING_CACHE_PATH.write_text(json.dumps({"cached_at": time.time(), "pricing": pricing}))
    return pricing


def lookup_price(domain: str, pricing: dict[str, dict] | None = None) -> float | None:
    """Look up the registration price for a domain in the Porkbun pricing dict."""
    if pricing is None:
        pricing = load_porkbun_pricing()
    if not pricing:
        return None
    if "." not in domain:
        return None
    tld = domain.rsplit(".", 1)[-1].lower()
    if "." in domain.split(".", 1)[1]:  # multi-part TLD like co.in
        rest = domain.split(".", 1)[1].lower()
        if rest in pricing:
            tld = rest
    entry = pricing.get(tld)
    if not isinstance(entry, dict):
        return None
    return _money_from_str(entry.get("registration"))


def lookup_renewal(domain: str, pricing: dict[str, dict] | None = None) -> float | None:
    """Look up the *renewal* price for a domain — the true keep-forever cost,
    which on many topical TLDs (`.family`, `.life`, `.fm`) far exceeds the
    first-year registration. Mirrors `lookup_price`; v28 surfaces this so the
    grid doesn't undersell a reg-cheap / renew-expensive TLD."""
    if pricing is None:
        pricing = load_porkbun_pricing()
    if not pricing or "." not in domain:
        return None
    tld = domain.rsplit(".", 1)[-1].lower()
    if "." in domain.split(".", 1)[1]:  # multi-part TLD like co.in
        rest = domain.split(".", 1)[1].lower()
        if rest in pricing:
            tld = rest
    entry = pricing.get(tld)
    if not isinstance(entry, dict):
        return None
    return _money_from_str(entry.get("renewal"))


# ---------- RDAP availability (with retry) ----------


def _load_rdap_endpoints() -> dict[str, list[str]]:
    """TLD (no dot) → list of RDAP base URLs. Cached on disk for 30 days."""
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


def dns_check(domain: str) -> AvailResult:
    """DoH-based availability fallback. Queries NS records for `domain` against
    Google's `dns.google/resolve` (with Cloudflare as backup) — both encrypt
    the query so ISPs that hijack plain DNS or block specific RDAP hosts can't
    interfere.

    Returns:
      - AvailResult(available=True,  backend="doh")  on Status=3 (NXDOMAIN)
      - AvailResult(available=False, backend="doh")  on Status=0 with NS Answer
      - AvailResult(available=None,  backend="doh", error=...) on any other status
        or transport failure

    Caveat: a registered domain with no NS configured returns NXDOMAIN here
    (false positive available). In practice every registrar sets default NS at
    registration time, so this is rare; the user re-verifies at checkout.
    """
    last_err: str | None = None
    for url in (DOH_GOOGLE_URL, DOH_CLOUDFLARE_URL):
        try:
            r = requests.get(
                url,
                params={"name": domain, "type": "NS"},
                headers={"accept": "application/dns-json"},
                timeout=DOH_TIMEOUT,
            )
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue
        if r.status_code != 200:
            last_err = f"DoH HTTP {r.status_code}"
            continue
        try:
            body = r.json()
        except Exception as e:
            last_err = f"DoH JSON parse: {e}"
            continue
        status = body.get("Status")
        if status == 3:
            return AvailResult(available=True, price=None, backend="doh")
        if status == 0 and body.get("Answer"):
            return AvailResult(available=False, price=None, backend="doh")
        last_err = f"DoH status={status}"
    return AvailResult(available=None, price=None, backend="doh", error=last_err)


def rdap_check(domain: str, *, retries: int = DEFAULT_RETRIES, backoff_s: float = DEFAULT_RETRY_BACKOFF_S) -> AvailResult:
    """Check availability via RDAP, with DoH fallback when RDAP can't be reached.

    Returns:
      - AvailResult(available=True)   for HTTP 404 (registry confirms not registered)
      - AvailResult(available=False)  for HTTP 200 (registry returns the record)
      - AvailResult(available=None, error=None) when there's no RDAP endpoint
        for that TLD AND DoH gives no definitive answer
      - AvailResult(available=None, error=...) when both RDAP and DoH failed

    DoH fallback engages when:
      (a) the RDAP call raises (network/SSL/Cujo intercept), or
      (b) the RDAP server returns a non-200/404 we can't interpret.
    Some networks (Charter+Cujo) intercept `rdap.radix.host` returning malformed
    TLS — the DoH fallback routes around that by querying NS records over HTTPS.
    """
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""
    services = _load_rdap_endpoints()
    urls = services.get(tld, [])
    if not urls:
        # No RDAP endpoint for this TLD. Try DoH as a last-resort signal.
        dns_result = dns_check(domain)
        if dns_result.available is not None:
            return AvailResult(available=dns_result.available, price=None,
                               backend="doh", error=None)
        return AvailResult(available=None, price=None, backend="rdap",
                           error=None)  # genuine gap
    base = urls[0].rstrip("/")
    last_err: str | None = None
    for attempt in range(retries + 1):
        try:
            r = requests.get(f"{base}/domain/{domain}", timeout=RDAP_TIMEOUT)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries:
                time.sleep(backoff_s)
                continue
            # All retries exhausted — try DoH fallback.
            return _rdap_or_doh_fallback(domain, last_err)
        if r.status_code == 404:
            return AvailResult(available=True, price=None, backend="rdap")
        if r.status_code == 200:
            return AvailResult(available=False, price=None, backend="rdap")
        if 500 <= r.status_code < 600 and attempt < retries:
            last_err = f"RDAP HTTP {r.status_code}"
            time.sleep(backoff_s)
            continue
        # Non-success non-retryable status — try DoH fallback.
        return _rdap_or_doh_fallback(domain, f"RDAP HTTP {r.status_code}")
    return _rdap_or_doh_fallback(domain, last_err)


def rdap_creation_date(domain: str, *, timeout: float = RDAP_TIMEOUT) -> "date | None":
    """Fetch the domain's RDAP `events` array and return the date associated
    with `eventAction: "registration"`. Returns None on any error (no RDAP
    endpoint for the TLD, network failure, missing event, malformed payload).

    This is the "true" domain age — independent of which registrar I bought
    it from. Used to soften SEO grading for newly-registered domains and
    surface the "this domain is aged, expect ranking momentum" signal.
    """
    from datetime import date as _date, datetime as _datetime
    tld = domain.rsplit(".", 1)[-1].lower() if "." in domain else ""
    services = _load_rdap_endpoints()
    urls = services.get(tld, [])
    if not urls:
        return None
    base = urls[0].rstrip("/")
    try:
        r = requests.get(f"{base}/domain/{domain}", timeout=timeout)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        payload = r.json()
    except Exception:
        return None
    for event in payload.get("events", []):
        if event.get("eventAction") == "registration":
            ed = event.get("eventDate")
            if not ed:
                return None
            try:
                # RDAP eventDate is ISO 8601, often with trailing Z.
                return _datetime.fromisoformat(ed.replace("Z", "+00:00")).date()
            except ValueError:
                try:
                    return _date.fromisoformat(ed[:10])
                except ValueError:
                    return None
    return None


def _rdap_or_doh_fallback(domain: str, rdap_err: str | None) -> AvailResult:
    """Used when RDAP fails to give a definitive answer. Tries DoH; returns
    DoH's answer if definitive, else surfaces the original RDAP error."""
    dns_result = dns_check(domain)
    if dns_result.available is not None:
        return AvailResult(available=dns_result.available, price=None,
                           backend="doh", error=None)
    return AvailResult(available=None, price=None, backend="rdap", error=rdap_err)


# ---------- AvailabilityChecker (composes RDAP + Porkbun pricing) ----------


class AvailabilityChecker:
    """Composes RDAP (availability) with Porkbun pricing (price). The two are
    independent — RDAP doesn't need any API key; Porkbun's `/pricing/get`
    is public.

    `log_fn(msg)`, if provided, is called with one human-readable status line
    per check so the user can see progress.
    """

    def __init__(
        self,
        porkbun_api_key: str | None = None,        # kept for API compat; not used post-2026-05-06
        porkbun_secret_key: str | None = None,     # same
        rate_delay_s: float = DEFAULT_RATE_DELAY_S,
        log_fn=None,
    ):
        self.rate_delay_s = rate_delay_s
        self.log_fn = log_fn
        self._last_call_at = 0.0
        self._pricing: dict[str, dict] | None = None  # lazy

    @property
    def backend(self) -> str:
        # Single backend now: RDAP + Porkbun-public-pricing. No auth needed.
        return "rdap+porkbun-pricing"

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call_at
        if elapsed < self.rate_delay_s:
            time.sleep(self.rate_delay_s - elapsed)
        self._last_call_at = time.time()

    def _log(self, msg: str) -> None:
        if self.log_fn is not None:
            self.log_fn(msg)

    def check(self, domain: str) -> AvailResult:
        self._rate_limit()
        avail = rdap_check(domain)
        if self._pricing is None:
            self._pricing = load_porkbun_pricing()
        price = lookup_price(domain, self._pricing)
        return AvailResult(
            available=avail.available,
            price=price,
            backend=self.backend,
            error=avail.error,
        )

    def make_check_callable(self):
        """Return a `(domain) -> (available, price, error)` callable for
        suggest.render_options(). Logs each check via self.log_fn if set."""
        def _f(domain: str):
            res = self.check(domain)
            if self.log_fn is not None:
                if res.error:
                    self._log(f"  ✕ {domain}  error: {res.error}")
                elif res.available is True:
                    price_s = f", ${res.price:.2f}/yr" if res.price is not None else ""
                    self._log(f"  ✓ {domain}  available{price_s}")
                elif res.available is False:
                    self._log(f"  ✗ {domain}  taken")
                else:
                    self._log(f"  ? {domain}  unknown (no RDAP endpoint for this TLD)")
            return res.available, res.price, res.error
        return _f


# ---------- back-compat shims ----------


def porkbun_check(domain: str, api_key: str = "", secret_key: str = "") -> AvailResult:
    """Deprecated: Porkbun's `/domain/checkAvailability` was removed in 2026.
    Kept as a thin wrapper that routes to the new RDAP+pricing path so any
    external caller still gets a sane result.
    """
    avail = rdap_check(domain)
    price = lookup_price(domain)
    return AvailResult(
        available=avail.available,
        price=price,
        backend="rdap+porkbun-pricing",
        error=avail.error,
    )
