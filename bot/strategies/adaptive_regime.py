"""
Adaptive Dual-Regime Strategy
=============================

Institutional-grade quantitative strategy that dynamically classifies market regimes
and deploys the optimal execution model:
1. Trend Regime (ADX >= 22.0):
   - Fast/Medium EMA (20/50) crossover aligned with 200 EMA macro filter.
   - Asymmetric profit extraction (4.0x - 5.0x ATR target, 1.8x ATR stop loss).
2. Range / Consolidation Regime (ADX <= 20.0):
   - Mean-reversion scalping off 2.2-std Bollinger Bands.
   - Momentum exhaustion confirmation (RSI < 32 oversold bounce, RSI > 68 overbought reject).
   - Fast target at 1.5x ATR.
3. Choppy / Uncertain Regime (20.0 < ADX < 22.0):
   - Bot stays strictly FLAT to prevent whipsaw losses and fee erosion.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
import numpy as np

from bot.indicators import adx, atr, bollinger_bands, ema, rsi
from bot.models import Kline, SignalType, TradeSignal
from bot.strategies.base import BaseStrategy


class AdaptiveRegimeStrategy(BaseStrategy):
    """Dynamically adapts between Trend Following and Mean Reversion based on ADX volatility."""

    def __init__(
        self,
        symbol: str,
        trend_adx_thresh: float = 22.0,
        range_adx_thresh: float = 20.0,
        trend_tp_mult: float = 5.0,
        trend_sl_mult: float = 1.8,
        range_tp_mult: float = 1.5,
        range_sl_mult: float = 1.5,
        bb_std: float = 2.2,
        rsi_oversold: float = 32.0,
        rsi_overbought: float = 68.0,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name="Adaptive_Dual_Regime", symbol=symbol, params=params)
        self.trend_adx_thresh = float(self.params.get("trend_adx_thresh", trend_adx_thresh))
        self.range_adx_thresh = float(self.params.get("range_adx_thresh", range_adx_thresh))
        self.trend_tp_mult = float(self.params.get("trend_tp_mult", trend_tp_mult))
        self.trend_sl_mult = float(self.params.get("trend_sl_mult", trend_sl_mult))
        self.range_tp_mult = float(self.params.get("range_tp_mult", range_tp_mult))
        self.range_sl_mult = float(self.params.get("range_sl_mult", range_sl_mult))
        self.bb_std = float(self.params.get("bb_std", bb_std))
        self.rsi_oversold = float(self.params.get("rsi_oversold", rsi_oversold))
        self.rsi_overbought = float(self.params.get("rsi_overbought", rsi_overbought))

    def on_candle(self, klines: List[Kline]) -> Optional[TradeSignal]:
        """Evaluate market regime and generate regime-specific trade signal."""
        min_candles = 55
        if len(klines) < min_candles:
            return None

        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        highs = np.array([float(k.high) for k in klines], dtype=np.float64)
        lows = np.array([float(k.low) for k in klines], dtype=np.float64)

        # Technical Indicators
        ema20 = ema(closes, 20)
        ema50 = ema(closes, 50)
        ema200 = ema(closes, min(200, len(closes) - 1)) if len(closes) >= 100 else ema(closes, 50)
        atr_vals = atr(highs, lows, closes, 14)
        adx_vals = adx(highs, lows, closes, 14)
        bb_up, bb_mid, bb_low = bollinger_bands(closes, 20, self.bb_std)
        rsi_vals = rsi(closes, 14)

        i = len(closes) - 1
        prev_i = i - 1

        curr_close = closes[i]
        curr_high = highs[i]
        curr_low = lows[i]
        curr_atr = atr_vals[i]
        curr_adx = adx_vals[i]
        curr_rsi = rsi_vals[i]

        if np.isnan(curr_atr) or curr_atr <= 0 or np.isnan(curr_adx):
            return None

        entry_dec = Decimal(str(round(curr_close, 4)))
        atr_dec = Decimal(str(round(curr_atr, 4)))
        timestamp = klines[i].close_time

        # ========================================================
        # REGIME 1: TRENDING (ADX >= trend_adx_thresh)
        # ========================================================
        if curr_adx >= self.trend_adx_thresh:
            bull_macro = curr_close > ema200[i]
            bear_macro = curr_close < ema200[i]

            bull_cross = (ema20[prev_i] <= ema50[prev_i]) and (ema20[i] > ema50[i])
            bear_cross = (ema20[prev_i] >= ema50[prev_i]) and (ema20[i] < ema50[i])

            sl_dist = atr_dec * Decimal(str(self.trend_sl_mult))
            tp_dist = atr_dec * Decimal(str(self.trend_tp_mult))

            if bull_macro and bull_cross:
                return TradeSignal(
                    symbol=self.symbol,
                    signal_type=SignalType.BUY,
                    entry_price=entry_dec,
                    stop_loss=max(Decimal("0.0001"), entry_dec - sl_dist),
                    take_profit=entry_dec + tp_dist,
                    timestamp=timestamp,
                    confidence=0.85,
                    metadata={"regime": "TREND", "adx": round(curr_adx, 2)},
                )
            elif bear_macro and bear_cross:
                return TradeSignal(
                    symbol=self.symbol,
                    signal_type=SignalType.SELL,
                    entry_price=entry_dec,
                    stop_loss=entry_dec + sl_dist,
                    take_profit=max(Decimal("0.0001"), entry_dec - tp_dist),
                    timestamp=timestamp,
                    confidence=0.85,
                    metadata={"regime": "TREND", "adx": round(curr_adx, 2)},
                )

        # ========================================================
        # REGIME 2: RANGING / MEAN REVERSION (ADX <= range_adx_thresh)
        # ========================================================
        elif curr_adx <= self.range_adx_thresh:
            # Long: pierced lower band and RSI oversold
            long_bounce = (curr_low <= bb_low[i]) and (curr_rsi <= self.rsi_oversold) and (curr_close > curr_low)
            # Short: pierced upper band and RSI overbought
            short_reject = (curr_high >= bb_up[i]) and (curr_rsi >= self.rsi_overbought) and (curr_close < curr_high)

            sl_dist = atr_dec * Decimal(str(self.range_sl_mult))
            tp_dist = atr_dec * Decimal(str(self.range_tp_mult))

            if long_bounce:
                return TradeSignal(
                    symbol=self.symbol,
                    signal_type=SignalType.BUY,
                    entry_price=entry_dec,
                    stop_loss=max(Decimal("0.0001"), entry_dec - sl_dist),
                    take_profit=entry_dec + tp_dist,
                    timestamp=timestamp,
                    confidence=0.75,
                    metadata={"regime": "RANGE", "adx": round(curr_adx, 2), "rsi": round(curr_rsi, 2)},
                )
            elif short_reject:
                return TradeSignal(
                    symbol=self.symbol,
                    signal_type=SignalType.SELL,
                    entry_price=entry_dec,
                    stop_loss=entry_dec + sl_dist,
                    take_profit=max(Decimal("0.0001"), entry_dec - tp_dist),
                    timestamp=timestamp,
                    confidence=0.75,
                    metadata={"regime": "RANGE", "adx": round(curr_adx, 2), "rsi": round(curr_rsi, 2)},
                )

        # ========================================================
        # REGIME 3: CHOP ZONE (range_adx_thresh < ADX < trend_adx_thresh)
        # ========================================================
        # Return None to preserve capital and avoid fee decay
        return None
