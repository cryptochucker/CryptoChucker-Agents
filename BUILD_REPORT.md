# CryptoChucker Agents Build Report

**Build date:** 2026-06-07
**Branch:** `build`
**Python:** 3.11 (Windows 11 Pro)
**Test count:** 275 passed, 0 failed (ruff clean)
**Reviewer/approver of record:** Codex CLI (`gpt-5.5`) at every stage gate

---

## What Was Built (All 6 Stages)

### Stage 1: Scaffold, Config, Utils, Docker, Secret Scan
- `config.yaml` + `utils/config_schema.py`: pydantic-validated config (all sections typed)
- `utils/logging_config.py` (loguru + rotation); `utils/fees.py` (per-exchange maker/taker)
- `utils/helpers.py` (watchlist CSV/JSON import/export); `utils/data_fetcher.py` (CCXT **public** OHLCV, 3x retry/backoff)
- `utils/risk_manager.py` (sizing, drawdown, limits); `utils/store.py` (SQLite: signals/scans/positions/trades/equity)
- `Dockerfile`, `docker-compose.yml`, `setup.sh`, `setup.ps1`; `.pre-commit-config.yaml` (gitleaks + ruff); `.env.example` (names only)

### Stage 2: Signal Engine + Money Line Pine + STRATEGY.md
- `agents/signal_agent.py`: `get_money_line()`, `confirm()`, `latest_signal()` with ATR/MFI/RSI/ADX (pure pandas, no `pandas_ta`)
- `indicators/money_line_pine.txt`: Pine v6 Money Line (compile-verified on TradingView, see `reviews/pine-money-line-compile.md`)
- `STRATEGY.md`: transparent, independently-implemented math

### Stage 3: Scanner + Alerts + Money Scanner Pine
- `agents/scanner_agent.py`: fresh-flip scanner with blacklist/whitelist, volume-surge, VWAP price-position, min-strength; config-driven signal params
- `agents/alert_agent.py`: Telegram/Discord/email fan-out + Plotly/kaleido chart image with link fallback; **secret-redacted** error logging
- `indicators/money_scanner_pine.txt`: Pine v6 30-symbol screener table (global-scope functions)

### Stage 4: Paper Executor + Risk + Fees + Live Safety
- `agents/executor_agent.py`: paper fills (profit target net of fees, trailing stop, bearish-flip exit, max hold, dip filter); position size **capped to max exposure**
- `utils/safety.py`: fail-closed **double gate** (`PAPER_TRADING=false` AND `ENABLE_LIVE_TRADING=true`, exact lowercase) + credential isolation (paper mode never reads API keys)

