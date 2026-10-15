import pytest

from bot.config import Settings
from bot.exceptions import ConfigurationError


def _make(**kw):
    base = dict(api_key="k" * 20, api_secret="s" * 20)
    base.update(kw)
    return Settings(**base)


def test_missing_credentials_rejected():
    with pytest.raises(ConfigurationError, match="credentials"):
        Settings(api_key="", api_secret="")


@pytest.mark.parametrize("url", ["http://testnet.binancefuture.com", "testnet.binancefuture.com", "https://"])
def test_non_https_or_malformed_base_url_rejected(url):
    with pytest.raises(ConfigurationError, match="base URL"):
        _make(base_url=url)


@pytest.mark.parametrize(
    "kw",
    [dict(max_retries=0), dict(retry_delay=-1), dict(request_timeout=0), dict(recv_window=0)],
)
def test_out_of_range_numbers_rejected(kw):
    with pytest.raises(ConfigurationError):
        _make(**kw)


def test_recv_window_upper_bound():
    with pytest.raises(ConfigurationError, match="60000"):
        _make(recv_window=60001)


def test_from_env_reads_values(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "abc")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "def")
    monkeypatch.setenv("MAX_RETRIES", "5")
    monkeypatch.setenv("RETRY_DELAY", "0.5")
    s = Settings.from_env(str(tmp_path / "missing.env"))
    assert (s.api_key, s.max_retries, s.retry_delay) == ("abc", 5, 0.5)


def test_from_env_bad_number_is_configuration_error(monkeypatch, tmp_path):
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "abc")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "def")
    monkeypatch.setenv("MAX_RETRIES", "three")
    with pytest.raises(ConfigurationError, match="MAX_RETRIES"):
        Settings.from_env(str(tmp_path / "missing.env"))


def test_is_testnet():
    assert _make().is_testnet
    assert not _make(base_url="https://fapi.binance.com").is_testnet


def test_masked_key_never_reveals_tail_or_short_keys():
    assert _make(api_key="ABCD" + "x" * 20).masked_key == "ABCD****"
    assert _make(api_key="short").masked_key == "****"
