"""
Input Validation and Exchange Filter Enforcement
=================================================

Two validation layers:

1. **CLI input parsing** (``validate_cli_inputs``)
   Converts raw string arguments from the command line into a validated
   ``OrderRequest`` Pydantic model.  Catches type errors, missing required
   fields, and obviously invalid values *before* hitting the API.

2. **Exchange rule enforcement** (``ExchangeValidator``)
   Validates the ``OrderRequest`` against live exchange rules fetched from
   ``/fapi/v1/exchangeInfo``:
   - LOT_SIZE: min/max quantity and step-size alignment
   - PRICE_FILTER: min/max price and tick-size alignment
   - MIN_NOTIONAL: minimum order value (price × quantity)
   - Symbol existence and trading status

   Exchange info is cached in memory to avoid redundant API calls.
"""

import logging
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional

from bot.client import BinanceClient
from bot.exceptions import ValidationError
from bot.models import (
    OrderRequest,
    OrderType,
    SymbolInfo,
)

logger = logging.getLogger("trading_bot.validators")


# ── Exchange Validator ────────────────────────────────────────────────


class ExchangeValidator:
    """Validates orders against live exchange rules and filters.

    Caches exchange info in memory so that repeated validations for the
    same symbol do not trigger additional API calls.
    """

    def __init__(self, client: BinanceClient) -> None:
        self._client = client
        self._symbol_cache: Dict[str, SymbolInfo] = {}

    # ── Cache Management ─────────────────────────────────────────────

    def load_exchange_info(self) -> None:
        """Fetch and cache all symbol info from the exchange."""
        logger.info("Loading exchange info from API...")
        data = self._client.get_exchange_info()
        for symbol_data in data.get("symbols", []):
            try:
                info = SymbolInfo.from_exchange_info(symbol_data)
                self._symbol_cache[info.symbol] = info
            except Exception as exc:
                # Skip symbols with malformed data rather than crashing
                logger.debug(
                    "Skipped symbol %s: %s",
                    symbol_data.get("symbol", "?"),
                    exc,
                )
        logger.info("Cached %d trading pairs", len(self._symbol_cache))

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        """Get cached symbol info, loading from API if needed.

        Raises:
            ValidationError: If the symbol does not exist on the exchange.
        """
        if not self._symbol_cache:
            self.load_exchange_info()

        symbol = symbol.upper()
        if symbol not in self._symbol_cache:
            raise ValidationError(
                field="symbol",
                message=(
                    f"Symbol '{symbol}' not found on the exchange.  "
                    f"Please check the spelling (e.g., BTCUSDT, ETHUSDT)."
                ),
                value=symbol,
            )
        return self._symbol_cache[symbol]

    # ── Order Validation ─────────────────────────────────────────────

    def validate_order(self, request: OrderRequest) -> OrderRequest:
        """Validate an order request against all exchange rules.

        Checks performed (in order):
        1. Symbol exists and is in TRADING status
        2. Quantity conforms to LOT_SIZE (min, max, step)
        3. Price conforms to PRICE_FILTER (min, max, tick) — for LIMIT/STOP
        4. Stop price conforms to PRICE_FILTER — for STOP orders
        5. Price is required for LIMIT and STOP orders
        6. Stop price is required for STOP orders

        Returns:
            The validated OrderRequest (unmodified).

        Raises:
            ValidationError: On any validation failure.
        """
        info = self.get_symbol_info(request.symbol)

        # Symbol status check
        if info.status != "TRADING":
            raise ValidationError(
                field="symbol",
                message=(
                    f"Symbol '{request.symbol}' is not currently trading "
                    f"(status: {info.status})."
                ),
                value=request.symbol,
            )

        # Quantity validation (LOT_SIZE)
        if info.lot_size:
            self._validate_quantity(request.quantity, info)

        # Price validation — required for LIMIT and STOP
        if request.order_type in (OrderType.LIMIT, OrderType.STOP):
            if request.price is None:
                raise ValidationError(
                    field="price",
                    message=(
                        f"Price is required for {request.order_type.value} orders."
                    ),
                )
            if info.price_filter:
                self._validate_price(request.price, info, field_name="price")

        # Stop price validation — required for STOP
        if request.order_type == OrderType.STOP:
            if request.stop_price is None:
                raise ValidationError(
                    field="stop_price",
                    message="Stop price is required for STOP (Stop-Limit) orders.",
                )
            if info.price_filter:
                self._validate_price(
                    request.stop_price, info, field_name="stop_price"
                )

        # Min notional check (price × quantity >= minimum)
        if (
            info.min_notional
            and request.price is not None
            and request.quantity is not None
        ):
            notional = request.price * request.quantity
            if notional < info.min_notional.notional:
                raise ValidationError(
                    field="notional",
                    message=(
                        f"Order notional value ({notional} USDT) is below the "
                        f"minimum required ({info.min_notional.notional} USDT).  "
                        f"Increase quantity or price."
                    ),
                    value=str(notional),
                )

        logger.info("Order validation passed for %s", request.symbol)
        return request

    # ── Filter Validators ────────────────────────────────────────────

    @staticmethod
    def _validate_quantity(quantity: Decimal, info: SymbolInfo) -> None:
        """Validate quantity against the LOT_SIZE filter.

        Checks min, max, and step-size alignment.  On step-size
        violation, the error message suggests the nearest valid quantity.
        """
        lot = info.lot_size

        if quantity < lot.min_qty:
            raise ValidationError(
                field="quantity",
                message=(
                    f"Quantity {quantity} is below the minimum "
                    f"{lot.min_qty} for {info.symbol}."
                ),
                value=str(quantity),
            )

        if lot.max_qty > 0 and quantity > lot.max_qty:
            raise ValidationError(
                field="quantity",
                message=(
                    f"Quantity {quantity} exceeds the maximum "
                    f"{lot.max_qty} for {info.symbol}."
                ),
                value=str(quantity),
            )

        if lot.step_size > 0:
            remainder = (quantity - lot.min_qty) % lot.step_size
            if remainder != 0:
                suggested = quantity - remainder
                raise ValidationError(
                    field="quantity",
                    message=(
                        f"Quantity {quantity} does not conform to step size "
                        f"{lot.step_size} for {info.symbol}.  "
                        f"Nearest valid value: {suggested}"
                    ),
                    value=str(quantity),
                )

    @staticmethod
    def _validate_price(
        price: Decimal,
        info: SymbolInfo,
        field_name: str = "price",
    ) -> None:
        """Validate price against the PRICE_FILTER.

        Checks min, max, and tick-size alignment.  On tick-size
        violation, the error message suggests the nearest valid price.
        """
        pf = info.price_filter

        if pf.min_price > 0 and price < pf.min_price:
            raise ValidationError(
                field=field_name,
                message=f"Price {price} is below the minimum {pf.min_price}.",
                value=str(price),
            )

        if pf.max_price > 0 and price > pf.max_price:
            raise ValidationError(
                field=field_name,
                message=f"Price {price} exceeds the maximum {pf.max_price}.",
                value=str(price),
            )

        if pf.tick_size > 0:
            remainder = price % pf.tick_size
            if remainder != 0:
                suggested = price - remainder
                raise ValidationError(
                    field=field_name,
                    message=(
                        f"Price {price} does not conform to tick size "
                        f"{pf.tick_size}.  Nearest valid value: {suggested}"
                    ),
                    value=str(price),
                )


