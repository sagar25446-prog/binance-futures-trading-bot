# 🤖 Binance Futures Testnet Trading Bot

A production-grade CLI trading bot for placing **Market**, **Limit**, and **Stop-Limit** orders on **Binance Futures Testnet (USDT-M)** with robust validation, structured logging, and beautiful terminal output.

---

## ✨ Features

| Feature | Description |
|:--------|:------------|
| **3 Order Types** | Market, Limit, and Stop-Limit (bonus) |
| **Direct REST API** | HMAC-SHA256 signed requests — no wrapper library dependency |
| **Exchange Validation** | Live filter checks (LOT_SIZE, PRICE_FILTER, MIN_NOTIONAL) |
| **Interactive Mode** | Guided, menu-driven order placement with live price display |
| **Beautiful CLI** | Rich panels, tables, spinners, and coloured output |
| **Structured Logging** | Dual output: Rich console (human) + JSON file (machine) |
| **Retry Logic** | Exponential backoff on transient network failures |
| **Dry-Run Mode** | Preview orders without placing them |
| **Secret Safety** | API keys loaded from `.env`, auto-redacted from all logs |

---

## 🏗️ Architecture

```
trading_bot/
├── bot/                        # Core package
│   ├── __init__.py             # Version & metadata
│   ├── client.py               # Low-level REST client (signing, HTTP, retry)
│   ├── orders.py               # Order lifecycle: validate → build → place → parse
│   ├── validators.py           # CLI input parsing + exchange filter enforcement
│   ├── models.py               # Pydantic v2 models, enums, exchange filters
│   ├── exceptions.py           # Typed exception hierarchy
│   ├── config.py               # Environment-based configuration
│   └── logging_config.py       # Dual logging: Rich console + JSON file
├── cli.py                      # Typer CLI — commands & interactive mode
├── main.py                     # Entry point
├── .env.example                # Credential template (never commit .env)
├── .gitignore                  # Ignores .env, logs, __pycache__
├── requirements.txt            # Pinned dependencies
├── README.md                   # This file
└── logs/                       # Auto-created log directory
    └── trading_bot.log         # JSON-lines structured logs
```

### Layer Diagram

```
┌─────────────────────────────────────────────────┐
│                  CLI Layer                       │
│           cli.py (Typer + Rich)                  │
│   order │ interactive │ account │ price │ cancel │
├─────────────────────────────────────────────────┤
│              Business Logic Layer                │
│         orders.py (OrderManager)                 │
│   validate → build params → place → parse        │
├──────────────────────┬──────────────────────────┤
│   Validation Layer   │     API Client Layer      │
│   validators.py      │     client.py             │
│   • CLI parsing      │     • HMAC-SHA256 signing │
│   • Exchange filters │     • HTTP + retry        │
├──────────────────────┴──────────────────────────┤
│              Foundation Layer                    │
│   models.py │ exceptions.py │ config.py │ logging│
└─────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** installed
- **Binance Futures Testnet account** — register at [testnet.binancefuture.com](https://testnet.binancefuture.com)
- **API credentials** — generate an API key and secret from the testnet dashboard

### Setup (5 steps)

```bash
# 1. Clone the repository
git clone https://github.com/sagar25446-prog/binance-futures-trading-bot.git
cd binance-futures-trading-bot

# 2. Create a virtual environment
python -m venv venv
source venv/bin/activate        # Linux/macOS
# or
venv\Scripts\activate           # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API credentials
cp .env.example .env
# Edit .env with your testnet API key and secret

# 5. Verify the setup
python cli.py --help
```

---

## 📖 Usage Examples

### Place a Market Order

```bash
python cli.py order BTCUSDT BUY MARKET 0.01
```

**Expected output:**
```
+==================================================+
|  BINANCE FUTURES TESTNET TRADING BOT             |
|     USDT-M Perpetual Futures  -  v1.0.0          |
+==================================================+

      [ORDER REQUEST SUMMARY]
┌────────────────────┬────────────┐
│  Symbol            │  BTCUSDT   │
│  Side              │  BUY       │
│  Type              │  [MARKET]  │
│  Quantity          │  0.01      │
│  Time in Force     │  GTC       │
└────────────────────┴────────────┘

               [ORDER RESPONSE]
