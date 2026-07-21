import pytest
from decimal import Decimal

from bot.orders import OrderManager
from bot.models import OrderRequest, OrderType, OrderSide, TimeInForce

# Dummy client to pass to OrderManager
class DummyClient:
    pass

def test_build_market_params():
    manager = OrderManager(DummyClient())
    req = OrderRequest(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.01")
    )
    params = manager._build_params(req)
    assert params["symbol"] == "BTCUSDT"
    assert params["side"] == "BUY"
    assert params["type"] == "MARKET"
    assert params["quantity"] == "0.01"
    assert "price" not in params

def test_build_limit_params():
    manager = OrderManager(DummyClient())
    req = OrderRequest(
        symbol="ETHUSDT",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1.5"),
        price=Decimal("3500"),
        time_in_force=TimeInForce.GTC
    )
    params = manager._build_params(req)
    assert params["symbol"] == "ETHUSDT"
    assert params["side"] == "SELL"
    assert params["type"] == "LIMIT"
    assert params["quantity"] == "1.5"
    assert params["price"] == "3500"
    assert params["timeInForce"] == "GTC"

def test_build_stop_limit_params():
    manager = OrderManager(DummyClient())
    req = OrderRequest(
        symbol="SOLUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.STOP,
        quantity=Decimal("5"),
        price=Decimal("150"),
        stop_price=Decimal("145")
    )
    params = manager._build_params(req)
    assert params["symbol"] == "SOLUSDT"
    assert params["side"] == "BUY"
    assert params["type"] == "STOP"
    assert params["quantity"] == "5"
    assert params["price"] == "150"
    assert params["triggerPrice"] == "145"
    assert params["timeInForce"] == "GTC"
