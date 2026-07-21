"""
CLI Entry Point -- Binance Futures Testnet Trading Bot
=====================================================

Built with **Typer** (CLI framework) and **Rich** (terminal formatting)
to provide a professional command-line experience.

Commands
--------
order        Place a Market, Limit, or Stop-Limit order via arguments.
interactive  Launch guided, menu-driven order placement.
account      View testnet account balances.
price        Get current market price for a symbol.
cancel       Cancel an open order by orderId.

Every command displays:
- A coloured order-request summary panel
- A formatted order-response table (orderId, status, executedQty, avgPrice)
- A success / failure banner

All actions are logged to ``logs/trading_bot.log`` (JSON-lines, DEBUG level).
"""

import io
import logging
import sys
from typing import Optional

# ── Force UTF-8 stdout/stderr on Windows to support Rich formatting ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace"
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace"
    )

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from bot import __version__
from bot.client import BinanceClient
from bot.config import Settings
from bot.exceptions import (
    BinanceAPIError,
    ConfigurationError,
    NetworkError,
    TradingBotError,
    ValidationError,
)
from bot.logging_config import setup_logging
from bot.models import OrderRequest, OrderResponse, OrderSide, OrderType
from bot.orders import OrderManager
from bot.validators import validate_cli_inputs

logger = logging.getLogger("trading_bot.cli")
console = Console(force_terminal=True)

app = typer.Typer(
    name="trading-bot",
    help=(
        "Binance Futures Testnet Trading Bot -- "
        "Place Market, Limit & Stop-Limit orders via CLI"
    ),
    add_completion=False,
    rich_markup_mode="rich",
    no_args_is_help=True,
)


# ── Shared Helpers ────────────────────────────────────────────────────


def _get_manager() -> tuple:
    """Initialize Settings, BinanceClient, and OrderManager.

    Returns:
        Tuple of (Settings, OrderManager).
    """
    settings = Settings.from_env()
    client = BinanceClient(settings)
    client.sync_time()
    return settings, OrderManager(client)


def _print_banner() -> None:
    """Print the application banner."""
    banner_text = (
        "[bold cyan]+==================================================+[/]\n"
        "[bold cyan]|[/]  [bold white]BINANCE FUTURES TESTNET TRADING BOT[/]            [bold cyan]|[/]\n"
        "[bold cyan]|[/]  [dim white]   USDT-M Perpetual Futures  -  v{ver}[/]      [bold cyan]|[/]\n"
        "[bold cyan]+==================================================+[/]"
    ).format(ver=__version__)
    console.print(banner_text)
    console.print()


def _print_order_summary(request: OrderRequest) -> None:
    """Print a formatted order-request summary panel."""
    table = Table(
        title="[ORDER REQUEST SUMMARY]",
        box=box.ROUNDED,
        title_style="bold yellow",
        border_style="yellow",
        show_header=False,
        padding=(0, 2),
    )
    table.add_column("Field", style="bold cyan", width=16)
    table.add_column("Value", style="white")

    side_style = (
        "bold green" if request.side == OrderSide.BUY else "bold red"
    )
    type_label = {
        "MARKET": "[MARKET]",
        "LIMIT": "[LIMIT]",
        "STOP": "[STOP-LIMIT]",
    }.get(request.order_type.value, request.order_type.value)

    table.add_row("Symbol", f"[bold]{request.symbol}[/bold]")
    table.add_row(
        "Side", f"[{side_style}]{request.side.value}[/{side_style}]"
    )
    table.add_row("Type", type_label)
    table.add_row("Quantity", str(request.quantity))

    if request.price is not None:
        table.add_row("Price", f"${request.price}")
    if request.stop_price is not None:
        table.add_row("Stop Price", f"${request.stop_price}")

    table.add_row("Time in Force", request.time_in_force.value)

    console.print(table)
    console.print()


