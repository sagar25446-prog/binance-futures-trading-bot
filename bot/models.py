"""
Data Models and Enumerations
=============================

Defines the core data structures used throughout the trading bot:

- **Enums**: OrderSide, OrderType, TimeInForce, OrderStatus for type-safe
  order parameters.
- **OrderRequest**: Pydantic model for validated order input with field-level
  validators (symbol format, positive quantities, etc.).
- **OrderResponse**: Pydantic model that maps Binance API response fields to
  clean Python attributes, including computed properties like `is_filled`.
- **Exchange filters**: LotSizeFilter, PriceFilter, MinNotionalFilter, and
  SymbolInfo for validating orders against exchange trading rules.

All monetary values use `Decimal` to avoid floating-point precision issues
that are critical in financial applications.
"""

from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ── Enumerations ──────────────────────────────────────────────────────


class OrderSide(str, Enum):
    """Order side — direction of the trade."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Supported order types.

    MARKET: Executes immediately at current market price.
    LIMIT:  Executes at the specified price or better.
    STOP:   Stop-Limit order that triggers a limit order when
            the stop price is reached.
    """

    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class TimeInForce(str, Enum):
    """Time-in-force policy for limit orders.

    GTC: Good Till Cancel — remains active until filled or cancelled.
    IOC: Immediate Or Cancel — fills what it can, cancels the rest.
    FOK: Fill Or Kill — must be fully filled or entirely cancelled.
    """

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class OrderStatus(str, Enum):
    """Order execution status returned by Binance."""

    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    NEW_INSURANCE = "NEW_INSURANCE"
    NEW_ADL = "NEW_ADL"





# ── Order Request Model ──────────────────────────────────────────────


class OrderRequest(BaseModel):
    """Validated order request model.

    This model performs basic field-level validation (format, ranges).
    Exchange-level validation (lot size, tick size, min notional) is
    handled by the ExchangeValidator in validators.py.
    """

    symbol: str = Field(
        ...,
        min_length=2,
        description="Trading pair symbol (e.g., BTCUSDT)",
    )
    side: OrderSide = Field(
        ...,
        description="Order side: BUY or SELL",
    )
    order_type: OrderType = Field(
        ...,
        description="Order type: MARKET, LIMIT, or STOP",
    )
    quantity: Decimal = Field(
        ...,
        gt=0,
        description="Order quantity (must be positive)",
    )
    price: Optional[Decimal] = Field(
        None,
        gt=0,
        description="Limit price — required for LIMIT and STOP orders",
    )
    stop_price: Optional[Decimal] = Field(
        None,
        gt=0,
        description="Stop trigger price — required for STOP orders",
    )
    time_in_force: TimeInForce = Field(
        default=TimeInForce.GTC,
        description="Time in force policy for limit orders",
    )

    model_config = {"str_strip_whitespace": True}

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        """Normalize symbol to uppercase and validate basic format."""
        v = v.upper().strip()
        if not v.isalnum():
            raise ValueError(
                f"Invalid symbol format: '{v}'. "
                "Symbol must contain only alphanumeric characters (e.g., BTCUSDT)."
            )
        if len(v) < 5:
            raise ValueError(
                f"Symbol '{v}' is too short. "
                "Expected format like 'BTCUSDT' or 'ETHUSDT'."
            )
        return v


# ── Order Response Model ─────────────────────────────────────────────


class OrderResponse(BaseModel):
    """Parsed Binance order response.

    Maps the JSON response from POST /fapi/v1/order into a clean Python
    object with computed properties for status checking.
    """

    order_id: int = Field(..., alias="orderId")
    symbol: str
    side: str
    order_type: str = Field(..., alias="type")
    status: str
    quantity: str = Field(..., alias="origQty")
    executed_qty: str = Field(..., alias="executedQty")
    price: str
    avg_price: str = Field(default="0", alias="avgPrice")
    stop_price: str = Field(default="0", alias="stopPrice")
    time_in_force: str = Field(default="GTC", alias="timeInForce")
    client_order_id: str = Field(default="", alias="clientOrderId")
    update_time: int = Field(default=0, alias="updateTime")
    cum_quote: str = Field(default="0", alias="cumQuote")
    reduce_only: bool = Field(default=False, alias="reduceOnly")
    working_type: str = Field(default="CONTRACT_PRICE", alias="workingType")

    model_config = {"populate_by_name": True}

    @property
    def is_filled(self) -> bool:
        """Check if the order is fully filled."""
        return self.status == OrderStatus.FILLED.value

    @property
    def is_active(self) -> bool:
        """Check if the order is still active (new or partially filled)."""
        return self.status in (
            OrderStatus.NEW.value,
            OrderStatus.PARTIALLY_FILLED.value,
        )


# ── Exchange Filter Models ───────────────────────────────────────────


class LotSizeFilter(BaseModel):
    """LOT_SIZE filter from exchange info.

    Defines the allowed quantity range and step size for orders.
    """

    min_qty: Decimal = Field(..., alias="minQty")
    max_qty: Decimal = Field(..., alias="maxQty")
    step_size: Decimal = Field(..., alias="stepSize")

    model_config = {"populate_by_name": True}


class PriceFilter(BaseModel):
    """PRICE_FILTER from exchange info.

    Defines the allowed price range and tick size for orders.
    """

    min_price: Decimal = Field(..., alias="minPrice")
    max_price: Decimal = Field(..., alias="maxPrice")
    tick_size: Decimal = Field(..., alias="tickSize")

    model_config = {"populate_by_name": True}


class MinNotionalFilter(BaseModel):
    """MIN_NOTIONAL filter from exchange info.

    Defines the minimum notional value (price * quantity) for orders.
    """

    notional: Decimal = Field(default=Decimal("5"))

    model_config = {"populate_by_name": True}


class SymbolInfo(BaseModel):
    """Exchange symbol information with parsed filters.

    Aggregates trading pair metadata and filter rules from the
    /fapi/v1/exchangeInfo endpoint.
    """

    symbol: str
    status: str
    base_asset: str = Field(..., alias="baseAsset")
    quote_asset: str = Field(..., alias="quoteAsset")
    price_precision: int = Field(..., alias="pricePrecision")
    quantity_precision: int = Field(..., alias="quantityPrecision")
    lot_size: Optional[LotSizeFilter] = None
    price_filter: Optional[PriceFilter] = None
    min_notional: Optional[MinNotionalFilter] = None

    model_config = {"populate_by_name": True}

    @classmethod
    def from_exchange_info(cls, data: dict) -> "SymbolInfo":
        """Factory method to parse a symbol entry from exchangeInfo response.

        Extracts LOT_SIZE, PRICE_FILTER, and MIN_NOTIONAL filters from the
        nested filters array and maps them to typed Pydantic models.
        """
        filters = {f["filterType"]: f for f in data.get("filters", [])}

        lot_size = (
            LotSizeFilter(**filters["LOT_SIZE"])
            if "LOT_SIZE" in filters
            else None
        )
        price_filter = (
            PriceFilter(**filters["PRICE_FILTER"])
            if "PRICE_FILTER" in filters
            else None
        )
        min_notional = (
            MinNotionalFilter(**filters["MIN_NOTIONAL"])
            if "MIN_NOTIONAL" in filters
            else None
        )

        return cls(
            symbol=data["symbol"],
            status=data["status"],
            base_asset=data["baseAsset"],
            quote_asset=data["quoteAsset"],
            price_precision=data["pricePrecision"],
            quantity_precision=data["quantityPrecision"],
            lot_size=lot_size,
            price_filter=price_filter,
            min_notional=min_notional,
        )
