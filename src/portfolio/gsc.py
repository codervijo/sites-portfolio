from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from .data import ROOT

CONFIG_DIR = Path.home() / ".config" / "portfolio" / "gsc"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
TOKEN_PATH = CONFIG_DIR / "token.json"
SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]

GSC_DIR = ROOT / "data" / "gsc"
DEFAULT_DAYS = 28
DEFAULT_LAG_DAYS = 3
DEFAULT_CONCURRENCY = 5


class MissingCredentialsError(RuntimeError):
    pass


def _interactive_flow() -> Credentials:
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    return flow.run_local_server(port=0, open_browser=True)


def _save_token(creds: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)


def authenticate(force: bool = False) -> Credentials:
    """Return valid Credentials. Runs interactive flow when needed.

    `force=True` always runs the interactive flow (e.g. when re-authing).
    """
    if not CREDENTIALS_PATH.exists():
        raise MissingCredentialsError(
            f"Missing OAuth client config at {CREDENTIALS_PATH}.\n"
            "See setup steps to download credentials.json from GCP Console."
        )

    creds: Credentials | None = None
    if not force and TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token and not force:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except RefreshError:
            pass  # Fall through to interactive flow

    creds = _interactive_flow()
    _save_token(creds)
    return creds


def get_service(creds: Credentials | None = None):
    creds = creds or authenticate()
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def list_properties(service=None) -> list[dict]:
    service = service or get_service()
    resp = service.sites().list().execute()
    return resp.get("siteEntry", [])


def property_to_domain(site_url: str) -> str:
    """Canonicalize a GSC property URL to a bare domain (lowercase, no www)."""
    if site_url.startswith("sc-domain:"):
        return site_url[len("sc-domain:"):].lower()
    parsed = urlparse(site_url)
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def coverage_map(properties: list[dict] | None = None) -> dict[str, list[dict]]:
    """Map domain -> list of GSC property entries that cover it."""
    properties = properties if properties is not None else list_properties()
    out: dict[str, list[dict]] = {}
    for p in properties:
        out.setdefault(property_to_domain(p["siteUrl"]), []).append(p)
    return out


def query_totals(service, site_url: str, start: date, end: date) -> dict:
    """Aggregate clicks/impressions/CTR/position for a property over [start, end]."""
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": [],
        "rowLimit": 1,
    }
    resp = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    rows = resp.get("rows") or []
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": None}
    r = rows[0]
    return {
        "clicks": int(r.get("clicks", 0)),
        "impressions": int(r.get("impressions", 0)),
        "ctr": float(r.get("ctr", 0.0)),
        "position": float(r["position"]) if "position" in r else None,
    }


def _merge_property_totals(per_property: list[dict]) -> dict:
    """Sum clicks/impressions across a domain's properties; impression-weighted average position."""
    total_clicks = sum(p["clicks"] for p in per_property)
    total_imp = sum(p["impressions"] for p in per_property)
    ctr = (total_clicks / total_imp) if total_imp else 0.0
    weighted = [(p["position"], p["impressions"]) for p in per_property if p["position"] is not None and p["impressions"]]
    if weighted:
        position = sum(pos * imp for pos, imp in weighted) / sum(imp for _, imp in weighted)
    else:
        position = None
    return {
        "clicks": total_clicks,
        "impressions": total_imp,
        "ctr": ctr,
        "position": position,
    }


def sync(
    domains: list[str],
    days: int = DEFAULT_DAYS,
    lag_days: int = DEFAULT_LAG_DAYS,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> tuple[Path, dict]:
    """Pull totals for each domain and snapshot to data/gsc/YYYY-MM-DD.json.

    Domains not verified in GSC are recorded with status='not-in-gsc' (no API call).
    Multi-property domains are merged into one row.
    """
    today = date.today()
    end = today - timedelta(days=lag_days)
    start = end - timedelta(days=days - 1)

    creds = authenticate()
    bootstrap = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    cov = coverage_map(list_properties(bootstrap))

    def fetch_for_domain(domain: str) -> dict:
        properties = cov.get(domain, [])
        if not properties:
            return {
                "domain": domain,
                "status": "not-in-gsc",
                "properties": [],
            }
        # httplib2 (under googleapiclient) is not thread-safe — build per-thread.
        local_service = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
        per_prop: list[dict] = []
        for p in properties:
            site_url = p["siteUrl"]
            totals = query_totals(local_service, site_url, start, end)
            per_prop.append({"site_url": site_url, **totals})
        merged = _merge_property_totals(per_prop)
        return {
            "domain": domain,
            "status": "ok",
            "properties": [p["site_url"] for p in per_prop],
            "per_property": per_prop,
            **merged,
        }

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        results = list(ex.map(fetch_for_domain, domains))

    GSC_DIR.mkdir(parents=True, exist_ok=True)
    out_path = GSC_DIR / f"{today.isoformat()}.json"
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "days": days,
        "lag_days": lag_days,
        "results": results,
    }
    out_path.write_text(json.dumps(snapshot, indent=2) + "\n")
    return out_path, snapshot


def list_snapshots() -> list[Path]:
    if not GSC_DIR.exists():
        return []
    return sorted(GSC_DIR.glob("*.json"), reverse=True)


def latest_snapshot() -> Path | None:
    files = list_snapshots()
    return files[0] if files else None


def previous_snapshot() -> Path | None:
    files = list_snapshots()
    return files[1] if len(files) > 1 else None


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text())