def _print_order_response(response: OrderResponse) -> None:
    """Print a formatted order-response table + success/failure banner."""
    status_styles = {
        "NEW": "bold yellow",
        "FILLED": "bold green",
        "PARTIALLY_FILLED": "bold cyan",
        "CANCELED": "bold red",
        "REJECTED": "bold red",
        "EXPIRED": "bold dim",
    }
    status_style = status_styles.get(response.status, "bold white")

    table = Table(
        title="[ORDER RESPONSE]",
        box=box.ROUNDED,
        title_style="bold green",
        border_style="green",
        show_header=False,
        padding=(0, 2),
    )
    table.add_column("Field", style="bold cyan", width=18)
    table.add_column("Value", style="white")

    table.add_row("Order ID", f"[bold]{response.order_id}[/bold]")
    table.add_row("Client Order ID", response.client_order_id)
    table.add_row("Symbol", response.symbol)
    table.add_row("Side", response.side)
    table.add_row("Type", response.order_type)
    table.add_row(
        "Status",
        f"[{status_style}]{response.status}[/{status_style}]",
    )
    table.add_row("Quantity", response.quantity)
    table.add_row("Executed Qty", response.executed_qty)
    table.add_row("Price", response.price)

    if response.avg_price and response.avg_price != "0":
        table.add_row(
            "Avg Price",
            f"[bold green]${response.avg_price}[/bold green]",
        )
    if response.stop_price and response.stop_price != "0":
        table.add_row("Stop Price", f"${response.stop_price}")
    if response.cum_quote and response.cum_quote != "0":
        table.add_row("Cum. Quote", f"${response.cum_quote}")

    table.add_row("Time in Force", response.time_in_force)

    console.print(table)

    # ── Success / failure banner ─────────────────────────────────────
    if response.status in ("NEW", "FILLED", "PARTIALLY_FILLED"):
        console.print(
            Panel(
                f"[bold green][OK] Order placed successfully![/bold green]\n"
                f"Order ID: [bold]{response.order_id}[/bold]  |  "
                f"Status: [{status_style}]{response.status}[/{status_style}]",
                border_style="green",
                box=box.DOUBLE,
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red][FAIL] Order was {response.status}[/bold red]",
                border_style="red",
                box=box.DOUBLE,
            )
        )


def _print_error(error: Exception) -> None:
    """Print a formatted, colour-coded error panel."""
    if isinstance(error, ValidationError):
        console.print(
            Panel(
                f"[bold red]Validation Error[/bold red]\n"
                f"Field: [cyan]{error.field}[/cyan]\n"
                f"{error.message}",
                title="[X] Invalid Input",
                border_style="red",
                box=box.ROUNDED,
            )
        )
    elif isinstance(error, BinanceAPIError):
        console.print(
            Panel(
                f"[bold red]API Error[/bold red] (Code: {error.code})\n"
                f"{error.message}",
                title="[X] Binance API Error",
                border_style="red",
                box=box.ROUNDED,
            )
        )
    elif isinstance(error, NetworkError):
        console.print(
            Panel(
                f"[bold red]Network Error[/bold red]\n{error.message}",
                title="[!] Connection Error",
                border_style="red",
                box=box.ROUNDED,
            )
        )
    elif isinstance(error, ConfigurationError):
        console.print(
            Panel(
                f"[bold red]Configuration Error[/bold red]\n{error.message}",
                title="[!] Setup Error",
                border_style="red",
                box=box.ROUNDED,
            )
        )
    else:
        console.print(
            Panel(
                f"[bold red]{type(error).__name__}[/bold red]\n{error}",
                title="[X] Unexpected Error",
                border_style="red",
                box=box.ROUNDED,
            )
        )


# ── CLI Commands ──────────────────────────────────────────────────────


