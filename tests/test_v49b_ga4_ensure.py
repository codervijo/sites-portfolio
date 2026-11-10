"""v49.B — GA4 find-or-create (`ga4_admin.ensure_property`) + CHECK_162."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from portfolio import ga4_admin
from portfolio.ga4_admin import StreamHit

FLEET = "415643559"
OTHER = "365405177"

MINIMAL_TOML = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'


# ---- pure helpers -----------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("https://www.CalcEngine.site/", "calcengine.site"),
    ("http://iotnews.today", "iotnews.today"),
    ("lamill.store", "lamill.store"),
    (" lamill.store ", "lamill.store"),
    ("", ""),
])
def test_normalize_host(raw, want):
    assert ga4_admin.normalize_host(raw) == want


def _hit(acct, pid, name, mid, host):
    return StreamHit(acct, "acct", pid, name, mid, host)


def test_find_for_domain_prefers_stream_host_then_display_name():
    idx = [
        _hit(FLEET, "1", "something", "G-AAA111", "a.com"),
        _hit(FLEET, "2", "b.com", None, None),
    ]
    assert [h.property_id for h in ga4_admin.find_for_domain("www.a.com", idx)] == ["1"]
    assert [h.property_id for h in ga4_admin.find_for_domain("b.com", idx)] == ["2"]
    assert ga4_admin.find_for_domain("c.com", idx) == []


# ---- HTTP-backed helpers (MockTransport) ------------------------------

class FakeGA4:
    """Tiny in-memory Admin API: accounts → properties → streams + retention."""

    def __init__(self):
        self.accounts = {FLEET: "LaMill Sites", OTHER: "LaMill Rentals"}
        self.props: dict[str, dict] = {}       # pid → {account, name}
        self.streams: dict[str, list] = {}     # pid → [stream dicts]
        self.retention: dict[str, str] = {}    # pid → value
        self.calls: list[str] = []
        self._n = 100

    def add(self, account, name, uri=None, mid=None, retention="TWO_MONTHS"):
        self._n += 1
        pid = str(self._n)
        self.props[pid] = {"account": account, "name": name}
        self.streams[pid] = []
        if mid:
            self.streams[pid].append({"type": "WEB_DATA_STREAM",
                                      "webStreamData": {"defaultUri": uri, "measurementId": mid}})
        self.retention[pid] = retention
        return pid

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.replace("/v1beta", "")
        self.calls.append(f"{req.method} {path}")
        if req.method == "GET" and path == "/accountSummaries":
            out = []
            for aid, name in self.accounts.items():
                out.append({"account": f"accounts/{aid}", "displayName": name,
                            "propertySummaries": [
                                {"property": f"properties/{pid}", "displayName": p["name"]}
                                for pid, p in self.props.items() if p["account"] == aid]})
            return httpx.Response(200, json={"accountSummaries": out})
        if path.endswith("/dataStreams") and req.method == "GET":
            pid = path.split("/")[2]
            return httpx.Response(200, json={"dataStreams": self.streams.get(pid, [])})
        if path.endswith("/dataStreams") and req.method == "POST":
            pid = path.split("/")[2]
            body = json.loads(req.content)
            mid = f"G-NEW{pid}X"
            self.streams[pid].append({"type": "WEB_DATA_STREAM",
                                      "webStreamData": {"defaultUri": body["webStreamData"]["defaultUri"],
                                                        "measurementId": mid}})
            return httpx.Response(200, json={"name": f"properties/{pid}/dataStreams/9",
                                             "webStreamData": {"measurementId": mid}})
        if path == "/properties" and req.method == "POST":
            body = json.loads(req.content)
            pid = self.add(body["parent"].split("/")[1], body["displayName"])
            return httpx.Response(200, json={"name": f"properties/{pid}"})
        if path.endswith("/dataRetentionSettings"):
            pid = path.split("/")[2]
            if req.method == "PATCH":
                self.retention[pid] = json.loads(req.content)["eventDataRetention"]
            v = self.retention[pid]
            return httpx.Response(200, json={"eventDataRetention": v, "userDataRetention": v})
        return httpx.Response(404, text=f"unhandled {req.method} {path}")

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_stream_index_lists_every_account_and_property():
    api = FakeGA4()
    api.add(FLEET, "lamill.store", "https://lamill.store", "G-JHCQC2SH9J")
    api.add(OTHER, "orphan", None, None)
    idx = ga4_admin.stream_index(client=api.client())
    assert {(h.account_id, h.host, h.measurement_id) for h in idx} == {
        (FLEET, "lamill.store", "G-JHCQC2SH9J"), (OTHER, None, None)}


def test_set_data_retention_probes_before_patching():
    api = FakeGA4()
    done = api.add(FLEET, "a.com", retention="FOURTEEN_MONTHS")
    todo = api.add(FLEET, "b.com")
    assert ga4_admin.set_data_retention(done, client=api.client()) is False
    assert not any(c.startswith("PATCH") for c in api.calls)
    assert ga4_admin.set_data_retention(todo, client=api.client()) is True
    assert api.retention[todo] == "FOURTEEN_MONTHS"


def test_ensure_found_reuses_and_sets_retention():
    api = FakeGA4()
    pid = api.add(FLEET, "a.com", "https://a.com", "G-AAA111")
    out = ga4_admin.ensure_property("a.com", FLEET, client=api.client())
    assert (out.status, out.measurement_id) == ("found", "G-AAA111")
    assert api.retention[pid] == "FOURTEEN_MONTHS"
    assert not any(c == "POST /properties" for c in api.calls)


def test_ensure_elsewhere_does_not_create():
    api = FakeGA4()
    api.add(OTHER, "a.com", "https://www.a.com/", "G-OLD111")
    out = ga4_admin.ensure_property("a.com", FLEET, client=api.client())
    assert out.status == "elsewhere" and out.measurement_id == "G-OLD111"
    assert "LaMill Rentals" in out.detail
    assert not any(c.startswith("POST") for c in api.calls)


def test_ensure_ambiguous_when_two_fleet_properties_match():
    api = FakeGA4()
    api.add(FLEET, "a.com", "https://a.com", "G-ONE111")
    api.add(FLEET, "a.com dup", "https://a.com", "G-TWO222")
    assert ga4_admin.ensure_property("a.com", FLEET, client=api.client()).status == "ambiguous"


def test_ensure_dry_run_creates_nothing():
    api = FakeGA4()
    out = ga4_admin.ensure_property("new.com", FLEET, dry_run=True, client=api.client())
    assert out.status == "would-create"
    assert not any(c.startswith(("POST", "PATCH")) for c in api.calls)


def test_ensure_creates_then_second_run_finds_it():
    api = FakeGA4()
    idx = ga4_admin.stream_index(client=api.client())
    first = ga4_admin.ensure_property("new.com", FLEET, index=idx, client=api.client())
    assert first.status == "created" and first.measurement_id.startswith("G-")
    assert api.retention[first.property_id] == "FOURTEEN_MONTHS"
    assert api.props[first.property_id] == {"account": FLEET, "name": "new.com"}
    # Same run (shared index) and a fresh run both reuse — no duplicate.
    again = ga4_admin.ensure_property("new.com", FLEET, index=idx, client=api.client())
    fresh = ga4_admin.ensure_property("new.com", FLEET, client=api.client())
    assert again.status == fresh.status == "found"
    assert again.measurement_id == fresh.measurement_id == first.measurement_id
    assert sum(1 for c in api.calls if c == "POST /properties") == 1


def test_ensure_adds_stream_to_streamless_fleet_property():
    api = FakeGA4()
    pid = api.add(FLEET, "half.com")  # create died before the stream landed
    out = ga4_admin.ensure_property("half.com", FLEET, client=api.client())
    assert out.status == "created" and out.property_id == pid
    assert not any(c == "POST /properties" for c in api.calls)


# ---- CHECK_162 + fixer ------------------------------------------------

from portfolio.checks.seo import check_162_ga4_id_recorded as c162  # noqa: E402


def _site(tmp_path: Path, name="example.test", toml=MINIMAL_TOML) -> Path:
    d = tmp_path / name
    (d / "src" / "layouts").mkdir(parents=True)
    (d / "package.json").write_text("{}")
    if toml is not None:
        (d / "lamill.toml").write_text(toml)
    return d


@pytest.fixture(autouse=True)
def _reset_index():
    c162._INDEX = None
    yield
    c162._INDEX = None


def test_check_na_for_non_web_and_hostgator(tmp_path):
    d = tmp_path / "x.test"
    d.mkdir()
    assert "n/a" in c162.run(str(d)).message
    hg = _site(tmp_path, "hg.test", 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "hostgator"\n\n'
               '[hosting]\ncpanel_user = "u"\ncpanel_url = "https://h:2083"\nftp_host = "h"\n'
               'ftp_user = "u"\nftp_port = 21\npublic_html_path = "/p/"\n')
    r = c162.run(str(hg))
    assert r.status == "pass" and "HostGator" in r.message
    bad = _site(tmp_path, "bad.test", 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "hostgator"\n')
    assert "unparseable" in c162.run(str(bad)).message


def test_check_warns_on_minimal_toml_and_passes_when_recorded(tmp_path):
    d = _site(tmp_path)
    r = c162.run(str(d))
    assert r.status == "warn" and "project fix" in r.message
    (d / "lamill.toml").write_text(MINIMAL_TOML + '\n[analytics]\nga4_id = "G-ABC123DEF4"\n')
    assert c162.run(str(d)).status == "pass"


def test_fix_adopts_single_source_id_and_preserves_file(tmp_path):
    toml = MINIMAL_TOML + '\n[content]\n# hand-written\nicp = "x"\n'
    d = _site(tmp_path, toml=toml)
    (d / "src" / "layouts" / "Base.astro").write_text('<script src="https://www.googletagmanager.com/gtag/js?id=G-41C0WXB0HR"></script>')
    assert c162._fix(d, dry_run=True, assume_yes=True).status == "would-fix"
    assert "[analytics]" not in (d / "lamill.toml").read_text()
    res = c162._fix(d, dry_run=False, assume_yes=True)
    assert res.status == "fixed" and "adopted G-41C0WXB0HR" in res.summary
    text = (d / "lamill.toml").read_text()
    assert 'ga4_id = "G-41C0WXB0HR"' in text and "# hand-written" in text
    assert c162._fix(d, dry_run=False, assume_yes=True).status == "nothing-to-do"


def test_fix_ignores_placeholder_and_flags_multiple_ids(tmp_path, monkeypatch):
    d = _site(tmp_path)
    (d / "src" / "a.ts").write_text('const id = "G-XXXXXXXXXX";')
    monkeypatch.setattr(ga4_admin, "has_token", lambda: False)
    assert c162._fix(d, dry_run=False, assume_yes=True).status == "manual"  # placeholder → falls to API → no token
    (d / "src" / "b.ts").write_text('"G-AAAA11111A" "G-BBBB22222B"')
    assert "several" in c162._fix(d, dry_run=False, assume_yes=True).summary


def _api_ready(monkeypatch, api: FakeGA4):
    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr("portfolio.apikeys.get_key", lambda k: FLEET if k == "GA4_ACCOUNT_ID" else None)
    monkeypatch.setattr(ga4_admin, "_client", lambda client=None: api.client())


def test_fix_creates_property_and_records_it(tmp_path, monkeypatch):
    api = FakeGA4()
    _api_ready(monkeypatch, api)
    d = _site(tmp_path, "fresh.test")
    assert c162._fix(d, dry_run=True, assume_yes=True).status == "would-fix"
    assert not any(c.startswith("POST") for c in api.calls)
    res = c162._fix(d, dry_run=False, assume_yes=True)
    assert res.status == "fixed" and "created" in res.summary
    assert c162.recorded_id(d).startswith("G-")
    assert c162.run(str(d)).status == "pass"


def test_fix_defers_property_in_other_account(tmp_path, monkeypatch):
    api = FakeGA4()
    api.add(OTHER, "civic.test", "https://civic.test", "G-HRTTQ9C448")
    _api_ready(monkeypatch, api)
    d = _site(tmp_path, "civic.test")
    res = c162._fix(d, dry_run=False, assume_yes=True)
    assert res.status == "manual" and "move it" in res.summary
    assert c162.recorded_id(d) is None


def test_fix_registered_in_tier1_registry():
    from portfolio import fix_registry
    fix_registry.reset_cache()
    assert fix_registry.get_tier_1("CHECK_162") is not None
