"""
Integration tests for Binance Futures trading bot
Focuses on OrderManager and BinanceClient end-to-end interactions with mocked network calls.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from bot.client import BinanceClient
from bot.config import Settings
from bot.models import OrderRequest, OrderSide, OrderType, OrderResponse
from bot.orders import OrderManager


@pytest.fixture
def mock_settings():
    return Settings(
        api_key="test_key",
        api_secret="test_secret",
        base_url="https://testnet.binancefuture.com",
    )


@pytest.fixture
def client(mock_settings):
    with BinanceClient(mock_settings) as c:
        yield c


@pytest.fixture
def order_manager(client):
    return OrderManager(client)


def test_order_manager_place_market_order_e2e(order_manager, client):
    """
    Test OrderManager.place_order() end-to-end for a standard MARKET order.
    Verifies that the correct fields are passed and a valid OrderResponse is returned.
    """
    request = OrderRequest(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1")
    )
    
    mock_response = {
        "orderId": 12345,
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "status": "NEW",
        "origQty": "0.1",
        "executedQty": "0",
        "price": "0",
        "avgPrice": "0"
    }

    with patch.object(order_manager._validator, 'validate_order') as mock_validate, \
         patch.object(client, 'place_order', return_value=mock_response) as mock_place_order:
        
        response = order_manager.place_order(request)
        
        mock_validate.assert_called_once_with(request)
        mock_place_order.assert_called_once_with({
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.1"
        })
        
        assert isinstance(response, OrderResponse)
        assert response.order_id == 12345
        assert response.status == "NEW"
        assert response.order_type == "MARKET"


def test_order_manager_place_stop_order_e2e(order_manager, client):
    """
    Test OrderManager.place_order() end-to-end for a STOP order.
    Verifies that STOP orders are processed properly and algorithms respond correctly.
    """
    request = OrderRequest(
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.STOP,
        quantity=Decimal("1.5"),
        price=Decimal("2000"),
        stop_price=Decimal("1900")
    )

    mock_raw_response = {
        "algoId": 98765,
        "symbol": "ETHUSDT",
        "side": "SELL",
        "type": "STOP",
        "origQty": "1.5",
        "price": "2000",
        "stopPrice": "1900"
    }
    
    with patch.object(order_manager._validator, 'validate_order') as mock_validate, \
         patch.object(client, '_make_request', return_value=mock_raw_response) as mock_make_request:
        
        response = order_manager.place_order(request)
        
        mock_validate.assert_called_once_with(request)
        mock_make_request.assert_called_once_with(
            "POST",
            "/fapi/v1/algoOrder",
            params={
                "symbol": "ETHUSDT",
                "side": "SELL",
                "type": "STOP",
                "quantity": "1.5",
                "price": "2000",
                "triggerPrice": "1900",
                "timeInForce": "GTC",
                "newOrderRespType": "RESULT",
                "algoType": "CONDITIONAL"
            }
        )
        
        assert isinstance(response, OrderResponse)
        assert response.order_id == 98765
        assert response.status == "NEW"
        assert response.order_type == "STOP"
        assert response.executed_qty == "0"


def test_binance_client_place_order_routing(client):
    """
    Test BinanceClient.place_order() algo endpoint routing.
    Verifies MARKET and LIMIT go to /fapi/v1/order and STOP/TAKE_PROFIT go to /fapi/v1/algoOrder.
    """
    with patch.object(client, '_make_request') as mock_make_request:
        # MARKET
        mock_make_request.return_value = {"orderId": 1}
        client.place_order({"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "1"})
        mock_make_request.assert_called_with(
            "POST", "/fapi/v1/order", params={"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET", "quantity": "1", "newOrderRespType": "RESULT"}
        )
        
        # LIMIT
        mock_make_request.return_value = {"orderId": 2}
        client.place_order({"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "1", "price": "100"})
        mock_make_request.assert_called_with(
            "POST", "/fapi/v1/order", params={"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "quantity": "1", "price": "100", "newOrderRespType": "RESULT"}
        )
        
        # STOP
        mock_make_request.return_value = {"algoId": 3}
        client.place_order({"symbol": "BTCUSDT", "side": "BUY", "type": "STOP", "quantity": "1", "price": "100", "stopPrice": "90"})
        mock_make_request.assert_called_with(
            "POST", "/fapi/v1/algoOrder", params={"symbol": "BTCUSDT", "side": "BUY", "type": "STOP", "quantity": "1", "price": "100", "stopPrice": "90", "newOrderRespType": "RESULT", "algoType": "CONDITIONAL"}
        )
        
        # TAKE_PROFIT
        mock_make_request.return_value = {"algoId": 4}
        client.place_order({"symbol": "BTCUSDT", "side": "SELL", "type": "TAKE_PROFIT", "quantity": "1", "price": "100", "stopPrice": "110"})
        mock_make_request.assert_called_with(
            "POST", "/fapi/v1/algoOrder", params={"symbol": "BTCUSDT", "side": "SELL", "type": "TAKE_PROFIT", "quantity": "1", "price": "100", "stopPrice": "110", "newOrderRespType": "RESULT", "algoType": "CONDITIONAL"}
        )


def test_binance_client_place_order_normalization(client):
    """
    Test BinanceClient.place_order() response normalization for algo orders.
    Verifies that missing fields (executedQty, status, type, orderId) are filled in.
    """
    mock_raw_response = {
        "algoId": 555,
        "symbol": "BTCUSDT",
        "side": "BUY"
    }
    
    with patch.object(client, '_make_request', return_value=mock_raw_response):
        result = client.place_order({"symbol": "BTCUSDT", "side": "BUY", "type": "STOP"})
        
        assert result["orderId"] == 555
        assert result["algoId"] == 555
        assert result["executedQty"] == "0"
        assert result["status"] == "NEW"
        assert result["type"] == "STOP"
