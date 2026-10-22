"""
Mean Reversion Strategy (Bollinger Bands + RSI Scalper)
======================================================

Captures mean-reverting price action in oscillating or range-bound markets:
1. Bollinger Bands (20, 2.0) define dynamic volatility boundaries.
2. RSI (14) identifies momentum exhaustion (oversold < 30, overbought > 70).
3. Long: Price rejects off the Lower Band with RSI climbing back out of oversold territory.
4. Short: Price rejects off the Upper Band with RSI dropping back out of overbought territory.
5. Exit / Take Profit: Middle band (20 SMA) or 1.5:1 R:R target.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
import numpy as np

from bot.indicators import atr, bollinger_bands, rsi
from bot.models import Kline, SignalType, TradeSignal
from bot.strategies.base import BaseStrategy


class BollingerRSIStrategy(BaseStrategy):
    """Mean Reversion Strategy using Bollinger Bands and RSI."""

    def __init__(
        self,
        symbol: str,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        rsi_oversold: float = 30.0,
        rsi_overbought: float = 70.0,
        atr_period: int = 14,
        atr_sl_mult: float = 1.5,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name="Bollinger_RSI_Reversion", symbol=symbol, params=params)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_period = atr_period
        self.atr_sl_mult = atr_sl_mult

    def on_candle(self, klines: List[Kline]) -> Optional[TradeSignal]:
        """Generate mean reversion signals from recent candles."""
        min_candles = max(self.bb_period + 5, self.rsi_period + 5)
        if len(klines) < min_candles:
            return None

        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        highs = np.array([float(k.high) for k in klines], dtype=np.float64)
        lows = np.array([float(k.low) for k in klines], dtype=np.float64)

        upper, mid, lower = bollinger_bands(closes, self.bb_period, self.bb_std)
        rsi_vals = rsi(closes, self.rsi_period)
        atr_vals = atr(highs, lows, closes, self.atr_period)

        i = len(closes) - 1
        prev_i = i - 1

        curr_close = closes[i]
        curr_rsi = rsi_vals[i]
        prev_rsi = rsi_vals[prev_i]
        curr_lower = lower[i]
        curr_upper = upper[i]
        curr_mid = mid[i]
        curr_atr = atr_vals[i]

        if np.isnan(curr_atr) or curr_atr <= 0 or np.isnan(curr_rsi):
            return None

        entry_dec = Decimal(str(round(curr_close, 4)))
        atr_dec = Decimal(str(round(curr_atr, 4)))
        sl_dist = atr_dec * Decimal(str(self.atr_sl_mult))

        # Long: Previous candle or current candle dipped below lower band & RSI recovers above oversold
        oversold_bounce = (curr_close <= curr_lower or closes[prev_i] <= lower[prev_i]) and (
            prev_rsi <= self.rsi_oversold and curr_rsi > prev_rsi
        )

        # Short: Previous candle or current candle pushed above upper band & RSI drops below overbought
        overbought_reject = (curr_close >= curr_upper or closes[prev_i] >= upper[prev_i]) and (
            prev_rsi >= self.rsi_overbought and curr_rsi < prev_rsi
        )

        timestamp = klines[i].close_time

        if oversold_bounce:
            stop_loss = max(Decimal("0.0001"), entry_dec - sl_dist)
            take_profit = Decimal(str(round(curr_mid, 4)))
            if take_profit <= entry_dec:
                take_profit = entry_dec + (sl_dist * Decimal("1.5"))

            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.BUY,
                entry_price=entry_dec,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.80,
                rationale=f"Oversold BB bounce: RSI={curr_rsi:.1f}, LowerBand={curr_lower:.2f}",
                timestamp=timestamp,
            )

        if overbought_reject:
            stop_loss = entry_dec + sl_dist
            take_profit = Decimal(str(round(curr_mid, 4)))
            if take_profit >= entry_dec:
                take_profit = max(Decimal("0.0001"), entry_dec - (sl_dist * Decimal("1.5")))

            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.SELL,
                entry_price=entry_dec,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=0.80,
                rationale=f"Overbought BB reject: RSI={curr_rsi:.1f}, UpperBand={curr_upper:.2f}",
                timestamp=timestamp,
            )

        return None
