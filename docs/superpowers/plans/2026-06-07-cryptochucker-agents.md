# CryptoChucker Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a paper-trading-complete, modular crypto trading suite (Money Line signal, multi-symbol scanner, paper executor, alerts, Streamlit dashboard, vectorbt backtester, two TradingView Pine indicators) that runs end-to-end on real public market data with zero errors, with live trading built but fail-closed behind a double gate.

**Architecture:** In-process asyncio agents orchestrated by `main.py` and scheduled with APScheduler. A single pydantic-validated `config.yaml` drives behavior; secrets live only in `.env`. SQLite is the default store. Each agent is a focused module with a small public interface and isolated failure.

**Tech Stack:** Python 3.11, ccxt, pandas, pandas_ta, vectorbt, streamlit, plotly, python-telegram-bot, loguru, APScheduler, pydantic, pyyaml, pytest, ruff. Reviewer/approver: Codex CLI (`gpt-5.5`).

**Authoritative spec:** `docs/superpowers/specs/2026-06-07-cryptochucker-agents-design.md` (Codex Gate 0 PASS).

---

## Conventions (read before any task)

- **TDD always:** write the failing test, run it red, write minimal code, run it green, commit. One action per step.
- **Commits:** Conventional Commits (`feat:`, `test:`, `chore:`, `docs:`, `fix:`). End every commit body with the Co-Authored-By line:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Run from repo root:** `C:\Users\jason\trading-view\personal-trading-suite\CryptoChucker-Agents`. Use the project venv `.venv` (created in Task 1.0). On Windows the interpreter is `.venv\Scripts\python.exe`; commands below use `python`/`pytest` assuming the venv is active or invoked via `python -m`.
- **No secrets, ever:** never read, print, copy, or commit a secret value from any `.env` (this repo's or another project's). Reference env var **names** only. `.env` is git-ignored; `.env.example` ships names only.
- **Codex review gate (end of every stage):** stage the diff and run the gate. This is the bridge the owner requires.

  ```bash
  # from repo root, with all stage changes staged (git add -A)
  git add -A
  printf 'You are the Stage Gate N reviewer (independent senior crypto trading-systems architect). REVIEW ONLY; do not modify files. Review the STAGED git diff for this stage against docs/superpowers/specs/2026-06-07-cryptochucker-agents-design.md. Check correctness, the live-trading double-gate safety (Section 11), secrets hygiene (no secret values, .gitignore, names-only), test quality, and spec adherence for this stage. Classify every finding BLOCKING/MEDIUM/LOW. End with exactly "VERDICT: PASS" (zero BLOCKING) or "VERDICT: CHANGES_REQUIRED" followed by the BLOCKING bullets.' | codex exec review -s read-only -c approval_policy="never" 2>&1 | tee reviews/gate-N-codex.md
  ```

  - Record the exact command, the `git rev-parse HEAD` / staged-diff ref, and a UTC timestamp at the top of `reviews/gate-N-codex.md`.
  - Fix every BLOCKING and re-run until `VERDICT: PASS`. Fix MEDIUM/LOW now or log them in `BUILD_REPORT.md` with rationale.
  - Only a PASS advances to the next stage. Commit the gate verdict file.
- **Definition of done / hard stop:** spec Section 1. When Stage 6 passes and all DoD items hold, STOP and hand off for formal approval. No extra polishing.

---

## File map (decomposition is locked here)

| File | Responsibility |
|---|---|
| `config.yaml` | All user settings (sample committed) |
| `.env.example` | Secret var NAMES only |
| `requirements.txt`, `pyproject.toml` | Deps + ruff/pytest config |
| `.pre-commit-config.yaml` | gitleaks + ruff |
| `utils/config_schema.py` | pydantic models + `load_config()` |
| `utils/logging_config.py` | loguru setup |
| `utils/fees.py` | per-exchange fee calculator |
| `utils/helpers.py` | watchlist CSV/JSON import/export |
| `utils/data_fetcher.py` | CCXT public OHLCV (+ retry) |
| `utils/risk_manager.py` | sizing, caps, drawdown stop |
| `utils/store.py` | SQLite persistence |
| `utils/safety.py` | live-trading double-gate guard + client factory |
| `utils/llm_copilot.py` | optional validator (OFF default) |
| `agents/signal_agent.py` | Money Line `get_money_line()` |
| `agents/scanner_agent.py` | multi-symbol scan + rank |
| `agents/alert_agent.py` | Telegram/Discord/email + chart |
| `agents/executor_agent.py` | paper executor; live guarded |
| `agents/backtester.py` | vectorbt metrics + grid search |
| `agents/dashboard.py` | Streamlit + Plotly (from approved mockup) |
| `indicators/money_line_pine.txt` | Pine v6 Money Line |
| `indicators/money_scanner_pine.txt` | Pine v6 Money Scanner (30 syms) |
| `main.py` | orchestrator |
| `tests/` | unit + safety + e2e paper smoke |

---

