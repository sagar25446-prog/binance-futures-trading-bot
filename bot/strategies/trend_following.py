"""
Trend Following Strategy (EMA Crossover + ATR Trailing Stop)
============================================================

A quantitative trend-following strategy designed for crypto futures markets:
1. Fast EMA (9) and Medium EMA (21) determine local momentum crossovers.
2. Baseline EMA (200) filters macro trend regime (Longs only above 200, Shorts only below 200).
3. ADX (14) ensures the market is genuinely trending (ADX > 20) and avoids whipsaws during chop.
4. ATR (14) establishes dynamic Stop-Loss (2x ATR) and Take-Profit (4x ATR, 1:2 R:R).
5. Ratchets trailing stops as price advances in the trade's favor.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
import numpy as np

from bot.indicators import adx, atr, ema
from bot.models import Kline, SignalType, TradeSignal
from bot.strategies.base import BaseStrategy


class EMATrendATRStrategy(BaseStrategy):
    """Multi-timeframe Trend Following Strategy."""

    def __init__(
        self,
        symbol: str,
        fast_period: int = 9,
        med_period: int = 21,
        slow_period: int = 200,
        atr_period: int = 14,
        atr_sl_mult: float = 2.0,
        risk_reward_ratio: float = 2.0,
        adx_filter: float = 20.0,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name="EMA_Trend_ATR", symbol=symbol, params=params)
        self.fast_period = fast_period
        self.med_period = med_period
        self.slow_period = slow_period
        self.atr_period = atr_period
        self.atr_sl_mult = atr_sl_mult
        self.risk_reward_ratio = risk_reward_ratio
        self.adx_filter = adx_filter

    def on_candle(self, klines: List[Kline]) -> Optional[TradeSignal]:
        """Generate trend signals from latest closed candles."""
        min_candles = max(self.slow_period + 5, 50)
        if len(klines) < min_candles:
            return None

        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        highs = np.array([float(k.high) for k in klines], dtype=np.float64)
        lows = np.array([float(k.low) for k in klines], dtype=np.float64)

        fast_ema = ema(closes, self.fast_period)
        med_ema = ema(closes, self.med_period)
        slow_ema = ema(closes, self.slow_period)
        atr_vals = atr(highs, lows, closes, self.atr_period)
        adx_vals = adx(highs, lows, closes, self.atr_period)

        # Look at the most recently completed candle
        i = len(closes) - 1
        prev_i = i - 1

        curr_close = closes[i]
        curr_fast = fast_ema[i]
        curr_med = med_ema[i]
        curr_slow = slow_ema[i]
        prev_fast = fast_ema[prev_i]
        prev_med = med_ema[prev_i]

        curr_atr = atr_vals[i]
        curr_adx = adx_vals[i]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        # Trend strength check
        is_trending = np.isnan(curr_adx) or curr_adx >= self.adx_filter

        # Bullish Crossover: Fast crosses above Medium while above 200 EMA
        bullish_cross = (prev_fast <= prev_med) and (curr_fast > curr_med)
        bullish_macro = curr_close > curr_slow

        # Bearish Crossover: Fast crosses below Medium while below 200 EMA
        bearish_cross = (prev_fast >= prev_med) and (curr_fast < curr_med)
        bearish_macro = curr_close < curr_slow

        entry_dec = Decimal(str(round(curr_close, 4)))
        atr_dec = Decimal(str(round(curr_atr, 4)))
        sl_dist = atr_dec * Decimal(str(self.atr_sl_mult))
        tp_dist = sl_dist * Decimal(str(self.risk_reward_ratio))

        timestamp = klines[i].close_time

        if bullish_cross and bullish_macro and is_trending:
            stop_loss = max(Decimal("0.0001"), entry_dec - sl_dist)
            take_profit = entry_dec + tp_dist
            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.BUY,
                entry_price=entry_dec,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.85,
                rationale=(
                    f"Bullish EMA({self.fast_period}/{self.med_period}) crossover above "
                    f"EMA({self.slow_period}), ADX={curr_adx:.1f}"
                ),
                timestamp=timestamp,
            )

        if bearish_cross and bearish_macro and is_trending:
            stop_loss = entry_dec + sl_dist
            take_profit = max(Decimal("0.0001"), entry_dec - tp_dist)
            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.SELL,
                entry_price=entry_dec,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.85,
                rationale=(
                    f"Bearish EMA({self.fast_period}/{self.med_period}) crossover below "
                    f"EMA({self.slow_period}), ADX={curr_adx:.1f}"
                ),
                timestamp=timestamp,
            )

        return None
