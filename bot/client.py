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
GET    /fapi/v1/time            – Server time (for clock sync)
GET    /fapi/v1/exchangeInfo    – Trading rules and symbol filters
GET    /fapi/v1/ticker/price    – Current market price
GET    /fapi/v2/account         – Account balances and positions
POST   /fapi/v1/order           – Place a standard order (MARKET/LIMIT)
POST   /fapi/v1/algoOrder       – Place a conditional order (STOP/TP)
DELETE /fapi/v1/order           – Cancel a standard order
DELETE /fapi/v1/algoOrder       – Cancel a conditional (algo) order
GET    /fapi/v1/openOrders      – List open standard orders
GET    /fapi/v1/openAlgoOrders  – List open conditional (algo) orders
"""

import hashlib
import hmac
import logging
import time
from email.utils import parsedate_to_datetime
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


class _RetryableServerError(Exception):
    """Internal signal: an idempotent request hit an HTTP 5xx and may be retried."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


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
    _RATE_LIMIT_CODES = {-1015, -1003}
    _TIMESTAMP_ERROR_CODE = -1021
    _RATE_LIMIT_HTTP_STATUSES = {418, 429}

    # Order-type values that must be routed to the Algo Order endpoint.
    _ALGO_ORDER_TYPES = (
        "STOP",
        "STOP_MARKET",
        "TAKE_PROFIT",
        "TAKE_PROFIT_MARKET",
    )

    # Failures where the request provably never reached Binance, so even a
    # state-changing call (POST/DELETE) can be retried without any risk of
    # executing it twice.  Any other transport failure (e.g. a read timeout)
    # is "ambiguous": Binance may already have processed the request.
    _NEVER_SENT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

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

        Retry policy (designed so an order can never be executed twice):

        * Idempotent ``GET`` requests are retried with exponential backoff
          on any transient network error and on HTTP 5xx responses.
        * ``POST`` / ``DELETE`` requests are retried **only** when the request
          provably never reached Binance (connection refused, connect
          timeout).  If a timeout happens after the request may have been
          sent, the outcome is unknown, so a ``NetworkError`` is raised
          immediately and the caller must check open orders instead of
          blindly resending.
        * A ``-1021`` (timestamp outside recvWindow) error triggers one
          automatic clock re-sync followed by one retry.
        * API-level errors (invalid symbol, insufficient balance, rate
          limit) are raised immediately without retry.

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
        method = method.upper()
        base_params = dict(params) if params else {}
        url = f"{self._base_url}{endpoint}"
        idempotent = method == "GET"

        last_error: Optional[NetworkError] = None
        resynced = False
        attempt = 0

        while attempt < self._max_retries:
            attempt += 1
            # Re-sign on every attempt so the timestamp is always fresh.
            request_params = (
                self._sign_params(dict(base_params)) if signed else dict(base_params)
            )
            try:
                logger.debug(
                    "API request [%d/%d]: %s %s params=%s",
                    attempt,
                    self._max_retries,
                    method,
                    endpoint,
                    {k: v for k, v in request_params.items() if k != "signature"},
                )

                response = self._send(method, url, request_params)
                data = self._parse_json(response)

                # Transient server-side failure: only safe to retry for GETs.
                if response.status_code >= 500 and idempotent:
                    raise _RetryableServerError(response.status_code)

                if response.status_code >= 400 or (
                    isinstance(data, dict)
                    and "code" in data
                    and str(data["code"]) != "200"
                ):
                    self._handle_api_error(data, response.status_code, response)

                logger.debug(
                    "API response [%s]: status=%d", endpoint, response.status_code
                )
                return data

            except BinanceAPIError as exc:
                # Clock drift: re-sync once, then retry (does not use up an attempt).
                if (
                    signed
                    and not resynced
                    and exc.code == self._TIMESTAMP_ERROR_CODE
                ):
                    resynced = True
                    attempt -= 1
                    logger.warning("Timestamp rejected (-1021); re-syncing clock")
                    self.sync_time()
                    continue
                raise

            except _RetryableServerError as exc:
                last_error = NetworkError(
                    f"Binance returned HTTP {exc.status_code} "
                    f"(attempt {attempt}/{self._max_retries})"
                )
                logger.warning("%s", last_error)

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ) as exc:
                never_sent = isinstance(exc, self._NEVER_SENT_ERRORS)
                last_error = NetworkError(
                    f"Network error on attempt {attempt}/{self._max_retries}: {exc}"
                )
                logger.warning(
                    "Network error [%d/%d]: %s", attempt, self._max_retries, str(exc)
                )
                if not (idempotent or never_sent):
                    raise NetworkError(
                        f"{method} {endpoint} failed after the request may have "
                        f"been sent ({type(exc).__name__}). The outcome is "
                        "unknown - check your open orders before retrying so "
                        "the order is not placed twice."
                    ) from exc

            if attempt < self._max_retries:
                delay = self._retry_delay * (2 ** (attempt - 1))
                logger.info("Retrying in %.1fs...", delay)
                time.sleep(delay)

        raise last_error or NetworkError("Request failed after all retries")

    @staticmethod
    def _parse_json(response: httpx.Response) -> Union[Dict[str, Any], List[Any]]:
        """Decode a JSON body, turning proxy/HTML error pages into API errors."""
        try:
            return response.json()
        except ValueError:
            snippet = response.text[:200].strip() or "<empty body>"
            logger.error(
                "Non-JSON response: http_status=%d body=%r",
                response.status_code,
                snippet,
            )
            raise BinanceAPIError(
                code=response.status_code,
                message=f"Unexpected non-JSON response from server: {snippet}",
                status_code=response.status_code,
            )

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
    def _retry_after_seconds(response: httpx.Response, default: int = 60) -> int:
        """Parse a ``Retry-After`` header (seconds or HTTP-date) defensively."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return default
        try:
            return max(int(raw), 0)
        except ValueError:
            try:
                delta = parsedate_to_datetime(raw).timestamp() - time.time()
                return max(int(delta), 0)
            except (TypeError, ValueError):
                return default

    @staticmethod
    def _handle_api_error(
        data: dict,
        status_code: int,
        response: httpx.Response,
    ) -> None:
        """Classify and raise the appropriate exception for an API error."""
        if not isinstance(data, dict):
            data = {}
        error_code = data.get("code", status_code)
        error_msg = data.get("msg", "Unknown API error")

        logger.error(
            "API error: code=%s msg='%s' http_status=%d",
            error_code,
            error_msg,
            status_code,
        )

        if (
            error_code in BinanceClient._RATE_LIMIT_CODES
            or status_code in BinanceClient._RATE_LIMIT_HTTP_STATUSES
        ):
            raise RateLimitError(BinanceClient._retry_after_seconds(response))

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
                    get execution details in the response.  The dict passed
                    in is not modified.

        Returns:
            Order response including orderId, status, executedQty, avgPrice.
            Conditional (algo) responses are normalised to the same shape.
        """
        params = dict(params)
        params["newOrderRespType"] = "RESULT"
        logger.info(
            "Placing order: symbol=%s side=%s type=%s qty=%s",
            params.get("symbol"),
            params.get("side"),
            params.get("type"),
            params.get("quantity"),
        )
        # Binance migrated conditional orders to the algoOrder endpoint
        is_algo = params.get("type") in self._ALGO_ORDER_TYPES
        endpoint = "/fapi/v1/order"
        if is_algo:
            endpoint = "/fapi/v1/algoOrder"
            params["algoType"] = "CONDITIONAL"

        result = self._make_request("POST", endpoint, params=params)
        if is_algo:
            result = self._normalize_algo_response(result, params)

        logger.info(
            "Order response: orderId=%s status=%s executedQty=%s avgPrice=%s",
            result.get("orderId"),
            result.get("status"),
            result.get("executedQty"),
            result.get("avgPrice"),
        )
        return result

    @staticmethod
    def _normalize_algo_response(
        result: Dict[str, Any], params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Map an Algo Order response onto the standard order response shape.

        The documented Algo API uses ``algoId``, ``clientAlgoId``,
        ``algoStatus``, ``orderType``, ``quantity`` and ``triggerPrice``,
        whereas the standard order API uses ``orderId``, ``clientOrderId``,
        ``status``, ``type``, ``origQty`` and ``stopPrice``.  The testnet has
        been observed returning a mix of both, so each standard field is only
        filled in when it is missing - values Binance already sent win.
        """
        result = dict(result)
        aliases = {
            "orderId": "algoId",
            "clientOrderId": "clientAlgoId",
            "stopPrice": "triggerPrice",
            "origQty": "quantity",
            "type": "orderType",
            "status": "algoStatus",
        }
        for standard, algo in aliases.items():
            if standard not in result and algo in result:
                result[standard] = result[algo]

        result.setdefault("executedQty", "0")
        result.setdefault("status", "NEW")  # newly accepted algo orders are NEW
        result.setdefault("type", params.get("type", "STOP"))
        result.setdefault("origQty", str(params.get("quantity", "0")))
        result.setdefault("price", str(params.get("price", "0")))
        return result

    def cancel_order(self, symbol: str, order_id: int) -> Dict[str, Any]:
        """Cancel a standard (non-algo) order.

        For orders placed via ``/fapi/v1/order`` (MARKET, LIMIT).
        For STOP/TAKE_PROFIT orders placed via the Algo API, use
        ``cancel_algo_order`` instead.

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

    def cancel_algo_order(
        self, symbol: str, algo_id: int
    ) -> Dict[str, Any]:
        """Cancel a conditional (algo) order.

        For orders placed via ``/fapi/v1/algoOrder`` (STOP, STOP_MARKET,
        TAKE_PROFIT, TAKE_PROFIT_MARKET).  These orders live under
        ``algoId``, not ``orderId``.

        Args:
            symbol:  Trading pair (e.g., BTCUSDT).
            algo_id: The algoId returned when the order was placed.

        Returns:
            Cancellation response from the API.
        """
        logger.info(
            "Cancelling algo order: symbol=%s algoId=%d", symbol, algo_id
        )
        return self._make_request(
            "DELETE",
            "/fapi/v1/algoOrder",
            params={"symbol": symbol.upper(), "algoId": algo_id},
        )

    def get_open_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all open standard orders, optionally filtered by symbol.

        Does NOT include algo/conditional orders.  Use
        ``get_open_algo_orders`` for those.

        Args:
            symbol: Optional trading pair filter.

        Returns:
            List of open order dicts.
        """
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._make_request("GET", "/fapi/v1/openOrders", params=params)

    def get_open_algo_orders(
        self, symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all open conditional (algo) orders.

        Returns orders placed via ``/fapi/v1/algoOrder``
        (STOP, STOP_MARKET, TAKE_PROFIT, etc.).

        Args:
            symbol: Optional trading pair filter.

        Returns:
            List of open algo order dicts.
        """
        params: Dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol.upper()
        return self._make_request(
            "GET", "/fapi/v1/openAlgoOrders", params=params
        )
