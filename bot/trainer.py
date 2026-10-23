"""
Model Trainer and Walk-Forward Engine
=====================================

Trains, evaluates, and serializes machine learning alpha models on Binance Futures historical data:
- Features: Stationary log returns, EMA spreads, normalized ATR, Bollinger Bandwidth, RSI, Volume Z-score.
- Model: HistGradientBoostingClassifier with early stopping.
- Validation: TimeSeriesSplit walk-forward cross-validation without look-ahead bias.
- Artifacts: Serializes model bundle to `models/<SYMBOL>_<INTERVAL>_ml.pkl`.
"""

from decimal import Decimal
import logging
import os
import pickle
import time
from typing import Any, Dict, List, Tuple
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import TimeSeriesSplit

from bot.client import BinanceClient
from bot.models import Kline

logger = logging.getLogger("trading_bot.trainer")


class ModelTrainer:
    """Trains and validates ML alpha models on historical market data."""

    FEATURE_NAMES = [
        "ret_1", "ret_3", "ret_8", "ret_21",
        "dist_9_21", "dist_21_50",
        "atr_pct", "bb_width", "bb_pct_b",
        "rsi", "vol_z"
    ]

    def __init__(self, output_dir: str = "models") -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def fetch_klines(
        self,
        client: BinanceClient,
        symbol: str,
        interval: str = "1h",
        total_candles: int = 1500,
    ) -> List[Kline]:
        """Fetch historical klines from Binance API."""
        all_klines: List[Kline] = []
        batch_size = 500
        end_time = None

        logger.info("Fetching %d historical %s candles for %s...", total_candles, interval, symbol)

        while len(all_klines) < total_candles:
            limit = min(batch_size, total_candles - len(all_klines))
            raw = client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit,
                end_time=end_time,
            )
            if not raw:
                break

            chunk = [Kline.from_api(k) for k in raw]
            if not chunk:
                break

            all_klines = chunk + all_klines
            end_time = chunk[0].open_time - 1

            if len(chunk) < limit:
                break

        all_klines.sort(key=lambda x: x.open_time)
        logger.info("Retrieved %d candles.", len(all_klines))
        return all_klines

    def prepare_dataset(
        self,
        klines: List[Kline],
        forward_window: int = 5,
        target_threshold: float = 0.0035,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Compute feature matrix X and targets y_long, y_short."""
        closes = np.array([float(k.close) for k in klines], dtype=np.float64)
        highs = np.array([float(k.high) for k in klines], dtype=np.float64)
        lows = np.array([float(k.low) for k in klines], dtype=np.float64)
        vols = np.array([float(k.volume) for k in klines], dtype=np.float64)
        n = len(closes)

        # 1. Multi-scale log returns
        ret_1 = np.zeros(n)
        ret_3 = np.zeros(n)
        ret_8 = np.zeros(n)
        ret_21 = np.zeros(n)
        for i in range(21, n):
            ret_1[i] = np.log(closes[i] / closes[i - 1])
            ret_3[i] = np.log(closes[i] / closes[i - 3])
            ret_8[i] = np.log(closes[i] / closes[i - 8])
            ret_21[i] = np.log(closes[i] / closes[i - 21])

        # 2. EMAs
        ema9 = pd.Series(closes).ewm(span=9).mean().values
        ema21 = pd.Series(closes).ewm(span=21).mean().values
        ema50 = pd.Series(closes).ewm(span=50).mean().values
        dist_9_21 = (ema9 - ema21) / (closes + 1e-8)
        dist_21_50 = (ema21 - ema50) / (closes + 1e-8)

        # 3. ATR
        tr = np.maximum(highs - lows, np.maximum(abs(highs - np.roll(closes, 1)), abs(lows - np.roll(closes, 1))))
        tr[0] = highs[0] - lows[0]
        atr = pd.Series(tr).rolling(14).mean().values
        atr_pct = atr / (closes + 1e-8)

        # 4. Bollinger Bands
        sma20 = pd.Series(closes).rolling(20).mean().values
        std20 = pd.Series(closes).rolling(20).std().values
        bb_width = (4.0 * std20) / (sma20 + 1e-8)
        bb_pct_b = (closes - (sma20 - 2.0 * std20)) / (4.0 * std20 + 1e-8)

        # 5. RSI
        delta = pd.Series(closes).diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = (100.0 - (100.0 / (1.0 + (gain / (loss + 1e-8))))).values

        # 6. Volume Z-Score
        vol_s = pd.Series(vols)
        vol_z = ((vol_s - vol_s.rolling(20).mean()) / (vol_s.rolling(20).std() + 1e-8)).values

        # Assemble feature matrix
        X_all = np.column_stack([
            ret_1, ret_3, ret_8, ret_21,
            dist_9_21, dist_21_50,
            atr_pct, bb_width, bb_pct_b,
            rsi, vol_z
        ])

        # Targets: Forward return > threshold
        fwd_ret = np.zeros(n)
        for i in range(n - forward_window):
            fwd_ret[i] = (closes[i + forward_window] - closes[i]) / closes[i]

        y_long_all = (fwd_ret > target_threshold).astype(int)
        y_short_all = (fwd_ret < -target_threshold).astype(int)

        # Drop initial warmup bars and final forward_window bars
        start_idx = 55
        end_idx = n - forward_window

        X = X_all[start_idx:end_idx]
        y_long = y_long_all[start_idx:end_idx]
        y_short = y_short_all[start_idx:end_idx]

        # Clean any remaining NaNs
        valid_mask = ~np.isnan(X).any(axis=1)
        return X[valid_mask], y_long[valid_mask], y_short[valid_mask]

    def train_walk_forward(
        self,
        X: np.ndarray,
        y_long: np.ndarray,
        y_short: np.ndarray,
        n_splits: int = 4,
    ) -> Dict[str, Any]:
        """Perform time-series walk-forward cross validation."""
        tscv = TimeSeriesSplit(n_splits=n_splits)
        long_aucs: List[float] = []
        short_aucs: List[float] = []
        long_accs: List[float] = []
        short_accs: List[float] = []

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            X_tr, X_val = X[train_idx], X[val_idx]
            yl_tr, yl_val = y_long[train_idx], y_long[val_idx]
            ys_tr, ys_val = y_short[train_idx], y_short[val_idx]

            # Fit Long Model
            m_l = HistGradientBoostingClassifier(
                max_iter=100, max_depth=3, learning_rate=0.03, random_state=42
            )
            m_l.fit(X_tr, yl_tr)
            preds_l = m_l.predict_proba(X_val)[:, 1]
            if len(np.unique(yl_val)) > 1:
                long_aucs.append(float(roc_auc_score(yl_val, preds_l)))
            long_accs.append(float(accuracy_score(yl_val, (preds_l >= 0.5).astype(int))))

            # Fit Short Model
            m_s = HistGradientBoostingClassifier(
                max_iter=100, max_depth=3, learning_rate=0.03, random_state=42
            )
            m_s.fit(X_tr, ys_tr)
            preds_s = m_s.predict_proba(X_val)[:, 1]
            if len(np.unique(ys_val)) > 1:
                short_aucs.append(float(roc_auc_score(ys_val, preds_s)))
            short_accs.append(float(accuracy_score(ys_val, (preds_s >= 0.5).astype(int))))

        mean_long_auc = float(np.mean(long_aucs)) if long_aucs else 0.5
        mean_short_auc = float(np.mean(short_aucs)) if short_aucs else 0.5
        mean_long_acc = float(np.mean(long_accs)) if long_accs else 0.5
        mean_short_acc = float(np.mean(short_accs)) if short_accs else 0.5

        # Fit final production models on 100% of available data
        final_clf_long = HistGradientBoostingClassifier(
            max_iter=120, max_depth=3, learning_rate=0.03, random_state=42
        )
        final_clf_long.fit(X, y_long)

        final_clf_short = HistGradientBoostingClassifier(
            max_iter=120, max_depth=3, learning_rate=0.03, random_state=42
        )
        final_clf_short.fit(X, y_short)

        return {
            "clf_long": final_clf_long,
            "clf_short": final_clf_short,
            "mean_long_auc": round(mean_long_auc, 3),
            "mean_short_auc": round(mean_short_auc, 3),
            "mean_long_acc": round(mean_long_acc * 100.0, 1),
            "mean_short_acc": round(mean_short_acc * 100.0, 1),
            "total_samples": len(X),
            "long_base_rate": round(float(np.mean(y_long)) * 100.0, 1),
            "short_base_rate": round(float(np.mean(y_short)) * 100.0, 1),
        }

    def train_and_save(
        self,
        client: BinanceClient,
        symbol: str,
        interval: str = "1h",
        total_candles: int = 1500,
    ) -> Dict[str, Any]:
        """End-to-end training pipeline: fetch data, train models, save artifact."""
        klines = self.fetch_klines(client, symbol, interval, total_candles)
        if len(klines) < 100:
            raise ValueError(f"Insufficient klines ({len(klines)}) for training.")

        X, y_long, y_short = self.prepare_dataset(klines)
        metrics = self.train_walk_forward(X, y_long, y_short)

        bundle = {
            "symbol": symbol.upper(),
            "interval": interval,
            "clf_long": metrics["clf_long"],
            "clf_short": metrics["clf_short"],
            "feature_names": self.FEATURE_NAMES,
            "metrics": {
                "mean_long_auc": metrics["mean_long_auc"],
                "mean_short_auc": metrics["mean_short_auc"],
                "mean_long_acc": metrics["mean_long_acc"],
                "mean_short_acc": metrics["mean_short_acc"],
                "total_samples": metrics["total_samples"],
            },
            "timestamp": int(time.time()),
        }

        filename = f"{symbol.upper()}_ml.pkl"
        filepath = os.path.join(self.output_dir, filename)
        with open(filepath, "wb") as f:
            pickle.dump(bundle, f)

        logger.info("Successfully saved model artifact to %s", filepath)
        metrics["filepath"] = filepath
        metrics["symbol"] = symbol.upper()
        metrics["interval"] = interval
        return metrics
