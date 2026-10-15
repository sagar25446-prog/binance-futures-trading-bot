"""End-to-end HTTP-layer tests using httpx.MockTransport (no real network)."""

import hashlib
import hmac
from urllib.parse import parse_qsl

import httpx
import pytest

from bot.client import BinanceClient
from bot.config import Settings
from bot.exceptions import BinanceAPIError

SECRET = "s3cret"


def make_client(handler, **kw):
    settings = Settings(api_key="KEY123", api_secret=SECRET, retry_delay=0.0, **kw)
    client = BinanceClient(settings)
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        headers={"X-MBX-APIKEY": settings.api_key},
    )
    return client


def _raw_query(request: httpx.Request) -> str:
    """Raw query (GET/DELETE) or form body (POST) exactly as sent on the wire."""
    return request.url.query.decode() or request.content.decode()


def assert_validly_signed(request: httpx.Request) -> dict:
    raw = _raw_query(request)
    signed_part, sep, signature = raw.rpartition("&signature=")
    assert sep, "signature must be the LAST parameter"
    expected = hmac.new(SECRET.encode(), signed_part.encode(), hashlib.sha256).hexdigest()
    assert signature == expected
    fields = dict(parse_qsl(signed_part))
    assert "timestamp" in fields and "recvWindow" in fields
    return fields


def test_signed_get_has_valid_signature_and_api_key_header():
    seen = {}

    def handler(request):
        seen["req"] = request
        return httpx.Response(200, json={"assets": []})

    make_client(handler)._make_request("GET", "/fapi/v2/account")
    assert seen["req"].headers["X-MBX-APIKEY"] == "KEY123"
    assert_validly_signed(seen["req"])


def test_signed_post_sends_signature_in_form_body_not_url():
    seen = {}

    def handler(request):
        seen["req"] = request
        return httpx.Response(200, json={"orderId": 1, "status": "NEW"})

    make_client(handler).place_order(
        {"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.01"}
    )
    req = seen["req"]
    assert req.method == "POST" and req.url.path == "/fapi/v1/order"
    assert req.url.query == b""  # secrets/signature never in the URL
    fields = assert_validly_signed(req)
    assert fields["newOrderRespType"] == "RESULT"


def test_unsigned_request_carries_no_signature():
    seen = {}

    def handler(request):
        seen["req"] = request
        return httpx.Response(200, json={"serverTime": 1_700_000_000_000})

    make_client(handler)._make_request("GET", "/fapi/v1/time", signed=False)
    assert b"signature" not in seen["req"].url.query
    assert b"timestamp" not in seen["req"].url.query


def test_sync_time_applies_offset_to_later_timestamps(monkeypatch):
    monkeypatch.setattr("time.time", lambda: 1_000.0)  # local clock = 1_000_000 ms
    stamps = []

    def handler(request):
        if request.url.path == "/fapi/v1/time":
            return httpx.Response(200, json={"serverTime": 1_005_000})  # +5s ahead
        stamps.append(int(dict(parse_qsl(request.url.query.decode()))["timestamp"]))
        return httpx.Response(200, json={})

    client = make_client(handler)
    assert client.sync_time() == 5_000
    client._make_request("GET", "/fapi/v2/account")
    assert stamps == [1_005_000]


def test_public_endpoints_hit_expected_paths_and_methods():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, dict(parse_qsl(request.url.query.decode()))))
        return httpx.Response(200, json=[] if "open" in request.url.path.lower() else {"price": "1", "symbols": []})

    c = make_client(handler)
    c.get_exchange_info()
    c.get_ticker_price("btcusdt")
    c.get_account_info()
    c.get_open_orders("ethusdt")
    c.get_open_orders()
    c.get_open_algo_orders("ethusdt")
    c.cancel_order("btcusdt", 7)
    c.cancel_algo_order("btcusdt", 8)

    by_path = [(m, p) for m, p, _ in calls]
    assert by_path == [
        ("GET", "/fapi/v1/exchangeInfo"),
        ("GET", "/fapi/v1/ticker/price"),
        ("GET", "/fapi/v2/account"),
        ("GET", "/fapi/v1/openOrders"),
        ("GET", "/fapi/v1/openOrders"),
        ("GET", "/fapi/v1/openAlgoOrders"),
        ("DELETE", "/fapi/v1/order"),
        ("DELETE", "/fapi/v1/algoOrder"),
    ]
    assert calls[1][2]["symbol"] == "BTCUSDT"      # symbols upper-cased
    assert calls[3][2]["symbol"] == "ETHUSDT"
    assert "symbol" not in calls[4][2]             # no filter when omitted
    assert calls[7][2]["algoId"] == "8"


def test_algo_order_end_to_end_with_documented_response_shape():
    def handler(request):
        assert request.url.path == "/fapi/v1/algoOrder"
        fields = assert_validly_signed(request)
        assert fields["algoType"] == "CONDITIONAL" and fields["triggerPrice"] == "199000"
        return httpx.Response(200, json={
            "algoId": 3000000000003505, "clientAlgoId": "c1", "algoType": "CONDITIONAL",
            "orderType": "STOP", "symbol": "BTCUSDT", "side": "BUY", "quantity": "0.001",
            "algoStatus": "NEW", "triggerPrice": "199000.0", "price": "200000.0",
        })

    result = make_client(handler).place_order({
        "symbol": "BTCUSDT", "side": "BUY", "type": "STOP", "quantity": "0.001",
        "price": "200000", "triggerPrice": "199000", "timeInForce": "GTC",
    })
    from bot.models import OrderResponse

    parsed = OrderResponse(**result)
    assert parsed.order_id == 3000000000003505
    assert parsed.quantity == "0.001" and parsed.status == "NEW"
    assert parsed.stop_price == "199000.0"


def test_api_error_payload_is_raised_with_code():
    def handler(request):
        return httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})

    with pytest.raises(BinanceAPIError) as exc:
        make_client(handler).get_ticker_price("NOPE")
    assert exc.value.code == -1121


def test_unsupported_http_method():
    with pytest.raises(ValueError, match="Unsupported"):
        make_client(lambda r: httpx.Response(200, json={}))._make_request("PUT", "/x")


def test_context_manager_closes_http_client():
    with BinanceClient(Settings(api_key="k", api_secret="s")) as c:
        inner = c._client
    assert inner.is_closed
