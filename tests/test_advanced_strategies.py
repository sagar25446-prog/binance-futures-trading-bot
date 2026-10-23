"""
Unit & Integration Tests for Advanced Strategies, ML Alpha, Trainer & Optimizer
"""

from decimal import Decimal
import os
import tempfile
import numpy as np
import pytest

from bot.models import Kline, SignalType
from bot.optimizer import StrategyOptimizer
from bot.strategies import (
    AdaptiveRegimeStrategy,
    MLAlphaStrategy,
    get_strategy,
    list_strategies,
)
from bot.trainer import ModelTrainer


def _make_dummy_klines(prices: list) -> list:
    klines = []
    t = 1600000000000
    for p in prices:
        dec_p = Decimal(str(p))
        k = Kline(
            open_time=t,
            open=dec_p,
            high=dec_p + Decimal("2.0"),
            low=dec_p - Decimal("2.0"),
            close=dec_p,
            volume=Decimal("150"),
            close_time=t + 60000,
        )
        klines.append(k)
        t += 60000
    return klines


def test_registry_includes_adaptive_and_ml():
    strats = list_strategies()
    strat_ids = [s["id"] for s in strats]
    assert "adaptive_regime" in strat_ids
    assert "ml_alpha" in strat_ids

    s_ad = get_strategy("adaptive_regime", "SOLUSDT")
    assert isinstance(s_ad, AdaptiveRegimeStrategy)

    s_ml = get_strategy("ml_alpha", "SOLUSDT")
    assert isinstance(s_ml, MLAlphaStrategy)


def test_adaptive_regime_insufficient_candles():
    strat = AdaptiveRegimeStrategy(symbol="SOLUSDT")
    klines = _make_dummy_klines([100.0] * 30)
    assert strat.on_candle(klines) is None


def test_adaptive_regime_execution():
    strat = AdaptiveRegimeStrategy(
        symbol="SOLUSDT",
        trend_adx_thresh=22.0,
        range_adx_thresh=20.0,
        trend_tp_mult=4.0,
        trend_sl_mult=1.8,
    )
    # Generate 70 candles with upward trend
    prices = [100.0 + i * 0.5 for i in range(70)]
    klines = _make_dummy_klines(prices)
    sig = strat.on_candle(klines)
    # May return a signal or None depending on exact crossover
    if sig:
        assert sig.signal_type in (SignalType.BUY, SignalType.SELL)
        assert sig.stop_loss is not None
        assert sig.take_profit is not None


def test_ml_alpha_features_extraction():
    strat = MLAlphaStrategy(symbol="BTCUSDT")
    # Less than 55 candles
    assert strat.extract_features(_make_dummy_klines([50000.0] * 30)) is None

    # Sufficient candles
    klines = _make_dummy_klines([50000.0 + i * 10 for i in range(65)])
    feat = strat.extract_features(klines)
    assert feat is not None
    assert feat.shape == (1, 11)


def test_ml_trainer_dataset_preparation():
    trainer = ModelTrainer(output_dir=tempfile.gettempdir())
    prices = [100.0 + np.sin(i / 5.0) * 5.0 for i in range(120)]
    klines = _make_dummy_klines(prices)

    X, y_long, y_short = trainer.prepare_dataset(klines, forward_window=3, target_threshold=0.002)
    assert len(X) > 0
    assert len(X) == len(y_long) == len(y_short)
    assert X.shape[1] == 11


def test_ml_trainer_walk_forward_and_save():
    with tempfile.TemporaryDirectory() as tmp_dir:
        trainer = ModelTrainer(output_dir=tmp_dir)
        prices = [100.0 + i * 0.2 + np.sin(i / 3.0) * 2.0 for i in range(150)]
        klines = _make_dummy_klines(prices)

        X, y_long, y_short = trainer.prepare_dataset(klines, forward_window=3, target_threshold=0.001)
        res = trainer.train_walk_forward(X, y_long, y_short, n_splits=3)

        assert "clf_long" in res
        assert "clf_short" in res
        assert res["total_samples"] == len(X)
