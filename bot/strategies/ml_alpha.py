"""
Machine Learning Alpha Strategy
===============================

Machine learning alpha strategy utilizing gradient-boosted decision trees
(HistGradientBoostingClassifier) trained via walk-forward cross-validation:
1. Feature Extraction: Stationary multi-timeframe returns, EMA momentum spreads,
   volatility ratios (ATR/close, BB width), RSI, and order-flow volume proxies.
2. Calibrated Probability Estimation: Outputs out-of-sample directional probabilities.
3. High-Conviction Thresholding: Only fires trades when confidence exceeds threshold
   (e.g., probability >= 0.55). Remains FLAT when confidence is intermediate.
4. Dynamic ATR Brackets: Implements volatility-scaled Stop-Loss and Take-Profit.
"""

from decimal import Decimal
import logging
import os
import pickle
from typing import Any, Dict, List, Optional
import numpy as np

from bot.indicators import atr, bollinger_bands, ema, rsi
from bot.models import Kline, SignalType, TradeSignal
from bot.strategies.base import BaseStrategy

logger = logging.getLogger("trading_bot.strategies.ml_alpha")


class MLAlphaStrategy(BaseStrategy):
    """Machine Learning Alpha Strategy with Probability Thresholding."""

    def __init__(
        self,
        symbol: str,
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.55,
        sl_atr_mult: float = 2.0,
        tp_atr_mult: float = 4.0,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name="ML_Alpha_Classifier", symbol=symbol, params=params)
        self.confidence_threshold = float(self.params.get("confidence_threshold", confidence_threshold))
        self.sl_atr_mult = float(self.params.get("sl_atr_mult", sl_atr_mult))
        self.tp_atr_mult = float(self.params.get("tp_atr_mult", tp_atr_mult))
        self.model_path = self.params.get("model_path", model_path)

        # Models
        self.clf_long = None
        self.clf_short = None
        self._load_or_init_model()

    def _load_or_init_model(self) -> None:
        """Load pre-trained models from disk if available."""
        if not self.model_path:
            # Default lookup path
            candidate = os.path.join("models", f"{self.symbol.upper()}_ml.pkl")
            if os.path.exists(candidate):
                self.model_path = candidate

        if self.model_path and os.path.exists(self.model_path):
            try:
                with open(self.model_path, "rb") as f:
                    bundle = pickle.load(f)
                    self.clf_long = bundle.get("clf_long")
                    self.clf_short = bundle.get("clf_short")
                    logger.info("Loaded pre-trained ML models from %s", self.model_path)
            except Exception as exc:
                logger.warning("Could not load ML model from %s: %s", self.model_path, exc)

    def extract_features(self, klines: List[Kline]) -> Optional[np.ndarray]:
        """Extract stationary feature vector for the latest candle."""
        if len(klines) < 55:
            return None

        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        highs = np.array([float(k.high) for k in klines], dtype=np.float64)
        lows = np.array([float(k.low) for k in klines], dtype=np.float64)
        vols = np.array([float(k.volume) for k in klines], dtype=np.float64)

        i = len(closes) - 1

        # 1. Multi-scale log returns
        ret_1 = np.log(closes[i] / closes[i - 1]) if closes[i - 1] > 0 else 0.0
        ret_3 = np.log(closes[i] / closes[i - 3]) if closes[i - 3] > 0 else 0.0
        ret_8 = np.log(closes[i] / closes[i - 8]) if closes[i - 8] > 0 else 0.0
        ret_21 = np.log(closes[i] / closes[i - 21]) if closes[i - 21] > 0 else 0.0

        # 2. Moving average distance
        ema9 = ema(closes, 9)
        ema21 = ema(closes, 21)
        ema50 = ema(closes, 50)
        dist_9_21 = (ema9[i] - ema21[i]) / (closes[i] + 1e-8)
        dist_21_50 = (ema21[i] - ema50[i]) / (closes[i] + 1e-8)

        # 3. Volatility (ATR)
        atr_vals = atr(highs, lows, closes, 14)
        curr_atr = atr_vals[i]
        atr_pct = curr_atr / (closes[i] + 1e-8)

        # 4. Bollinger Bands
        bb_up, bb_mid, bb_low = bollinger_bands(closes, 20, 2.0)
        bb_width = (bb_up[i] - bb_low[i]) / (bb_mid[i] + 1e-8)
        bb_pct_b = (closes[i] - bb_low[i]) / (bb_up[i] - bb_low[i] + 1e-8)

        # 5. Momentum (RSI)
        rsi_vals = rsi(closes, 14)
        curr_rsi = rsi_vals[i]

        # 6. Volume Z-score
        vol_mean = np.mean(vols[-20:])
        vol_std = np.std(vols[-20:])
        vol_z = (vols[i] - vol_mean) / (vol_std + 1e-8)

        feat_vector = np.array([
            ret_1, ret_3, ret_8, ret_21,
            dist_9_21, dist_21_50,
            atr_pct, bb_width, bb_pct_b,
            curr_rsi, vol_z
        ], dtype=np.float64).reshape(1, -1)

        return feat_vector

    def on_candle(self, klines: List[Kline]) -> Optional[TradeSignal]:
        """Generate probability-filtered trade signal."""
        feat = self.extract_features(klines)
        if feat is None:
            return None

        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        highs = np.array([float(k.high) for k in klines], dtype=np.float64)
        lows = np.array([float(k.low) for k in klines], dtype=np.float64)
        atr_vals = atr(highs, lows, closes, 14)
        curr_atr = atr_vals[-1]

        if np.isnan(curr_atr) or curr_atr <= 0:
            return None

        curr_close = closes[-1]
        entry_dec = Decimal(str(round(curr_close, 4)))
        atr_dec = Decimal(str(round(curr_atr, 4)))
        sl_dist = atr_dec * Decimal(str(self.sl_atr_mult))
        tp_dist = atr_dec * Decimal(str(self.tp_atr_mult))
        timestamp = klines[-1].close_time

        # If model is loaded, evaluate predictions
        prob_long = 0.5
        prob_short = 0.5

        if self.clf_long is not None and self.clf_short is not None:
            try:
                prob_long = float(self.clf_long.predict_proba(feat)[0, 1])
                prob_short = float(self.clf_short.predict_proba(feat)[0, 1])
            except Exception as exc:
                logger.warning("ML prediction failed: %s", exc)
                return None
        else:
            # Fallback heuristic when model file is not present yet
            # Uses statistical factor combo: positive returns + momentum cross + healthy RSI
            ret_1 = feat[0, 0]
            ret_8 = feat[0, 2]
            dist_9_21 = feat[0, 4]
            curr_rsi = feat[0, 9]

            if dist_9_21 > 0 and ret_8 > 0 and 45 < curr_rsi < 65:
                prob_long = 0.60
            elif dist_9_21 < 0 and ret_8 < 0 and 35 < curr_rsi < 55:
                prob_short = 0.60

        # Filter by confidence threshold
        if prob_long >= self.confidence_threshold and prob_long > prob_short:
            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.BUY,
                entry_price=entry_dec,
                stop_loss=max(Decimal("0.0001"), entry_dec - sl_dist),
                take_profit=entry_dec + tp_dist,
                timestamp=timestamp,
                confidence=round(prob_long, 3),
                metadata={"prob_long": round(prob_long, 3), "prob_short": round(prob_short, 3)},
            )
        elif prob_short >= self.confidence_threshold and prob_short > prob_long:
            return TradeSignal(
                symbol=self.symbol,
                signal_type=SignalType.SELL,
                entry_price=entry_dec,
                stop_loss=entry_dec + sl_dist,
                take_profit=max(Decimal("0.0001"), entry_dec - tp_dist),
                timestamp=timestamp,
                confidence=round(prob_short, 3),
                metadata={"prob_long": round(prob_long, 3), "prob_short": round(prob_short, 3)},
            )

        return None
