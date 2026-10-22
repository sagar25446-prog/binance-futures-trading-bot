"""
Unit Tests for Backtester Engine
"""

from decimal import Decimal
from unittest.mock import MagicMock
import pytest

from bot.backtester import BacktestEngine
from bot.models import Kline, SignalType, TradeSignal
from bot.strategies.base import BaseStrategy


class DummyAlwaysBuyStrategy(BaseStrategy):
    def __init__(self, symbol="BTCUSDT"):
        super().__init__("Dummy", symbol)
        self.fired = False

    def on_candle(self, klines):
        if not self.fired and len(klines) >= 50:
            self.fired = True
            c = klines[-1].close
            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.BUY,
                entry_price=c,
                stop_loss=c - Decimal("100"),
                take_profit=c + Decimal("200"),
            )
        return None


def test_backtest_execution():
    strat = DummyAlwaysBuyStrategy()
    engine = BacktestEngine(strategy=strat, initial_balance=10000.0, risk_per_trade_pct=0.01)

    klines = []
    t = 1600000000000
    # 60 candles with price rising from 1000 to 1300
    for i in range(60):
        p = Decimal(str(1000 + (i * 5)))
        k = Kline(
            open_time=t,
            open=p,
            high=p + Decimal("20"),
            low=p - Decimal("5"),
            close=p + Decimal("10"),
            volume=Decimal("10"),
            close_time=t + 60000,
        )
        klines.append(k)
        t += 60000

    results = engine.run(klines)
    assert results["initial_balance"] == 10000.0
    assert "win_rate" in results
    assert "profit_factor" in results
    assert "total_trades" in results
    assert results["total_trades"] >= 1
    assert results["wins"] >= 1
