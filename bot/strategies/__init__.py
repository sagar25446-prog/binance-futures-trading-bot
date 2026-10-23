"""
Strategy Registry
=================

Exposes available quantitative strategies and a helper factory.
Supports:
- Trend Following (EMA Trend + ATR)
- Mean Reversion (Bollinger Bands + RSI)
- Adaptive Dual-Regime (Dynamic ADX Regime Switching)
- Machine Learning Alpha (HistGradientBoosting Probability Classifier)
"""

from typing import Any, Dict, List, Type
from bot.strategies.adaptive_regime import AdaptiveRegimeStrategy
from bot.strategies.base import BaseStrategy
from bot.strategies.mean_reversion import BollingerRSIStrategy
from bot.strategies.ml_alpha import MLAlphaStrategy
from bot.strategies.trend_following import EMATrendATRStrategy

STRATEGY_REGISTRY: Dict[str, Type[BaseStrategy]] = {
    "trend": EMATrendATRStrategy,
    "ema_trend": EMATrendATRStrategy,
    "mean_reversion": BollingerRSIStrategy,
    "bollinger_rsi": BollingerRSIStrategy,
    "adaptive_regime": AdaptiveRegimeStrategy,
    "adaptive": AdaptiveRegimeStrategy,
    "ml_alpha": MLAlphaStrategy,
    "ml": MLAlphaStrategy,
}


def get_strategy(
    name: str, symbol: str, params: Dict[str, Any] = None
) -> BaseStrategy:
    """Factory function to instantiate a strategy by name.

    Args:
        name: Strategy name (e.g. 'adaptive_regime', 'ml_alpha', 'trend', 'mean_reversion').
        symbol: Trading pair symbol.
        params: Optional hyperparameter overrides.

    Returns:
        Configured BaseStrategy instance.

    Raises:
        ValueError: If strategy name is unknown.
    """
    key = name.lower().strip()
    if key not in STRATEGY_REGISTRY:
        valid = ", ".join(sorted(set(STRATEGY_REGISTRY.keys())))
        raise ValueError(f"Unknown strategy '{name}'. Available: {valid}")

    strat_cls = STRATEGY_REGISTRY[key]
    return strat_cls(symbol=symbol, params=params)


def list_strategies() -> List[Dict[str, str]]:
    """List available strategies with descriptions."""
    return [
        {
            "id": "adaptive_regime",
            "name": "Adaptive Dual-Regime Strategy",
            "description": (
                "Dynamic volatility regime switcher: deploys high-R:R trend following "
                "in trending markets (ADX >= 22) and Bollinger-RSI scalping in ranging "
                "markets (ADX <= 20). Avoids chop entirely."
            ),
            "best_for": "All crypto futures (1h/4h), high-beta pairs (SOL, BNB, AVAX).",
        },
        {
            "id": "ml_alpha",
            "name": "Machine Learning Alpha Classifier",
            "description": (
                "HistGradientBoosting probability classifier trained via walk-forward validation. "
                "Only enters when out-of-sample directional confidence exceeds threshold."
            ),
            "best_for": "Algorithmic execution with statistical probability filtering.",
        },
        {
            "id": "trend",
            "name": "EMA Trend + ATR Trailing Stop",
            "description": (
                "Multi-timeframe trend following using EMA 9/21 cross, "
                "200 EMA macro filter, ADX trend strength, and ATR trailing stop."
            ),
            "best_for": "Trending markets, major momentum shifts (15m/1h/4h).",
        },
        {
            "id": "mean_reversion",
            "name": "Bollinger Bands + RSI Mean Reversion",
            "description": (
                "Oscillator scalper trading oversold bounces and overbought "
                "rejections back to the 20 SMA middle band."
            ),
            "best_for": "Sideways, oscillating, or range-bound consolidation (5m/15m).",
        },
    ]


__all__ = [
    "BaseStrategy",
    "EMATrendATRStrategy",
    "BollingerRSIStrategy",
    "AdaptiveRegimeStrategy",
    "MLAlphaStrategy",
    "get_strategy",
    "list_strategies",
    "STRATEGY_REGISTRY",
]
