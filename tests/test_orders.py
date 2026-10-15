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


def test_list_open_orders_normalises_standard_and_algo_rows():
    class FakeClient:
        def get_open_orders(self, symbol=None):
            return [{"orderId": 5, "symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
                     "origQty": "0.1", "price": "60000", "stopPrice": "0", "status": "NEW"}]

        def get_open_algo_orders(self, symbol=None):
            # documented Algo API shape
            return [{"algoId": 2, "symbol": "BTCUSDT", "side": "SELL", "orderType": "STOP",
                     "quantity": "0.2", "price": "61000", "triggerPrice": "60500",
                     "algoStatus": "NEW"}]

    rows = OrderManager(FakeClient()).list_open_orders("btcusdt")
    assert [r["kind"] for r in rows] == ["algo", "standard"]  # numeric id order: 2 < 5
    algo, std = rows
    assert (algo["type"], algo["quantity"], algo["trigger"], algo["status"]) == ("STOP", "0.2", "60500", "NEW")
    assert (std["type"], std["quantity"], std["price"]) == ("LIMIT", "0.1", "60000")


# ── OrderManager behaviour against a scripted client ──────────────────


class ScriptedClient:
    def __init__(self):
        self.calls = []

    def place_order(self, params):
        self.calls.append(("place", params))
        return {"orderId": 1, "symbol": params["symbol"], "side": params["side"],
                "type": params["type"], "status": "NEW", "origQty": params["quantity"],
                "executedQty": "0", "price": params.get("price", "0")}

    def get_ticker_price(self, symbol):
        return {"symbol": symbol, "price": "123.45"}

    def get_account_info(self):
        return {"assets": [
            {"asset": "USDT", "walletBalance": "100.5", "unrealizedProfit": "1",
             "marginBalance": "101.5", "availableBalance": "90"},
            {"asset": "BNB", "walletBalance": "0"},
        ]}

    def cancel_order(self, symbol, order_id):
        self.calls.append(("cancel", symbol, order_id))
        from bot.exceptions import BinanceAPIError
        raise BinanceAPIError(-2011, "Unknown order sent.")

    def cancel_algo_order(self, symbol, algo_id):
        self.calls.append(("cancel_algo", symbol, algo_id))
        return {"code": "200", "msg": "success"}

    def get_open_orders(self, symbol=None):
        return [{"orderId": 1}]

    def get_open_algo_orders(self, symbol=None):
        return [{"algoId": 2}]


def test_cancel_falls_back_to_algo_endpoint_on_unknown_order():
    client = ScriptedClient()
    OrderManager(client).cancel_order("btcusdt", 99)
    assert client.calls == [("cancel", "BTCUSDT", 99), ("cancel_algo", "BTCUSDT", 99)]


def test_cancel_reraises_other_api_errors():
    from bot.exceptions import BinanceAPIError

    class Client(ScriptedClient):
        def cancel_order(self, symbol, order_id):
            raise BinanceAPIError(-1121, "Invalid symbol.")

    with pytest.raises(BinanceAPIError):
        OrderManager(Client()).cancel_order("X", 1)


def test_get_current_price_and_balances_skip_zero_assets():
    manager = OrderManager(ScriptedClient())
    assert manager.get_current_price("btcusdt") == Decimal("123.45")
    balances = manager.get_account_balances()
    assert [b["asset"] for b in balances] == ["USDT"]
    assert balances[0]["available_balance"] == "90"


def test_get_open_orders_merges_standard_and_algo():
    assert OrderManager(ScriptedClient()).get_open_orders("btcusdt") == [{"orderId": 1}, {"algoId": 2}]


def test_place_order_runs_validation_then_sends_params():
    client = ScriptedClient()
    manager = OrderManager(client)
    manager._validator.validate_order = lambda req: req  # exchange rules tested elsewhere
    req = OrderRequest(symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.LIMIT,
                       quantity=Decimal("0.5"), price=Decimal("100"))
    resp = manager.place_order(req)
    assert resp.order_id == 1 and resp.is_active and not resp.is_filled
    assert client.calls[0][1]["timeInForce"] == "GTC"


def test_unsupported_order_type_is_rejected():
    from bot.exceptions import ValidationError

    manager = OrderManager(ScriptedClient())

    class Fake:
        order_type = type("T", (), {"value": "TRAILING"})()

    with pytest.raises(ValidationError, match="Unsupported"):
        manager._build_params(Fake())
