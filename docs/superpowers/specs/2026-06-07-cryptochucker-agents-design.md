# CryptoChucker Agents, Design Spec

- **Date:** 2026-06-07
- **Status:** Draft for Codex Gate 0 review, then user formal approval
- **Owner:** Jason Elam
- **Repo target:** `github.com/cryptochucker/CryptoChucker-Agents` (open-source)
- **Source brief:** `personal-trading-suite/CryptoChucker_Agents_Master_Prompt.md`
- **Reviewer/approver of record:** Codex CLI (`gpt-5.5`) at every stage gate

---

## 1. Summary and end goal

Build a **paper-trading-complete**, modular crypto trading suite ("CryptoChucker Agents") in Python 3.11 that
replicates the *intent* of Bullmania's Money Line / Money Scanner and GoBabyTrade's rule-based bot, and significantly
enhances it for a single solo trader at $0 recurring cost. The suite runs end-to-end on **real public market data** in
paper mode. The live-order path is built behind a CCXT abstraction but **ships disabled** (`PAPER_TRADING=true` default;
no live keys committed). Two companion **TradingView Pine v6 indicators** (Money Line, Money Scanner) are written,
compile-verified, and saved into the user's live TradingView account so they can be pulled up on any coin at any time.

This is a **bounded build with a fixed finish line**. There is no open-ended refinement loop.

### Definition of done (the explicit stop condition)

The build is COMPLETE, and work STOPS, when ALL of the following hold:

1. All six build stages carry a recorded **Codex PASS** (no BLOCKING findings) in `reviews/gate-N-codex.md`.
2. Unit tests and integration tests pass.
3. A deterministic **end-to-end paper smoke test** runs the full pipeline (data fetch, signal, scan, test-channel
   alert, paper fill, persistence, dashboard serve, backtest metrics) with **zero errors**, plus one live run on real
   public data.
4. Both TradingView indicators are **compile-verified and saved** to the user's TradingView account in new slots, and
   their source is committed to `indicators/`.
5. `README.md`, `STRATEGY.md`, `config.yaml`, `.env.example`, `setup.sh`, and `setup.ps1` are complete; the repo is
   pushed to `github.com/cryptochucker/CryptoChucker-Agents`.
6. A `BUILD_REPORT.md` summarizes what was built, every Codex gate verdict, and exact run instructions.

Then the repo is handed to the user for **formal approval**. No additional polishing past this line.

---

## 2. Scope

### In scope (this build)
- Signal engine (Money Line) in Python (`pandas_ta`), with multi-timeframe confirmation and `signal_strength` 0-100.
- Multi-symbol scanner (50-500+ symbols) with APScheduler cadence, ranking, blacklist/whitelist.
- Executor in **paper mode** via a CCXT abstraction; live path present but disabled.
- Risk manager (position sizing, daily caps, max single-trade, max-drawdown hard stop).
- Alerts: Telegram, Discord, email (each independently toggleable).
- Streamlit + Plotly dashboard (UX approved via mockup; see Section 10).
- Backtester on `vectorbt`: metrics (Sharpe, Sortino, max drawdown, win rate, profit factor), CSV + Plotly equity
  curve, plus a simple parameter grid search.
- Optional LLM signal-validator co-pilot, built but **OFF by default**, on existing Anthropic/OpenAI keys.
- Two TradingView Pine v6 indicators: Money Line (overlay) and Money Scanner (screener table).
- SQLite persistence (default), Supabase optional/toggleable.
- Docker + docker-compose; Railway-ready; `setup.sh` + `setup.ps1`; full README; GitHub Actions CI.

### Out of scope / deferred (clearly labeled follow-ons)
- **Live order execution enabled** (real capital). Code path exists, ships disabled; enabling is a separate,
  explicitly-scoped follow-on after the user has run paper mode.
- Walk-forward optimization and Monte Carlo simulation (backtester is "core + grid search" by decision).
- Redis inter-agent pub/sub (optional in the prompt; in-process orchestrator is sufficient).
- `ta-lib` (hard to install on Windows; `pandas_ta` covers the need).
- Pine on-chart scanning of hundreds of symbols (TradingView caps `request.security` symbols per indicator; the Python
  scanner handles hundreds-scale).

