"""
Logging Configuration
=====================

Sets up a dual-output logging system:

1. **Console** — Rich-formatted, coloured, human-readable output at the
   configured log level (default INFO).  Ideal for interactive use.
2. **File** — Structured JSON-lines written to a rotating log file at
   DEBUG level.  Machine-parseable for post-mortem analysis.

A ``SecretSanitizer`` filter automatically redacts API keys, secrets,
and signatures from all log output to prevent credential leaks.

Log rotation keeps file sizes manageable (5 MB max, 3 backups).
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from rich.logging import RichHandler


# ── Secret Sanitizer ──────────────────────────────────────────────────


class SecretSanitizer(logging.Filter):
    """Logging filter that redacts sensitive data from log records.

    Patterns matched:
    - API keys and secrets in key-value assignments
    - Signature query parameters
    - X-MBX-APIKEY header values
    """

    _PATTERNS = [
        # api_key = "ABCDEFGH..."  →  api_key = "ABCD****"
        (
            re.compile(
                r"(api[_-]?key[\"'\s:=]+)([A-Za-z0-9]{8})[A-Za-z0-9]+",
                re.IGNORECASE,
            ),
            r"\1\2****",
        ),
        # api_secret = "ABCD..."  →  api_secret = "ABCD****"
        (
            re.compile(
                r"(api[_-]?secret[\"'\s:=]+)([A-Za-z0-9]{4})[A-Za-z0-9]+",
                re.IGNORECASE,
            ),
            r"\1\2****",
        ),
        # signature=abcdef1234...  →  signature=abcdef12****
        (
            re.compile(
                r"(signature[=&])([a-f0-9]{8})[a-f0-9]+",
                re.IGNORECASE,
            ),
            r"\1\2****",
        ),
        # X-MBX-APIKEY: ABCDEFGH...  →  X-MBX-APIKEY: ABCDEFGH****
        (
            re.compile(
                r"(X-MBX-APIKEY[\"'\s:=]+)([A-Za-z0-9]{8})[A-Za-z0-9]+",
                re.IGNORECASE,
            ),
            r"\1\2****",
        ),
    ]

    def filter(self, record: logging.LogRecord) -> bool:
        """Sanitize the log record message and arguments in-place."""
        if isinstance(record.msg, str):
            for pattern, replacement in self._PATTERNS:
                record.msg = pattern.sub(replacement, record.msg)
        if record.args:
            sanitized = []
            for arg in record.args:
                if isinstance(arg, str):
                    for pattern, replacement in self._PATTERNS:
                        arg = pattern.sub(replacement, arg)
                sanitized.append(arg)
            record.args = tuple(sanitized)
        return True


# ── JSON Formatter ────────────────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects.

    Each line contains: timestamp (ISO-8601 UTC), level, logger name,
    message, module, function, line number, and optional exception info.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": str(record.exc_info[1]),
            }
        return json.dumps(log_entry, default=str)


# ── Setup Function ────────────────────────────────────────────────────


def setup_logging(
    log_dir: str = "logs",
    log_level: str = "INFO",
) -> None:
    """Configure dual-output logging (console + JSON file).

    Args:
        log_dir:   Directory for log files.  Created if it doesn't exist.
        log_level: Minimum level for console output (file always logs DEBUG).
    """
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger("trading_bot")
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    sanitizer = SecretSanitizer()

    # ── Console handler (Rich) ────────────────────────────────────────
    console_handler = RichHandler(
        level=getattr(logging, log_level.upper(), logging.INFO),
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        show_time=True,
        show_path=False,
        markup=True,
    )
    console_handler.addFilter(sanitizer)
    root.addHandler(console_handler)

    # ── File handler (JSON, rotating) ─────────────────────────────────
    log_file = os.path.join(log_dir, "trading_bot.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB per file
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(JSONFormatter())
    file_handler.addFilter(sanitizer)
    root.addHandler(file_handler)

    # ── Suppress noisy third-party loggers ────────────────────────────
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
