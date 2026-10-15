"""CLI tests: Typer's CliRunner with the network layer replaced by fakes."""

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import cli
from bot.config import Settings
from bot.exceptions import BinanceAPIError, NetworkError
from bot.models import OrderResponse

runner = CliRunner()

FILLED = OrderResponse(
    orderId=42,
    symbol="BTCUSDT",
    side="BUY",
    type="MARKET",
    status="FILLED",
    origQty="0.01",
    executedQty="0.01",
    price="0",
    avgPrice="65000.5",
    cumQuote="650.005",
)


def _fake_session(manager, base_url="https://testnet.binancefuture.com"):
    settings = Settings(api_key="k" * 20, api_secret="s" * 20, base_url=base_url)

    @contextmanager
    def session():
        yield settings, manager

    return session


@pytest.fixture
def manager(monkeypatch):
    m = MagicMock()
    monkeypatch.setattr(cli, "_session", _fake_session(m))
    return m


def test_version():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "Trading Bot" in result.output


def test_order_dry_run_never_touches_the_network(monkeypatch):
    def boom():
        raise AssertionError("dry run must not open a session")

    monkeypatch.setattr(cli, "_session", boom)
    result = runner.invoke(cli.app, ["order", "BTCUSDT", "BUY", "MARKET", "0.01", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output


def test_order_success(manager):
    manager.place_order.return_value = FILLED
    result = runner.invoke(cli.app, ["order", "BTCUSDT", "BUY", "MARKET", "0.01"])
    assert result.exit_code == 0
    assert "Order placed successfully" in result.output
    assert "65000.5" in result.output
    manager.place_order.assert_called_once()


def test_order_rejected_status_shows_failure_banner(manager):
    manager.place_order.return_value = FILLED.model_copy(update={"status": "REJECTED"})
    result = runner.invoke(cli.app, ["order", "BTCUSDT", "BUY", "MARKET", "0.01"])
    assert result.exit_code == 0
    assert "REJECTED" in result.output


@pytest.mark.parametrize(
    "args, needle",
    [
        (["order", "BTCUSDT", "HOLD", "MARKET", "1"], "Invalid side"),
        (["order", "BTCUSDT", "BUY", "LIMIT", "1"], "Price is required"),
        (["order", "BTCUSDT", "BUY", "MARKET", "Infinity"], "Invalid quantity"),
    ],
)
def test_order_validation_errors_exit_1(args, needle):
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 1
    assert needle in result.output


@pytest.mark.parametrize(
    "error, needle",
    [
        (BinanceAPIError(-2019, "Margin is insufficient"), "Binance API Error"),
        (NetworkError("down"), "Connection Error"),
        (RuntimeError("kaboom"), "Unexpected Error"),
    ],
)
def test_order_error_panels(manager, error, needle):
    manager.place_order.side_effect = error
    result = runner.invoke(cli.app, ["order", "BTCUSDT", "BUY", "MARKET", "0.01"])
    assert result.exit_code == 1
    assert needle in result.output


def test_orders_table_merges_standard_and_algo(manager):
    manager.list_open_orders.return_value = [
        dict(id="1", symbol="BTCUSDT", side="BUY", type="LIMIT", quantity="0.1",
             price="60000", trigger="0", status="NEW", kind="standard"),
        dict(id="9", symbol="ETHUSDT", side="SELL", type="STOP", quantity="2",
             price="3000", trigger="3100", status="NEW", kind="algo"),
    ]
    result = runner.invoke(cli.app, ["orders"])
    assert result.exit_code == 0
    for text in ("OPEN ORDERS", "BTCUSDT", "ETHUSDT", "3100"):
        assert text in result.output


def test_orders_empty_and_filtered(manager):
    manager.list_open_orders.return_value = []
    result = runner.invoke(cli.app, ["orders", "btcusdt"])
    assert result.exit_code == 0
    assert "No open orders" in result.output
    manager.list_open_orders.assert_called_once_with("btcusdt")


def test_orders_error_exit_1(manager):
    manager.list_open_orders.side_effect = NetworkError("down")
    assert runner.invoke(cli.app, ["orders"]).exit_code == 1


def test_account_table(manager):
    manager.get_account_balances.return_value = [
        dict(asset="USDT", wallet_balance="1000", available_balance="900",
             unrealized_pnl="5", margin_balance="1005")
    ]
    result = runner.invoke(cli.app, ["account"])
    assert result.exit_code == 0
    assert "USDT" in result.output and "1005" in result.output


def test_account_empty(manager):
    manager.get_account_balances.return_value = []
    assert "No non-zero balances" in runner.invoke(cli.app, ["account"]).output


def test_price(manager):
    manager.get_current_price.return_value = "65000.1"
    result = runner.invoke(cli.app, ["price", "btcusdt"])
    assert result.exit_code == 0
    assert "65000.1" in result.output


def test_cancel(manager):
    result = runner.invoke(cli.app, ["cancel", "BTCUSDT", "123"])
    assert result.exit_code == 0
    assert "cancelled successfully" in result.output
    manager.cancel_order.assert_called_once_with("BTCUSDT", 123)


def test_cancel_failure(manager):
    manager.cancel_order.side_effect = BinanceAPIError(-2011, "Unknown order sent.")
    assert runner.invoke(cli.app, ["cancel", "BTCUSDT", "123"]).exit_code == 1


def test_interactive_happy_path(manager):
    manager.get_current_price.return_value = "65000"
    manager.place_order.return_value = FILLED
    # symbol, side, type, qty, confirm place, place another?
    result = runner.invoke(cli.app, ["interactive"], input="BTCUSDT\nBUY\nMARKET\n0.01\ny\nn\n")
    assert result.exit_code == 0
    assert "Order placed successfully" in result.output
    assert "Thanks for using" in result.output


def test_interactive_declined_then_exit(manager):
    manager.get_current_price.side_effect = NetworkError("no price")
    result = runner.invoke(cli.app, ["interactive"], input="BTCUSDT\nBUY\nMARKET\n0.01\nn\nn\n")
    assert result.exit_code == 0
    assert "Order cancelled" in result.output
    manager.place_order.assert_not_called()


def test_interactive_bad_input_then_quit(manager):
    manager.get_current_price.return_value = "65000"
    result = runner.invoke(cli.app, ["interactive"], input="BTCUSDT\nBUY\nMARKET\nabc\nn\n")
    assert result.exit_code == 0
    assert "Invalid Input" in result.output


# ── _session ─────────────────────────────────────────────────────────


def test_session_closes_client_even_when_body_raises(monkeypatch):
    fake_client = MagicMock()
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda c: Settings(api_key="k" * 20, api_secret="s" * 20)))
    monkeypatch.setattr(cli, "BinanceClient", lambda settings: fake_client)
    with pytest.raises(RuntimeError):
        with cli._session():
            raise RuntimeError("boom")
    fake_client.sync_time.assert_called_once()
    fake_client.close.assert_called_once()


def test_session_warns_on_non_testnet_host(monkeypatch):
    fake_client = MagicMock()
    live = Settings(api_key="k" * 20, api_secret="s" * 20, base_url="https://fapi.binance.com")
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda c: live))
    monkeypatch.setattr(cli, "BinanceClient", lambda settings: fake_client)
    with cli._session():
        pass
    fake_client.close.assert_called_once()


def test_main_configures_logging_from_env(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(cli, "setup_logging", lambda **kw: seen.update(kw))
    monkeypatch.setattr(cli, "app", lambda: None)
    cli.main()
    assert seen == {"log_dir": str(tmp_path), "log_level": "DEBUG"}
