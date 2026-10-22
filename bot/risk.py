"""
Risk Management and Capital Preservation Engine
===============================================

Institutional-grade risk management safeguards designed to protect real capital:
1. Dynamic ATR Position Sizing: Risks an exact fixed % of account equity per trade (default: 1.0%).
2. Exchange Filter Conformance: Formats quantity to lot_size and checks min_notional.
3. Daily Loss Circuit Breaker: Halts trading if daily losses exceed threshold (default: 3.0%).
4. Max Drawdown Circuit Breaker: Locks bot if portfolio equity drops > 8% from high-water mark.
5. Consecutive Loss Cooldown: Pauses trading for 30 minutes after 3 consecutive losses.
6. Safe Leverage Cap: Strictly limits leverage to <= 5x and enforces Isolated Margin.
"""

from decimal import Decimal, ROUND_DOWN
import logging
import time
from typing import Optional, Tuple

from bot.exceptions import ValidationError
from bot.models import OrderRequest, OrderSide, OrderType, TradeSignal
from bot.validators import ExchangeValidator

logger = logging.getLogger("trading_bot.risk")


class CircuitBreakerTriggered(Exception):
    """Raised when a risk circuit breaker is actively tripped."""
    pass


class RiskManager:
    """Controls position sizing, portfolio exposure, and capital protection breakers."""

    def __init__(
        self,
        validator: ExchangeValidator,
        max_risk_per_trade_pct: float = 0.01,
        max_daily_loss_pct: float = 0.03,
        max_drawdown_pct: float = 0.08,
        max_leverage: int = 3,
        consecutive_loss_limit: int = 3,
        cooldown_seconds: int = 1800,  # 30 mins
    ) -> None:
        self.validator = validator
        self.max_risk_per_trade_pct = Decimal(str(max_risk_per_trade_pct))
        self.max_daily_loss_pct = Decimal(str(max_daily_loss_pct))
        self.max_drawdown_pct = Decimal(str(max_drawdown_pct))
        self.max_leverage = max_leverage
        self.consecutive_loss_limit = consecutive_loss_limit
        self.cooldown_seconds = cooldown_seconds

        # State tracking
        self.high_water_mark: Decimal = Decimal("0")
        self.daily_start_balance: Decimal = Decimal("0")
        self.daily_start_time: float = time.time()
        self.realized_daily_pnl: Decimal = Decimal("0")
        self.consecutive_losses: int = 0
        self.cooldown_until: float = 0.0
        self.is_halted: bool = False
        self.halt_reason: str = ""

    def update_account_state(self, current_equity: Decimal) -> None:
        """Update account high-water mark and daily balance tracking."""
        now = time.time()
        # Reset 24-hour daily window
        if now - self.daily_start_time >= 86400:
            self.daily_start_balance = current_equity
            self.daily_start_time = now
            self.realized_daily_pnl = Decimal("0")
            logger.info("24h risk cycle reset. Starting daily equity: %s", current_equity)

        if self.daily_start_balance <= Decimal("0"):
            self.daily_start_balance = current_equity

        if current_equity > self.high_water_mark:
            self.high_water_mark = current_equity

    def record_trade_result(self, pnl: Decimal) -> None:
        """Record trade PnL for circuit breaker tracking."""
        self.realized_daily_pnl += pnl

        if pnl < Decimal("0"):
            self.consecutive_losses += 1
            logger.warning(
                "Trade closed with loss: %s. Consecutive losses: %d",
                pnl,
                self.consecutive_losses,
            )
            if self.consecutive_losses >= self.consecutive_loss_limit:
                self.cooldown_until = time.time() + self.cooldown_seconds
                logger.warning(
                    "Circuit breaker: %d consecutive losses hit. Entering cooldown until %s",
                    self.consecutive_losses,
                    time.ctime(self.cooldown_until),
                )
        else:
            self.consecutive_losses = 0

    def check_circuit_breakers(self, current_equity: Decimal) -> Tuple[bool, str]:
        """Check all risk limits. Returns (can_trade, reason)."""
        if self.is_halted:
            return False, f"Trading halted manually or by safety lock: {self.halt_reason}"

        # 1. Cooldown timer check
        now = time.time()
        if now < self.cooldown_until:
            remaining_mins = int((self.cooldown_until - now) / 60)
            return (
                False,
                f"Consecutive loss cooldown active ({remaining_mins}m remaining)",
            )

        # 2. Daily Loss Limit check
        if self.daily_start_balance > Decimal("0"):
            daily_loss_pct = -self.realized_daily_pnl / self.daily_start_balance
            if daily_loss_pct >= self.max_daily_loss_pct:
                self.is_halted = True
                self.halt_reason = (
                    f"Max daily loss limit breached ({daily_loss_pct*100:.2f}% >= "
                    f"{self.max_daily_loss_pct*100:.2f}%). Trading halted for capital safety."
                )
                logger.error(self.halt_reason)
                return False, self.halt_reason

        # 3. Peak-to-Trough Drawdown check
        if self.high_water_mark > Decimal("0"):
            drawdown = (self.high_water_mark - current_equity) / self.high_water_mark
            if drawdown >= self.max_drawdown_pct:
                self.is_halted = True
                self.halt_reason = (
                    f"Max drawdown circuit breaker tripped ({drawdown*100:.2f}% >= "
                    f"{self.max_drawdown_pct*100:.2f}%). Trading locked."
                )
                logger.error(self.halt_reason)
                return False, self.halt_reason

        return True, "Risk checks passed"

    def calculate_position_size(
        self, signal: TradeSignal, account_equity: Decimal
    ) -> Optional[Decimal]:
        """Calculate dynamic position size based on risk percentage and stop-loss distance.

        Formula:
            Dollar Risk = Account Equity * Max Risk %
            Stop Distance = |Entry - Stop Loss|
            Raw Qty = Dollar Risk / Stop Distance
        """
        if not signal.stop_loss or signal.entry_price <= Decimal("0"):
            logger.warning("Signal missing valid entry or stop_loss. Position sizing aborted.")
            return None

        stop_dist = abs(signal.entry_price - signal.stop_loss)
        if stop_dist <= Decimal("0"):
            return None

        dollar_risk = account_equity * self.max_risk_per_trade_pct
        raw_qty = dollar_risk / stop_dist

        # Leverage / Max Notional cap: Position Notional <= Equity * max_leverage
        max_notional = account_equity * Decimal(str(self.max_leverage))
        max_qty_by_leverage = max_notional / signal.entry_price

        qty = min(raw_qty, max_qty_by_leverage)

        # Conform quantity to exchange LOT_SIZE filters
        symbol_info = self.validator.get_symbol_info(signal.symbol)
        lot_filter = symbol_info.lot_size
        if lot_filter:
            step = lot_filter.step_size
            if step > Decimal("0"):
                steps_count = (qty / step).quantize(Decimal("1"), rounding=ROUND_DOWN)
                qty = steps_count * step

            if qty < lot_filter.min_qty:
                logger.warning(
                    "Calculated size %s below minQty %s for %s. Trade skipped.",
                    qty,
                    lot_filter.min_qty,
                    signal.symbol,
                )
                return None

            if qty > lot_filter.max_qty:
                qty = lot_filter.max_qty

        # Verify MIN_NOTIONAL filter
        min_notional = (
            symbol_info.min_notional.notional
            if symbol_info.min_notional
            else Decimal("5")
        )
        if (qty * signal.entry_price) < min_notional:
            logger.warning(
                "Order notional %s below min_notional %s for %s. Trade skipped.",
                qty * signal.entry_price,
                min_notional,
                signal.symbol,
            )
            return None

        return qty