# Stage 1 -> Gate 1: Scaffold, config, utils, Docker, secret scan

### Task 1.0: Project bootstrap

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `.pre-commit-config.yaml`, `.env.example`, `config.yaml`, `pytest.ini`, package `__init__.py` files, `tests/__init__.py`.

- [ ] **Step 1: Create the venv and dependency files**

`requirements.txt`:
```
ccxt>=4.4
pandas>=2.2
numpy>=1.26
pandas_ta>=0.3.14b
vectorbt>=0.26
streamlit>=1.40
plotly>=5.24
kaleido>=0.2
python-telegram-bot>=21
APScheduler>=3.10
pydantic>=2.9
pyyaml>=6.0
loguru>=0.7
python-dotenv>=1.0
requests>=2.32
anthropic>=0.40
openai>=1.50
```
`requirements-dev.txt`:
```
pytest>=8.3
pytest-asyncio>=0.24
ruff>=0.7
pre-commit>=4.0
```

- [ ] **Step 2: Create config + env templates**

`.env.example` (NAMES ONLY):
```
# Exchange (only needed to ENABLE live; paper needs none)
EXCHANGE_API_KEY=
EXCHANGE_API_SECRET=
EXCHANGE_API_PASSWORD=
# Alerts
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DISCORD_WEBHOOK_URL=
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASSWORD=
ALERT_EMAIL_TO=
# Optional LLM co-pilot (OFF by default)
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
# Live trading is OFF unless BOTH are set true
PAPER_TRADING=true
ENABLE_LIVE_TRADING=false
```

`config.yaml` (sample, full):
```yaml
exchange: blofin            # blofin|bitget|binance|bybit|kraken|coinbase
paper_trading: true
data:
  primary_timeframe: 4h
  confirm_timeframe: 1h
  ohlcv_limit: 300
watchlist:
  source: file             # file|top_volume
  file: watchlist.json
  top_volume_n: 50
  blacklist: []
  whitelist: []
scanner:
  interval_minutes: 5
  min_strength: 55
  rank_top_n: 10
  volume_surge_mult: 2.0
signal:
  money_line_length: 8
  smooth: 14
  slope_len: 3
  use_rsi_filter: false
  use_adx_filter: false
risk:
  account_balance: 10000
  risk_pct: 0.01
  max_exposure_pct: 0.15
  max_trades_per_day: 10
  max_consecutive_losses: 4
  max_drawdown_pct: 0.20
executor:
  profit_target_pct: 0.06
  use_dip_filter: true
  trailing_stop_pct: 0.03
  max_hold_hours: 48
fees:
  blofin: {maker: 0.0002, taker: 0.0006}
  binance: {maker: 0.0002, taker: 0.0004}
alerts:
  telegram: true
  discord: false
  email: false
  send_chart_image: true
persistence:
  backend: sqlite          # sqlite|supabase
  sqlite_path: data/cryptochucker.db
llm_copilot:
  enabled: false
  provider: anthropic      # anthropic|openai|ollama
pine:
  scanner_symbols: []      # up to 30; user fills in
```

- [ ] **Step 3: Tooling config**

`pyproject.toml` (ruff) and `pytest.ini` (testpaths=tests, asyncio_mode=auto). `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks: [{id: gitleaks}]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.7.4
    hooks: [{id: ruff}]
```

- [ ] **Step 4: Create package skeleton** — `agents/`, `utils/`, `indicators/`, `tests/`, `data/`, `logs/` with `__init__.py` where needed; add `logs/.gitkeep`.

- [ ] **Step 5: Commit**
```bash
git add -A && git commit -m "chore: project bootstrap (deps, config, tooling skeleton)"
```

### Task 1.1: Config schema (pydantic)

**Files:** Create `utils/config_schema.py`; Test `tests/test_config_schema.py`.

- [ ] **Step 1: Failing test**
```python
# tests/test_config_schema.py
import pytest, yaml
from utils.config_schema import load_config, Config

def test_load_valid_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin", "paper_trading": True,
        "data": {"primary_timeframe": "4h", "confirm_timeframe": "1h", "ohlcv_limit": 300},
        "risk": {"account_balance": 10000, "risk_pct": 0.01, "max_exposure_pct": 0.15,
                 "max_trades_per_day": 10, "max_consecutive_losses": 4, "max_drawdown_pct": 0.2},
    }))
    cfg = load_config(str(p))
    assert isinstance(cfg, Config)
    assert cfg.risk.risk_pct == 0.01

def test_invalid_config_raises_clear_error(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"exchange": "blofin", "risk": {"risk_pct": 5}}))
    with pytest.raises(ValueError) as e:
        load_config(str(p))
    assert "risk_pct" in str(e.value)
```

- [ ] **Step 2: Run red** — `python -m pytest tests/test_config_schema.py -v` -> FAIL (no module).