### Stage 5: Dashboard + Backtester + LLM Co-Pilot
- `agents/dashboard.py`: Streamlit dashboard (Overview/Scanner/Backtest tabs; PAPER pill; KPIs; equity curve from real store; positions; **Recent alerts** feed; **Live logs**; **ticker search** to jump to any coin's Money Line). Default render makes **zero network calls** (chart fetch is button-gated).
- `agents/backtester.py`: pure pandas/numpy engine (mark-to-market equity; crypto 24/7 annualized Sharpe/Sortino, maxDD, win rate, profit factor; configurable `fee_rate`; CSV export) + grid search
- `utils/llm_copilot.py`: optional validator (anthropic/openai/ollama; OFF by default; lazy imports; secret redaction incl. bare-token regex)

### Stage 6: Orchestrator + E2E Smoke + README
- `main.py`: `build_app()` factory + `_App.run_once()` (per-agent exception isolation) + APScheduler `run()`. Honors the real-env double gate (paper by default).
- `tests/fixtures/ohlcv_btc_4h.csv` + `tests/test_e2e_paper_smoke.py`: deterministic end-to-end paper smoke (no network) proving a signal/trade/position/equity row persists, a real alert transport is exercised, and ccxt `create_order` is never called.
- `README.md` (quick start, key guidance names-only, double-gate live warning, manual Pine-add steps, dashboard), `watchlist.json`, `BUILD_REPORT.md`.

---

## Codex Gate Verdicts

| Gate | Stage | Verdict file | Result |
|---|---|---|---|
| Gate 0 | Design spec | `reviews/gate-0-codex-r2-PASS.md` | PASS (2 rounds) |
| Gate 1 | Scaffold + utils | `reviews/gate-1-codex.md` | PASS |
| Gate 2 | Signal engine | `reviews/gate-2-codex.md` | PASS (3 rounds) |
| Gate 3 | Scanner + alerts | `reviews/gate-3-codex.md` | PASS (3 rounds) |
| Gate 4 | Executor + safety | `reviews/gate-4-codex.md` | PASS (3 rounds) |
| Gate 5 | Dashboard + backtester | `reviews/gate-5-codex.md` | PASS (3 rounds) |
| Gate 6 | Orchestrator + e2e + release | `reviews/gate-6-codex.md` | PASS |

Across the build Codex caught and forced fixes for real bugs each stage (RSI/MFI zero-denominator, false first-bar flip,
secret-leak in alert logging, case-insensitive live gate, default-path credential leak, realized-only equity,
stock-market annualization, network-on-render, fee/PnL inconsistency, orchestrator gate mismatch). All resolved.

---

## Live Paper Smoke Run Evidence (DoD item)

- **Command:** `build_app(load_config('config.yaml')).run_once()` (paper mode)
- **UTC:** 2026-06-07T22:08:03Z
- **Exchange / data:** `blofin`, real CCXT public OHLCV (BTC ~$61,745 at run time)
- **Watchlist:** 8 symbols (`watchlist.json`, blofin perps)
- **Result:** `RUN_ONCE_OK`, zero unhandled exceptions; 0 fresh flips at that instant (expected, flips are rare moment-to-moment); 1 equity snapshot written.
- **Deterministic proof of a full trade cycle:** `tests/test_e2e_paper_smoke.py` (10 tests) runs the pipeline on the committed fixture and asserts a paper trade/position/equity/alert with `create_order` call_count == 0.

## Dashboard Render Evidence (runtime, not just compile)

- **Run command:** `streamlit run agents/dashboard.py` (or `.venv\Scripts\python.exe -m streamlit run agents/dashboard.py`)
- **Local URL:** `http://localhost:8501` (Streamlit default)
- **Serve status:** renders with no traceback (`hasError: false`); dark-themed layout with Overview/Scanner/Backtest tabs.
- With a seeded store (pipeline run over the committed fixture: 48 signals, 2 paper trades, 2 open positions, 8 equity rows) the dashboard shows real KPIs, positions, alerts feed, and live logs.
- Default render makes **zero network calls**; the Overview chart and ticker search fetch only on button click.
- Ticker search verified present (`Search ticker` input + `Load chart` button).

## Generated Artifact Paths

| Artifact | Path | Notes |
|---|---|---|
| SQLite store | `data/cryptochucker.db` | Tables: `signals`, `scans`, `positions`, `trades`, `equity`. Created by `Store.init()`. |
| Store path in config | `persistence.sqlite_path` in `config.yaml` | Overridable; default `data/cryptochucker.db`. |
| Backtester equity CSV | caller-supplied `path` arg to `BacktestResult.to_csv(path)` | Writes `<path>` (equity curve) and `<path>.trades.csv` (trade log). No hardcoded default path; caller chooses filename. |
| Dashboard backtest CSV | In-memory download button in the Backtest tab | File name: `equity_<SYMBOL>_<TF>.csv`; served as bytes via `st.download_button`, not written to disk. |
| Backtest metrics | Returned in `BacktestResult` fields: `sharpe`, `sortino`, `max_drawdown`, `win_rate`, `profit_factor`; displayed in the dashboard Backtest tab and available via `print(result)`. |

## Secret Scan Evidence (DoD item)

- `.gitignore` excludes `.env`, `.env.*`, key files, logs, and DBs; `.venv/` is git-ignored (never committed).
- `.env.example` ships key NAMES + the default gate values only.
- `detect-secrets` over the committed source (`agents utils tests main.py config.yaml .env.example indicators`) flags
  only `tests/test_alert_agent.py` and `tests/test_llm_copilot.py`, which contain **intentional fake** secret strings
  (e.g. `sk-abc123...`, a 40-char hex) used to PROVE the redaction works - not real secrets.
- A full `git log -p --all` high-risk pattern scan returns only those same intentional test fixtures.
- The canonical `gitleaks` scan runs in **CI on every push** (`.github/workflows/ci.yml`) and in the pre-commit hook.
- **Conclusion: no real secret values in the repo or its history.**

---

## MEDIUM/LOW Finding Disposition (summary)

Every BLOCKING finding at each gate was fixed and re-reviewed to PASS (see each `reviews/gate-N-codex.md`). MEDIUM/LOW
items were either fixed in the same stage or fixed as post-pass polish; none were silently deferred except the
config-submodel tightening (explicitly planned to land per-consuming-stage, and all sections are now typed).
**Authorized deviation:** `vectorbt` and `pandas_ta` have no Windows/Python-3.11 wheels, so equivalent pure
pandas/numpy implementations ship instead (documented in `requirements.txt`, `STRATEGY.md`, and here). The two Pine
indicators ship as **compile-verified committed source + manual-add steps** (auto-deploy was intentionally not used
after it risked an existing script; see `reviews/pine-money-line-compile.md`).

---

## Exact Run Instructions

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python.exe -m pytest -q            # tests (272 pass)
.venv\Scripts\python.exe -m ruff check .         # lint
.venv\Scripts\python.exe main.py                 # start scheduler (paper)
.venv\Scripts\python.exe -m streamlit run agents/dashboard.py   # dashboard
docker compose up                                 # containerized
```

**This release operates in PAPER mode only.** Live order execution is SCAFFOLDED (the `PAPER_TRADING`/`ENABLE_LIVE_TRADING`
double gate, the authenticated-client factory in `utils/safety.py`, and the guarded `_live_order()` path) but is
INTENTIONALLY NOT wired into the signal-execution path. `Executor.on_signal()` always uses the paper-fill route in this
release. The env gates currently govern credential/client construction and the `_live_order` guard, not order placement
from signals. Wiring and validating live execution is a clearly-scoped follow-on (requires `PAPER_TRADING=false` AND
`ENABLE_LIVE_TRADING=true` -- both exact strings -- to be set in `.env` when that wiring is added).

---

## Definition-of-Done Checklist (spec Section 1)

| Item | Status |
|---|---|
| All Codex gates 0-6 PASS (no BLOCKING) | DONE |
| Unit + integration tests pass (incl. live-safety tests) | DONE (272 pass) |
| Deterministic e2e paper smoke (zero errors) + live run on real public data | DONE |
| Pine indicators compile-verified + source committed (manual-add) | DONE |
| gitleaks/detect-secrets: zero real committed secrets (working tree + history) | DONE |
| README/STRATEGY/config/.env.example/setup scripts complete | DONE |
| BUILD_REPORT summarizes build + gate verdicts + finding disposition | DONE |
| Published to github.com/cryptochucker/CryptoChucker-Agents | _pending final push (controller)_ |
