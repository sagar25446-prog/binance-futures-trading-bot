"""ExchangeValidator end-to-end rules, driven by a fake exchangeInfo payload."""

from decimal import Decimal

import pytest

from bot.exceptions import ValidationError
from bot.models import OrderRequest, OrderSide, OrderType, SymbolInfo
from bot.validators import ExchangeValidator


def _symbol(symbol="BTCUSDT", status="TRADING", **over):
    data = {
        "symbol": symbol, "status": status, "baseAsset": symbol[:-4], "quoteAsset": "USDT",
        "pricePrecision": 2, "quantityPrecision": 3,
        "filters": [
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
            {"filterType": "PRICE_FILTER", "minPrice": "10", "maxPrice": "1000000", "tickSize": "0.1"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"},
        ],
    }
    data.update(over)
    return data


class FakeClient:
    def __init__(self, symbols):
        self.symbols = symbols
        self.exchange_info_calls = 0

    def get_exchange_info(self):
        self.exchange_info_calls += 1
        return {"symbols": self.symbols}


@pytest.fixture
def validator():
    return ExchangeValidator(FakeClient([_symbol(), _symbol("ETHUSDT", status="BREAK")]))


def req(**kw):
    base = dict(symbol="BTCUSDT", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=Decimal("0.01"))
    base.update(kw)
    return OrderRequest(**base)


def test_valid_orders_pass(validator):
    assert validator.validate_order(req())
    assert validator.validate_order(req(order_type=OrderType.LIMIT, price=Decimal("50000.5")))
    assert validator.validate_order(
        req(order_type=OrderType.STOP, price=Decimal("50000"), stop_price=Decimal("49900"))
    )


def test_exchange_info_is_fetched_once_and_cached():
    client = FakeClient([_symbol()])
    v = ExchangeValidator(client)
    v.validate_order(req())
    v.validate_order(req())
    assert client.exchange_info_calls == 1


def test_unknown_symbol_rejected(validator):
    with pytest.raises(ValidationError, match="not found"):
        validator.validate_order(req(symbol="DOGEUSDT"))


def test_non_trading_symbol_rejected(validator):
    with pytest.raises(ValidationError, match="not currently trading"):
        validator.validate_order(req(symbol="ETHUSDT"))


def test_malformed_symbols_are_skipped_not_fatal():
    v = ExchangeValidator(FakeClient([{"symbol": "BROKEN"}, _symbol()]))
    assert v.get_symbol_info("btcusdt").symbol == "BTCUSDT"


@pytest.mark.parametrize(
    "qty, needle",
    [("0.0001", "below the minimum"), ("1001", "exceeds the maximum"), ("0.0015", "step size")],
)
def test_quantity_rules(validator, qty, needle):
    with pytest.raises(ValidationError, match=needle):
        validator.validate_order(req(quantity=Decimal(qty)))


def test_step_size_error_suggests_nearest_valid_quantity(validator):
    with pytest.raises(ValidationError, match="Nearest valid value: 0.001"):
        validator.validate_order(req(quantity=Decimal("0.0015")))


@pytest.mark.parametrize(
    "price, needle",
    [("5", "below the minimum"), ("2000000", "exceeds the maximum"), ("50000.55", "tick size")],
)
def test_price_rules(validator, price, needle):
    with pytest.raises(ValidationError, match=needle):
        validator.validate_order(req(order_type=OrderType.LIMIT, price=Decimal(price)))


def test_limit_requires_price_and_stop_requires_stop_price(validator):
    with pytest.raises(ValidationError, match="Price is required"):
        validator.validate_order(req(order_type=OrderType.LIMIT))
    with pytest.raises(ValidationError, match="Stop price is required"):
        validator.validate_order(req(order_type=OrderType.STOP, price=Decimal("50000")))


def test_stop_price_is_validated_against_price_filter(validator):
    with pytest.raises(ValidationError) as exc:
        validator.validate_order(
            req(order_type=OrderType.STOP, price=Decimal("50000"), stop_price=Decimal("50000.55"))
        )
    assert exc.value.field == "stop_price"


def test_min_notional_enforced(validator):
    # 0.001 * 50000 = 50 < 100
    with pytest.raises(ValidationError, match="minimum required"):
        validator.validate_order(
            req(order_type=OrderType.LIMIT, quantity=Decimal("0.001"), price=Decimal("50000"))
        )


def test_symbol_without_filters_still_parses():
    info = SymbolInfo.from_exchange_info(_symbol(filters=[]))
    assert info.lot_size is None and info.price_filter is None and info.min_notional is None
