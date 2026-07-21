"""
Custom Exception Hierarchy
==========================

Provides granular exception types for different failure modes:
- Configuration errors (missing API keys)
- Input validation failures (bad symbol, quantity, price)
- Binance API errors (with error code mapping)
- Network failures (timeouts, connection issues)
- Rate limiting (with retry-after support)

Each exception carries structured metadata for logging and user-facing
error messages.
"""

from typing import Any, Dict, Optional


class TradingBotError(Exception):
    """Base exception for all trading bot errors.

    Attributes:
        message: Human-readable error description.
        details: Structured metadata for logging and debugging.
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class ConfigurationError(TradingBotError):
    """Raised when required configuration is missing or invalid.

    Typical causes:
    - Missing BINANCE_TESTNET_API_KEY or BINANCE_TESTNET_API_SECRET
    - Invalid base URL format
    - Missing .env file
    """

    pass


class ValidationError(TradingBotError):
    """Raised when user input fails validation.

    Attributes:
        field: The name of the field that failed validation.
        value: The invalid value that was provided.
    """

    def __init__(
        self,
        field: str,
        message: str,
        value: Optional[Any] = None,
    ):
        self.field = field
        self.value = value
        details = {"field": field}
        if value is not None:
            details["value"] = str(value)
        super().__init__(message, details)


class BinanceAPIError(TradingBotError):
    """Raised when the Binance API returns an error response.

    Attributes:
        code: Binance-specific error code (e.g., -1121 for invalid symbol).
        status_code: HTTP status code from the response.
    """

    def __init__(self, code: int, message: str, status_code: int = 0):
        self.code = code
        self.status_code = status_code
        details = {"error_code": code, "http_status": status_code}
        super().__init__(
            f"Binance API Error [{code}]: {message}",
            details,
        )


class NetworkError(TradingBotError):
    """Raised on connection timeouts, DNS failures, or other network issues.

    The client retries transient network errors with exponential backoff
    before raising this exception.
    """

    pass


class InsufficientBalanceError(BinanceAPIError):
    """Raised when the account has insufficient margin for the order.

    This is a specific Binance API error (typically code -2019) that
    indicates the account balance is too low to cover the margin
    requirement for the requested order.
    """

    pass


class RateLimitError(BinanceAPIError):
    """Raised when the API rate limit is exceeded.

    Attributes:
        retry_after: Seconds to wait before retrying.
    """

    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__(
            code=-1015,
            message=f"Rate limit exceeded. Retry after {retry_after}s.",
            status_code=429,
        )
