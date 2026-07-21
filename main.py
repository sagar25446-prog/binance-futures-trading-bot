#!/usr/bin/env python3
"""
Entry point for the Binance Futures Testnet Trading Bot.

This script simply delegates to the CLI module.  You can run the bot with:

    python main.py --help
    python main.py order BTCUSDT BUY MARKET 0.01
    python main.py interactive
"""

from cli import main

if __name__ == "__main__":
    main()