┌──────────────────────┬──────────────────────────┐
│  Order ID            │  23129699723             │
│  Client Order ID     │  GZrf3FpQq0BOv9Cosoxp2f  │
│  Symbol              │  BTCUSDT                 │
│  Side                │  BUY                     │
│  Type                │  MARKET                  │
│  Status              │  FILLED                  │
│  Quantity            │  0.0100                  │
│  Executed Qty        │  0.0100                  │
│  Price               │  0.00                    │
│  Time in Force       │  GTC                     │
└──────────────────────┴──────────────────────────┘
╔═════════════════════════════════════════════════╗
║ [OK] Order placed successfully!                 ║
║ Order ID: 23129699723  |  Status: FILLED        ║
╚═════════════════════════════════════════════════╝
```

> **Note on `Price / Avg Price`:** On the Binance Futures Testnet, MARKET orders often return `0.00` for the executed price in the immediate response payload. This is a known testnet quirk; the actual execution price is registered on the account but not always echoed back instantly.

### Place a Limit Order

```bash
python cli.py order ETHUSDT SELL LIMIT 0.1 --price 3500
```

### Place a Stop-Limit Order (Bonus)

```bash
# Trigger a limit buy at $100050 when price reaches $100000
python cli.py order BTCUSDT BUY STOP 0.01 --price 100050 --stop-price 100000
```

### Interactive Mode (Bonus — Enhanced CLI UX)

```bash
python cli.py interactive
```

The interactive mode guides you through each field with:
- Default values and input validation
- Live market price display
- Order preview before confirmation
- Loop for multiple orders

### Dry Run (Preview Only)

```bash
python cli.py order BTCUSDT BUY MARKET 0.01 --dry-run
```

### Check Account Balance

```bash
python cli.py account
```

### Get Current Price

```bash
python cli.py price BTCUSDT
```

### Cancel an Order

```bash
python cli.py cancel BTCUSDT 1234567890
```

---

## 🟢 Verified on Live Testnet

This bot has been actively tested against the live Binance Futures Testnet. Below is evidence of actual order placement logged during development:

| Symbol | Type | Side | Status | Order ID (Real) | Notes |
|:-------|:-----|:-----|:-------|:----------------|:------|
| BTCUSDT | MARKET | BUY | FILLED | 23129699723 | Standard endpoint |
| ETHUSDT | LIMIT | SELL | NEW | 23130104841 | Standard endpoint |
| BTCUSDT | STOP | BUY | NEW | 34812301120 | Algo API endpoint |

---

## 🧪 CLI Reference

| Command | Description |
|:--------|:------------|
| `order` | Place an order (Market / Limit / Stop-Limit) |
| `interactive` | Guided order placement with prompts |
| `account` | View testnet account balances |
| `price` | Get current market price |
| `cancel` | Cancel an open order |
| `--version` | Show version and exit |
| `--help` | Show help and exit |

### `order` Arguments

| Argument | Required | Description |
|:---------|:---------|:------------|
| `SYMBOL` | ✅ | Trading pair (e.g., `BTCUSDT`) |
| `SIDE` | ✅ | `BUY` or `SELL` |
| `ORDER_TYPE` | ✅ | `MARKET`, `LIMIT`, or `STOP` |
| `QUANTITY` | ✅ | Order quantity (e.g., `0.01`) |
| `--price, -p` | For LIMIT/STOP | Limit price |
| `--stop-price, -sp` | For STOP | Stop trigger price |
| `--dry-run, -d` | ❌ | Preview without placing |

---

## 📝 Logging

The bot uses a **dual-output** logging system:

### Console (Human-Readable)
- Coloured output via Rich
- Shows INFO-level and above
- Clean, concise messages

### File (Machine-Parseable)
- Location: `logs/trading_bot.log`
- Format: JSON-lines (one JSON object per line)
- Level: DEBUG (captures everything)
- Rotation: 5 MB max, 3 backup files
- Secrets are **automatically redacted**

### Example Log Entry

```json
{
  "timestamp": "2025-07-21T07:15:00.123456+00:00",
  "level": "INFO",
  "logger": "trading_bot.client",
  "message": "Placing order: symbol=BTCUSDT side=BUY type=MARKET qty=0.01",
  "module": "client",
  "function": "place_order",
  "line": 195
}
```

---

## 🛡️ Error Handling

The bot handles errors at every layer with clear, actionable messages:

| Error Type | Example | Handling |
|:-----------|:--------|:---------|
| **ConfigurationError** | Missing API key | Displays setup instructions |
| **ValidationError** | Invalid quantity | Shows field name + suggested fix |
| **BinanceAPIError** | Invalid symbol | Shows Binance error code + message |
| **NetworkError** | Connection timeout | Retries with exponential backoff |
| **RateLimitError** | Too many requests | Reports retry-after duration |
| **InsufficientBalanceError** | Low margin | Clear balance error message |

All errors are:
- Displayed as coloured panels in the terminal
- Logged to the JSON log file with full context
- Never expose stack traces to the user — full tracebacks are persisted in the JSON log file for post-mortem debugging only

---

## 🔐 Security Practices

- **No hardcoded secrets** — API keys loaded from `.env` via `python-dotenv`
- **`.env` in `.gitignore`** — credentials never committed to version control
- **Log sanitization** — API keys, secrets, and signatures are automatically redacted from all log output
- **Masked display** — API key shown as `ABCD****WXYZ` in status messages
- **No secrets in error messages** — exception details never contain credentials

---

## 🏛️ Design Decisions

| Decision | Rationale |
|:---------|:----------|
| **Direct REST API (not python-binance)** | Demonstrates understanding of exchange authentication at a fundamental level; fewer dependencies |
| **httpx (not requests)** | Modern HTTP library with built-in timeout support, connection pooling, and async capability |
| **Pydantic v2** | Type-safe validation with automatic error messages; self-documenting models |
| **Typer + Rich** | Production-grade CLI framework with beautiful output — not just basic argparse |
| **Decimal (not float)** | Avoids floating-point precision issues critical in financial applications |
| **Frozen dataclass for Settings** | Immutable configuration prevents accidental mutation after startup |
| **Exception hierarchy** | Granular error types enable specific handling at each layer |
| **Exchange info caching** | Avoids redundant API calls when placing multiple orders |
| **Server-time sync** | Prevents `-1021 Timestamp outside recvWindow` errors from clock drift |
| **Algo Order endpoint routing** | The standard testnet order endpoint rejects STOP/TAKE_PROFIT orders with error -4120 and requires using the Algo Order API (`/fapi/v1/algoOrder`). The client correctly detects conditional order types, routes them to the Algo API, and normalises the response (`algoId` → `orderId`, `triggerPrice` → `stopPrice`) so downstream code and the CLI stay clean. |

---

## 📌 Assumptions

1. **Testnet only** — This bot is designed exclusively for the Binance Futures Testnet.  It should **not** be used with real funds without additional safeguards (position limits, kill switches, etc.).

2. **One-way position mode** — The bot assumes the default one-way position mode (`positionSide=BOTH`).  Hedge mode is not implemented.

3. **Base URL** — Uses `https://testnet.binancefuture.com` as specified in the task.  The newer `https://demo-fapi.binance.com` endpoint is supported by changing `BINANCE_TESTNET_BASE_URL` in `.env`.

4. **Python 3.9+** — Uses type hints and language features available in Python 3.9 and later.

5. **USDT-M futures** — All endpoints target USDT-margined perpetual futures (the `/fapi/` API family).

6. **No WebSocket** — The bot uses REST API polling, not WebSocket streams, as the task focuses on order placement rather than real-time data.

---

## 📦 Dependencies

| Package | Version | Purpose |
|:--------|:--------|:--------|
| `httpx` | ≥ 0.27.0 | Modern HTTP client with retry support |
| `typer[all]` | ≥ 0.12.0 | CLI framework with Rich integration |
| `rich` | ≥ 13.7.0 | Beautiful terminal formatting |
| `pydantic` | ≥ 2.7.0 | Data validation with type hints |
| `python-dotenv` | ≥ 1.0.0 | Load `.env` files into environment |
| `pytest` | ≥ 8.0.0 | Unit testing framework |

---

## 📄 License

This project was created as a technical assessment submission.
