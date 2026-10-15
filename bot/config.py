"""
Configuration Management
========================

Loads application settings from environment variables (via .env file)
with sensible defaults.  Validates that required API credentials are
present at startup and provides a ``masked_key`` property so that keys
can be referenced in logs without leaking secrets.

Environment variables
---------------------
BINANCE_TESTNET_API_KEY      – API key from Binance Futures Testnet
BINANCE_TESTNET_API_SECRET   – API secret from Binance Futures Testnet
BINANCE_TESTNET_BASE_URL     – REST base URL (default: testnet.binancefuture.com)
LOG_LEVEL                    – Console log level (default: INFO)
LOG_DIR                      – Directory for log files (default: logs)
RECV_WINDOW                  – Signature recv window in ms (default: 5000)
MAX_RETRIES                  – Max retry attempts on failure (default: 3)
RETRY_DELAY                  – Base delay between retries in seconds (default: 1.0)
REQUEST_TIMEOUT              – HTTP request timeout in seconds (default: 30.0)
"""

import os
from dataclasses import dataclass
from typing import Callable, TypeVar
from urllib.parse import urlparse

from dotenv import load_dotenv

from bot.exceptions import ConfigurationError

_T = TypeVar("_T")

_TESTNET_HOSTS = {"testnet.binancefuture.com", "demo-fapi.binance.com"}


def _env(name: str, default: str, cast: Callable[[str], _T]) -> _T:
    """Read an env var and cast it, reporting bad values as ConfigurationError."""
    raw = os.getenv(name, default)
    try:
        return cast(raw)
    except ValueError:
        raise ConfigurationError(
            f"Invalid value for {name}: {raw!r} "
            f"(expected {getattr(cast, '__name__', 'a valid value')})."
        )


@dataclass(frozen=True)
class Settings:
    """Immutable application settings loaded from the environment.

    Raises ``ConfigurationError`` if required API credentials are missing.
    """

    api_key: str
    api_secret: str
    base_url: str = "https://testnet.binancefuture.com"
    recv_window: int = 5000
    max_retries: int = 3
    retry_delay: float = 1.0
    request_timeout: float = 30.0
    log_level: str = "INFO"
    log_dir: str = "logs"

    def __post_init__(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ConfigurationError(
                "API credentials are required. "
                "Set BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET "
                "in your .env file.  See .env.example for the template."
            )
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ConfigurationError(
                f"Invalid base URL {self.base_url!r}: it must be a full "
                "https:// URL. Requests are signed, so plain http is refused."
            )
        if self.max_retries < 1:
            raise ConfigurationError("MAX_RETRIES must be at least 1.")
        if self.retry_delay < 0 or self.request_timeout <= 0 or self.recv_window <= 0:
            raise ConfigurationError(
                "RETRY_DELAY must be >= 0, and REQUEST_TIMEOUT and "
                "RECV_WINDOW must be positive."
            )
        if self.recv_window > 60000:
            raise ConfigurationError(
                "RECV_WINDOW cannot exceed 60000 ms (Binance's maximum)."
            )

    # ── Factory ───────────────────────────────────────────────────────

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "Settings":
        """Load settings from environment variables / .env file."""
        load_dotenv(env_path)
        return cls(
            api_key=os.getenv("BINANCE_TESTNET_API_KEY", ""),
            api_secret=os.getenv("BINANCE_TESTNET_API_SECRET", ""),
            base_url=os.getenv(
                "BINANCE_TESTNET_BASE_URL",
                "https://testnet.binancefuture.com",
            ),
            recv_window=_env("RECV_WINDOW", "5000", int),
            max_retries=_env("MAX_RETRIES", "3", int),
            retry_delay=_env("RETRY_DELAY", "1.0", float),
            request_timeout=_env("REQUEST_TIMEOUT", "30.0", float),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            log_dir=os.getenv("LOG_DIR", "logs"),
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @property
    def is_testnet(self) -> bool:
        """True when the configured host is a known Binance Futures testnet."""
        return (urlparse(self.base_url).hostname or "") in _TESTNET_HOSTS

    @property
    def masked_key(self) -> str:
        """Return a partially masked API key safe for display/logging."""
        if len(self.api_key) >= 16:
            return f"{self.api_key[:4]}****"
        return "****"
