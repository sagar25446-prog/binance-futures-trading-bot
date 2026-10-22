"""
Technical Indicators Engine
===========================

High-performance, pure vectorized technical indicators built on NumPy.
Provides exact mathematical formulations for algorithmic trading strategies:
- Moving Averages: SMA, EMA
- Volatility: Average True Range (ATR), Bollinger Bands
- Momentum: Relative Strength Index (RSI), MACD
- Trend Strength: Average Directional Index (ADX)
"""

from typing import Tuple, Union
import numpy as np


def to_numpy(data: Union[list, np.ndarray]) -> np.ndarray:
    """Ensure data is float64 1D numpy array."""
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim != 1:
        arr = arr.flatten()
    return arr


def sma(data: Union[list, np.ndarray], period: int) -> np.ndarray:
    """Simple Moving Average (SMA).

    Args:
        data: 1D price array.
        period: Lookback period.

    Returns:
        Array of SMA values with NaNs for the initial period.
    """
    arr = to_numpy(data)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period or period <= 0:
        return out

    cumsum = np.cumsum(np.insert(arr, 0, 0))
    out[period - 1 :] = (cumsum[period:] - cumsum[:-period]) / period
    return out


def ema(data: Union[list, np.ndarray], period: int) -> np.ndarray:
    """Exponential Moving Average (EMA).

    Args:
        data: 1D price array.
        period: Lookback period.

    Returns:
        Array of EMA values.
    """
    arr = to_numpy(data)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period or period <= 0:
        return out

    multiplier = 2.0 / (period + 1.0)
    # Seed with SMA of initial window
    out[period - 1] = np.mean(arr[:period])
    for i in range(period, n):
        out[i] = (arr[i] - out[i - 1]) * multiplier + out[i - 1]
    return out


def atr(
    high: Union[list, np.ndarray],
    low: Union[list, np.ndarray],
    close: Union[list, np.ndarray],
    period: int = 14,
) -> np.ndarray:
    """Average True Range (ATR) using Wilder's smoothing.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: Lookback period (default: 14).

    Returns:
        Array of ATR values.
    """
    h = to_numpy(high)
    l = to_numpy(low)
    c = to_numpy(close)
    n = len(c)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1 or period <= 0:
        return out

    # True Range components
    tr = np.zeros(n, dtype=np.float64)
    tr[0] = h[0] - l[0]
    for i in range(1, n):
        hl = h[i] - l[i]
        hc = abs(h[i] - c[i - 1])
        lc = abs(l[i] - c[i - 1])
        tr[i] = max(hl, hc, lc)

    # Wilder's smoothed ATR
    out[period] = np.mean(tr[1 : period + 1])
    for i in range(period + 1, n):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def rsi(close: Union[list, np.ndarray], period: int = 14) -> np.ndarray:
    """Relative Strength Index (RSI).

    Args:
        close: 1D close price array.
        period: RSI period (default: 14).

    Returns:
        Array of RSI values [0.0, 100.0].
    """
    c = to_numpy(close)
    n = len(c)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < period + 1 or period <= 0:
        return out

    deltas = np.diff(c)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Initial average
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0.0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))

    # Wilder's smoothing
    for i in range(period, len(deltas)):
        idx = i + 1
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0.0:
            out[idx] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[idx] = 100.0 - (100.0 / (1.0 + rs))

    return out


