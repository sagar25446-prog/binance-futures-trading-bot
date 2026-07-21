"""
Binance Futures Testnet REST API Client
=======================================

Low-level HTTP client that handles:
- HMAC-SHA256 request signing (per Binance authentication spec)
- Automatic timestamp injection with server-time synchronization
- Retry logic with exponential backoff for transient failures
- Error classification into typed exceptions (API, network, rate limit)

All higher-level modules (orders, validators) use this client to
interact with the Binance Futures Testnet REST API.

Endpoints used
--------------
GET  /fapi/v1/time          – Server time (for clock sync)
GET  /fapi/v1/exchangeInfo  – Trading rules and symbol filters
GET  /fapi/v1/ticker/price  – Current market price
GET  /fapi/v2/account       – Account balances and positions
POST /fapi/v1/order         – Place a new order
DELETE /fapi/v1/order       – Cancel an existing order
GET  /fapi/v1/openOrders    – List open orders
"""

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlencode

import httpx

from bot.config import Settings
from bot.exceptions import (
    BinanceAPIError,
    InsufficientBalanceError,
    NetworkError,
    RateLimitError,
)

logger = logging.getLogger("trading_bot.client")


class BinanceClient:
    """Binance Futures Testnet REST API client.

    Usage::

        settings = Settings.from_env()
        with BinanceClient(settings) as client:
            client.sync_time()
            info = client.get_exchange_info()
            order = client.place_order({...})
    """

    # Binance error codes that map to specific exception types
    _INSUFFICIENT_BALANCE_CODES = {-2019}
    _RATE_LIMIT_CODES = {-1015}

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/")
        self._recv_window = settings.recv_window
        self._max_retries = settings.max_retries
        self._retry_delay = settings.retry_delay
        self._time_offset: int = 0  # millisecond offset from server

        self._client = httpx.Client(
            timeout=settings.request_timeout,
            headers={
                "X-MBX-APIKEY": settings.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        logger.info(
            "BinanceClient initialized (base_url=%s, key=%s)",
            self._base_url,
            settings.masked_key,
        )

    # ── Context Manager ──────────────────────────────────────────────

    def __enter__(self) -> "BinanceClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        self._client.close()
        logger.debug("HTTP client closed")

    # ── Signature Generation ─────────────────────────────────────────

    def _get_timestamp(self) -> int:
        """Get current timestamp in milliseconds, adjusted for server offset."""
        return int(time.time() * 1000) + self._time_offset

    def _generate_signature(self, query_string: str) -> str:
        """Generate HMAC-SHA256 signature for the query string.

        The signature is computed as:
            HMAC_SHA256(api_secret, query_string).hexdigest()

        This matches Binance's authentication specification where the
        ``totalParams`` (query string + body) is signed with the API secret.
        """
        return hmac.new(
            self._settings.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _sign_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add timestamp, recvWindow, and signature to request parameters.

        Parameters are signed in order:
        1. Add ``timestamp`` and ``recvWindow``
        2. Build the query string from all parameters
        3. Compute HMAC-SHA256 signature
        4. Append ``signature`` as the last parameter
        """
        params["timestamp"] = self._get_timestamp()
        params["recvWindow"] = self._recv_window
        query_string = urlencode(params)
        params["signature"] = self._generate_signature(query_string)
        return params

    # ── HTTP Request Layer ───────────────────────────────────────────

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = True,
    ) -> Union[Dict[str, Any], List[Any]]:
        """Execute an HTTP request with retry logic and error handling.

        Retries are performed with exponential backoff for transient
        network errors (connection refused, timeout, read error).
        API-level errors (invalid symbol, insufficient balance) are
        raised immediately without retry.

        Args:
            method:   HTTP method (GET, POST, DELETE).
            endpoint: API endpoint path (e.g., /fapi/v1/order).
            params:   Request parameters.
            signed:   Whether to sign the request (add timestamp + signature).

        Returns:
            Parsed JSON response as a dict or list.

        Raises:
            BinanceAPIError: On API-level errors.
            NetworkError: On connection/timeout failures after all retries.
            RateLimitError: When rate limit is exceeded.
        """
        params = dict(params) if params else {}
        url = f"{self._base_url}{endpoint}"

        if signed:
            params = self._sign_params(params)

        last_error: Optional[NetworkError] = None

        for attempt in range(1, self._max_retries + 1):
            try:
                logger.debug(
                    "API request [%d/%d]: %s %s params=%s",
                    attempt,
                    self._max_retries,
                    method.upper(),
                    endpoint,
                    {k: v for k, v in params.items() if k != "signature"},
                )

                response = self._send(method, url, params)
                data = response.json()

                # ── Check for API errors ─────────────────────────────
                if response.status_code >= 400 or (
                    isinstance(data, dict) and "code" in data
                ):
                    self._handle_api_error(data, response.status_code, response)

                logger.debug(
                    "API response [%s]: status=%d",
                    endpoint,
                    response.status_code,
                )
                return data

            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.ReadError,
                httpx.WriteError,
                httpx.PoolTimeout,
            ) as exc:
                last_error = NetworkError(
                    f"Network error on attempt {attempt}/{self._max_retries}: {exc}"
                )
                logger.warning(
                    "Network error [%d/%d]: %s",
                    attempt,
                    self._max_retries,
                    str(exc),
                )
                if attempt < self._max_retries:
                    delay = self._retry_delay * (2 ** (attempt - 1))
                    logger.info("Retrying in %.1fs...", delay)
                    time.sleep(delay)
                    # Re-sign with fresh timestamp on retry
                    if signed:
                        for key in ("timestamp", "signature", "recvWindow"):
                            params.pop(key, None)
                        params = self._sign_params(params)

            except (RateLimitError, BinanceAPIError, InsufficientBalanceError):
                raise  # Don't retry on API-level errors

        raise last_error or NetworkError("Request failed after all retries")

    def _send(
        self,
        method: str,
        url: str,
        params: Dict[str, Any],
    ) -> httpx.Response:
        """Dispatch the HTTP request by method."""
        method = method.upper()
        if method == "GET":
            return self._client.get(url, params=params)
        if method == "POST":
            return self._client.post(url, data=params)
        if method == "DELETE":
            return self._client.delete(url, params=params)
        raise ValueError(f"Unsupported HTTP method: {method}")

    @staticmethod
    def _handle_api_error(
        data: dict,
        status_code: int,
        response: httpx.Response,
    ) -> None:
        """Classify and raise the appropriate exception for an API error."""
        error_code = data.get("code", status_code)
        error_msg = data.get("msg", "Unknown API error")

        logger.error(
            "API error: code=%s msg='%s' http_status=%d",
            error_code,
            error_msg,
            status_code,
        )

        if error_code in BinanceClient._RATE_LIMIT_CODES:
            retry_after = int(response.headers.get("Retry-After", 60))
            raise RateLimitError(retry_after)

        if error_code in BinanceClient._INSUFFICIENT_BALANCE_CODES:
            raise InsufficientBalanceError(
                code=error_code,
                message=error_msg,
                status_code=status_code,
            )

        raise BinanceAPIError(
            code=error_code,
            message=error_msg,
            status_code=status_code,
        )

    # ── Public API Methods ───────────────────────────────────────────

    def sync_time(self) -> int:
        """Synchronize local clock with Binance server time.

        Computes a millisecond offset that is applied to all subsequent
        signed requests, preventing ``-1021 Timestamp outside recvWindow``
        errors.

        Returns:
            The computed time offset in milliseconds.
        """
        local_time = int(time.time() * 1000)
        data = self._make_request("GET", "/fapi/v1/time", signed=False)
        server_time = data["serverTime"]
        self._time_offset = server_time - local_time
        logger.info("Time synced with server (offset=%dms)", self._time_offset)
        return self._time_offset

    def get_exchange_info(self) -> Dict[str, Any]:
        """Fetch exchange information including trading rules and filters.

        Returns:
            Full exchangeInfo response containing symbol definitions,
            lot-size/price/notional filters, and rate limits.
        """
        return self._make_request(
            "GET", "/fapi/v1/exchangeInfo", signed=False
        )

    def get_ticker_price(self, symbol: str) -> Dict[str, Any]:
        """Get current market price for a symbol.

        Args:
            symbol: Trading pair (e.g., BTCUSDT).

        Returns:
            Dict with ``symbol`` and ``price`` keys.
        """
        return self._make_request(
            "GET",
            "/fapi/v1/ticker/price",
            params={"symbol": symbol.upper()},
            signed=False,
        )

    def get_account_info(self) -> Dict[str, Any]:
        """Get account information including balances and positions.

        Returns:
            Account data with ``assets`` and ``positions`` arrays.
        """
        return self._make_request("GET", "/fapi/v2/account")

    def place_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Place a new order on Binance Futures Testnet.

        Args:
            params: Order parameters (symbol, side, type, quantity, etc.).
                    ``newOrderRespType=RESULT`` is added automatically to
                    get execution details in the response.

        Returns:
            Order response including orderId, status, executedQty, avgPrice.
        """
        params["newOrderRespType"] = "RESULT"
        logger.info(
            "Placing order: symbol=%s side=%s type=%s qty=%s",
            params.get("symbol"),
            params.get("side"),
            params.get("type"),
            params.get("quantity"),
        )
        # Binance migrated conditional orders to the algoOrder endpoint
        endpoint = "/fapi/v1/order"
        if params.get("type") in ("STOP", "STOP_MARKET", "TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
            endpoint = "/fapi/v1/algoOrder"
            params["algoType"] = "CONDITIONAL"

        result = self._make_request("POST", endpoint, params=params)
        
        # Normalize Algo API response to match standard order response structure
        if "algoId" in result and "orderId" not in result:
            result["orderId"] = result["algoId"]
        if "executedQty" not in result:
            result["executedQty"] = "0"
        if "status" not in result:
            result["status"] = "NEW" # Algo orders are typically NEW when placed
        if "type" not in result:
            result["type"] = params.get("type", "STOP")
        logger.info(
            "Order response: orderId=%s status=%s executedQty=%s avgPrice=%s",
            result.get("orderId"),
            result.get("status"),
            result.get("executedQty"),
            result.get("avgPrice"),
        )
        return result

    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel an existing order.

        Args:
            symbol:   Trading pair (e.g., BTCUSDT).
            order_id: The orderId to cancel.

        Returns:
            Cancellation response from the API.
        """
        logger.info("Cancelling order: symbol=%s orderId=%d", symbol, order_id)
        return self._make_request(
            "DELETE",
            "/fapi/v1/order",
            params={"symbol": symbol.upper(), "orderId": order_id},
        )

    def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all open orders, optionally filtered by symbol.

        Args:
            symbol: Optional trading pair filter.

        Returns:
            List of open order dicts.
        """
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._make_request("GET", "/fapi/v1/openOrders", params=params)
