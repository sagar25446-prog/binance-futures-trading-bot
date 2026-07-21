import logging
from bot.logging_config import SecretSanitizer

def test_secret_sanitizer():
    sanitizer = SecretSanitizer()
    
    # Test api_key redaction
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Connecting with api_key='1234567890abcdef'", args=(), exc_info=None
    )
    sanitizer.filter(record)
    assert "12345678****" in record.msg
    assert "90abcdef" not in record.msg
    
    # Test api_secret redaction
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Using api_secret = abcdef123456", args=(), exc_info=None
    )
    sanitizer.filter(record)
    assert "abcd****" in record.msg
    assert "123456" not in record.msg
    
    # Test signature redaction
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="signature=a1b2c3d4e5f6g7h8", args=(), exc_info=None
    )
    sanitizer.filter(record)
    assert "a1b2c3d4****" in record.msg
    
    # Test header redaction
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0,
        msg="Headers: X-MBX-APIKEY: 1234567890abcdef", args=(), exc_info=None
    )
    sanitizer.filter(record)
    assert "12345678****" in record.msg
