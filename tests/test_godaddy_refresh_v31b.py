"""v31.B — GoDaddy inventory refresh: fetch_inventory + refresh_godaddy_csv."""
from __future__ import annotations

import csv

import httpx

from portfolio import godaddy


def _client(handler):
    return httpx.Client(base_url=godaddy.API_BASE, transport=httpx.MockTransport(handler))


def _api(domains, *, ns_in_summary=True):
    """Handler: /v1/domains → summaries; /v1/domains/{d} → detail."""
    def handler(req):
        p = req.url.path
        if p == "/v1/domains":
            summ = []
            for d in domains:
                row = {"domain": d["domain"], "status": d.get("status", "ACTIVE"),
                       "expires": d.get("expires"), "renewAuto": d.get("renewAuto", True)}
                if ns_in_summary:
                    row["nameServers"] = d.get("nameServers", [])
                summ.append(row)
            return httpx.Response(200, json=summ)
        dom = p.rsplit("/", 1)[-1]
        d = next((x for x in domains if x["domain"] == dom), None)
        if d is None:
            return httpx.Response(404)
        return httpx.Response(200, json={
            "domain": dom, "nameServers": d.get("nameServers", []),
            "status": d.get("status", "ACTIVE"), "expires": d.get("expires"),
            "renewAuto": d.get("renewAuto", True)})
    return handler


def test_fetch_inventory_uses_summary():
    doms = [{"domain": "a.com", "expires": "2027-01-01T00:00:00Z",
             "renewAuto": True, "nameServers": ["ns1.cf", "ns2.cf"]}]
    inv = godaddy.fetch_inventory("K", "S", client=_client(_api(doms)))
    assert inv[0]["domain"] == "a.com" and inv[0]["nameServers"] == ["ns1.cf", "ns2.cf"]


def test_fetch_inventory_filters_cancelled():
    doms = [
        {"domain": "live.com", "status": "ACTIVE", "expires": "2027-01-01T00:00:00Z", "nameServers": ["ns1.cf"]},
        {"domain": "dead.com", "status": "CANCELLED", "expires": "2013-01-01T00:00:00Z", "nameServers": []},
    ]
    inv = godaddy.fetch_inventory("K", "S", client=_client(_api(doms)))
    assert [d["domain"] for d in inv] == ["live.com"]
    inv_all = godaddy.fetch_inventory("K", "S", client=_client(_api(doms)), active_only=False)
    assert len(inv_all) == 2


def test_fetch_inventory_falls_back_to_detail_for_ns():
    doms = [{"domain": "a.com", "expires": "2027-01-01T00:00:00Z",
             "renewAuto": True, "nameServers": ["ns1.cf"]}]
    inv = godaddy.fetch_inventory("K", "S", client=_client(_api(doms, ns_in_summary=False)))
    assert inv[0]["nameServers"] == ["ns1.cf"]


def test_refresh_merges_preserving_manual_columns(tmp_path):
    csv_path = tmp_path / "godaddy.csv"
    csv_path.write_text(
        "Domain Name,TLD,Expiration Date,Status,Auto-renew,Nameservers,Renewal Price,Estimated Value\n"
        "a.com,.com,2025-01-01,Active,Off,old.ns old2.ns,$ 19.99,$ 500.00\n"
    )
    doms = [{"domain": "a.com", "expires": "2027-06-06T00:00:00Z", "renewAuto": True,
             "nameServers": ["ns1.cf", "ns2.cf"], "status": "ACTIVE"}]
    n = godaddy.refresh_godaddy_csv("K", "S", csv_path, client=_client(_api(doms)))
    assert n == 1
    r = list(csv.DictReader(csv_path.open()))[0]
    # dynamic fields refreshed from the API
    assert r["Expiration Date"] == "2027-06-06"
    assert r["Auto-renew"] == "On"
    assert r["Nameservers"] == "ns1.cf ns2.cf"
    # manual-only columns preserved
    assert r["Renewal Price"] == "$ 19.99"
    assert r["Estimated Value"] == "$ 500.00"


def test_refresh_adds_new_and_drops_removed(tmp_path):
    csv_path = tmp_path / "godaddy.csv"
    csv_path.write_text(
        "Domain Name,TLD,Expiration Date,Auto-renew,Nameservers\n"
        "old.com,.com,2025-01-01,On,x.ns\n"
    )
    doms = [{"domain": "new.com", "expires": "2027-01-01T00:00:00Z",
             "renewAuto": True, "nameServers": ["ns1.cf"]}]
    godaddy.refresh_godaddy_csv("K", "S", csv_path, client=_client(_api(doms)))
    names = [r["Domain Name"] for r in csv.DictReader(csv_path.open())]
    assert "old.com" not in names and "new.com" in names


def test_refresh_fresh_file_uses_min_header(tmp_path):
    csv_path = tmp_path / "godaddy.csv"
    doms = [{"domain": "a.com", "expires": "2027-01-01T00:00:00Z",
             "renewAuto": False, "nameServers": ["ns1.cf"]}]
    godaddy.refresh_godaddy_csv("K", "S", csv_path, client=_client(_api(doms)))
    r = list(csv.DictReader(csv_path.open()))[0]
    assert r["Domain Name"] == "a.com" and r["Auto-renew"] == "Off"
    assert "Renewal Price" in r  # _MIN_HEADER carries the preserved columns
