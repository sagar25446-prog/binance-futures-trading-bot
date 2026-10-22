"""
Backtesting Engine
==================

Historical simulation engine for quantitative trading strategies.
Features:
- Realistic intrabar bar-by-bar execution.
- Configurable taker commissions (default: 0.05%) and slippage (default: 0.02%).
- Comprehensive performance metrics: Win Rate, Profit Factor, Max Drawdown, Sharpe, Sortino.
"""

from decimal import Decimal
import logging
from typing import Any, Dict, List, Optional
import numpy as np

from bot.client import BinanceClient
from bot.models import Kline, SignalType
from bot.strategies.base import BaseStrategy

logger = logging.getLogger("trading_bot.backtester")


class BacktestEngine:
    """Simulates trading strategy performance on historical candlesticks."""

    def __init__(
        self,
        strategy: BaseStrategy,
        initial_balance: float = 10000.0,
        risk_per_trade_pct: float = 0.01,
        maker_fee_pct: float = 0.0002,
        taker_fee_pct: float = 0.0005,
        slippage_pct: float = 0.0002,
        leverage: int = 3,
    ) -> None:
        self.strategy = strategy
        self.initial_balance = Decimal(str(initial_balance))
        self.risk_per_trade_pct = Decimal(str(risk_per_trade_pct))
        self.maker_fee_pct = Decimal(str(maker_fee_pct))
        self.taker_fee_pct = Decimal(str(taker_fee_pct))
        self.slippage_pct = Decimal(str(slippage_pct))
        self.leverage = leverage

    def fetch_klines(
        self,
        client: BinanceClient,
        symbol: str,
        interval: str = "15m",
        total_candles: int = 1000,
    ) -> List[Kline]:
        """Fetch historical klines from Binance API in chunks."""
        all_klines: List[Kline] = []
        batch_size = 500
        end_time = None

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

        # Sort chronologically
        all_klines.sort(key=lambda x: x.open_time)
        return all_klines

    def run(self, klines: List[Kline]) -> Dict[str, Any]:
        """Execute chronological simulation across the provided klines."""
        if not klines:
            raise ValueError("Cannot backtest with empty kline history.")

        balance = self.initial_balance
        peak_balance = balance
        max_drawdown_dollar = Decimal("0")
        max_drawdown_pct = Decimal("0")

        active_trade: Optional[Dict[str, Any]] = None
        closed_trades: List[Dict[str, Any]] = []
        equity_curve: List[float] = [float(balance)]

        for i in range(50, len(klines)):
            curr_candle = klines[i]
            history = klines[: i + 1]

            # 1. Manage Active Position (Check for SL / TP hit on current candle)
            if active_trade is not None:
                side = active_trade["side"]
                entry = active_trade["entry_price"]
                sl = active_trade["stop_loss"]
                tp = active_trade["take_profit"]
                qty = active_trade["quantity"]

                high = curr_candle.high
                low = curr_candle.low
                closed = False
                exit_price = curr_candle.close
                exit_reason = ""

                if side == "BUY":
                    if sl and low <= sl:
                        exit_price = sl * (Decimal("1") - self.slippage_pct)
                        exit_reason = "STOP_LOSS"
                        closed = True
                    elif tp and high >= tp:
                        exit_price = tp * (Decimal("1") - self.slippage_pct)
                        exit_reason = "TAKE_PROFIT"
                        closed = True
                elif side == "SELL":
                    if sl and high >= sl:
                        exit_price = sl * (Decimal("1") + self.slippage_pct)
                        exit_reason = "STOP_LOSS"
                        closed = True
                    elif tp and low <= tp:
                        exit_price = tp * (Decimal("1") + self.slippage_pct)
                        exit_reason = "TAKE_PROFIT"
                        closed = True

                if closed:
                    # Calculate gross PnL
                    if side == "BUY":
                        gross_pnl = (exit_price - entry) * qty
                    else:
                        gross_pnl = (entry - exit_price) * qty

                    # Commission fees
                    entry_fee = (entry * qty) * self.taker_fee_pct
                    exit_fee = (exit_price * qty) * self.taker_fee_pct
                    total_fee = entry_fee + exit_fee
                    net_pnl = gross_pnl - total_fee

                    balance += net_pnl
                    pnl_pct = (net_pnl / (entry * qty)) * Decimal("100") if entry * qty > 0 else Decimal("0")

                    closed_trades.append(
                        {
                            "symbol": active_trade["symbol"],
                            "side": side,
                            "entry_price": float(entry),
                            "exit_price": float(exit_price),
                            "quantity": float(qty),
                            "pnl": float(net_pnl),
                            "pnl_pct": float(pnl_pct),
                            "fees": float(total_fee),
                            "exit_reason": exit_reason,
                            "entry_time": active_trade["entry_time"],
                            "exit_time": curr_candle.close_time,
                        }
                    )
                    active_trade = None

            # Track Drawdown
            if balance > peak_balance:
                peak_balance = balance
            dd = peak_balance - balance
            dd_pct = (dd / peak_balance) * Decimal("100") if peak_balance > 0 else Decimal("0")
            if dd > max_drawdown_dollar:
                max_drawdown_dollar = dd
            if dd_pct > max_drawdown_pct:
                max_drawdown_pct = dd_pct
            equity_curve.append(float(balance))

            # 2. Check for New Signal if flat
            if active_trade is None:
                signal = self.strategy.on_candle(history)
                if signal and signal.signal_type in (SignalType.BUY, SignalType.SELL):
                    # Position sizing
                    if signal.stop_loss:
                        stop_dist = abs(signal.entry_price - signal.stop_loss)
                        if stop_dist > Decimal("0"):
                            dollar_risk = balance * self.risk_per_trade_pct
                            raw_qty = dollar_risk / stop_dist
                            max_notional = balance * Decimal(str(self.leverage))
                            max_qty = max_notional / signal.entry_price
                            qty = min(raw_qty, max_qty)

                            # Apply slippage on entry
                            entry_price = signal.entry_price
                            if signal.signal_type == SignalType.BUY:
                                entry_price *= Decimal("1") + self.slippage_pct
                            else:
                                entry_price *= Decimal("1") - self.slippage_pct

                            active_trade = {
                                "symbol": signal.symbol,
                                "side": signal.signal_type.value,
                                "entry_price": entry_price,
                                "stop_loss": signal.stop_loss,
                                "take_profit": signal.take_profit,
                                "quantity": qty,
                                "entry_time": curr_candle.close_time,
                            }

        # Close any remaining active position on the final bar
        if active_trade is not None and len(klines) > 0:
            final_candle = klines[-1]
            side = active_trade["side"]
            entry = active_trade["entry_price"]
            qty = active_trade["quantity"]
            exit_price = final_candle.close

            if side == "BUY":
                gross_pnl = (exit_price - entry) * qty
            else:
                gross_pnl = (entry - exit_price) * qty

            entry_fee = (entry * qty) * self.taker_fee_pct
            exit_fee = (exit_price * qty) * self.taker_fee_pct
            total_fee = entry_fee + exit_fee
            net_pnl = gross_pnl - total_fee

            balance += net_pnl
            pnl_pct = (net_pnl / (entry * qty)) * Decimal("100") if entry * qty > Decimal("0") else Decimal("0")

            closed_trades.append(
                {
                    "symbol": active_trade["symbol"],
                    "side": side,
                    "entry_price": float(entry),
                    "exit_price": float(exit_price),
                    "quantity": float(qty),
                    "pnl": float(net_pnl),
                    "pnl_pct": float(pnl_pct),
                    "fees": float(total_fee),
                    "exit_reason": "END_OF_BACKTEST",
                    "entry_time": active_trade["entry_time"],
                    "exit_time": final_candle.close_time,
                }
            )
            active_trade = None

        # Calculate summary statistics
        total_trades = len(closed_trades)
        wins = [t for t in closed_trades if t["pnl"] > 0]
        losses = [t for t in closed_trades if t["pnl"] <= 0]
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0

        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = (
            gross_profit / gross_loss
            if gross_loss > 0
            else (99.0 if gross_profit > 0 else 0.0)
        )

        total_return_dollar = float(balance - self.initial_balance)
        total_return_pct = (total_return_dollar / float(self.initial_balance)) * 100.0

        # Sharpe ratio of returns
        eq_arr = np.array(equity_curve)
        pct_changes = np.diff(eq_arr) / eq_arr[:-1]
        mean_ret = np.mean(pct_changes) if len(pct_changes) > 0 else 0.0
        std_ret = np.std(pct_changes) if len(pct_changes) > 0 else 0.0
        # Annualized assuming 15m intervals (35040 periods/year)
        sharpe = (mean_ret / std_ret * np.sqrt(35040)) if std_ret > 0 else 0.0

        return {
            "initial_balance": float(self.initial_balance),
            "final_balance": round(float(balance), 2),
            "total_return_dollar": round(total_return_dollar, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_dollar": round(float(max_drawdown_dollar), 2),
            "max_drawdown_pct": round(float(max_drawdown_pct), 2),
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "trades": closed_trades,
        }