def bollinger_bands(
    close: Union[list, np.ndarray], period: int = 20, std_dev: float = 2.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Bollinger Bands (Upper, Middle, Lower).

    Args:
        close: 1D close prices.
        period: Moving average period (default: 20).
        std_dev: Number of standard deviations (default: 2.0).

    Returns:
        Tuple of (upper_band, middle_band, lower_band).
    """
    c = to_numpy(close)
    mid = sma(c, period)
    n = len(c)
    upper = np.full(n, np.nan, dtype=np.float64)
    lower = np.full(n, np.nan, dtype=np.float64)

    for i in range(period - 1, n):
        window = c[i - period + 1 : i + 1]
        sigma = np.std(window, ddof=0)
        upper[i] = mid[i] + (std_dev * sigma)
        lower[i] = mid[i] - (std_dev * sigma)

    return upper, mid, lower


def macd(
    close: Union[list, np.ndarray], fast: int = 12, slow: int = 26, signal: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Moving Average Convergence Divergence (MACD).

    Args:
        close: 1D close price array.
        fast: Fast EMA period (default: 12).
        slow: Slow EMA period (default: 26).
        signal: Signal EMA period (default: 9).

    Returns:
        Tuple of (macd_line, signal_line, histogram).
    """
    c = to_numpy(close)
    fast_ema = ema(c, fast)
    slow_ema = ema(c, slow)
    macd_line = fast_ema - slow_ema

    # Signal line is EMA of valid MACD line
    valid_idx = np.where(~np.isnan(macd_line))[0]
    signal_line = np.full_like(macd_line, np.nan)
    if len(valid_idx) >= signal:
        first_valid = valid_idx[0]
        sig_vals = ema(macd_line[first_valid:], signal)
        signal_line[first_valid : first_valid + len(sig_vals)] = sig_vals

    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def adx(
    high: Union[list, np.ndarray],
    low: Union[list, np.ndarray],
    close: Union[list, np.ndarray],
    period: int = 14,
) -> np.ndarray:
    """Average Directional Index (ADX) - Measures trend strength.

    Values > 25 indicate a strong trending market; values < 20 indicate range/chop.

    Args:
        high: High prices.
        low: Low prices.
        close: Close prices.
        period: Lookback period (default: 14).

    Returns:
        Array of ADX values.
    """
    h = to_numpy(high)
    l = to_numpy(low)
    c = to_numpy(close)
    n = len(c)
    out = np.full(n, np.nan, dtype=np.float64)
    if n < (period * 2) + 1 or period <= 0:
        return out

    # True range
    atr_vals = atr(h, l, c, period)

    # Directional movement
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        up_move = h[i] - h[i - 1]
        down_move = l[i - 1] - l[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        else:
            plus_dm[i] = 0.0

        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
        else:
            minus_dm[i] = 0.0

    # Smooth DM with Wilder's technique
    plus_di = np.full(n, np.nan, dtype=np.float64)
    minus_di = np.full(n, np.nan, dtype=np.float64)
    dx = np.full(n, np.nan, dtype=np.float64)

    smooth_plus_dm = np.sum(plus_dm[1 : period + 1])
    smooth_minus_dm = np.sum(minus_dm[1 : period + 1])

    for i in range(period, n):
        if i > period:
            smooth_plus_dm = smooth_plus_dm - (smooth_plus_dm / period) + plus_dm[i]
            smooth_minus_dm = smooth_minus_dm - (smooth_minus_dm / period) + minus_dm[i]

        curr_atr = atr_vals[i]
        if not np.isnan(curr_atr) and curr_atr > 0:
            plus_di[i] = 100.0 * (smooth_plus_dm / (curr_atr * period))
            minus_di[i] = 100.0 * (smooth_minus_dm / (curr_atr * period))

            di_sum = plus_di[i] + minus_di[i]
            di_diff = abs(plus_di[i] - minus_di[i])
            dx[i] = 100.0 * (di_diff / di_sum) if di_sum > 0 else 0.0

    # ADX is smoothed DX
    valid_dx = [x for x in dx if not np.isnan(x)]
    if len(valid_dx) >= period:
        first_dx_idx = np.where(~np.isnan(dx))[0][0]
        start_adx_idx = first_dx_idx + period - 1
        if start_adx_idx < n:
            out[start_adx_idx] = np.mean(dx[first_dx_idx : start_adx_idx + 1])
            for i in range(start_adx_idx + 1, n):
                if not np.isnan(dx[i]):
                    out[i] = (out[i - 1] * (period - 1) + dx[i]) / period

    return out
