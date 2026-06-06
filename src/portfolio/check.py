from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import tldextract

from .data import ROOT, load_domains, load_plan

CHECKS_DIR = ROOT / "data" / "checks"
WIP_CATEGORIES = ("My brand", "SEO under way", "Next session", "Under build")

PARKED_HOST_SUFFIXES = (
    "cashparking.com",
    "parkingcrew.net",
    "sedoparking.com",
    "park.io",
    "domaincontrol.com",
    "l.ink",  # Porkbun URL Forwarding lands here (v32.B — mdburst false-green)
)
FOR_SALE_HOST_SUFFIXES = (
    "afternic.com",
    "dan.com",
    "sedo.com",
    "bodis.com",
    "uniregistry.com",
)

USER_AGENT = "portfolio-cli/0.1"
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 15.0

CLASSIFICATION_PRIORITY = {
    "live-site": 0,
    "forwarder": 1,
    "for-sale": 2,
    "parked": 3,
    "error": 4,
    "ssl-broken": 5,
    "dead": 6,
}


BODY_EXCERPT_LIMIT = 2000
PARKING_REDIRECT_BODY_LIMIT = 1000

JS_PARKING_REDIRECT_RE = re.compile(
    r"""window\.location(?:\.href)?\s*=\s*['"]/(lander|landing|sale|park|parking|for[-_]?sale|coming[-_]?soon)\b""",
    re.IGNORECASE,
)


@dataclass
class CheckResult:
    domain: str
    variant: str
    fetched_at: str
    dns_ok: bool
    status: int | None
    final_url: str | None
    classification: str
    redirect_chain: list[str] = field(default_factory=list)
    response_time_ms: int | None = None
    error: str | None = None
    body_excerpt: str | None = None
    classification_reason: str | None = None


def _etld(host: str) -> str:
    ext = tldextract.extract(host)
    return f"{ext.domain}.{ext.suffix}".lower()


def _has_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    host = host.lower()
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _classify_error(err: str) -> str:
    e = err.lower()
    if "ssl" in e or "tls" in e or "certificate" in e or "cert_" in e:
        return "ssl-broken"
    return "dead"


def _looks_like_parking_redirect(body: str | None) -> bool:
    if not body or len(body) > PARKING_REDIRECT_BODY_LIMIT:
        return False
    return JS_PARKING_REDIRECT_RE.search(body) is not None


def _classify(
    domain: str,
    final_url: str | None,
    status: int | None,
    error: str | None,
    body: str | None = None,
) -> tuple[str, str | None]:
    """Returns (classification, optional reason)."""
    if error:
        return _classify_error(error), None
    if not final_url:
        return "dead", None
    final_host = httpx.URL(final_url).host.lower()
    if _has_suffix(final_host, FOR_SALE_HOST_SUFFIXES):
        return "for-sale", "for-sale-host-suffix"
    if _has_suffix(final_host, PARKED_HOST_SUFFIXES):
        return "parked", "parked-host-suffix"
    if status is not None and status >= 400:
        return "error", None
    if _etld(final_host) != _etld(domain):
        return "forwarder", None
    if _looks_like_parking_redirect(body):
        return "parked", "js-redirect-to-parking-page"
    return "live-site", None


async def _fetch(client: httpx.AsyncClient, domain: str, variant: str) -> CheckResult:
    host = f"www.{domain}" if variant == "www" else domain
    url = f"https://{host}"
    fetched_at = datetime.now(timezone.utc).isoformat()
    loop = asyncio.get_event_loop()
    start = loop.time()
    chain: list[str] = []

    try:
        resp = await client.get(url, follow_redirects=True)
        elapsed_ms = int((loop.time() - start) * 1000)
        chain = [str(h.url) for h in resp.history]
        final_url = str(resp.url)
        body_full = ""
        try:
            body_full = resp.text
        except Exception:
            body_full = ""
        body_excerpt = body_full[:BODY_EXCERPT_LIMIT] if body_full else None
        classification, reason = _classify(domain, final_url, resp.status_code, None, body_full)
        return CheckResult(
            domain=domain,
            variant=variant,
            fetched_at=fetched_at,
            dns_ok=True,
            status=resp.status_code,
            final_url=final_url,
            classification=classification,
            classification_reason=reason,
            redirect_chain=chain,
            response_time_ms=elapsed_ms,
            error=None,
            body_excerpt=body_excerpt,
        )
    except Exception as e:
        elapsed_ms = int((loop.time() - start) * 1000)
        err = f"{type(e).__name__}: {e}"
        msg = str(e).lower()
        dns_failure = (
            "name or service not known" in msg
            or "nodename nor servname" in msg
            or "no address associated" in msg
            or "name resolution" in msg
        )
        classification, reason = _classify(domain, None, None, err)
        return CheckResult(
            domain=domain,
            variant=variant,
            fetched_at=fetched_at,
            dns_ok=not dns_failure,
            status=None,
            final_url=None,
            classification=classification,
            classification_reason=reason,
            redirect_chain=chain,
            response_time_ms=elapsed_ms,
            error=err,
            body_excerpt=None,
        )


async def _run_all(domains: list[str], concurrency: int) -> list[CheckResult]:
    sem = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(READ_TIMEOUT, connect=CONNECT_TIMEOUT)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, verify=True) as client:
        async def task(d: str, v: str) -> CheckResult:
            async with sem:
                return await _fetch(client, d, v)

        coros = [task(d, v) for d in domains for v in ("bare", "www")]
        return await asyncio.gather(*coros)


def wip_domains() -> list[str]:
    plan = load_plan()
    return sorted(d for d, c in plan.items() if c in WIP_CATEGORIES)


def all_domains() -> list[str]:
    return sorted(d.name for d in load_domains())


def run_check(only: str = "wip", concurrency: int = 20) -> tuple[Path, list[CheckResult]]:
    if only == "wip":
        domains = wip_domains()
    elif only == "all":
        domains = all_domains()
    else:
        raise ValueError(f"Unknown scope: {only!r} (use 'wip' or 'all')")

    if not domains:
        raise RuntimeError(f"No domains found for scope {only!r}")

    results = asyncio.run(_run_all(domains, concurrency))
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = CHECKS_DIR / f"{today}.json"
    out.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "scope": only,
                "results": [asdict(r) for r in results],
            },
            indent=2,
        )
        + "\n"
    )
    return out, results


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text())


def list_snapshots() -> list[Path]:
    if not CHECKS_DIR.exists():
        return []
    return sorted(CHECKS_DIR.glob("*.json"), reverse=True)


def latest_snapshot() -> Path | None:
    files = list_snapshots()
    return files[0] if files else None


def previous_snapshot() -> Path | None:
    files = list_snapshots()
    return files[1] if len(files) > 1 else None


def best_per_domain(snapshot: dict) -> dict[str, dict]:
    by_domain: dict[str, dict] = {}
    for r in snapshot["results"]:
        existing = by_domain.get(r["domain"])
        rp = CLASSIFICATION_PRIORITY.get(r["classification"], 99)
        ep = CLASSIFICATION_PRIORITY.get(existing["classification"], 99) if existing else 100
        if existing is None or rp < ep:
            by_domain[r["domain"]] = r
    return by_domain