- [ ] **Step 3: Implement**
```python
# utils/config_schema.py
from __future__ import annotations
import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

class DataCfg(BaseModel):
    primary_timeframe: str = "4h"
    confirm_timeframe: str = "1h"
    ohlcv_limit: int = 300

class RiskCfg(BaseModel):
    account_balance: float = 10000
    risk_pct: float = Field(0.01, gt=0, le=0.5)
    max_exposure_pct: float = Field(0.15, gt=0, le=1)
    max_trades_per_day: int = 10
    max_consecutive_losses: int = 4
    max_drawdown_pct: float = Field(0.20, gt=0, le=1)

class Config(BaseModel):
    exchange: str = "blofin"
    paper_trading: bool = True
    data: DataCfg = DataCfg()
    risk: RiskCfg = RiskCfg()
    # remaining sections kept permissive dicts for the sample; tighten per stage as used
    model_config = {"extra": "allow"}

    @field_validator("exchange")
    @classmethod
    def known_exchange(cls, v):
        if v not in {"blofin", "bitget", "binance", "bybit", "kraken", "coinbase"}:
            raise ValueError(f"unsupported exchange: {v}")
        return v

def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    try:
        return Config(**raw)
    except ValidationError as e:
        raise ValueError(f"Invalid config.yaml: {e}") from e
```

- [ ] **Step 4: Run green** -> PASS. **Step 5: Commit** `test:`/`feat:` config schema.

### Task 1.2: Logging (loguru)

**Files:** Create `utils/logging_config.py`; Test `tests/test_logging_config.py`.

- [ ] **Step 1: Failing test** — assert `setup_logging()` returns a logger that writes to a rotating file in `logs/` and never raises.
```python
from utils.logging_config import setup_logging
def test_setup_logging(tmp_path):
    log = setup_logging(log_dir=str(tmp_path))
    log.info("hello")
    assert any(p.suffix == ".log" for p in tmp_path.iterdir())
```
- [ ] **Step 2: Red.** **Step 3: Implement** loguru with colored console sink + `logs/app_{time}.log` rotation="10 MB", retention="10 days", plus optional JSON sink toggled by arg. Return `loguru.logger`. **Step 4: Green. Step 5: Commit.**

### Task 1.3: Fees calculator

**Files:** Create `utils/fees.py`; Test `tests/test_fees.py`.

- [ ] **Step 1: Failing test**
```python
from utils.fees import fee
def test_taker_fee():
    assert fee(1000, "blofin", taker=True, table={"blofin": {"maker": 0.0002, "taker": 0.0006}}) == pytest.approx(0.6)
def test_unknown_exchange_uses_default():
    assert fee(1000, "unknown", taker=True, table={}) == pytest.approx(1.0)  # 0.001 default
```
- [ ] **Step 2: Red. Step 3: Implement**
```python
# utils/fees.py
DEFAULT = {"maker": 0.0005, "taker": 0.001}
def fee(notional: float, exchange: str, taker: bool = True, table: dict | None = None) -> float:
    rates = (table or {}).get(exchange, DEFAULT)
    return abs(notional) * rates["taker" if taker else "maker"]
```
- [ ] **Step 4: Green. Step 5: Commit.**

### Task 1.4: Watchlist import/export (helpers)

**Files:** Create `utils/helpers.py`; Test `tests/test_helpers.py`.

- [ ] **Step 1: Failing test** — round-trip a list of symbols through CSV and JSON.
```python
from utils.helpers import save_watchlist, load_watchlist
def test_roundtrip_json(tmp_path):
    p = tmp_path / "w.json"; save_watchlist(["BTC/USDT","ETH/USDT"], str(p)); assert load_watchlist(str(p)) == ["BTC/USDT","ETH/USDT"]
def test_roundtrip_csv(tmp_path):
    p = tmp_path / "w.csv"; save_watchlist(["BTC/USDT"], str(p)); assert load_watchlist(str(p)) == ["BTC/USDT"]
```
- [ ] **Step 2: Red. Step 3: Implement** `save_watchlist`/`load_watchlist` switching on extension (`.json` via json, `.csv` via csv one-column). **Step 4: Green. Step 5: Commit.**

### Task 1.5: Data fetcher (CCXT public)

**Files:** Create `utils/data_fetcher.py`; Test `tests/test_data_fetcher.py`.

- [ ] **Step 1: Failing test** — mock a ccxt exchange so `fetch_ohlcv` returns a DataFrame with columns `[open,high,low,close,volume]` indexed by timestamp; assert retry on transient `NetworkError`.
```python
import pandas as pd
from unittest.mock import MagicMock
from utils.data_fetcher import DataFetcher
def test_fetch_ohlcv_shape():
    ex = MagicMock()
    ex.fetch_ohlcv.return_value = [[1_700_000_000_000, 1,2,0.5,1.5, 100]] * 5
    df = DataFetcher(exchange_obj=ex).fetch_ohlcv("BTC/USDT", "4h", 5)
    assert list(df.columns) == ["open","high","low","close","volume"] and len(df) == 5
```
- [ ] **Step 2: Red. Step 3: Implement** `DataFetcher(exchange="blofin", exchange_obj=None)` building a **public** ccxt client (`getattr(ccxt, exchange)({"enableRateLimit": True})`) when no object injected; `fetch_ohlcv` with 3x retry/backoff on `ccxt.NetworkError`; `top_volume_symbols(n)` via `fetch_tickers` sorted by quoteVolume. **No API keys used.** **Step 4: Green. Step 5: Commit.**

