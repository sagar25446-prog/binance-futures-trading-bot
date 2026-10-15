from unittest.mock import patch

import httpx
import pytest

from bot.client import BinanceClient
from bot.config import Settings
from bot.exceptions import BinanceAPIError, InsufficientBalanceError, RateLimitError


def test_handle_api_error_rate_limit():
    data = {"code": -1015, "msg": "Too many requests"}
    response = httpx.Response(429, headers={"Retry-After": "120"})
    with pytest.raises(RateLimitError) as exc:
        BinanceClient._handle_api_error(data, 429, response)
    assert exc.value.retry_after == 120

def test_handle_api_error_insufficient_balance():
    data = {"code": -2019, "msg": "Insufficient balance"}
    response = httpx.Response(400)
    with pytest.raises(InsufficientBalanceError) as exc:
        BinanceClient._handle_api_error(data, 400, response)
    assert exc.value.code == -2019

def test_handle_api_error_generic():
    data = {"code": -1013, "msg": "Filter failure: LOT_SIZE"}
    response = httpx.Response(400)
    with pytest.raises(BinanceAPIError) as exc:
        BinanceClient._handle_api_error(data, 400, response)
    assert exc.value.code == -1013
    assert "LOT_SIZE" in exc.value.message

@patch("time.sleep")
def test_network_retry_logic(mock_sleep):
    """Test that NetworkError is raised on failure, but retries work on transient errors."""
    settings = Settings(
        api_key="test_key",
        api_secret="test_secret",
        max_retries=3,
        retry_delay=0.1
    )
    client = BinanceClient(settings)

    mock_response = httpx.Response(200, json={"success": True})

    with patch.object(client._client, "request", side_effect=[
        httpx.ConnectError("Connection refused"),
        httpx.TimeoutException("Timeout"),
        mock_response
    ]) as mock_request:
        result = client._make_request("GET", "/test")

        # It should succeed on the 3rd attempt
        assert result == {"success": True}
        assert mock_request.call_count == 3
        assert mock_sleep.call_count == 2


# ── Retry safety, resync and error handling ───────────────────────────


def _client(**overrides):
    kwargs = dict(api_key="test_key", api_secret="test_secret", max_retries=3, retry_delay=0.0)
    kwargs.update(overrides)
    return BinanceClient(Settings(**kwargs))


@patch("time.sleep")
def test_post_is_not_retried_after_ambiguous_read_timeout(_sleep):
    """A read timeout on POST may mean the order was placed: never resend it."""
    from bot.exceptions import NetworkError

    client = _client()
    with patch.object(
        client._client, "request", side_effect=httpx.ReadTimeout("slow")
    ) as mock_request:
        with pytest.raises(NetworkError, match="outcome is unknown"):
            client._make_request("POST", "/fapi/v1/order", params={"symbol": "BTCUSDT"})
    assert mock_request.call_count == 1


@patch("time.sleep")
def test_post_is_retried_when_connection_never_established(_sleep):
    client = _client()
    ok = httpx.Response(200, json={"orderId": 1})
    with patch.object(
        client._client, "request", side_effect=[httpx.ConnectError("refused"), ok]
    ) as mock_request:
        assert client._make_request("POST", "/fapi/v1/order") == {"orderId": 1}
    assert mock_request.call_count == 2


@patch("time.sleep")
def test_get_retries_on_5xx_then_raises_network_error(_sleep):
    from bot.exceptions import NetworkError

    client = _client()
    bad = httpx.Response(503, json={"msg": "unavailable"})
    with patch.object(client._client, "request", return_value=bad) as mock_request:
        with pytest.raises(NetworkError, match="HTTP 503"):
            client._make_request("GET", "/fapi/v1/time", signed=False)
    assert mock_request.call_count == 3


def test_post_5xx_is_surfaced_not_retried():
    """On POST a 5xx means 'execution status unknown' - surface it, don't resend."""
    client = _client()
    bad = httpx.Response(503, json={"code": -1007, "msg": "Timeout waiting for response"})
    with patch.object(client._client, "request", return_value=bad) as mock_request:
        with pytest.raises(BinanceAPIError) as exc:
            client._make_request("POST", "/fapi/v1/order")
    assert exc.value.code == -1007
    assert mock_request.call_count == 1


