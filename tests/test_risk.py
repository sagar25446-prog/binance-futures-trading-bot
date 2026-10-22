"""
Unit Tests for Risk Management Engine
"""

from decimal import Decimal
from unittest.mock import MagicMock
import pytest

from bot.models import LotSizeFilter, MinNotionalFilter, PriceFilter, SignalType, SymbolInfo, TradeSignal
from bot.risk import RiskManager
from bot.validators import ExchangeValidator


@pytest.fixture
def mock_validator():
    validator = MagicMock(spec=ExchangeValidator)
    validator.get_symbol_info.return_value = SymbolInfo(
        symbol="BTCUSDT",
        status="TRADING",
        baseAsset="BTC",
        quoteAsset="USDT",
        pricePrecision=2,
        quantityPrecision=3,
        lot_size=LotSizeFilter(minQty=Decimal("0.001"), maxQty=Decimal("100.0"), stepSize=Decimal("0.001")),
        price_filter=PriceFilter(minPrice=Decimal("0.01"), maxPrice=Decimal("1000000.0"), tickSize=Decimal("0.01")),
        min_notional=MinNotionalFilter(notional=Decimal("5.0")),
    )
    return validator


def test_position_sizing(mock_validator):
    rm = RiskManager(validator=mock_validator, max_risk_per_trade_pct=0.01, max_leverage=3)
    equity = Decimal("10000.0")  # 1% risk = $100

    # Entry: 50,000, Stop Loss: 49,000 -> Stop Distance = 1,000
    # Expected Qty = $100 / 1,000 = 0.1 BTC
    signal = TradeSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        entry_price=Decimal("50000.0"),
        stop_loss=Decimal("49000.0"),
        take_profit=Decimal("52000.0"),
    )
    qty = rm.calculate_position_size(signal, equity)
    assert qty == Decimal("0.100")


def test_daily_loss_circuit_breaker(mock_validator):
    rm = RiskManager(validator=mock_validator, max_daily_loss_pct=0.03)
    equity = Decimal("10000.0")
    rm.update_account_state(equity)

    # Initial state: can trade
    can_trade, _ = rm.check_circuit_breakers(equity)
    assert can_trade is True

    # Record loss of $350 (3.5% > 3.0%)
    rm.record_trade_result(Decimal("-350.0"))
    can_trade, reason = rm.check_circuit_breakers(equity)
    assert can_trade is False
    assert "daily loss limit breached" in reason.lower()


def test_max_drawdown_circuit_breaker(mock_validator):
    rm = RiskManager(validator=mock_validator, max_drawdown_pct=0.08)
    rm.update_account_state(Decimal("10000.0"))  # Peak = 10,000

    # Equity drops to $9,100 (9% drawdown > 8%)
    can_trade, reason = rm.check_circuit_breakers(Decimal("9100.0"))
    assert can_trade is False
    assert "drawdown circuit breaker" in reason.lower()


def test_consecutive_loss_cooldown(mock_validator):
    rm = RiskManager(validator=mock_validator, consecutive_loss_limit=3, cooldown_seconds=600)
    rm.update_account_state(Decimal("10000.0"))

    rm.record_trade_result(Decimal("-10.0"))
    rm.record_trade_result(Decimal("-10.0"))
    assert rm.consecutive_losses == 2
    can_trade, _ = rm.check_circuit_breakers(Decimal("9980.0"))
    assert can_trade is True

    # 3rd consecutive loss
    rm.record_trade_result(Decimal("-10.0"))
    assert rm.consecutive_losses == 3
    can_trade, reason = rm.check_circuit_breakers(Decimal("9970.0"))
    assert can_trade is False
    assert "cooldown active" in reason.lower()
