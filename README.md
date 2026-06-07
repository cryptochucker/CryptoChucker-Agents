# CryptoChucker Agents

A modular, paper-trading-complete crypto trading suite built on Python 3.11.
Signals come from the **Money Line**, a volume-weighted, EMA-smoothed trend indicator.
The scanner watches multiple symbols, ranks fresh flip signals, and drives a paper
executor with full risk management. All results persist to SQLite. Alerts fan out
to Telegram/Discord/email. An optional LLM co-pilot can validate signals before
execution. A Streamlit dashboard provides live monitoring, and a built-in backtester
lets you grid-search parameters.

Live trading is built but **fail-closed** behind a double gate: you must explicitly
set both `PAPER_TRADING=false` AND `ENABLE_LIVE_TRADING=true` in `.env` to unlock it.

> **WARNING: Live order execution is BUILT but UNTESTED in this release.** It ships
> disabled by default and requires both env gates to be set explicitly. The system
> defaults to paper mode when either gate is absent or set to any value other than the
> exact enabling strings. Enable live trading only after you have validated paper mode
> end-to-end for your exchange and symbol set. You do so entirely at your own risk.

---

## Quick Start

### Docker Compose (recommended)

```bash
cp .env.example .env          # fill in the keys you need (see section below)
docker compose up             # starts the trading suite + dashboard
```

The dashboard is served at `http://localhost:8501`.

### Virtual environment (development)

```bash
python -m venv .venv
# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py

# Linux/macOS
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

---

## Environment Variables (API Keys)

Copy `.env.example` to `.env` and fill in the values you need.
**Never commit `.env` to source control.** The `.gitignore` excludes it.

| Variable | Purpose |
|---|---|
| `EXCHANGE_API_KEY` | Exchange API key (only needed for live trading) |
| `EXCHANGE_API_SECRET` | Exchange API secret |
| `EXCHANGE_API_PASSWORD` | Exchange API passphrase (BloFin, Bitget) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for alerts |
| `DISCORD_WEBHOOK_URL` | Discord webhook URL for alerts |
| `SMTP_HOST` | SMTP host for email alerts |
| `SMTP_PORT` | SMTP port (default 587) |
| `SMTP_USER` | SMTP username |
| `SMTP_PASSWORD` | SMTP password |
| `ALERT_EMAIL_TO` | Alert recipient email address |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key (LLM co-pilot, off by default) |
| `OPENAI_API_KEY` | OpenAI API key (LLM co-pilot, off by default) |
| `PAPER_TRADING` | Set `true` to force paper mode (default: `true`) |
| `ENABLE_LIVE_TRADING` | Set `true` to unlock the live gate (default: `false`) |

**Paper trading is the default.** You do not need any exchange credentials to run in paper mode.
To enable live trading, BOTH `PAPER_TRADING=false` AND `ENABLE_LIVE_TRADING=true` must be set.

---

## Customising Rules (`config.yaml`)

All trading behaviour is driven by `config.yaml`. Key sections:

```yaml
exchange: blofin        # Exchange: blofin|bitget|binance|bybit|kraken|coinbase
paper_trading: true     # Always true until BOTH env gates are set

scanner:
  interval_minutes: 5   # How often to scan the watchlist
  min_strength: 55      # Minimum signal strength to act on (0-100)
  volume_surge_mult: 2.0  # Minimum volume vs rolling average to qualify

signal:
  money_line_length: 8  # VWMA window
  smooth: 14            # EMA span
  slope_len: 3          # Slope averaging window

executor:
  profit_target_pct: 0.06    # Take-profit at 6% net (after fees)
  trailing_stop_pct: 0.03    # Trailing stop distance
  max_hold_hours: 48         # Force exit after 48h
  use_dip_filter: true       # Only enter on dips (close < EMA20 or RSI < 40)

risk:
  account_balance: 10000     # Paper account size in USD
  risk_pct: 0.01             # Risk 1% of balance per trade
  max_exposure_pct: 0.15     # Maximum portfolio exposure
  max_drawdown_pct: 0.20     # Kill switch at 20% drawdown

