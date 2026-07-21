from decimal import Decimal
import pytest

from bot.validators import validate_cli_inputs
from bot.models import OrderType, OrderSide
from bot.exceptions import ValidationError

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