### Task 1.6: Risk manager

**Files:** Create `utils/risk_manager.py`; Test `tests/test_risk_manager.py`.

- [ ] **Step 1: Failing test**
```python
from utils.risk_manager import position_size, drawdown_breached
def test_position_size():
    # risk $100 (1% of 10k), entry 100 stop 95 -> size = 100/5 = 20 units
    assert position_size(10000, 0.01, entry=100, stop=95) == pytest.approx(20.0)
def test_drawdown_breached():
    assert drawdown_breached([100, 120, 90], max_dd_pct=0.2) is True   # 25% from peak 120
    assert drawdown_breached([100, 110, 105], max_dd_pct=0.2) is False
```
- [ ] **Step 2: Red. Step 3: Implement** `position_size = (balance*risk_pct)/abs(entry-stop)`; `drawdown_breached(equity, max_dd_pct)` comparing running peak; plus `check_limits(trades_today, consecutive_losses, exposure_pct, cfg)`. **Step 4: Green. Step 5: Commit.**

### Task 1.7: Store (SQLite)

**Files:** Create `utils/store.py`; Test `tests/test_store.py`.

- [ ] **Step 1: Failing test** — open an in-memory/temp db, `save_signal(...)`, `load_signals()` returns it.
```python
from utils.store import Store
def test_signal_roundtrip(tmp_path):
    s = Store(str(tmp_path/"t.db")); s.init()
    s.save_signal({"symbol":"BTC/USDT","tf":"4h","state":"BULLISH","strength":80})
    rows = s.load_signals(); assert rows[0]["symbol"] == "BTC/USDT"
```
- [ ] **Step 2: Red. Step 3: Implement** `Store(path)` using stdlib `sqlite3` with `Row` factory; `init()` creates tables `signals, scans, positions, trades, equity`; `save_*`/`load_*`. **Step 4: Green. Step 5: Commit.**

### Task 1.8: Docker + setup scripts

**Files:** Create `Dockerfile`, `docker-compose.yml`, `setup.sh`, `setup.ps1`.

- [ ] **Step 1:** `Dockerfile` (python:3.11-slim, copy, `pip install -r requirements.txt`, default `CMD ["python","main.py"]`). `docker-compose.yml` with a `suite` service and a `dashboard` service (`streamlit run agents/dashboard.py`). `setup.sh`/`setup.ps1`: create venv, install deps, copy `.env.example`->`.env` if missing. - [ ] **Step 2: Commit** `chore: docker + setup scripts`.

### Task 1.9: CI workflow

**Files:** Create `.github/workflows/ci.yml`.

- [ ] **Step 1:** GitHub Actions: on push/PR -> setup Python 3.11, `pip install -r requirements.txt -r requirements-dev.txt`, `ruff check .`, run gitleaks action, `pytest -q`. - [ ] **Step 2: Commit** `ci: lint + secret scan + tests`.

### Task 1.G: Codex Gate 1

- [ ] Run the Codex review gate (Conventions) with `N=1`. Fix BLOCKING, re-run to `VERDICT: PASS`. Commit `reviews/gate-1-codex.md`. **Do not start Stage 2 until PASS.**

---

# Stage 2 -> Gate 2: Signal engine + Money Line Pine + STRATEGY.md

### Task 2.1: Money Line core (`get_money_line`)

**Files:** Create `agents/signal_agent.py`; Test `tests/test_signal_agent.py`.