alerts:
  telegram: true
  discord: false
  email: false
  send_chart_image: true

llm_copilot:
  enabled: false          # Off by default; set true + supply API key to enable
  provider: anthropic     # anthropic|openai|ollama
```

Edit `watchlist.json` to control which symbols are scanned:

```json
["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"]
```

---

## Backtesting

Use the backtester from Python or via the dashboard:

```python
from agents.backtester import Backtester
from utils.config_schema import load_config
import pandas as pd

cfg = load_config("config.yaml")
df = pd.read_csv("my_ohlcv_data.csv", index_col=0, parse_dates=True)

bt = Backtester(cfg)
result = bt.run(df)
print(result)
# Returns: total_return, sharpe_ratio, sortino_ratio, max_drawdown,
#          num_trades, win_rate, profit_factor, calmar_ratio
```

**Grid search** over parameters:

```python
param_grid = {
    "money_line_length": [6, 8, 10],
    "smooth": [10, 14, 20],
    "volume_surge_mult": [1.5, 2.0, 2.5],
}
results = bt.grid_search(df, param_grid)
# Returns a list of (params_dict, metrics_dict) sorted by Sharpe ratio
```

From the dashboard: open the **Backtester** tab, load a CSV or live data, and click **Run Backtest**.

---

## Adding the TradingView Indicators Manually

Two Pine v6 indicators are included in `indicators/`:
- `indicators/money_line_pine.txt` - Money Line overlay for individual charts
- `indicators/money_scanner_pine.txt` - Multi-symbol Money Line scanner (up to 30 symbols)

**How to add them to a TradingView chart:**

1. Open TradingView in your browser.
2. Open the **Pine Script Editor** (bottom panel or `Alt+P`).
3. Click **New script** to open a blank editor tab.
4. Open the relevant `.txt` file in this repo and paste the entire contents into the editor.
5. Click **Save** (give it any name).
6. Click **Add to chart**.
7. Repeat for the second indicator.

Auto-deploy via TradingView MCP is intentionally skipped to avoid overwriting any existing
scripts you may have saved. Manual paste is the safe, one-time operation.

---

## Dashboard

```bash
# With venv active:
python -m streamlit run agents/dashboard.py

# With Docker:
docker compose up dashboard
```

Dashboard at `http://localhost:8501` shows:

- Mode pill (PAPER / LIVE)
- Agent toggle controls
- KPIs: total return, Sharpe ratio, win rate, open positions
- Recent signals feed
- Equity curve chart
- Load live chart button (opens TradingView)
- Backtest tab with parameter grid search
- Live logs panel

The dashboard is a dark-themed, mobile-friendly Streamlit app that reads live state
directly from the SQLite store. The **Overview** tab shows a mode pill (PAPER/LIVE),
current KPIs (total return, Sharpe ratio, win rate, open positions), a scrolling
signals feed, and a real-time equity curve chart. The **Scanner** tab lists recent
signals with strength bars and allows manual re-scans. The **Backtest** tab exposes
the parameter grid-search UI: load a CSV or pull live OHLCV data, configure the
grid, and view ranked results sorted by Sharpe ratio. Run it with
`streamlit run agents/dashboard.py` (or `docker compose up dashboard`).

---

## Notes on Dependencies

`vectorbt` and `pandas_ta` have no wheels for Windows/Python 3.11 so equivalent
pure-pandas/numpy implementations are used throughout:

- Money Line indicator: `agents/signal_agent.py` (ATR, MFI, RSI, ADX all pure pandas)
- Backtester: `agents/backtester.py` (vectorbt-equivalent metrics, pure numpy)

The math is documented in `STRATEGY.md`.

---

## Running Tests

```bash
.venv\Scripts\python.exe -m pytest -q
# or
python -m pytest -q
```

All tests are deterministic (no network required). The e2e smoke test
(`tests/test_e2e_paper_smoke.py`) exercises the full pipeline using
the committed CSV fixture (`tests/fixtures/ohlcv_btc_4h.csv`).
