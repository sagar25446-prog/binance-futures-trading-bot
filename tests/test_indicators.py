"""
Unit Tests for Technical Indicators Engine
"""

import numpy as np
import pytest

from bot.indicators import adx, atr, bollinger_bands, ema, macd, rsi, sma


def test_sma_calculation():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    res = sma(data, 3)
    assert np.isnan(res[0])
    assert np.isnan(res[1])
    assert pytest.approx(res[2]) == 20.0
    assert pytest.approx(res[3]) == 30.0
    assert pytest.approx(res[4]) == 40.0


def test_ema_calculation():
    data = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0])
    res = ema(data, 3)
    assert np.isnan(res[0])
    assert np.isnan(res[1])
    assert pytest.approx(res[2]) == 11.0  # SMA seed
    # Next EMA = (13 - 11)*0.5 + 11 = 12.0
    assert pytest.approx(res[3]) == 12.0


def test_atr_calculation():
    highs = np.array([10.0, 12.0, 11.0, 13.0, 15.0, 14.0, 16.0, 17.0, 18.0, 19.0, 20.0, 21.0, 22.0, 23.0, 24.0, 25.0])
    lows = highs - 2.0
    closes = highs - 1.0

    res = atr(highs, lows, closes, period=14)
    assert len(res) == len(highs)
    # Valid ATR should be ~2.0
    assert not np.isnan(res[-1])
    assert pytest.approx(res[-1], abs=0.5) == 2.0


def test_rsi_bounds():
    # Uptrend prices
    uptrend = np.linspace(100, 200, 30)
    res_up = rsi(uptrend, 14)
    assert not np.isnan(res_up[-1])
    assert res_up[-1] > 80.0  # Overbought

    # Downtrend prices
    downtrend = np.linspace(200, 100, 30)
    res_down = rsi(downtrend, 14)
    assert not np.isnan(res_down[-1])
    assert res_down[-1] < 20.0  # Oversold


def test_bollinger_bands():
    data = np.linspace(100, 120, 30)
    upper, mid, lower = bollinger_bands(data, period=10, std_dev=2.0)
    assert len(upper) == len(data)
    assert not np.isnan(upper[-1])
    assert upper[-1] > mid[-1]
    assert mid[-1] > lower[-1]


def test_macd():
    data = np.random.randn(50).cumsum() + 100.0
    macd_line, sig_line, hist = macd(data, fast=12, slow=26, signal=9)
    assert len(macd_line) == len(data)
    assert not np.isnan(macd_line[-1])
    assert pytest.approx(hist[-1]) == (macd_line[-1] - sig_line[-1])


def test_adx():
    highs = np.linspace(100, 150, 40) + np.random.rand(40) * 2.0
    lows = highs - 3.0
    closes = (highs + lows) / 2.0
    adx_vals = adx(highs, lows, closes, period=14)
    assert len(adx_vals) == len(closes)
    valid = adx_vals[~np.isnan(adx_vals)]
    assert len(valid) > 0
    assert (valid >= 0.0).all() and (valid <= 100.0).all()