- [ ] **Step 1: Failing test**
```python
# tests/test_signal_agent.py
import numpy as np, pandas as pd
from agents.signal_agent import get_money_line
def _df(prices, vol=None):
    n=len(prices); idx=pd.date_range("2026-01-01", periods=n, freq="4h")
    c=np.array(prices,float)
    return pd.DataFrame({"open":c,"high":c*1.005,"low":c*0.995,"close":c,
                         "volume":(vol if vol is not None else np.full(n,1000.0))}, index=idx)
def test_columns_and_flip():
    up=list(np.linspace(100,140,40)); down=list(np.linspace(140,100,40))
    out=get_money_line(_df(up+down))
    assert set(["money_line","state","flip_detected","signal_strength"]).issubset(out.columns)
    assert out["state"].isin(["BULLISH","BEARISH"]).all()
    assert out["flip_detected"].sum() >= 1
    assert out["signal_strength"].between(0,100).all()
def test_uptrend_is_bullish_at_end():
    out=get_money_line(_df(list(np.linspace(100,160,80))))
    assert out["state"].iloc[-1] == "BULLISH"
```
- [ ] **Step 2: Red.** **Step 3: Implement**
```python
# agents/signal_agent.py
from __future__ import annotations
import numpy as np, pandas as pd
import pandas_ta as ta

def get_money_line(df: pd.DataFrame, length: int = 8, smooth: int = 14, slope_len: int = 3) -> pd.DataFrame:
    """Volume-weighted, EMA-smoothed money-flow trend line that flips BULLISH/BEARISH.
    Independently implemented faithful equivalent (see STRATEGY.md)."""
    out = df.copy()
    tp = (out["high"] + out["low"] + out["close"]) / 3.0
    vwma = (tp * out["volume"]).rolling(length).sum() / out["volume"].rolling(length).sum()
    ml = vwma.ewm(span=smooth, adjust=False).mean().bfill()
    out["money_line"] = ml
    slope = ml.diff().rolling(slope_len).mean().fillna(0.0)
    out["state"] = np.where(slope >= 0, "BULLISH", "BEARISH")
    out["flip_detected"] = out["state"].ne(out["state"].shift()).fillna(False)
    # strength 0-100 from normalized slope + volume surge + MFI distance from 50
    atr = ta.atr(out["high"], out["low"], out["close"], length=14).bfill()
    slope_norm = (slope.abs() / atr.replace(0, np.nan)).fillna(0)
    vol_surge = (out["volume"] / out["volume"].rolling(20).mean().bfill()).fillna(1)
    mfi = ta.mfi(out["high"], out["low"], out["close"], out["volume"], length=14).fillna(50)
    raw = 40 * np.tanh(slope_norm * 8) + 30 * np.tanh((vol_surge - 1)) + 30 * (np.abs(mfi - 50) / 50)
    out["signal_strength"] = raw.clip(0, 100).round(1)
    return out
```
- [ ] **Step 4: Green.** **Step 5: Commit** `feat: Money Line signal engine`.

### Task 2.2: Multi-timeframe confirmation + filters

**Files:** Modify `agents/signal_agent.py`; Test add to `tests/test_signal_agent.py`.

- [ ] **Step 1: Failing test** — `confirm(primary_df, confirm_df)` returns True only when both end BULLISH; `latest_signal(df)` returns `{state,strength,flip,price}`. - [ ] **Step 2: Red.** **Step 3: Implement** `confirm()` and `latest_signal()`, plus optional RSI/ADX gating controlled by args. **Step 4: Green. Step 5: Commit.**

### Task 2.3: Money Line Pine v6 (write + compile-verify)

**Files:** Create `indicators/money_line_pine.txt`.

- [ ] **Step 1: Write Pine v6 source** (mirrors the Python logic):
```pine
//@version=6
indicator("CryptoChucker - Money Line v1", overlay=true)
length = input.int(8, "VWMA length")
smooth = input.int(14, "EMA smooth")
slopeLen = input.int(3, "Slope length")
tp = (high + low + close) / 3.0
vwma = math.sum(tp * volume, length) / math.sum(volume, length)
ml = ta.ema(vwma, smooth)
slope = ta.sma(ta.change(ml), slopeLen)
bull = slope >= 0
mlColor = bull ? color.new(color.teal, 0) : color.new(color.red, 0)
plot(ml, "Money Line", color=mlColor, linewidth=2)
flipUp = bull and not bull[1]
flipDn = (not bull) and bull[1]
plotshape(flipUp, title="Bull flip", style=shape.triangleup, location=location.belowbar, color=color.teal, size=size.small)
plotshape(flipDn, title="Bear flip", style=shape.triangledown, location=location.abovebar, color=color.red, size=size.small)
alertcondition(flipUp, "Money Line Bullish Flip", "Money Line flipped BULLISH on {{ticker}}")
alertcondition(flipDn, "Money Line Bearish Flip", "Money Line flipped BEARISH on {{ticker}}")
```
- [ ] **Step 2: Compile-verify via TradingView MCP** — `pine_new` (new slot), `pine_set_source`, `pine_smart_compile`; read `pine_get_errors` until clean; capture the result into `reviews/pine-money-line-compile.md`. If MCP slot creation fails, keep source + compile log + add manual-save steps to README (fallback satisfies done).
- [ ] **Step 3: Commit** `feat: Money Line Pine v6 indicator`.

### Task 2.4: STRATEGY.md

**Files:** Create `STRATEGY.md`.

- [ ] **Step 1:** Document the Money Line math transparently and as an **independent implementation** (no clone/trademark claims): typical price, VWMA(length), EMA(smooth), slope sign -> state, flip detection, strength formula. - [ ] **Step 2: Commit** `docs: STRATEGY.md`.

### Task 2.G: Codex Gate 2

- [ ] Run the Codex gate (`N=2`). Fix BLOCKING, re-run to PASS, commit `reviews/gate-2-codex.md`.

---

# Stage 3 -> Gate 3: Scanner + alerts + Money Scanner Pine

### Task 3.1: Scanner agent

**Files:** Create `agents/scanner_agent.py`; Test `tests/test_scanner_agent.py`.