@app.command()
def order(
    symbol: str = typer.Argument(
        ..., help="Trading pair (e.g., BTCUSDT)"
    ),
    side: str = typer.Argument(
        ..., help="Order side: BUY or SELL"
    ),
    order_type: str = typer.Argument(
        ..., help="Order type: MARKET, LIMIT, or STOP"
    ),
    quantity: str = typer.Argument(
        ..., help="Order quantity (e.g., 0.001)"
    ),
    price: Optional[str] = typer.Option(
        None, "--price", "-p", help="Limit price (required for LIMIT/STOP)"
    ),
    stop_price: Optional[str] = typer.Option(
        None,
        "--stop-price",
        "-sp",
        help="Stop trigger price (required for STOP)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-d", help="Preview order without placing it"
    ),
) -> None:
    """Place a Market, Limit, or Stop-Limit order.

    \b
    Examples:
        # Market buy 0.01 BTC
        python cli.py order BTCUSDT BUY MARKET 0.01

        # Limit sell 0.5 ETH at $3500
        python cli.py order ETHUSDT SELL LIMIT 0.5 --price 3500

        # Stop-limit buy 0.01 BTC: trigger at $100000, limit at $100050
        python cli.py order BTCUSDT BUY STOP 0.01 --price 100050 --stop-price 100000

        # Dry run (preview without placing)
        python cli.py order BTCUSDT BUY MARKET 0.01 --dry-run
    """
    _print_banner()

    try:
        # Validate CLI inputs into a typed OrderRequest
        request = validate_cli_inputs(
            symbol, side, order_type, quantity, price, stop_price
        )
        _print_order_summary(request)

        if dry_run:
            console.print(
                Panel(
                    "[bold yellow][DRY RUN] Order not placed[/bold yellow]\n"
                    "[dim]Remove --dry-run to execute this order.[/dim]",
                    border_style="yellow",
                )
            )
            return

        # Connect and place order
        with console.status(
            "[bold cyan]Connecting to Binance Testnet...[/bold cyan]",
            spinner="dots",
        ):
            settings, manager = _get_manager()

        with console.status(
            "[bold cyan]Placing order...[/bold cyan]", spinner="dots"
        ):
            response = manager.place_order(request)

        _print_order_response(response)

    except TradingBotError as exc:
        _print_error(exc)
        logger.error("Order failed: %s", str(exc))
        raise typer.Exit(code=1)
    except Exception as exc:
        _print_error(exc)
        logger.exception("Unexpected error during order placement")
        raise typer.Exit(code=1)


@app.command()
def interactive() -> None:
    """Launch interactive order placement mode with guided prompts.

    \b
    Walks you through each field step-by-step:
    symbol > side > type > quantity > price > confirmation > result.
    Displays the current market price to help you set limit prices.
    Loops until you choose to exit.
    """
    _print_banner()
    console.print("[bold cyan]>> Interactive Order Placement Mode[/bold cyan]")
    console.print(
        "[dim]Follow the prompts to build and place your order.\n"
        "Press Ctrl+C at any time to exit.[/dim]\n"
    )

    try:
        # Initialize connection once for the whole session
        with console.status(
            "[bold cyan]Connecting to Binance Testnet...[/bold cyan]",
            spinner="dots",
        ):
            settings, manager = _get_manager()
        console.print("[green][OK][/green] Connected to Binance Testnet\n")

        while True:
            # ── Gather inputs ────────────────────────────────────────
            console.rule("[bold cyan]New Order[/bold cyan]", style="cyan")
            console.print()

            symbol = Prompt.ask(
                "[bold cyan]Symbol[/bold cyan]", default="BTCUSDT"
            ).upper().strip()

            # Show current price as context
            try:
                with console.status("[dim]Fetching price...[/dim]"):
                    current_price = manager.get_current_price(symbol)
                console.print(
                    f"  [dim]Current {symbol} price: "
                    f"[bold green]${current_price}[/bold green][/dim]\n"
                )
            except Exception:
                console.print(
                    "  [dim yellow][!] Could not fetch current price[/dim yellow]\n"
                )
                current_price = None

            side = Prompt.ask(
                "[bold cyan]Side[/bold cyan]",
                choices=["BUY", "SELL"],
                default="BUY",
            )

            otype = Prompt.ask(
                "[bold cyan]Order Type[/bold cyan]",
                choices=["MARKET", "LIMIT", "STOP"],
                default="MARKET",
            )

            quantity = Prompt.ask("[bold cyan]Quantity[/bold cyan]")

            price_str: Optional[str] = None
            stop_str: Optional[str] = None

            if otype in ("LIMIT", "STOP"):
                default_price = str(current_price) if current_price else None
                price_str = Prompt.ask(
                    "[bold cyan]Limit Price[/bold cyan]",
                    default=default_price,
                )

            if otype == "STOP":
                stop_str = Prompt.ask(
                    "[bold cyan]Stop Trigger Price[/bold cyan]"
                )

            # ── Validate and preview ─────────────────────────────────
            try:
                request = validate_cli_inputs(
                    symbol, side, otype, quantity, price_str, stop_str
                )
            except ValidationError as exc:
                _print_error(exc)
                console.print()
                if Confirm.ask("Try again?", default=True):
                    continue
                break

            console.print()
            _print_order_summary(request)

            if not Confirm.ask("[bold yellow]Place this order?[/bold yellow]"):
                console.print("[dim]Order cancelled.[/dim]\n")
                if not Confirm.ask("Place another order?", default=True):
                    break
                continue

            # ── Place order ──────────────────────────────────────────
            try:
                with console.status(
                    "[bold cyan]Placing order...[/bold cyan]", spinner="dots"
                ):
                    response = manager.place_order(request)
                _print_order_response(response)
            except TradingBotError as exc:
                _print_error(exc)
                logger.error("Order failed: %s", str(exc))

            console.print()
            if not Confirm.ask("Place another order?", default=True):
                break

        console.print(
            "\n[bold cyan]Thanks for using the Trading Bot![/bold cyan]"
        )

    except ConfigurationError as exc:
        _print_error(exc)
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print(
            "\n\n[bold cyan]Session ended.  Goodbye![/bold cyan]"
        )
    except Exception as exc:
        _print_error(exc)
        logger.exception("Unexpected error in interactive mode")
        raise typer.Exit(code=1)


