"""
Unit Tests for Trading Engine
"""

from decimal import Decimal
from unittest.mock import MagicMock
import pytest

from bot.client import BinanceClient
from bot.engine import TradingEngine
from bot.models import SignalType, TradeSignal, TradingMode
from bot.risk import RiskManager
from bot.storage import Storage
from bot.strategies.base import BaseStrategy


class MockStrategy(BaseStrategy):
    def __init__(self, symbol="BTCUSDT"):
        super().__init__("MockStrategy", symbol)
        self.signal_to_return = None

    def on_candle(self, klines):
        return self.signal_to_return


@pytest.fixture
def mock_engine():
    client = MagicMock(spec=BinanceClient)
    client.get_ticker_price.return_value = {"symbol": "BTCUSDT", "price": "50000.00"}
    client.get_klines.return_value = [
        [1600000000000 + i * 60000, "50000", "50100", "49900", "50000", "10", 1600000000000 + (i + 1) * 60000, "500000", 100]
        for i in range(100)
    ]
    client.get_account_info.return_value = {"totalMarginBalance": "10000.00"}

    strat = MockStrategy("BTCUSDT")
    risk_mgr = MagicMock(spec=RiskManager)
    risk_mgr.check_circuit_breakers.return_value = (True, "OK")
    risk_mgr.calculate_position_size.return_value = Decimal("0.1")
    risk_mgr.realized_daily_pnl = Decimal("0")

    storage = Storage(":memory:")

    engine = TradingEngine(
        client=client,
        strategy=strat,
        risk_manager=risk_mgr,
        storage=storage,
        symbol="BTCUSDT",
        mode=TradingMode.PAPER,
        paper_initial_balance=10000.0,
    )
    return engine, strat, client


def test_engine_paper_step(mock_engine):
    engine, strat, client = mock_engine
    telemetry = engine.step()
    assert telemetry["symbol"] == "BTCUSDT"
    assert telemetry["mode"] == "PAPER"
    assert telemetry["last_price"] == 50000.0
    assert telemetry["equity"] == 10000.0
    assert telemetry["open_position"] is None


def test_engine_paper_entry_and_exit(mock_engine):
    engine, strat, client = mock_engine

    # Generate buy signal
    strat.signal_to_return = TradeSignal(
        symbol="BTCUSDT",
        signal_type=SignalType.BUY,
        entry_price=Decimal("50000.0"),
        stop_loss=Decimal("49000.0"),
        take_profit=Decimal("52000.0"),
    )

    telemetry = engine.step()
    assert engine.paper_position is not None
    assert engine.paper_position["side"] == "BUY"
    assert engine.paper_position["quantity"] == Decimal("0.1")

    # Now simulate price rising to 52,500 (triggering Take Profit)
    client.get_ticker_price.return_value = {"symbol": "BTCUSDT", "price": "52500.00"}
    strat.signal_to_return = None

    telemetry2 = engine.step()
    assert engine.paper_position is None  # Position closed!
    assert engine.paper_balance > Decimal("10000.0")  # Profit realized


def test_panic_close_paper(mock_engine):
    engine, strat, client = mock_engine
    engine.paper_position = {
        "trade_id": "test1234",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "entry_price": Decimal("50000"),
        "quantity": Decimal("0.1"),
        "stop_loss": Decimal("49000"),
        "take_profit": Decimal("52000"),
    }
    res = engine.panic_close_all()
    assert res["positions_closed"] is True
    assert engine.paper_position is None
