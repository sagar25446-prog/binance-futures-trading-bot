from decimal import Decimal

import pytest

from bot.exceptions import ValidationError
from bot.models import OrderSide, OrderType
from bot.validators import validate_cli_inputs


def test_validate_cli_inputs_market():
    """Test valid market order parsing."""
    req = validate_cli_inputs(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity="0.01",
        price=None,
        stop_price=None,
    )
    assert req.symbol == "BTCUSDT"
    assert req.side == OrderSide.BUY
    assert req.order_type == OrderType.MARKET
    assert req.quantity == Decimal("0.01")
    assert req.price is None

def test_validate_cli_inputs_limit():
    """Test valid limit order parsing."""
    req = validate_cli_inputs(
        symbol="ETHUSDT",
        side="SELL",
        order_type="LIMIT",
        quantity="1.5",
        price="3500",
        stop_price=None,
    )
    assert req.symbol == "ETHUSDT"
    assert req.side == OrderSide.SELL
    assert req.order_type == OrderType.LIMIT
    assert req.quantity == Decimal("1.5")
    assert req.price == Decimal("3500")

def test_validate_cli_inputs_missing_price():
    """Test limit order with missing price throws ValidationError."""
    with pytest.raises(ValidationError) as exc:
        validate_cli_inputs(
            symbol="ETHUSDT",
            side="SELL",
            order_type="LIMIT",
            quantity="1.5",
            price=None,
            stop_price=None,
        )
    assert "price" in str(exc.value).lower()

def test_validate_cli_inputs_stop_limit():
    """Test valid stop-limit order parsing."""
    req = validate_cli_inputs(
        symbol="BNBUSDT",
        side="BUY",
        order_type="STOP",
        quantity="10",
        price="500",
        stop_price="490",
    )
    assert req.order_type == OrderType.STOP
    assert req.price == Decimal("500")
    assert req.stop_price == Decimal("490")


@pytest.mark.parametrize("bad", ["Infinity", "-Infinity", "NaN", "inf", "0", "-1", "abc", ""])
def test_non_finite_and_non_positive_quantities_rejected(bad):
    with pytest.raises(ValidationError):
        validate_cli_inputs("BTCUSDT", "BUY", "MARKET", bad)


def test_infinite_price_rejected():
    with pytest.raises(ValidationError):
        validate_cli_inputs("BTCUSDT", "BUY", "LIMIT", "1", price="Infinity")


def test_model_rejects_infinite_quantity():
    from decimal import Decimal

    from pydantic import ValidationError as PydanticError

    from bot.models import OrderRequest

    with pytest.raises(PydanticError):
        OrderRequest(symbol="BTCUSDT", side="BUY", order_type="MARKET", quantity=Decimal("Infinity"))