- [ ] **Step 1: Failing test** — given a fake DataFetcher returning two symbols (one fresh bullish flip, one no-flip), `Scanner(cfg, fetcher, signal_fn).scan()` returns ranked `SignalEvent`s, top-N, respecting blacklist and `min_strength`.
```python
from agents.scanner_agent import Scanner
def test_scan_ranks_and_filters(fake_fetcher, cfg):
    events = Scanner(cfg, fake_fetcher).scan(["BTC/USDT","ETH/USDT"])
    assert all(e.strength >= cfg.scanner.min_strength for e in events)
    assert events == sorted(events, key=lambda e: e.strength, reverse=True)
```
- [ ] **Step 2: Red.** **Step 3: Implement** `Scanner` with a `SignalEvent` dataclass `(symbol, tf, state, strength, flip, price, ts)`; iterate watchlist, call `get_money_line` via `data_fetcher`, apply volume-surge + VWAP filters + blacklist/whitelist, keep fresh flips >= min_strength, sort desc, take `rank_top_n`. **Step 4: Green. Step 5: Commit.**

### Task 3.2: Alert agent transports

**Files:** Create `agents/alert_agent.py`; Test `tests/test_alert_agent.py`.

- [ ] **Step 1: Failing test** — with all transports mocked, `AlertAgent(cfg).send(event)` calls only enabled channels and formats a message containing symbol, tf, state, strength.
```python
def test_send_only_enabled(monkeypatch, cfg_telegram_only):
    sent = {}
    monkeypatch.setattr("agents.alert_agent._post_telegram", lambda *a, **k: sent.setdefault("tg", a))
    AlertAgent(cfg_telegram_only).send(make_event())
    assert "tg" in sent
```
- [ ] **Step 2: Red.** **Step 3: Implement** `_post_telegram` (python-telegram-bot / Bot.send_message via `TELEGRAM_BOT_TOKEN`), `_post_discord` (requests POST webhook), `_send_email` (smtplib); `send()` dispatches per config toggles; never logs token values. **Step 4: Green. Step 5: Commit.**

### Task 3.3: Alert chart image + link fallback

**Files:** Modify `agents/alert_agent.py`; Test add.

- [ ] **Step 1: Failing test** — `build_chart_image(df)` returns PNG bytes when kaleido available; `chart_link(symbol)` returns a TradingView URL; `send()` attaches image if `send_chart_image` and generation succeeds, else falls back to link (assert fallback path when image fn raises). - [ ] **Step 2: Red. Step 3: Implement** Plotly candlestick+Money Line -> `fig.to_image(format="png")` (kaleido), wrapped in try/except -> link fallback. **Step 4: Green. Step 5: Commit.**

### Task 3.4: Money Scanner Pine v6 (30 symbols)

**Files:** Create `indicators/money_scanner_pine.txt`.

- [ ] **Step 1: Write Pine v6 source** — a table indicator; a `ml_state(sym)` helper using `request.security(sym, timeframe.period, <money line state expr>)`; iterate a 30-element `input.symbol` array; render a `table.new` with Symbol/State/Strength/Flip columns colored teal/red. Cap at exactly 30 inputs by design.
- [ ] **Step 2: Compile-verify via MCP** against the full 30-symbol default; capture to `reviews/pine-money-scanner-compile.md`; fallback as in 2.3.
- [ ] **Step 3: Commit** `feat: Money Scanner Pine v6 indicator`.

### Task 3.G: Codex Gate 3

- [ ] Run gate (`N=3`) -> PASS -> commit `reviews/gate-3-codex.md`.

---

# Stage 4 -> Gate 4: Paper executor + risk + fees + live-safety

### Task 4.1: Live-trading safety guard (write FIRST, fail-closed)

**Files:** Create `utils/safety.py`; Test `tests/test_safety.py`.

- [ ] **Step 1: Failing test (the critical safety contract)**
```python
from utils.safety import live_enabled, make_exchange_client, LiveTradingDisabled
def test_default_blocks_live():
    assert live_enabled({"PAPER_TRADING":"true","ENABLE_LIVE_TRADING":"false"}) is False
def test_single_flag_still_blocks():
    assert live_enabled({"PAPER_TRADING":"false","ENABLE_LIVE_TRADING":"false"}) is False
    assert live_enabled({"PAPER_TRADING":"true","ENABLE_LIVE_TRADING":"true"}) is False
def test_both_flags_enable():
    assert live_enabled({"PAPER_TRADING":"false","ENABLE_LIVE_TRADING":"true"}) is True
def test_paper_client_is_public(monkeypatch):
    client = make_exchange_client("blofin", env={"PAPER_TRADING":"true","ENABLE_LIVE_TRADING":"false"})
    assert client.apiKey in (None, "")   # never authenticated in paper
```
- [ ] **Step 2: Red.** **Step 3: Implement**
```python
# utils/safety.py
import os, ccxt
class LiveTradingDisabled(RuntimeError): ...
def _truthy(v): return str(v).strip().lower() == "true"
def live_enabled(env=None) -> bool:
    e = env or os.environ
    return _truthy(e.get("PAPER_TRADING", "true")) is False and _truthy(e.get("ENABLE_LIVE_TRADING", "false")) is True
def make_exchange_client(exchange: str, env=None):
    e = env or os.environ
    klass = getattr(ccxt, exchange)
    if live_enabled(e):
        return klass({"apiKey": e.get("EXCHANGE_API_KEY",""), "secret": e.get("EXCHANGE_API_SECRET",""),
                      "password": e.get("EXCHANGE_API_PASSWORD",""), "enableRateLimit": True})
    return klass({"enableRateLimit": True})  # PUBLIC ONLY in paper
def guard_live(env=None):
    if not live_enabled(env): raise LiveTradingDisabled("Live trading is disabled (need PAPER_TRADING=false AND ENABLE_LIVE_TRADING=true)")
```
- [ ] **Step 4: Green.** **Step 5: Commit** `feat: fail-closed live-trading double gate`.

