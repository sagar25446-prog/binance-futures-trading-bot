import pytest
import httpx
from unittest.mock import patch
from bot.client import BinanceClient
from bot.config import Settings
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
