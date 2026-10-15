import json
import logging

from bot.logging_config import JSONFormatter, SecretSanitizer, setup_logging


def test_setup_logging_writes_json_lines_and_redacts(tmp_path):
    setup_logging(log_dir=str(tmp_path), log_level="WARNING")
    log = logging.getLogger("trading_bot.test")
    log.debug("api_key=ABCDEFGH12345678 should be redacted")
    for h in logging.getLogger("trading_bot").handlers:
        h.flush()

    lines = (tmp_path / "trading_bot.log").read_text().strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["level"] == "DEBUG"  # file handler always records DEBUG
    assert "ABCDEFGH****" in entry["message"]
    assert "12345678" not in entry["message"]


def test_setup_logging_is_idempotent(tmp_path):
    setup_logging(log_dir=str(tmp_path))
    setup_logging(log_dir=str(tmp_path))
    assert len(logging.getLogger("trading_bot").handlers) == 2  # console + file, no duplicates


def test_json_formatter_includes_exception_details():
    try:
        raise ValueError("bad thing")
    except ValueError:
        import sys
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    out = json.loads(JSONFormatter().format(record))
    assert out["exception"]["type"] == "ValueError"
    assert out["exception"]["message"] == "bad thing"


def test_sanitizer_redacts_string_args_too():
    record = logging.LogRecord(
        "t", logging.INFO, __file__, 1, "sig %s", ("signature=abcdef1234567890",), None
    )
    SecretSanitizer().filter(record)
    assert record.args == ("signature=abcdef12****",)
