"""v35.B — tests for the shared httpx lifecycle + error taxonomy (`_httpapi`)."""
from __future__ import annotations

import httpx
import pytest

from portfolio import _httpapi
from portfolio._httpapi import (
    HttpApiError,
    PermanentHTTPError,
    TransientHTTPError,
    classify_status,
    managed_client,
    raise_for,
    status_is_transient,
    transient_network_errors,
)


# ---- taxonomy ----------------------------------------------------------


def test_transient_and_permanent_are_httpapierror_and_runtimeerror():
    # Backward-compat: existing `except RuntimeError` / base handlers still catch.
    assert issubclass(TransientHTTPError, HttpApiError)
    assert issubclass(PermanentHTTPError, HttpApiError)
    assert issubclass(HttpApiError, RuntimeError)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retryable_statuses_are_transient(status):
    assert status_is_transient(status) is True
    assert classify_status(status) is TransientHTTPError


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 418])
def test_other_4xx_are_permanent(status):
    assert status_is_transient(status) is False
    assert classify_status(status) is PermanentHTTPError


# ---- managed_client ----------------------------------------------------


def test_managed_client_closes_a_built_client():
    closed = {"n": 0}

    class _Spy(httpx.Client):
        def close(self):
            closed["n"] += 1
            super().close()

    with managed_client(None, lambda: _Spy()) as c:
        assert isinstance(c, httpx.Client)
    assert closed["n"] == 1


def test_managed_client_does_not_close_a_supplied_client():
    closed = {"n": 0}

    class _Spy(httpx.Client):
        def close(self):
            closed["n"] += 1
            super().close()

    supplied = _Spy()
    with managed_client(supplied, lambda: pytest.fail("factory must not run")) as c:
        assert c is supplied
    assert closed["n"] == 0  # caller owns it
    supplied.close()


def test_managed_client_closes_built_client_on_exception():
    closed = {"n": 0}

    class _Spy(httpx.Client):
        def close(self):
            closed["n"] += 1
            super().close()

    with pytest.raises(ValueError):
        with managed_client(None, lambda: _Spy()):
            raise ValueError("boom")
    assert closed["n"] == 1


# ---- transient_network_errors -----------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("slow"),
        httpx.ReadTimeout("slow"),
        httpx.ConnectError("refused"),
    ],
)
def test_network_errors_map_to_transient(exc):
    with pytest.raises(TransientHTTPError) as ei:
        with transient_network_errors("GET /x"):
            raise exc
    assert "GET /x" in str(ei.value)


def test_transient_network_errors_passes_through_non_network():
    # A response-level error inside the block is NOT a network error → re-raised as-is.
    with pytest.raises(PermanentHTTPError):
        with transient_network_errors("GET /x"):
            raise PermanentHTTPError("403")


def test_transient_network_errors_noop_on_success():
    with transient_network_errors("GET /x"):
        pass  # no raise


# ---- raise_for ---------------------------------------------------------


def _resp(status: int, body: str = "") -> httpx.Response:
    return httpx.Response(status_code=status, text=body)


def test_raise_for_silent_on_2xx():
    raise_for(_resp(200, "ok"), "GET /x")  # no raise
    raise_for(_resp(204), "GET /x")


def test_raise_for_permanent_on_4xx():
    with pytest.raises(PermanentHTTPError) as ei:
        raise_for(_resp(403, "forbidden"), "GET /x")
    assert "HTTP 403" in str(ei.value)
    assert "forbidden" in str(ei.value)


def test_raise_for_transient_on_429_and_5xx():
    with pytest.raises(TransientHTTPError):
        raise_for(_resp(429, "slow down"), "GET /x")
    with pytest.raises(TransientHTTPError):
        raise_for(_resp(503, "unavailable"), "GET /x")


def test_raise_for_uses_provider_classes():
    class MyError(HttpApiError):
        pass

    class MyTransient(MyError, TransientHTTPError):
        pass

    with pytest.raises(MyError):  # permanent → provider permanent class
        raise_for(_resp(401), "GET /x", transient_cls=MyTransient, permanent_cls=MyError)
    with pytest.raises(MyTransient):  # 429 → provider transient class (also MyError)
        raise_for(_resp(429), "GET /x", transient_cls=MyTransient, permanent_cls=MyError)


def test_raise_for_truncates_body():
    with pytest.raises(PermanentHTTPError) as ei:
        raise_for(_resp(400, "z" * 1000), "GET /path", body_chars=50)
    assert str(ei.value).count("z") == 50