### Task 4.2: Paper executor

**Files:** Create `agents/executor_agent.py`; Test `tests/test_executor_agent.py`.

- [ ] **Step 1: Failing test** — `Executor(cfg, store).on_signal(event)` in paper mode records a simulated fill in store, applies fees to net P&L, and **never** calls ccxt `create_order` (mock asserts not-called); calling `_live_order(...)` while disabled raises `LiveTradingDisabled`.
```python
def test_paper_fill_no_live_order(mock_ccxt, store, cfg_paper):
    ex = Executor(cfg_paper, store, client=mock_ccxt)
    ex.on_signal(make_bull_event())
    assert mock_ccxt.create_order.call_count == 0
    assert store.load_trades()[-1]["mode"] == "paper"
def test_live_order_blocked(cfg_paper, store):
    with pytest.raises(LiveTradingDisabled):
        Executor(cfg_paper, store)._live_order("BTC/USDT","buy",1.0)
```
- [ ] **Step 2: Red.** **Step 3: Implement** buy on bullish flip (+ optional dip), sell at `profit_target_pct` net of `fees.fee()` or on bearish flip; trailing stop + max-hold; `paper_fill()` writes to store; `_live_order()` calls `guard_live()` then ccxt (unreachable in paper). Position sizing via `risk_manager`. **Step 4: Green. Step 5: Commit.**

### Task 4.3: Risk + fees wiring + exposure/drawdown stops

**Files:** Modify `agents/executor_agent.py`; Test add.

- [ ] **Step 1: Failing test** — executor refuses new entries when `drawdown_breached` or daily cap hit. - [ ] **Step 2: Red. Step 3: Implement** integrate `risk_manager.check_limits` + `drawdown_breached` before entries; emergency stop flag. **Step 4: Green. Step 5: Commit.**

### Task 4.G: Codex Gate 4

- [ ] Run gate (`N=4`). Codex must confirm the safety tests prove paper cannot place live orders. -> PASS -> commit `reviews/gate-4-codex.md`.

---

# Stage 5 -> Gate 5: Dashboard + backtester + LLM co-pilot

### Task 5.1: Backtester core (vectorbt)

**Files:** Create `agents/backtester.py`; Test `tests/test_backtester.py`.

- [ ] **Step 1: Failing test** — `run_backtest(df, cfg)` returns a `Result` with keys `sharpe, sortino, max_drawdown, win_rate, profit_factor, equity_curve` (equity is a Series); on a fixed fixture the values are finite. - [ ] **Step 2: Red. Step 3: Implement** signals from `get_money_line` (entries on bullish flip, exits on bearish flip), `vectorbt.Portfolio.from_signals`, derive metrics; `to_csv(path)`; `equity_curve` for Plotly. **Step 4: Green. Step 5: Commit.**

### Task 5.2: Grid search

**Files:** Modify `agents/backtester.py`; Test add.

- [ ] **Step 1: Failing test** — `grid_search(df, {"money_line_length":[6,8], "smooth":[10,14]})` returns a DataFrame with one row per combo, sorted by sharpe desc. - [ ] **Step 2: Red. Step 3: Implement** itertools.product over the grid, run each, collect metrics. **Step 4: Green. Step 5: Commit.**

### Task 5.3: LLM co-pilot (OFF by default)

**Files:** Create `utils/llm_copilot.py`; Test `tests/test_llm_copilot.py`.

- [ ] **Step 1: Failing test** — when `cfg.llm_copilot.enabled is False`, `validate(signal)` returns `{"decision":"skip","confidence":0,"reason":"copilot disabled"}` without any network call; when enabled (provider mocked), returns schema-validated dict. - [ ] **Step 2: Red. Step 3: Implement** provider failover (anthropic/openai/ollama), redaction of any numbers that look like keys, schema-validated output, hard early-return when disabled. **Step 4: Green. Step 5: Commit.**

### Task 5.4: Dashboard (from approved mockup)

**Files:** Create `agents/dashboard.py` (adapt `docs/mockup/app.py`).

