# Binance Futures Algorithmic Trading Bot & Execution Suite

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-146%20passed-success.svg)](https://pytest.org)
[![Risk Controls](https://img.shields.io/badge/Risk%20Engine-Institutional%20Grade-brightgreen.svg)](#-capital-preservation--risk-safeguards)
[![Machine Learning](https://img.shields.io/badge/ML%20Alpha-HistGradientBoosting-orange.svg)](#-machine-learning-alpha-pipeline)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A production-grade, autonomous algorithmic trading system and quantitative execution suite for **Binance USDT-M Futures**. Built for real-world mathematical edge, institutional risk management, machine learning calibration, and autonomous profit generation.

---

## ⚡ Highlights & Key Features

| Capability | Description |
|:---|:---|
| **Autonomous Real-Time Bot** | Evaluates alpha signals, sizes positions dynamically, and manages bracket orders with automated Breakeven and Trailing Stop protection. |
| **Institutional Risk Engine** | Hard circuit breakers: 3% daily loss limit, 8% max drawdown stop, 30m consecutive loss cooldown, and strict 1% equity risk per trade. |
| **Dual-Regime Alpha Strategy** | Dynamically detects market regimes (ADX >= 22 = Trend, ADX <= 20 = Range), deploying asymmetric 5:1 trend runners and 2.2-std Bollinger mean-reversion while avoiding chop. |
| **Machine Learning Alpha** | Gradient-boosted decision trees (`HistGradientBoostingClassifier`) trained via walk-forward validation with out-of-sample directional probability filters. |
| **Automated Model Trainer** | `cli.py train <SYMBOL>`: Pulls live Binance historical candles, generates stationary features, runs walk-forward CV, and saves calibrated model artifacts. |
| **Hyperparameter Optimizer** | `cli.py optimize <SYMBOL>`: Evaluates parameter permutations across historical data to maximize Profit Factor and Sharpe Ratio net of all fees. |
| **Dual Trading Modes** | **Paper Mode** (realistic simulation with taker fees, slippage, and balance tracking) and **Live Real-Money Mode** (`--confirm` required). |
| **Emergency Panic Switch** | Instant one-command kill switch (`cli.py panic`) cancelling all working orders and market-closing open positions. |
| **System Readiness Verifier** | `cli.py verify <SYMBOL>`: Validates API latency, time offset, lot size precision, and exchange filters before deploying funds. |

---

## 🛡️ Capital Preservation & Risk Safeguards

When trading real capital in crypto futures, capital preservation is the #1 priority. The bot enforces the following rules at the code level:

1. **Dynamic Position Sizing**:
   $$\text{Position Size} = \frac{\text{Account Balance} \times \text{Risk \%}}{|\text{Entry Price} - \text{Stop Loss Price}|}$$
   Every trade risks an exact percentage of equity (default: 1.0%), automatically scaled by market volatility (ATR).
2. **Breakeven Profit Protection**:
   Once unrealized profit reaches $+1.5\text{x}$ initial stop distance, the engine automatically moves the Stop-Loss to `entry_price + fees`, guaranteeing that winning trades can never turn into losses.
3. **Forced Isolated Margin**:
   The engine mandates `ISOLATED` margin mode on Binance so that risk is strictly contained to the allocated margin and cannot wipe the account balance.
4. **Conservative Leverage Ceiling**:
   Leverage is capped at **3x** (configurable up to a maximum of 5x). High-risk 20x–125x leverage is actively blocked.
5. **Daily Loss Circuit Breaker**:
   If realized losses in any 24-hour rolling window reach **3.0%** of starting balance, all trading halts immediately.
6. **Peak-to-Trough Drawdown Lock**:
   If portfolio equity drops **8.0%** below its all-time high-water mark, trading locks and requires manual reset.
7. **Consecutive Loss Cooldown**:
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

Copy `.env.example` to `.env` and insert your Binance API credentials:

```bash
cp .env.example .env
```

```env
BINANCE_API_KEY=your_api_key_here
BINANCE_API_SECRET=your_api_secret_here
BINANCE_BASE_URL=https://testnet.binancefuture.com
TRADING_MODE=paper
MAX_LEVERAGE=3
```

> **Safety Notice:** Always test thoroughly in **Paper Mode** on testnet before deploying real capital.

---

## 📈 Quantitative Strategies

### 1. Adaptive Dual-Regime (`adaptive_regime`) — Recommended
- **Regime Detection**: Calculates ADX (14) and Bollinger bandwidth.
- **Trend Regime ($\text{ADX} \ge 22$)**: Enters on 20/50 EMA crossover in the direction of the 200 EMA with an asymmetric $5.0 \times \text{ATR}$ profit target and $1.8 \times \text{ATR}$ stop.
- **Range Regime ($\text{ADX} \le 20$)**: Enters on extreme 2.2-std Bollinger Band touches combined with RSI exhaustion (<32 / >68) targeting the mean ($1.5 \times \text{ATR}$).
- **Chop Zone ($20 < \text{ADX} < 22$)**: Remains strictly **FLAT** to avoid paying taker fees in choppy markets.
- **Breakeven Protection**: Locks stop loss at breakeven once $+1.5\text{x}$ ATR profit is reached.

### 2. Machine Learning Alpha (`ml_alpha`)
- Evaluates stationary log returns across multiple time horizons, EMA momentum spreads, ATR volatility ratio, Bollinger %B, RSI, and volume Z-scores.
- Calibrated probability output: only fires trades when directional confidence exceeds threshold (e.g. $P \ge 0.55$).

### 3. EMA Trend Following (`trend`)
- Multi-timeframe trend following using EMA 9/21 cross, 200 EMA macro filter, and ADX strength confirmation.

### 4. Mean Reversion (`mean_reversion`)
- Bollinger Band boundary scalping with RSI oversold/overbought momentum recovery.

---

## 💻 CLI Commands

### Verify System Readiness
```bash
python cli.py verify BTCUSDT
```

### Train Machine Learning Alpha Model
```bash
python cli.py train SOLUSDT --interval 1h --candles 1500
```

### Optimize Strategy Hyperparameters
```bash
python cli.py optimize SOLUSDT --strategy adaptive_regime --interval 1h --candles 1500
```

### Run Historical Backtest
```bash
python cli.py backtest SOLUSDT --strategy adaptive_regime --interval 1h --candles 1500
```

### Start Autonomous Trading (Paper Mode)
```bash
python cli.py start SOLUSDT --strategy adaptive_regime --interval 1h --mode paper
```

### Start Autonomous Trading (Live Real-Money Mode)
```bash
python cli.py start SOLUSDT --strategy adaptive_regime --interval 1h --mode live --confirm
```

### Emergency Panic Kill Switch
```bash
python cli.py panic SOLUSDT
```

---

## 🧪 Running Tests

```bash
python -m pytest
```
All **146 unit and integration tests** pass out of the box with zero warnings.

---

## 📄 License

MIT License. Designed for quantitative algorithmic trading on Binance Futures.
