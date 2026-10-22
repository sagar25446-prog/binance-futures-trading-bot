"""
Base Strategy Interface
=======================

Abstract base class for all algorithmic trading strategies.
Defines the lifecycle hooks:
- on_candle: Ingests new candlestick history and generates TradeSignals.
- get_state: Returns strategy-specific diagnostic and parameter state.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from bot.models import Kline, TradeSignal


class BaseStrategy(ABC):
    """Abstract trading strategy."""

    def __init__(self, name: str, symbol: str, params: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.symbol = symbol.upper()
        self.params = params or {}

    @abstractmethod
    def on_candle(self, klines: List[Kline]) -> Optional[TradeSignal]:
        """Process candlestick history and return an actionable TradeSignal if generated.

        Args:
            klines: List of Kline objects chronologically ordered (oldest to newest).

        Returns:
            TradeSignal if an entry or exit condition is met, else None.
        """
        pass

    def get_state(self) -> Dict[str, Any]:
        """Return diagnostic metrics and state dictionary."""
        return {
            "name": self.name,
            "symbol": self.symbol,
            "params": self.params,
        }