@app.command()
def account() -> None:
    """View testnet account balances.

    Displays a table of all non-zero asset balances including wallet
    balance, available balance, unrealized PnL, and margin balance.
    """
    _print_banner()

    try:
        with console.status(
            "[bold cyan]Fetching account info...[/bold cyan]", spinner="dots"
        ):
            _settings, manager = _get_manager()
            balances = manager.get_account_balances()

        if not balances:
            console.print("[yellow]No non-zero balances found.[/yellow]")
            return

        table = Table(
            title="[ACCOUNT BALANCES]",
            box=box.ROUNDED,
            title_style="bold green",
            border_style="green",
        )
        table.add_column("Asset", style="bold cyan")
        table.add_column("Wallet Balance", style="white", justify="right")
        table.add_column("Available", style="green", justify="right")
        table.add_column("Unrealized PnL", style="yellow", justify="right")
        table.add_column("Margin Balance", style="white", justify="right")

        for bal in balances:
            table.add_row(
                bal["asset"],
                bal["wallet_balance"],
                bal["available_balance"],
                bal["unrealized_pnl"],
                bal["margin_balance"],
            )

        console.print(table)

    except TradingBotError as exc:
        _print_error(exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        _print_error(exc)
        logger.exception("Unexpected error")
        raise typer.Exit(code=1)


@app.command()
def price(
    symbol: str = typer.Argument(
        "BTCUSDT", help="Trading pair (e.g., BTCUSDT)"
    ),
) -> None:
    """Get current market price for a symbol.

    \b
    Example:
        python cli.py price ETHUSDT
    """
    try:
        with console.status(
            f"[bold cyan]Fetching {symbol.upper()} price...[/bold cyan]",
            spinner="dots",
        ):
            _settings, manager = _get_manager()
            current = manager.get_current_price(symbol)

        console.print(
            Panel(
                f"[bold white]{symbol.upper()}[/bold white]\n"
                f"[bold green]${current}[/bold green]",
                title="[CURRENT PRICE]",
                border_style="green",
                box=box.ROUNDED,
            )
        )
    except TradingBotError as exc:
        _print_error(exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        _print_error(exc)
        logger.exception("Unexpected error")
        raise typer.Exit(code=1)


@app.command()
def cancel(
    symbol: str = typer.Argument(..., help="Trading pair (e.g., BTCUSDT)"),
    order_id: int = typer.Argument(..., help="Order ID to cancel"),
) -> None:
    """Cancel an open order by its Order ID.

    \b
    Example:
        python cli.py cancel BTCUSDT 123456789
    """
    try:
        with console.status(
            "[bold cyan]Cancelling order...[/bold cyan]", spinner="dots"
        ):
            _settings, manager = _get_manager()
            manager.cancel_order(symbol, order_id)

        console.print(
            Panel(
                f"[bold green][OK] Order {order_id} cancelled successfully[/bold green]",
                border_style="green",
            )
        )
    except TradingBotError as exc:
        _print_error(exc)
        raise typer.Exit(code=1)
    except Exception as exc:
        _print_error(exc)
        logger.exception("Unexpected error")
        raise typer.Exit(code=1)


# ── Version Callback ─────────────────────────────────────────────────


def _version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(
            f"[bold cyan]Trading Bot[/bold cyan] v{__version__}"
        )
        raise typer.Exit()


@app.callback()
def _main_callback(
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """Binance Futures Testnet Trading Bot"""
    pass


# ── Entry Point ──────────────────────────────────────────────────────


def main() -> None:
    """Application entry point -- sets up logging then launches the CLI."""
    setup_logging()
    app()


if __name__ == "__main__":
    main()