def test_timestamp_error_triggers_single_resync_and_retry():
    client = _client()
    stale = httpx.Response(400, json={"code": -1021, "msg": "Timestamp outside recvWindow"})
    ok = httpx.Response(200, json={"ok": True})
    with patch.object(client._client, "request", side_effect=[stale, ok]), patch.object(
        client, "sync_time", return_value=0
    ) as mock_sync:
        assert client._make_request("GET", "/fapi/v2/account") == {"ok": True}
    mock_sync.assert_called_once()


def test_timestamp_error_resyncs_only_once():
    client = _client()
    stale = httpx.Response(400, json={"code": -1021, "msg": "Timestamp outside recvWindow"})
    with patch.object(client._client, "request", return_value=stale), patch.object(
        client, "sync_time", return_value=0
    ) as mock_sync:
        with pytest.raises(BinanceAPIError) as exc:
            client._make_request("GET", "/fapi/v2/account")
    assert exc.value.code == -1021
    mock_sync.assert_called_once()


def test_non_json_error_page_becomes_api_error():
    client = _client()
    html = httpx.Response(502, text="<html>Bad Gateway</html>")
    with patch.object(client._client, "request", return_value=html):
        with pytest.raises(BinanceAPIError, match="non-JSON"):
            client._make_request("POST", "/fapi/v1/order")


def test_http_429_without_binance_code_is_rate_limit():
    response = httpx.Response(429, headers={"Retry-After": "7"})
    with pytest.raises(RateLimitError) as exc:
        BinanceClient._handle_api_error({}, 429, response)
    assert exc.value.retry_after == 7


@pytest.mark.parametrize(
    "header, expected",
    [(None, 60), ("12", 12), ("garbage", 60), ("-5", 0)],
)
def test_retry_after_parsing(header, expected):
    headers = {"Retry-After": header} if header is not None else {}
    assert BinanceClient._retry_after_seconds(httpx.Response(429, headers=headers)) == expected


def test_retry_after_accepts_http_date():
    response = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert BinanceClient._retry_after_seconds(response) == 0  # date in the past


def test_place_order_does_not_mutate_callers_dict():
    client = _client()
    original = {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "1"}
    snapshot = dict(original)
    with patch.object(client, "_make_request", return_value={"orderId": 1}):
        client.place_order(original)
    assert original == snapshot


def test_normalize_algo_response_documented_shape():
    """Fields exactly as documented for POST /fapi/v1/algoOrder."""
    raw = {
        "algoId": 2146760,
        "clientAlgoId": "abc",
        "orderType": "STOP",
        "quantity": "0.01",
        "algoStatus": "NEW",
        "triggerPrice": "750.000",
        "price": "751.000",
    }
    out = BinanceClient._normalize_algo_response(raw, {"type": "STOP"})
    assert out["orderId"] == 2146760
    assert out["clientOrderId"] == "abc"
    assert out["type"] == "STOP"
    assert out["origQty"] == "0.01"
    assert out["status"] == "NEW"
    assert out["stopPrice"] == "750.000"
    assert out["executedQty"] == "0"


def test_normalize_algo_response_prefers_values_binance_sent():
    raw = {"algoId": 1, "origQty": "5", "quantity": "9", "status": "NEW", "algoStatus": "X"}
    out = BinanceClient._normalize_algo_response(raw, {"type": "STOP", "quantity": "1"})
    assert out["origQty"] == "5"
    assert out["status"] == "NEW"


def test_normalize_algo_response_falls_back_to_request_params():
    out = BinanceClient._normalize_algo_response(
        {"algoId": 1}, {"type": "TAKE_PROFIT", "quantity": "2", "price": "10"}
    )
    assert (out["type"], out["origQty"], out["price"]) == ("TAKE_PROFIT", "2", "10")
