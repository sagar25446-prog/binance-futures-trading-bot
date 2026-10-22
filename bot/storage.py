"""
Storage and Trade Journal
=========================

SQLite persistence for trade logs, execution journal, and equity tracking.
Ensures state is fully preserved across restarts, reboots, and network disconnects.
"""

from decimal import Decimal
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional
from bot.models import TradeRecord


class Storage:
    """SQLite trade journal and bot state storage."""

    def __init__(self, db_path: str = "data/trading_bot.db") -> None:
        self.db_path = db_path
        self._mem_conn = None
        if db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:")
            self._mem_conn.row_factory = sqlite3.Row
        else:
            os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL,
                    quantity REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    pnl REAL,
                    pnl_pct REAL,
                    fee REAL DEFAULT 0,
                    entry_time INTEGER NOT NULL,
                    exit_time INTEGER,
                    status TEXT NOT NULL,
                    mode TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL,
                    equity REAL NOT NULL,
                    unrealized_pnl REAL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS bot_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def record_trade_entry(self, trade: TradeRecord) -> None:
        """Insert a newly opened trade."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO trades (
                    trade_id, symbol, side, entry_price, quantity,
                    stop_loss, take_profit, fee, entry_time, status, mode
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id,
                    trade.symbol,
                    trade.side,
                    float(trade.entry_price),
                    float(trade.quantity),
                    float(trade.stop_loss) if trade.stop_loss else None,
                    float(trade.take_profit) if trade.take_profit else None,
                    float(trade.fee),
                    trade.entry_time,
                    trade.status,
                    trade.mode,
                ),
            )

    def record_trade_exit(
        self,
        trade_id: str,
        exit_price: Decimal,
        pnl: Decimal,
        pnl_pct: Decimal,
        fee: Decimal,
        status: str,
    ) -> None:
        """Update an open trade upon exit."""
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE trades SET
                    exit_price = ?,
                    pnl = ?,
                    pnl_pct = ?,
                    fee = fee + ?,
                    exit_time = ?,
                    status = ?
                WHERE trade_id = ?
                """,
                (
                    float(exit_price),
                    float(pnl),
                    float(pnl_pct),
                    float(fee),
                    int(time.time() * 1000),
                    status,
                    trade_id,
                ),
            )

    def record_equity(self, equity: Decimal, unrealized_pnl: Decimal = Decimal("0")) -> None:
        """Snapshot account equity and unrealized PnL."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO equity_history (timestamp, equity, unrealized_pnl) VALUES (?, ?, ?)",
                (int(time.time()), float(equity), float(unrealized_pnl)),
            )

    def get_open_trades(self, mode: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch all currently open trades."""
        query = "SELECT * FROM trades WHERE status = 'OPEN'"
        params = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)

        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def get_trade_stats(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """Compute performance statistics across completed trades."""
        query = "SELECT * FROM trades WHERE status != 'OPEN'"
        params = []
        if mode:
            query += " AND mode = ?"
            params.append(mode)

        with self._get_connection() as conn:
            rows = [dict(r) for r in conn.execute(query, params).fetchall()]

        total_trades = len(rows)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "wins": 0,
                "losses": 0,
            }

        wins = [r for r in rows if (r.get("pnl") or 0) > 0]
        losses = [r for r in rows if (r.get("pnl") or 0) <= 0]
        total_pnl = sum((r.get("pnl") or 0) for r in rows)
        gross_profit = sum((r.get("pnl") or 0) for r in wins)
        gross_loss = abs(sum((r.get("pnl") or 0) for r in losses))

        win_rate = (len(wins) / total_trades) * 100.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 2),
            "total_pnl": round(total_pnl, 4),
            "profit_factor": round(profit_factor, 2),
            "wins": len(wins),
            "losses": len(losses),
        }
