import pytest
import httpx
from bot.client import BinanceClient
from bot.exceptions import BinanceAPIError, RateLimitError, InsufficientBalanceError

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