---

## 3. Locked decisions (from brainstorming)

| Decision | Choice |
|---|---|
| End goal | Paper-trading-complete suite; live built but shipped disabled |
| Codex gate cadence | Stage-gated: Gate 0 (spec) + 6 build-stage gates |
| LLM co-pilot | Built, toggleable, OFF by default; existing Anthropic/OpenAI keys; no new credential |
| Backtester depth | vectorbt core + full metrics + CSV + Plotly equity curve + simple grid search |
| Persistence | SQLite default (self-contained); Supabase optional |
| Alerting | Native Python (python-telegram-bot, Discord webhook, smtplib); reuse existing `TELEGRAM_BOT_TOKEN` |
| Default exchange (data + disabled-live adapter) | BloFin/BitGet (existing keys) via CCXT; multi-exchange supported |
| TradingView indicators | `CryptoChucker - Money Line v1`, `CryptoChucker - Money Scanner v1` (new slots) |
| Pine scanner watchlist | Default 30 symbols, user-editable in indicator settings |
| Money Line framing | Documented faithful money-flow equivalent, not a reverse-engineered clone |
| GitHub | Publish to `github.com/cryptochucker`; switch active gh account to `cryptochucker` at push |

---

## 4. Stack reuse map (leverage vs add)

**Headline: zero new paid services required.** Every capability maps to an existing asset or a $0 open-source library.
The only new credential that ever arises is Grok (`XAI_API_KEY`), and it is not needed (Anthropic/OpenAI present; Ollama
is a $0 local fallback). Reusable trading code is TypeScript/JS, so "reuse" means port proven logic and reuse
credentials, parameter values, and architecture, not import modules.

### Leverage (existing)
- **Executor + safety + trade limits**: `claude-tradingview-mcp-trading/bot.js` (paper-first `PAPER_TRADING` gate, HMAC
  orders, `runSafetyCheck`, `checkTradeLimits`, CSV trade log). Highest-value reuse for `executor_agent` + `risk_manager`.
- **Proven risk guardrail values**: `MAX_TRADE_SIZE_USD`, `MAX_TRADES_PER_DAY`, `MAX_CONSECUTIVE_LOSSES` (existing `.env`).
- **Scanner architecture**: `tradingview-mcp-jackson/src/core/morning.js` + meme-coin `scanner.service.ts`.
- **Market data**: `bot.js fetchCandles` (Binance public) and meme-coin Birdeye/DexScreener/GeckoTerminal wrappers; CCXT
  is the spec-mandated primary.
- **Watchlist schema**: `tradingview-mcp-jackson/rules.example.json`; TradingView MCP `watchlist_*`; CoinGecko free tier.
- **Alerts**: gravity-claw Telegram runtime + Hermes gateway + JMS Slack-webhook fetch pattern; `TELEGRAM_BOT_TOKEN` present.
- **LLM co-pilot**: `gravity-claw/src/llm.ts` multi-provider failover + JMS AI Gateway (redaction + schema validation).
- **Persistence**: SQLite (gravity-claw tier-1) default; Supabase admin client + `integration_events` schema optional.
- **Docker/Railway**: gravity-claw `Dockerfile` + Railway config; n8n `docker-compose`; `RAILWAY_TOKEN` present.
- **Pine conventions + deploy flow**: 11 existing v5 indicators + `pine-script-rest-management` skill + TradingView MCP
  `pine_*` tools (confirmed live: CDP connected).

