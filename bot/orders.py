"""
Order Placement Business Logic
===============================

Orchestrates the full order lifecycle:
    validate → build params → place via API → parse response

Supported order types:
- **MARKET**     — Executes immediately at current market price.
- **LIMIT**      — Placed at a specified price, fills when the market
                   reaches that price.
- **STOP**       — Stop-Limit order: places a limit order when the
                   stop trigger price is reached.

The ``OrderManager`` is the primary interface for placing orders.  It
delegates low-level concerns (signing, HTTP, retry) to ``BinanceClient``
and validation to ``ExchangeValidator``.
"""

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

from bot.client import BinanceClient
from bot.exceptions import ValidationError
from bot.models import (
    OrderRequest,
    OrderResponse,
    OrderType,
)
from bot.validators import ExchangeValidator

logger = logging.getLogger("trading_bot.orders")


class OrderManager:
    """Manages order lifecycle: validation → building → placement → response.

    Usage::

        with BinanceClient(settings) as client:
            manager = OrderManager(client)
            response = manager.place_order(request)
    """

    def __init__(self, client: BinanceClient) -> None:
        self._client = client
        self._validator = ExchangeValidator(client)

    # ── Main Entry Point ─────────────────────────────────────────────

    def place_order(self, request: OrderRequest) -> OrderResponse:
        """Validate and place an order on Binance Futures Testnet.

        Steps:
        1. Validate the request against exchange rules (lot size, tick
           size, symbol existence, trading status).
        2. Build the API parameter dict for the specific order type.
        3. Send the order to the exchange via ``BinanceClient.place_order``.
        4. Parse the raw JSON response into an ``OrderResponse`` model.

        Args:
            request: A validated OrderRequest model.

        Returns:
            An OrderResponse with orderId, status, executedQty, avgPrice, etc.

        Raises:
            ValidationError: If the order fails exchange-level validation.
            BinanceAPIError: If the API rejects the order.
            NetworkError: If the request fails after all retries.
        """
        logger.info(
            "Processing order: %s %s %s qty=%s",
            request.order_type.value,
            request.side.value,
            request.symbol,
            request.quantity,
        )

        # Step 1: Validate against exchange rules
        self._validator.validate_order(request)

        # Step 2: Build API parameters
        params = self._build_params(request)

        # Step 3: Send to exchange
        logger.info("Sending order to exchange...")
        raw_response = self._client.place_order(params)

        # Step 4: Parse response
        response = OrderResponse(**raw_response)
        logger.info(
            "Order placed: orderId=%d status=%s executedQty=%s avgPrice=%s",
            response.order_id,
            response.status,
            response.executed_qty,
            response.avg_price,
        )
        return response

    # ── Parameter Builders ───────────────────────────────────────────

    def _build_params(self, request: OrderRequest) -> Dict[str, Any]:
        """Route to the correct parameter builder by order type."""
        builders = {
            OrderType.MARKET: self._build_market_params,
            OrderType.LIMIT: self._build_limit_params,
            OrderType.STOP: self._build_stop_limit_params,
        }

        builder = builders.get(request.order_type)
        if not builder:
            raise ValidationError(
                field="order_type",
                message=f"Unsupported order type: {request.order_type.value}",
                value=request.order_type.value,
            )

        return builder(request)

    @staticmethod
    def _build_market_params(request: OrderRequest) -> Dict[str, Any]:
        """Build API parameters for a MARKET order.

        Market orders execute immediately at the best available price.
        No price or timeInForce is needed.
        """
        return {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": "MARKET",
            "quantity": str(request.quantity),
        }

    @staticmethod
    def _build_limit_params(request: OrderRequest) -> Dict[str, Any]:
        """Build API parameters for a LIMIT order.

        Limit orders are placed at the specified price and remain on the
        order book until filled, cancelled, or expired (per timeInForce).
        """
        return {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": "LIMIT",
            "quantity": str(request.quantity),
            "price": str(request.price),
            "timeInForce": request.time_in_force.value,
        }

    @staticmethod
    def _build_stop_limit_params(request: OrderRequest) -> Dict[str, Any]:
        """Build API parameters for a STOP (Stop-Limit) order.

        When the market reaches ``stopPrice``, a limit order is placed at
        ``price``.  This allows traders to set entry/exit points that
        trigger automatically.
        """
        return {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": "STOP",
            "quantity": str(request.quantity),
            "price": str(request.price),
            "stopPrice": str(request.stop_price),
            "timeInForce": request.time_in_force.value,
        }

    # ── Helper Methods ───────────────────────────────────────────────

    def get_current_price(self, symbol: str) -> Decimal:
        """Fetch the current market price for a symbol.

        Useful for displaying alongside order placement or for setting
        default prices in interactive mode.

        Returns:
            Current price as a Decimal.
        """
        data = self._client.get_ticker_price(symbol.upper())
        price = Decimal(data["price"])
        logger.debug("Current %s price: %s", symbol, price)
        return price

    def get_account_balances(self) -> List[Dict[str, str]]:
        """Get non-zero account balances from the testnet account.

        Returns:
            List of dicts with asset, wallet_balance, unrealized_pnl,
            margin_balance, and available_balance.
        """
        data = self._client.get_account_info()
        balances = []
        for asset in data.get("assets", []):
            wallet_balance = Decimal(asset.get("walletBalance", "0"))
            if wallet_balance != 0:
                balances.append(
                    {
                        "asset": asset["asset"],
                        "wallet_balance": str(wallet_balance),
                        "unrealized_pnl": asset.get("unrealizedProfit", "0"),
                        "margin_balance": asset.get("marginBalance", "0"),
                        "available_balance": asset.get(
                            "availableBalance", "0"
                        ),
                    }
                )
        return balances

    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel an open order.

        Args:
            symbol:   Trading pair (e.g., BTCUSDT).
            order_id: The orderId to cancel.

        Returns:
            Cancellation response from the API.
        """
        logger.info("Cancelling order %d for %s", order_id, symbol)
        return self._client.cancel_order(symbol.upper(), order_id)

    def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by symbol.

        Args:
            symbol: Optional trading pair filter.

        Returns:
            List of open order dicts.
        """
        return self._client.get_open_orders(
            symbol.upper() if symbol else None
        )
