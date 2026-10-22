# Binance Futures Algorithmic Trading Bot & Execution Suite

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-140%20passed-success.svg)](https://pytest.org)
[![Risk Controls](https://img.shields.io/badge/Risk%20Engine-Institutional%20Grade-brightgreen.svg)](#-capital-preservation--risk-safeguards)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-grade, autonomous algorithmic trading system and execution suite for **Binance USDT-M Futures**. Built for real-world reliability, strict capital preservation, and live execution.

---

## ⚡ Highlights & Key Features

| Capability | Description |
|:---|:---|
| **Autonomous Real-Time Bot** | Ingests real-time prices & klines, evaluates alpha signals, sizes positions dynamically, and ratchets trailing stops automatically. |
| **Institutional Risk Engine** | Hard circuit breakers: 3% daily loss limit, 8% max drawdown stop, 30m consecutive loss cooldown, and strict 1% equity risk per trade. |
| **Dual Trading Modes** | **Paper Trading** (real-time forward-test with simulated fills, slippage, and fees) and **Live Real-Money Mode** (`--confirm` required). |
| **Historical Backtester** | Pulls historical Binance klines directly via API to simulate Win Rate, Profit Factor, Sharpe Ratio, and Drawdown curves. |
| **Emergency Panic Switch** | Instant one-command panic button (`trading-bot panic`) cancelling all working orders and market-closing open positions. |
| **Proven Alpha Strategies** | Multi-timeframe Trend Following (`trend` - EMA 9/21/200 + ATR) & Mean Reversion (`mean_reversion` - Bollinger Bands + RSI). |
| **Manual Execution Suite** | Complete CLI for Market, Limit, and Stop-Limit orders with exchange filter validation (Lot Size, Price Filter, Min Notional). |

---

## 🛡️ Capital Preservation & Risk Safeguards

When trading real capital in crypto futures, risk management is paramount. The bot enforces the following rules at the code level:

1. **Dynamic Position Sizing**:
   $$\text{Position Size} = \frac{\text{Account Balance} \times \text{Risk \%}}{|\text{Entry Price} - \text{Stop Loss Price}|}$$
   Every trade risks an exact percentage of equity (default: 1.0%), automatically accounting for volatility via ATR.
2. **Forced Isolated Margin**:
   The engine mandates `ISOLATED` margin mode on Binance so that risk is strictly contained to the allocated margin and cannot wipe the account.
3. **Conservative Leverage Caps**:
   Leverage is capped at **3x** (configurable up to a safe ceiling of 5x). Reckless 20x–125x leverage is actively blocked.
4. **Daily Loss Circuit Breaker**:
   If realized losses in any 24-hour window reach **3.0%** of starting balance, all trading halts immediately.
5. **Peak-to-Trough Drawdown Lock**:
   If portfolio equity drops **8.0%** below its all-time high-water mark, trading locks and requires manual reset.
6. **Consecutive Loss Cooldown**:
   After 3 consecutive stop-outs, the bot pauses trading for 30 minutes to prevent revenge-trading during whipsaw regimes.

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/sagar25446-prog/binance-futures-trading-bot.git
cd binance-futures-trading-bot
pip install -r requirements.txt
```

### 2. Configure Credentials

Copy `.env.example` to `.env` and insert your API credentials:

```bash
cp .env.example .env
```

```ini
BINANCE_TESTNET_API_KEY=your_key_here
BINANCE_TESTNET_API_SECRET=your_secret_here
BINANCE_TESTNET_BASE_URL=https://testnet.binancefuture.com
```

*(For live real-money trading, set `BINANCE_TESTNET_BASE_URL=https://fapi.binance.com` with your mainnet keys).*

---

## 🤖 Running the Autonomous Bot

### Paper Trading Mode (Zero Risk Forward-Testing)
Runs on live Binance price data with simulated fills, 5 bps taker commission, and slippage:

```bash
python cli.py start BTCUSDT --strategy trend --interval 15m --mode paper
```

To run a single polling check and print the live telemetry dashboard:
```bash
python cli.py start BTCUSDT --single-step
```

### Live Real-Money Trading
To trade with real capital on Binance Futures, the explicit `--confirm` flag is strictly required:

```bash
python cli.py start BTCUSDT --strategy trend --interval 15m --mode live --confirm
```

---

## 📊 Backtesting Strategies on Historical Data

Test quantitative strategies against real historical candles directly from Binance:

```bash
# Backtest Trend Following on 1,000 15m candles
python cli.py backtest BTCUSDT --strategy trend --interval 15m --candles 1000

# Backtest Mean Reversion on 500 5m candles
python cli.py backtest BTCUSDT --strategy mean_reversion --interval 5m --candles 500
```

Sample backtest report output:
```
  Backtest Results: EMA_Trend_ATR on BTCUSDT (15m)
┌───────────────────────────┬─────────────────┐
│ Metric                    │ Value           │
├───────────────────────────┼─────────────────┤
│ Initial Balance           │ $10,000.00      │
│ Final Balance             │ $10,845.20      │
│ Net Return                │ +$845.20 (+8.45%)│
│ Max Drawdown              │ $210.50 (2.05%) │
│ Total Trades              │ 18              │
│ Wins / Losses             │ 12 / 6          │
│ Win Rate                  │ 66.67%          │
│ Profit Factor             │ 2.45            │
│ Sharpe Ratio (Annualized) │ 1.84            │
└───────────────────────────┴─────────────────┘
```

---

## 🚨 Emergency Kill Switch

If market conditions become extreme or you need to exit all exposure immediately:

```bash
python cli.py panic BTCUSDT
```
This command:
1. Cancels all working Limit, Market, and Stop-Loss orders.
2. Cancels all conditional Algo orders (`/fapi/v1/algoOrder`).
3. Executes a Market exit order (`reduceOnly=True`) to completely flatten the position.

---

## 📈 Quantitative Strategies

List all built-in strategies and their target market regimes:

```bash
python cli.py strategies
```

1. **EMA Trend + ATR Trailing Stop (`trend`)**:
   - **Entry**: Fast EMA (9) crosses above Medium EMA (21) while Price > 200 EMA and ADX > 20.
   - **Stop-Loss**: Dynamic $2 \times \text{ATR}$.
   - **Take-Profit**: Dynamic $4 \times \text{ATR}$ (1:2 asymmetric risk-reward).
   - **Best for**: Trending markets, momentum expansion.

2. **Bollinger Bands + RSI Mean Reversion (`mean_reversion`)**:
   - **Entry**: Price rejects lower Bollinger Band with RSI climbing back out of oversold (< 30).
   - **Take-Profit**: Middle band (20 SMA).
   - **Best for**: Range-bound, sideways consolidation.

---

## 💻 Manual CLI Command Reference

| Command | Usage | Description |
|:---|:---|:---|
| `start` | `python cli.py start BTCUSDT --mode paper` | Start the autonomous bot with live Rich dashboard |
| `backtest` | `python cli.py backtest BTCUSDT --candles 1000` | Run historical backtesting with performance statistics |
| `panic` | `python cli.py panic BTCUSDT` | Emergency Kill Switch: cancel orders & flatten position |
| `positions` | `python cli.py positions` | View all active futures positions, margin, and unrealized PnL |
| `order` | `python cli.py order BTCUSDT BUY MARKET 0.01` | Place manual Market, Limit, or Stop-Limit order |
| `interactive` | `python cli.py interactive` | Guided menu-driven order placement |
| `account` | `python cli.py account` | Check wallet balance and margin health |
| `price` | `python cli.py price BTCUSDT` | Check live market price |
| `orders` | `python cli.py orders BTCUSDT` | List all open standard and algo orders |
| `cancel` | `python cli.py cancel BTCUSDT 12345678` | Cancel open order by ID |

---

## 🧪 Testing & Verification

The test suite contains **140 comprehensive unit and integration tests** covering indicators, risk logic, circuit breakers, strategies, orders, and CLI:

```bash
# Run all tests
python -m pytest -p no:capture
```

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