- [ ] **Step 1:** Port the approved mockup, replacing synthetic data with reads from `Store` (signals, positions, trades, equity, scans) and live `get_money_line` for the chart; keep the approved layout (sidebar toggles, Overview/Scanner/Backtest tabs, dark, mobile-friendly). - [ ] **Step 2: Runtime check** — `streamlit run agents/dashboard.py --server.headless true` serves with HTTP 200 and no exceptions (capture to `reviews/dashboard-serve.md`). - [ ] **Step 3: Commit** `feat: Streamlit dashboard`.

### Task 5.G: Codex Gate 5

- [ ] Run gate (`N=5`) -> PASS -> commit `reviews/gate-5-codex.md`.

---

# Stage 6 -> Gate 6: Orchestrator + e2e smoke + README/CI + publish

### Task 6.1: Orchestrator (`main.py`)

**Files:** Create `main.py`; Test `tests/test_main.py`.

- [ ] **Step 1: Failing test** — `build_app(cfg)` wires agents and returns an object exposing `run_once()` that executes one scan->signal->executor(paper)->store->alert(mocked) cycle without raising; per-agent exceptions are caught and logged, not propagated. - [ ] **Step 2: Red. Step 3: Implement** load config + logging, instantiate Store/DataFetcher/Scanner/Executor/AlertAgent, APScheduler job calling `run_once()`, graceful shutdown handlers, per-agent try/except isolation. **Step 4: Green. Step 5: Commit.**

### Task 6.2: End-to-end paper smoke test (deterministic)

**Files:** Create `tests/fixtures/ohlcv_btc_4h.csv`, `tests/test_e2e_paper_smoke.py`.

- [ ] **Step 1: Create fixture** — a committed CSV of ~300 4h BTC bars (synthetic but realistic, with at least 2 flips). - [ ] **Step 2: Failing test** — wire a DataFetcher that reads the fixture, run `build_app(cfg_paper).run_once()` end to end; assert: a signal row, a paper trade (no live order), an equity row, an alert payload (mocked transport), and zero exceptions. - [ ] **Step 3: Red -> implement glue -> green.** **Step 4: Commit** `test: deterministic e2e paper smoke`.

### Task 6.3: README + BUILD_REPORT

**Files:** Create `README.md`, `BUILD_REPORT.md`.

- [ ] **Step 1:** README: quick start (`docker-compose up` and venv path), how to get API keys (names only), how to customize rules, backtesting guide, **manual Pine-add steps**, dashboard screenshots. BUILD_REPORT: what was built, each gate verdict (links to `reviews/`), MEDIUM/LOW disposition, run instructions. - [ ] **Step 2: Commit** `docs: README + BUILD_REPORT`.

### Task 6.4: Live smoke run (real public data, paper)

- [ ] **Step 1:** Run `python -c "from main import build_app; from utils.config_schema import load_config; build_app(load_config('config.yaml')).run_once()"` against real CCXT public data in paper mode; confirm zero errors; start the dashboard headless and confirm it serves. - [ ] **Step 2:** Record evidence in BUILD_REPORT: exact command, UTC timestamp, symbols scanned, dashboard URL + status, artifacts (trade log, equity CSV, backtest metrics). - [ ] **Step 3: Commit** `chore: live paper smoke evidence`.

### Task 6.5: Publish to GitHub (cryptochucker)

- [ ] **Step 1:** Final gitleaks scan over working tree + history -> zero secrets. - [ ] **Step 2:** `gh auth switch --user cryptochucker`; `gh repo create cryptochucker/CryptoChucker-Agents --public --source . --remote origin --push`. - [ ] **Step 3: Commit/push** any final changes.

### Task 6.G: Codex Gate 6 (final)

- [ ] Run the final gate (`N=6`) over the whole build. Require `VERDICT: PASS`. Commit `reviews/gate-6-codex.md`. **When PASS + all DoD items (spec Section 1) hold: STOP and hand off for formal approval. No further changes.**

---

## Self-review (run against the spec)

- **Spec coverage:** signal/Money Line (2.1-2.2), scanner (3.1), executor+risk+fees (4.x), alerts+chart (3.2-3.3), dashboard (5.4), backtester+grid (5.1-5.2), config-driven (1.0-1.1), Docker (1.8), CI+secret scan (1.9), LLM co-pilot off (5.3), two Pine indicators (2.3, 3.4), SQLite store (1.7), watchlist import/export (1.4), fee calculator (1.3), live double-gate + safety tests (4.1-4.2), e2e paper smoke + live run (6.2, 6.4), publish (6.5), Codex gates 1-6 (each Task N.G). Every spec requirement maps to a task.
- **Placeholder scan:** code steps carry real test + implementation code; mechanical tasks (Docker, CI, README) specify exact contents.
- **Type consistency:** `get_money_line` columns (`money_line/state/flip_detected/signal_strength`), `SignalEvent` fields, `Store` method names, and `safety.live_enabled/make_exchange_client/guard_live` are used consistently across tasks.