# ── CLI Input Parser ─────────────────────────────────────────────────


def validate_cli_inputs(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: Optional[str] = None,
    stop_price: Optional[str] = None,
) -> OrderRequest:
    """Validate and parse raw CLI string inputs into an OrderRequest.

    This function bridges the gap between raw CLI strings and the typed
    OrderRequest model.  It provides user-friendly error messages for
    each field, guiding the user to correct their input.

    Args:
        symbol:     Trading pair (e.g., "BTCUSDT").
        side:       "BUY" or "SELL".
        order_type: "MARKET", "LIMIT", or "STOP" / "STOP_LIMIT" / "STOP-LIMIT".
        quantity:   Positive number as a string.
        price:      Limit price (required for LIMIT/STOP).
        stop_price: Stop trigger price (required for STOP).

    Returns:
        A validated OrderRequest model.

    Raises:
        ValidationError: On any input validation failure.
    """
    # ── Side ──────────────────────────────────────────────────────────
    side = side.upper().strip()
    if side not in ("BUY", "SELL"):
        raise ValidationError(
            field="side",
            message=f"Invalid side '{side}'.  Must be 'BUY' or 'SELL'.",
            value=side,
        )

    # ── Order type (with aliases) ────────────────────────────────────
    order_type = order_type.upper().strip().replace("-", "_")
    type_map = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "STOP": "STOP",
        "STOP_LIMIT": "STOP",
    }
    if order_type not in type_map:
        raise ValidationError(
            field="order_type",
            message=(
                f"Invalid order type '{order_type}'.  "
                "Must be 'MARKET', 'LIMIT', or 'STOP' (Stop-Limit)."
            ),
            value=order_type,
        )
    mapped_type = type_map[order_type]

    # ── Quantity ─────────────────────────────────────────────────────
    try:
        qty = Decimal(quantity.strip())
        if qty <= 0:
            raise ValueError("non-positive")
    except (InvalidOperation, ValueError):
        raise ValidationError(
            field="quantity",
            message=(
                f"Invalid quantity '{quantity}'.  "
                "Must be a positive number (e.g., 0.001)."
            ),
            value=quantity,
        )

    # ── Limit price ──────────────────────────────────────────────────
    parsed_price: Optional[Decimal] = None
    if price is not None and price.strip():
        try:
            parsed_price = Decimal(price.strip())
            if parsed_price <= 0:
                raise ValueError("non-positive")
        except (InvalidOperation, ValueError):
            raise ValidationError(
                field="price",
                message=(
                    f"Invalid price '{price}'.  "
                    "Must be a positive number."
                ),
                value=price,
            )
    elif mapped_type in ("LIMIT", "STOP"):
        raise ValidationError(
            field="price",
            message=f"Price is required for {mapped_type} orders.",
        )

    # ── Stop price ───────────────────────────────────────────────────
    parsed_stop: Optional[Decimal] = None
    if stop_price is not None and stop_price.strip():
        try:
            parsed_stop = Decimal(stop_price.strip())
            if parsed_stop <= 0:
                raise ValueError("non-positive")
        except (InvalidOperation, ValueError):
            raise ValidationError(
                field="stop_price",
                message=(
                    f"Invalid stop price '{stop_price}'.  "
                    "Must be a positive number."
                ),
                value=stop_price,
            )
    elif mapped_type == "STOP":
        raise ValidationError(
            field="stop_price",
            message="Stop price is required for STOP (Stop-Limit) orders.",
        )

    return OrderRequest(
        symbol=symbol.upper().strip(),
        side=side,
        order_type=mapped_type,
        quantity=qty,
        price=parsed_price,
        stop_price=parsed_stop,
    )
