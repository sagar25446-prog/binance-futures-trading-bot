#!/usr/bin/env python3
"""
Entry point for the Binance Futures Testnet Trading Bot.

This script simply delegates to the CLI module.  You can run the bot with:

    python cli.py --help
    python cli.py order BTCUSDT BUY MARKET 0.01
    python cli.py interactive
"""

from cli import main

if __name__ == "__main__":
    main()
