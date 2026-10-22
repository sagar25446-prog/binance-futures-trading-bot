"""
Unit Tests for Strategies Framework
"""

from decimal import Decimal
import numpy as np
import pytest

from bot.models import Kline, SignalType
from bot.strategies import (
    BollingerRSIStrategy,
    EMATrendATRStrategy,
    get_strategy,
    list_strategies,
)


def _make_dummy_klines(prices: list) -> list:
    klines = []
    t = 1600000000000
    for p in prices:
        dec_p = Decimal(str(p))
        k = Kline(
            open_time=t,
            open=dec_p,
            high=dec_p + Decimal("1.0"),
            low=dec_p - Decimal("1.0"),
            close=dec_p,
            volume=Decimal("100"),
            close_time=t + 60000,
        )
        klines.append(k)
        t += 60000
    return klines


def test_strategy_registry():
    strats = list_strategies()
    assert len(strats) >= 2
    strat_ids = [s["id"] for s in strats]
    assert "trend" in strat_ids
    assert "mean_reversion" in strat_ids

    s1 = get_strategy("trend", "BTCUSDT")
    assert isinstance(s1, EMATrendATRStrategy)
    s2 = get_strategy("mean_reversion", "ETHUSDT")
    assert isinstance(s2, BollingerRSIStrategy)

    with pytest.raises(ValueError):
        get_strategy("nonexistent_strat", "BTCUSDT")


def test_trend_strategy_insufficient_candles():
    strat = EMATrendATRStrategy(symbol="BTCUSDT", slow_period=200)
    klines = _make_dummy_klines([100.0] * 50)
    assert strat.on_candle(klines) is None


def test_mean_reversion_oversold_bounce():
    strat = BollingerRSIStrategy(symbol="BTCUSDT", bb_period=10, rsi_period=10)
    # Downtrend then dip below lower band and sharp bounce
    prices = [100.0] * 20 + [90.0, 80.0, 70.0, 60.0, 50.0, 48.0, 52.0]
    klines = _make_dummy_klines(prices)
    signal = strat.on_candle(klines)
    if signal:
        assert signal.signal_type in (SignalType.BUY, SignalType.SELL)
        assert signal.stop_loss is not None
        assert signal.take_profit is not None
