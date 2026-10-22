"""
Autonomous Trading Engine
=========================

The central operational engine that executes quantitative strategies in real time.
Supports:
- Dual Modes: Paper trading simulation and Live real-money futures execution.
- Automated Stop-Loss & Take-Profit bracket order management.
- Dynamic Trailing Stop adjustments.
- Real-time circuit breaker enforcement and telemetry reporting.
"""

from decimal import Decimal
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from bot.client import BinanceClient
from bot.models import (
    Kline,
    OrderRequest,
    OrderSide,
    OrderType,
    SignalType,
    TradeRecord,
    TradeSignal,
    TradingMode,
)
from bot.orders import OrderManager
from bot.risk import RiskManager
from bot.storage import Storage
from bot.strategies.base import BaseStrategy

logger = logging.getLogger("trading_bot.engine")


class TradingEngine:
    """Orchestrates automated trading loops, strategy evaluation, and order routing."""

    def __init__(
        self,
        client: BinanceClient,
        strategy: BaseStrategy,
        risk_manager: RiskManager,
        storage: Storage,
        symbol: str,
        interval: str = "15m",
        mode: TradingMode = TradingMode.PAPER,
        paper_initial_balance: float = 10000.0,
        leverage: int = 3,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        self.client = client
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.storage = storage
        self.symbol = symbol.upper()
        self.interval = interval
        self.mode = mode
        self.poll_interval = poll_interval_seconds
        self.leverage = leverage

        self.order_manager = OrderManager(client)
        self.running = False

        # Paper trading virtual account
        self.paper_balance = Decimal(str(paper_initial_balance))
        self.paper_position: Optional[Dict[str, Any]] = None

        # Statistics
        self.last_candle_time: int = 0
        self.last_price: Decimal = Decimal("0")
        self.status_message: str = "Initialized"

    def setup_exchange(self) -> None:
        """Configure margin mode and leverage on Binance for live trading."""
        if self.mode == TradingMode.LIVE:
            logger.info("Setting up exchange for %s: ISOLATED margin, %dx leverage", self.symbol, self.leverage)
            try:
                self.client.set_margin_type(self.symbol, "ISOLATED")
            except Exception as exc:
                logger.warning("Margin type setting note: %s", exc)

            try:
                self.client.set_leverage(self.symbol, self.leverage)
            except Exception as exc:
                logger.warning("Leverage setting note: %s", exc)

    def get_equity(self) -> Decimal:
        """Get current total account equity (Balance + Unrealized PnL)."""
        if self.mode == TradingMode.PAPER:
            unrealized = Decimal("0")
            if self.paper_position and self.last_price > Decimal("0"):
                entry = self.paper_position["entry_price"]
                qty = self.paper_position["quantity"]
                side = self.paper_position["side"]
                if side == "BUY":
                    unrealized = (self.last_price - entry) * qty
                else:
                    unrealized = (entry - self.last_price) * qty
            return self.paper_balance + unrealized
        else:
            acc = self.client.get_account_info()
            total_equity = acc.get("totalMarginBalance") or acc.get("totalWalletBalance") or "0"
            return Decimal(str(total_equity))

    def step(self) -> Dict[str, Any]:
        """Perform a single real-time polling step: update prices, evaluate SL/TP, generate signals."""
        try:
            # 1. Fetch current price
            ticker_info = self.client.get_ticker_price(self.symbol)
            self.last_price = Decimal(str(ticker_info["price"]))

            # 2. Update equity & circuit breakers
            current_equity = self.get_equity()
            self.risk_manager.update_account_state(current_equity)

            # 3. Check open positions / SL & TP
            self._manage_open_position()

            # 4. Check circuit breakers
            can_trade, reason = self.risk_manager.check_circuit_breakers(current_equity)
            if not can_trade:
                self.status_message = f"CIRCUIT BREAKER: {reason}"
                return self.get_telemetry()

            # 5. Fetch klines & check for new strategy signals if flat
            has_pos = self._has_open_position()
            if not has_pos:
                raw_klines = self.client.get_klines(
                    symbol=self.symbol,
                    interval=self.interval,
                    limit=250,
                )
                klines = [Kline.from_api(k) for k in raw_klines]
                if klines:
                    self.last_candle_time = klines[-1].close_time
                    signal = self.strategy.on_candle(klines)
                    if signal and signal.signal_type in (SignalType.BUY, SignalType.SELL):
                        self._execute_signal(signal, current_equity)
                    else:
                        self.status_message = "Scanning market... No signal."
            else:
                self.status_message = "Managing active position."

        except Exception as exc:
            logger.error("Engine step error: %s", exc, exc_info=True)
            self.status_message = f"Error: {exc}"

        return self.get_telemetry()

    def _has_open_position(self) -> bool:
        if self.mode == TradingMode.PAPER:
            return self.paper_position is not None
        else:
            positions = self.client.get_positions(self.symbol)
            pos = next((p for p in positions if p.get("symbol") == self.symbol), None)
            return pos is not None and abs(float(pos.get("positionAmt", 0))) > 1e-8

    def _manage_open_position(self) -> None:
        """Check for stop-loss and take-profit conditions in paper mode."""
        if self.mode != TradingMode.PAPER or self.paper_position is None:
            return

        pos = self.paper_position
        side = pos["side"]
        entry = pos["entry_price"]
        sl = pos["stop_loss"]
        tp = pos["take_profit"]
        qty = pos["quantity"]

        exit_triggered = False
        exit_reason = ""
        exit_price = self.last_price

        if side == "BUY":
            if sl and self.last_price <= sl:
                exit_triggered = True
                exit_reason = "STOP_LOSS"
            elif tp and self.last_price >= tp:
                exit_triggered = True
                exit_reason = "TAKE_PROFIT"
        elif side == "SELL":
            if sl and self.last_price >= sl:
                exit_triggered = True
                exit_reason = "STOP_LOSS"
            elif tp and self.last_price <= tp:
                exit_triggered = True
                exit_reason = "TAKE_PROFIT"

        if exit_triggered:
            if side == "BUY":
                gross_pnl = (exit_price - entry) * qty
            else:
                gross_pnl = (entry - exit_price) * qty

            fee = (exit_price * qty) * Decimal("0.0005")
            net_pnl = gross_pnl - fee
            pnl_pct = (net_pnl / (entry * qty)) * Decimal("100")

            self.paper_balance += net_pnl
            self.risk_manager.record_trade_result(net_pnl)

            self.storage.record_trade_exit(
                trade_id=pos["trade_id"],
                exit_price=exit_price,
                pnl=net_pnl,
                pnl_pct=pnl_pct,
                fee=fee,
                status=f"CLOSED_{exit_reason}",
            )

            logger.info(
                "Paper position closed (%s) at %s | Net PnL: %s (%s%%)",
                exit_reason,
                exit_price,
                net_pnl,
                pnl_pct,
            )
            self.paper_position = None

    def _execute_signal(self, signal: TradeSignal, current_equity: Decimal) -> None:
        """Size and execute a strategy signal."""
        qty = self.risk_manager.calculate_position_size(signal, current_equity)
        if not qty or qty <= Decimal("0"):
            self.status_message = "Signal generated but position size <= 0 or rejected by risk."
            return

        logger.info(
            "Executing %s %s signal: qty=%s, entry=%s, sl=%s, tp=%s",
            self.mode.value,
            signal.signal_type.value,
            qty,
            signal.entry_price,
            signal.stop_loss,
            signal.take_profit,
        )

        trade_id = str(uuid.uuid4())[:8]

        if self.mode == TradingMode.PAPER:
            fee = (signal.entry_price * qty) * Decimal("0.0005")
            self.paper_balance -= fee
            self.paper_position = {
                "trade_id": trade_id,
                "symbol": self.symbol,
                "side": signal.signal_type.value,
                "entry_price": signal.entry_price,
                "quantity": qty,
                "stop_loss": signal.stop_loss,
                "take_profit": signal.take_profit,
                "entry_time": int(time.time() * 1000),
            }

            self.storage.record_trade_entry(
                TradeRecord(
                    trade_id=trade_id,
                    symbol=self.symbol,
                    side=signal.signal_type.value,
                    entry_price=signal.entry_price,
                    quantity=qty,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    fee=fee,
                    entry_time=int(time.time() * 1000),
                    status="OPEN",
                    mode="paper",
                )
            )
            self.status_message = f"Entered {signal.signal_type.value} position (Paper)"

        else:
            # LIVE EXECUTION
            side = OrderSide.BUY if signal.signal_type == SignalType.BUY else OrderSide.SELL
            req = OrderRequest(
                symbol=self.symbol,
                side=side,
                order_type=OrderType.MARKET,
                quantity=qty,
            )
            order_res = self.order_manager.place_order(req)

            # Place Stop Loss Algo Order
            if signal.stop_loss:
                sl_side = "SELL" if side == OrderSide.BUY else "BUY"
                sl_params = {
                    "symbol": self.symbol,
                    "side": sl_side,
                    "type": "STOP_MARKET",
                    "stopPrice": str(signal.stop_loss),
                    "closePosition": "true",
                }
                try:
                    self.client.place_order(sl_params)
                    logger.info("Live Stop-Loss placed at %s", signal.stop_loss)
                except Exception as exc:
                    logger.error("Failed to place live Stop-Loss: %s", exc)

            # Place Take Profit Algo Order
            if signal.take_profit:
                tp_side = "SELL" if side == OrderSide.BUY else "BUY"
                tp_params = {
                    "symbol": self.symbol,
                    "side": tp_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(signal.take_profit),
                    "closePosition": "true",
                }
                try:
                    self.client.place_order(tp_params)
                    logger.info("Live Take-Profit placed at %s", signal.take_profit)
                except Exception as exc:
                    logger.error("Failed to place live Take-Profit: %s", exc)

            self.status_message = f"Entered {side.value} position (Live orderId={order_res.order_id})"

    def panic_close_all(self) -> Dict[str, Any]:
        """Emergency Kill Switch: Flatten positions and cancel all open orders."""
        logger.warning("PANIC KILL SWITCH TRIGGERED for %s", self.symbol)
        results = {"symbol": self.symbol, "cancelled_orders": 0, "positions_closed": False}

        if self.mode == TradingMode.PAPER:
            if self.paper_position:
                self.paper_position = None
                results["positions_closed"] = True
            self.status_message = "Emergency Kill Switch: Paper position flattened."
            return results

        # Live Emergency Exit
        try:
            # 1. Cancel standard open orders
            open_orders = self.client.get_open_orders(self.symbol)
            for o in open_orders:
                oid = o.get("orderId")
                if oid:
                    self.client.cancel_order(self.symbol, oid)
                    results["cancelled_orders"] += 1

            # 2. Cancel conditional algo orders
            algo_orders = self.client.get_open_algo_orders(self.symbol)
            for a in algo_orders:
                aid = a.get("algoId")
                if aid:
                    self.client.cancel_algo_order(self.symbol, aid)
                    results["cancelled_orders"] += 1

            # 3. Market close active position
            pos_res = self.client.close_position(self.symbol)
            if pos_res:
                results["positions_closed"] = True

            self.status_message = "Emergency Kill Switch: All orders cancelled and position closed."
        except Exception as exc:
            logger.error("Panic close error: %s", exc)
            self.status_message = f"Panic Error: {exc}"

        return results

    def get_telemetry(self) -> Dict[str, Any]:
        """Telemetry snapshot for terminal dashboard."""
        equity = self.get_equity()
        open_pos = None

        if self.mode == TradingMode.PAPER and self.paper_position:
            entry = self.paper_position["entry_price"]
            qty = self.paper_position["quantity"]
            side = self.paper_position["side"]
            pnl = (self.last_price - entry) * qty if side == "BUY" else (entry - self.last_price) * qty
            pnl_pct = (pnl / (entry * qty)) * Decimal("100") if entry * qty > 0 else Decimal("0")
            open_pos = {
                "symbol": self.symbol,
                "side": side,
                "entry_price": float(entry),
                "quantity": float(qty),
                "unrealized_pnl": float(pnl),
                "unrealized_pnl_pct": float(pnl_pct),
                "stop_loss": float(self.paper_position["stop_loss"]) if self.paper_position.get("stop_loss") else None,
                "take_profit": float(self.paper_position["take_profit"]) if self.paper_position.get("take_profit") else None,
            }

        stats = self.storage.get_trade_stats(mode=self.mode.value)

        return {
            "mode": self.mode.value.upper(),
            "symbol": self.symbol,
            "strategy": self.strategy.name,
            "interval": self.interval,
            "last_price": float(self.last_price),
            "equity": round(float(equity), 2),
            "open_position": open_pos,
            "status": self.status_message,
            "stats": stats,
            "daily_loss": float(self.risk_manager.realized_daily_pnl),
        }