### Add (net-new, all $0, no new services)
- `signal_agent.py` money-flow Money Line in `pandas_ta` (green-field; the heart of the product).
- `dashboard.py` Streamlit + Plotly (green-field; UX approved).
- `backtester.py` on vectorbt (green-field).
- `logging_config.py` loguru (green-field).
- CCXT abstraction wrapping the executor (generalizes bot.js's BitGet-specific HMAC).
- `indicators/money_line_pine.txt` and `indicators/money_scanner_pine.txt` (no existing money-flow Pine indicator).
- Optional only: Grok `XAI_API_KEY` (not used by default).

---

## 5. Architecture

In-process modular "agent" suite. `main.py` orchestrates agents via asyncio tasks scheduled by APScheduler. A single
`config.yaml` (pydantic-validated) drives all behavior; secrets live only in `.env`. SQLite is the default
self-contained store. Each agent has one clear purpose, a small public interface, and fails in isolation so the
orchestrator survives a single-agent error.

```
APScheduler tick
  -> scanner_agent (watchlist)
     -> data_fetcher (CCXT public OHLCV, retry/rate-limit)
     -> signal_agent.get_money_line() per symbol
     -> rank flips, apply blacklist/whitelist
     -> [optional] llm_copilot.validate()
     -> executor_agent (paper fill via risk_manager)
     -> store (SQLite) + alert_agent (Telegram/Discord/email)
  -> dashboard reads store and renders (Streamlit/Plotly)
```

---

## 6. Repository layout

```
CryptoChucker-Agents/
├── README.md                  # setup, API keys, customization, backtesting, screenshots
├── STRATEGY.md                # transparent Money Line / Money Scanner math
├── BUILD_REPORT.md            # final summary + Codex gate verdicts (written at Gate 6)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example               # key NAMES only, never values
├── config.yaml                # all user-editable settings (pydantic-validated)
├── setup.sh                   # *nix bootstrap
├── setup.ps1                  # Windows bootstrap
├── main.py                    # orchestrator
├── agents/
│   ├── signal_agent.py        # Money Line                       [FRESH; ref: bot.js math]
│   ├── scanner_agent.py       # multi-symbol scanner             [port: morning.js / scanner.service.ts]
│   ├── executor_agent.py      # CCXT paper executor, live-disabled[port: bot.js]
│   ├── alert_agent.py         # Telegram/Discord/email           [port: gravity-claw + JMS webhook]
│   ├── dashboard.py           # Streamlit + Plotly               [FRESH; UX approved]
│   └── backtester.py          # vectorbt + grid search           [FRESH]
├── indicators/
│   ├── money_line_pine.txt    # CryptoChucker - Money Line v1    [FRESH]
│   └── money_scanner_pine.txt # CryptoChucker - Money Scanner v1 [FRESH]
├── utils/
│   ├── data_fetcher.py        # CCXT public OHLCV + rate-limit   [ref: bot.js fetchCandles]
│   ├── risk_manager.py        # sizing + caps + drawdown stop    [port: bot.js checkTradeLimits]
│   ├── llm_copilot.py         # validator, OFF by default        [port: gravity-claw llm.ts + JMS gateway]
│   ├── logging_config.py      # loguru                           [FRESH]
│   ├── store.py               # SQLite default / Supabase opt    [ref: gravity-claw tier-1 + JMS admin]
│   ├── config_schema.py       # pydantic models for config.yaml  [FRESH improvement]
│   └── helpers.py
├── tests/                     # unit tests + deterministic paper smoke test
│   └── fixtures/              # fixed OHLCV CSV for the smoke test
├── reviews/                   # gate-0..6-codex.md verdicts
├── .github/workflows/ci.yml   # lint + paper smoke test on push
└── logs/                      # .gitignore'd
```

---

## 7. Component specifications

Each unit lists: purpose, public interface, key dependencies, reuse source.

- **`utils/config_schema.py`** — pydantic models validating `config.yaml`; fail-fast with a clear message on bad config.
  Interface: `load_config(path) -> Config`. Deps: pydantic, pyyaml.
- **`utils/logging_config.py`** — loguru setup: colored console, rotating file sink, optional JSON sink for cloud.
  Interface: `setup_logging(cfg)`. Imported once; all agents inherit.
- **`utils/data_fetcher.py`** — `fetch_ohlcv(symbol, timeframe, limit) -> DataFrame`, `top_volume_symbols(n) -> list`.
  CCXT public endpoints (no auth) with retry, reconnect, rate-limit handling. Deps: ccxt, pandas.
- **`agents/signal_agent.py`** — `get_money_line(df) -> DataFrame[money_line, state, flip_detected, signal_strength]`.
  Cumulative typical-price x volume money flow, EMA/VWMA-smoothed; `state` from smoothed slope sign; `flip_detected`
  on state change; `signal_strength` 0-100 from normalized volume + momentum. Multi-timeframe confirmation
  (`confirm(symbol, primary_tf, confirm_tf)`). Optional filters: volume surge, RSI, ADX. Deps: pandas_ta.
- **`agents/scanner_agent.py`** — scans watchlist every N minutes (APScheduler), runs `signal_agent` per symbol,
  applies blacklist/whitelist + advanced filters (volume > 2x avg, price vs VWAP), ranks top-10 strongest flips, emits
  events. Interface: `scan() -> list[SignalEvent]`. Deps: data_fetcher, signal_agent, APScheduler.
- **`utils/risk_manager.py`** — `position_size(account, risk_pct, entry, stop) -> float`, `check_limits(state) -> bool`
  (daily cap, max single-trade, max exposure), `drawdown_stop(equity_curve) -> bool`. Seeded with proven `.env` values.
- **`agents/executor_agent.py`** — consumes signals, applies `risk_manager`, simulates fills in paper mode, logs P&L.
  Live path behind a CCXT adapter (default BloFin/BitGet), multi-exchange; **ships disabled**. Rules (config-driven):
  buy on bullish flip + optional dip (price < EMA or RSI < 40); sell at profit target after fees OR on bearish flip;
  optional trailing stop, time-based exit, max hold. Interface: `on_signal(event)`, `paper_fill(...)`. Deps: ccxt.
- **`agents/alert_agent.py`** — `send(event)` fan-out to Telegram (python-telegram-bot), Discord (webhook), email
  (smtplib); per-channel toggle and rich formatting. Reuses existing `TELEGRAM_BOT_TOKEN`.
- **`utils/llm_copilot.py`** — `validate(signal) -> {decision, confidence, reason}` with multi-provider failover
  (Anthropic/OpenAI/Ollama), redaction pre-check, schema-validated output. **OFF by default.** Deps: anthropic, openai.
- **`agents/dashboard.py`** — Streamlit + Plotly: KPI cards, candlestick + Money Line overlay, top signals, equity
  curve, positions, alerts feed, logs, scanner tab, backtest tab; per-agent start/stop toggles; mobile-friendly dark
  theme. Matches approved mockup (Section 10).
- **`agents/backtester.py`** — vectorbt run over OHLCV + Money Line signal; metrics (Sharpe, Sortino, max drawdown,
  win rate, profit factor); CSV export + Plotly equity curve; simple parameter grid search. Interface:
  `run_backtest(cfg) -> Result`, `grid_search(cfg, grid) -> DataFrame`.
- **`utils/store.py`** — SQLite default (tables: signals, scans, positions, trades, equity); Supabase optional via
  config flag. Interface: `save_*`, `load_*`. Mirrors bot.js trade-log columns.
- **`main.py`** — loads config, sets up logging, instantiates agents, schedules them, handles graceful shutdown and
  per-agent error isolation.

---

## 8. TradingView Pine indicators

Two Pine v6 indicators are first-class deliverables, written and **deployed into the user's live TradingView account**
(not just committed to the repo). Both are saved as **new script slots** (the 11 existing "JMS AI" scripts are never
touched).

### `CryptoChucker - Money Line v1` (overlay)
A trend-following money-flow line that flips bullish/bearish, with flip markers and `alertcondition`s for native
TradingView alerts. Works on whatever symbol the chart shows, so it can be pulled up on any coin at any timeframe. Mirrors
the Python `get_money_line` logic so on-chart and in-suite signals agree.

### `CryptoChucker - Money Scanner v1` (screener table)
An on-chart table listing up to **30 configurable watchlist symbols** with each symbol's current Money Line state
(bull/bear), strength, and a recent-flip flag, via `request.security`. Honest limitation: TradingView caps the number of
symbols a single indicator can reference (about 40), so this covers a core watchlist; the Python `scanner_agent` handles
hundreds-scale scanning with push alerts.

### Deployment mechanism (and honest caveat)
For each indicator: write Pine v6 source, **compile-verify against live TradingView** via the MCP
(`pine_smart_compile` / `pine_check`) until error-free, then save as a new slot. Source is committed to `indicators/`.
Caveat (per the user's `tv_add_to_chart_fallback` experience): the 2026 TradingView UI sometimes will not auto-add a
brand-new script to the chart via automation, so the final "add to chart" may be a single manual click from the
Indicators dialog. Creation, compile, and save are automated.

---

## 9. Data flow (paper mode)

`APScheduler tick -> scanner_agent -> data_fetcher (CCXT public) -> signal_agent.get_money_line -> rank flips ->
[optional llm_copilot.validate] -> executor_agent (paper fill via risk_manager) -> store (SQLite) + alert_agent
(Telegram/Discord/email) -> dashboard reads store and renders`.

---

## 10. Dashboard UX (approved)

The front-end is the real Streamlit + Plotly stack, validated via a runnable mockup (`personal-trading-suite/mockup/`)
the user reviewed and approved. Layout: left sidebar (brand, PAPER pill, per-agent start/stop toggles incl. LLM co-pilot
off by default, exchange + timeframe selectors, scan interval, emergency stop); main area with three tabs:
- **Overview**: KPI cards (equity, today's P&L, open positions, win rate, active signals); BTC/USDT candlestick with
  Money Line overlay + flip markers; top signals column; equity curve; open positions with color-coded P&L; recent
  alerts feed; collapsible live logs.
- **Scanner**: state/strength/symbol filters over the scan; green/red state; strength heat.
- **Backtest**: parameter inputs + Run; metric cards; equity curve.

Dark theme, mobile-friendly (cards stack, sidebar collapses). The mockup app.py is committed under `docs/mockup/` as a
reproducible UX reference.

---

## 11. Configuration and secrets

- **`config.yaml`** (pydantic-validated): exchange, watchlist, timeframes (primary + confirmation), scan interval,
  risk (`risk_pct`, max exposure, daily cap, drawdown stop), executor rules (profit target, dip filter, trailing stop,
  max hold), alert channel toggles, persistence backend (sqlite/supabase), LLM co-pilot toggle + provider, Pine scanner
  watchlist. No hard-coded values anywhere.
- **`.env`** (never committed): exchange keys, `TELEGRAM_BOT_TOKEN`, `DISCORD_WEBHOOK_URL`, email creds, optional
  Anthropic/OpenAI/Supabase. `.env.example` ships key names only.
- **Security**: `.gitignore` blocks `.env`/keys; a pre-commit secret scan prevents committing the user's existing
  BloFin/BitGet/Telegram keys; `PAPER_TRADING=true` default; live order placement requires explicit config + keys.

---

## 12. Error handling and resilience

loguru with rotation + JSON sink; CCXT rate-limit and reconnect handling; graceful shutdown on SIGINT/SIGTERM; each
agent runs in an isolated task so a single failure does not crash the orchestrator; auto-restart logic for transient
data-source errors; clear, actionable error messages on config/credential problems.

---

## 13. Testing and verification

- **Unit tests** (pytest) per module: signal math, risk sizing, config validation, store round-trips, alert payload
  formatting (mocked transports), backtester metrics.
- **Deterministic paper smoke test**: runs the full pipeline on a fixed OHLCV fixture (CI-able), asserting zero errors
  and expected event shapes.
- **Live smoke run** at Gate 6: one real run on public data; dashboard started headless and asserted to serve;
  backtest produces metrics. Per the user's "validate before done" rule, verification is runtime, not just compile.
- **CI**: GitHub Actions runs lint + the deterministic smoke test on push.

---

## 14. Codex review-gate workflow (the spine of this build)

**Mechanic per gate.** Implement the slice, stage it in git, then run Codex against the diff:
`codex exec review` (read-only sandbox) for code stages, or `codex exec -s read-only "<rubric>"` piped the spec for
Gate 0. Codex returns findings classified **BLOCKING / MEDIUM / LOW**. I fix every BLOCKING and re-review until clean;
MEDIUM/LOW are fixed now or logged with a defer rationale. Each gate's verdict is saved to `reviews/gate-N-codex.md`
and surfaced to the user in-session. Only a **PASS (no BLOCKING)** advances the build.

| Gate | Slice reviewed |
|---|---|
| 0 | This spec + the proposed additions in Section 15. Codex signs off on direction. |
| 1 | Scaffold + config + pydantic loader + utils (logging, helpers, data_fetcher, risk_manager, store) + Docker. |
| 2 | signal_agent + Money Line Pine (compile-verified) + STRATEGY.md + unit tests. |
| 3 | scanner_agent + alert_agent + Money Scanner Pine (compile-verified) + tests. |
| 4 | executor_agent (CCXT, paper-default, live-disabled) + risk_manager wiring + tests. |
| 5 | dashboard + backtester + llm_copilot (OFF) + tests. |
| 6 | main.py orchestrator + end-to-end paper smoke test + README + setup scripts + CI. Final PASS, then live smoke run. |

---

## 15. Proposed additions beyond the master prompt (for Codex Gate 0 sign-off)

The master prompt is the requirements baseline. These additions/improvements are proposed and require Codex approval at
Gate 0:

1. Frame Money Line / Money Scanner as a **documented faithful equivalent**, not a reverse-engineered clone.
2. **Money Scanner Pine indicator** + **live deployment of both Pine indicators** to TradingView (prompt listed only a
   Money Line `.txt`).
3. **pydantic** config validation (fail-fast).
4. **CCXT abstraction** generalizing bot.js's BitGet-specific HMAC.
5. **SQLite-default persistence** (`store.py`) for a self-contained repo.
6. **`setup.ps1`** for Windows alongside `setup.sh`.
7. **Deterministic paper smoke test** + **GitHub Actions CI**.
8. **`STRATEGY.md`** documenting the indicator math transparently.
9. **Pre-commit secret scan** + secrets hygiene for the public repo.

---

## 16. Deployment and delivery

- Docker + docker-compose (Python 3.11 base); one-command bring-up; Railway-ready (env-driven config; `RAILWAY_TOKEN`
  present if cloud deploy is desired later).
- Published to `github.com/cryptochucker/CryptoChucker-Agents`. At push time, switch active gh account with
  `gh auth switch --user cryptochucker` (already authenticated; scopes `repo`, `gist`, `read:org`).

---

## 17. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Money Line is not a literal clone of a closed-source indicator | Build a documented faithful equivalent; STRATEGY.md is explicit |
| Pine `request.security` symbol cap | Pine scanner covers 30; Python scanner does hundreds |
| New-script auto-add to chart unreliable (2026 UI) | Automate create/compile/save; one manual click to add if needed |
| Secret leakage to public repo | `.gitignore` + pre-commit secret scan + `.env.example` names only |
| Live trading risk | Ships disabled; `PAPER_TRADING=true`; enabling is a separate follow-on |
| Reusable code is TypeScript, not Python | Treat as reference logic + proven values; Python is net-new but de-risked |
| Scope creep / endless refinement | Fixed definition of done (Section 1); stop when met |

---

## 18. Build stages summary

Stage 1 -> Gate 1: scaffolding + utils + Docker.
Stage 2 -> Gate 2: signal engine + Money Line Pine.
Stage 3 -> Gate 3: scanner + alerts + Money Scanner Pine.
Stage 4 -> Gate 4: paper executor + risk manager.
Stage 5 -> Gate 5: dashboard + backtester + LLM co-pilot (off).
Stage 6 -> Gate 6: orchestrator + end-to-end paper smoke test + README/CI + publish.

Each gate requires a Codex PASS before proceeding. When Stage 6 passes and the definition of done is met, the build
stops and the repo is handed to the user for formal approval.
