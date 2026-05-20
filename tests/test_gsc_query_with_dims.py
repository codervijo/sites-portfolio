"""Tests for v16.B — gsc.query_with_dims dimension-aware helper."""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from portfolio.gsc import DEFAULT_DAYS, DEFAULT_LAG_DAYS, query_with_dims


def _fake_service(response_rows: list[dict]):
    """Build a MagicMock GSC service that returns `response_rows`."""
    service = MagicMock()
    service.searchanalytics().query().execute.return_value = {
        "rows": response_rows,
    }
    return service


def _captured_body(service) -> dict:
    """Return the body dict passed to the last .query(body=...) call.

    `service.searchanalytics().query` is a MagicMock — `call_args.kwargs`
    holds the kwargs of the latest call."""
    call_args = service.searchanalytics().query.call_args
    return call_args.kwargs["body"]


def test_returns_typed_rows():
    service = _fake_service([
        {"keys": ["ev charger cost"], "clicks": 4, "impressions": 156,
         "ctr": 0.025, "position": 8.2},
        {"keys": ["motorhome hire seattle"], "clicks": 3, "impressions": 89,
         "ctr": 0.033, "position": 12.1},
    ])
    rows = query_with_dims(
        service, "https://example.com/",
        dimensions=["query"], row_limit=10,
    )
    assert len(rows) == 2
    assert rows[0]["keys"] == ["ev charger cost"]
    assert rows[0]["clicks"] == 4
    assert rows[0]["impressions"] == 156
    assert rows[0]["ctr"] == 0.025
    assert rows[0]["position"] == 8.2


def test_sends_expected_body_shape():
    service = _fake_service([])
    query_with_dims(
        service, "https://example.com/",
        days=28, dimensions=["query", "page"], row_limit=50,
    )
    body = _captured_body(service)
    assert body["dimensions"] == ["query", "page"]
    assert body["rowLimit"] == 50
    # Date range: end = today - lag_days; start = end - days.
    expected_end = date.today() - timedelta(days=DEFAULT_LAG_DAYS)
    expected_start = expected_end - timedelta(days=28)
    assert body["startDate"] == expected_start.isoformat()
    assert body["endDate"] == expected_end.isoformat()


def test_empty_rows_returns_empty_list():
    service = _fake_service([])
    rows = query_with_dims(
        service, "https://example.com/",
        dimensions=["query"], row_limit=10,
    )
    assert rows == []


def test_missing_position_field_returns_none():
    """GSC sometimes omits `position` when no impressions in the slice."""
    service = _fake_service([
        {"keys": ["no-data"], "clicks": 0, "impressions": 0, "ctr": 0.0},
    ])
    rows = query_with_dims(
        service, "https://example.com/",
        dimensions=["query"], row_limit=10,
    )
    assert rows[0]["position"] is None


def test_handles_multi_dim_keys():
    """When multiple dimensions, GSC returns one key per dim in order."""
    service = _fake_service([
        {"keys": ["ev charger cost", "https://example.com/blog/post1"],
         "clicks": 4, "impressions": 156, "ctr": 0.025, "position": 8.2},
    ])
    rows = query_with_dims(
        service, "https://example.com/",
        dimensions=["query", "page"], row_limit=10,
    )
    assert rows[0]["keys"] == [
        "ev charger cost", "https://example.com/blog/post1"
    ]


def test_default_days_and_lag_days():
    service = _fake_service([])
    query_with_dims(
        service, "https://example.com/",
        dimensions=["query"], row_limit=10,
    )
    body = _captured_body(service)
    expected_end = date.today() - timedelta(days=DEFAULT_LAG_DAYS)
    expected_start = expected_end - timedelta(days=DEFAULT_DAYS)
    assert body["startDate"] == expected_start.isoformat()
    assert body["endDate"] == expected_end.isoformat()


def test_lag_days_override():
    service = _fake_service([])
    query_with_dims(
        service, "https://example.com/",
        days=7, dimensions=["query"], row_limit=10, lag_days=0,
    )
    body = _captured_body(service)
    expected_end = date.today()
    assert body["endDate"] == expected_end.isoformat()
