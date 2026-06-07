# CryptoChucker Agents, Design Spec

- **Date:** 2026-06-07
- **Revision:** r2 (incorporates Codex Gate 0 review; see Section 19 resolution log)
- **Status:** Re-submitted for Codex Gate 0, then user formal approval
- **Owner:** Jason Elam
- **Repo target:** `github.com/cryptochucker/CryptoChucker-Agents` (open-source, public)
- **Source brief:** `docs/CryptoChucker_Agents_Master_Prompt.md`
- **Reviewer/approver of record:** Codex CLI (`gpt-5.5`) at every stage gate

---

## 1. Summary and end goal

Build a **paper-trading-complete**, modular crypto trading suite ("CryptoChucker Agents") in Python 3.11 that
replicates the *intent* of Bullmania's Money Line / Money Scanner and GoBabyTrade's rule-based bot, and significantly
enhances it for a single solo trader at $0 recurring cost. The suite runs end-to-end on **real public market data** in
paper mode. The live-order path is built behind a CCXT abstraction but **ships disabled behind a fail-closed double
gate** (Section 11); no live keys are committed. Two companion **TradingView Pine v6 indicators** (Money Line, Money
Scanner) are written and compile-verified, with source committed and saved into the user's TradingView account on a
best-effort basis (Section 8).

This is a **bounded build with a fixed finish line**. There is no open-ended refinement loop.

### Definition of done (the explicit stop condition)

The build is COMPLETE, and work STOPS, when ALL of the following hold:

1. **Gates 0 through 6** each carry a recorded **Codex PASS** (no BLOCKING findings) in `reviews/gate-N-codex.md`.
2. Unit and integration tests pass, **including the live-trading safety tests** (Section 11) that prove paper mode
   cannot place a live order and that live credentials are never loaded under test/CI.
3. A deterministic **end-to-end paper smoke test** runs the full pipeline (data fetch, signal, scan, test-channel
   alert, paper fill, persistence, dashboard serve, backtest metrics) with **zero errors**, plus one live run on real
   public data whose evidence is recorded in `BUILD_REPORT.md`: exact command, UTC timestamp, symbols scanned,
   dashboard URL + serve status, and generated artifacts (trade log, equity CSV, backtest metrics file).
4. Both TradingView indicators are **compile-verified** (compile log or screenshot captured) and their source committed
   to `indicators/`. Saving them into the live TradingView account is a best-effort delivery task; if MCP automation
   cannot create the new slot, the accepted fallback is committed source + compile evidence + one-click manual-save
   instructions in the README. The fallback still satisfies done.
5. A **`gitleaks` (or `detect-secrets`) scan over the full repo and its git history reports zero committed secrets.**
6. `README.md`, `STRATEGY.md`, `config.yaml`, `.env.example`, `setup.sh`, and `setup.ps1` are complete; the repo is
   pushed to `github.com/cryptochucker/CryptoChucker-Agents`.
7. A `BUILD_REPORT.md` summarizes what was built, every Codex gate verdict, and **how each MEDIUM/LOW finding was fixed
   or deferred with rationale and owner**, plus exact run instructions.

Then the repo is handed to the user for **formal approval**. No additional polishing past this line.

---

## 2. Scope

### In scope (this build)
- Signal engine (Money Line) in Python (`pandas_ta`), with multi-timeframe confirmation and `signal_strength` 0-100.
- Multi-symbol scanner (50-500+ symbols) with APScheduler cadence, ranking (top 10), blacklist/whitelist.
- Executor in **paper mode** via a CCXT abstraction; live path present but disabled behind the Section 11 double gate.
- Risk manager (position sizing, daily caps, max single-trade, max exposure, max-drawdown hard stop).
- Alerts: Telegram, Discord, email (each independently toggleable), **with a generated Plotly chart image (kaleido) and
  a chart-link fallback** on scanner alerts.
- Streamlit + Plotly dashboard (UX approved via mockup; see Section 10).
- Backtester on `vectorbt`: metrics (Sharpe, Sortino, max drawdown, win rate, profit factor), CSV + Plotly equity
  curve, plus a simple parameter grid search.
- **Watchlist import/export (CSV and JSON)** and a **per-exchange fee calculator** (both explicit master-brief items).
- Optional LLM signal-validator co-pilot, built but **OFF by default**, on existing Anthropic/OpenAI keys.
- Two TradingView Pine v6 indicators: Money Line (overlay) and Money Scanner (screener table, 30 symbols by design).
- SQLite persistence (default), Supabase optional/toggleable.
- Docker + docker-compose; Railway-ready; `setup.sh` + `setup.ps1`; full README; GitHub Actions CI (lint + secret scan
  + paper smoke test).

### Out of scope / deferred (clearly labeled follow-ons)
- **Live order execution enabled** (real capital). Code path exists, ships disabled behind the double gate; enabling is
  a separate, explicitly-scoped follow-on after the user has run paper mode.
- **Walk-forward optimization and Monte Carlo simulation.** This is an **approved scope reduction** from the master
  brief's backtester wording: simple parameter **grid search is the Gate-0-accepted optimizer** for this bounded build;
  walk-forward and Monte Carlo are a labeled follow-on.
- Redis inter-agent pub/sub (optional in the prompt; in-process orchestrator is sufficient).
- `ta-lib` (hard to install on Windows; `pandas_ta` covers the need).
- Pine on-chart scanning of hundreds of symbols (TradingView limits per-indicator `request.security` usage; the Python
  scanner handles hundreds-scale).

---

## 3. Locked decisions (from brainstorming)

| Decision | Choice |
|---|---|
| End goal | Paper-trading-complete suite; live built but shipped disabled behind a double gate |
| Codex gate cadence | Stage-gated: Gate 0 (spec) + 6 build-stage gates (Gates 0-6) |
| LLM co-pilot | Built, toggleable, OFF by default; existing Anthropic/OpenAI keys; no new credential |
| Backtester depth | vectorbt core + full metrics + CSV + Plotly equity curve + simple grid search (approved reduction) |
| Persistence | SQLite default (self-contained); Supabase optional |
| Alerting | Native Python (python-telegram-bot, Discord webhook, smtplib); chart image via kaleido + link fallback |
| Default exchange (data + disabled-live adapter) | BloFin/BitGet via CCXT; multi-exchange supported |
| TradingView indicators | `CryptoChucker - Money Line v1`, `CryptoChucker - Money Scanner v1` (new slots) |
| Pine scanner watchlist | 30 symbols by design, user-editable in indicator settings |
| Money Line framing | Independently implemented faithful money-flow equivalent; no clone/trademark claims |
| GitHub | Publish to `github.com/cryptochucker`; switch active gh account to `cryptochucker` at push |

---

## 4. Stack reuse map (leverage vs add)

**Headline: zero new paid services required.** Every capability maps to an existing asset or a $0 open-source library.
The only new credential that ever arises is Grok (`XAI_API_KEY`), and it is not needed (Anthropic/OpenAI present; Ollama
is a $0 local fallback). Reusable trading code is TypeScript/JS, so "reuse" means **port proven logic and reuse only the
*architecture and parameter shapes*, never secret values** (Section 11), and re-implement in Python.

### Leverage (existing, as reference patterns only)
- **Executor + safety + trade limits**: `claude-tradingview-mcp-trading/bot.js` (paper-first gate, safety checks, trade
  limits, CSV trade log). Reference for `executor_agent` + `risk_manager` logic shape.
- **Risk guardrail shapes**: the *names and tuned magnitudes* of `MAX_TRADE_SIZE_USD`, `MAX_TRADES_PER_DAY`,
  `MAX_CONSECUTIVE_LOSSES` inform `config.yaml` defaults (values are re-entered by the user, not copied from any `.env`).
- **Scanner architecture**: `tradingview-mcp-jackson/src/core/morning.js` + meme-coin `scanner.service.ts`.
- **Market data**: `bot.js fetchCandles` (Binance public) and meme-coin Birdeye/DexScreener/GeckoTerminal wrappers; CCXT
  is the spec-mandated primary.
- **Watchlist schema**: `tradingview-mcp-jackson/rules.example.json`; TradingView MCP `watchlist_*`; CoinGecko free tier.
- **Alerts**: gravity-claw Telegram runtime + JMS Slack-webhook fetch pattern (pattern only).
- **LLM co-pilot**: `gravity-claw/src/llm.ts` multi-provider failover + JMS AI Gateway (redaction + schema validation).
- **Persistence**: SQLite (gravity-claw tier-1) default; Supabase admin-client pattern optional.
- **Docker/Railway**: gravity-claw `Dockerfile` + Railway config; n8n `docker-compose` (patterns only).
- **Pine conventions + deploy flow**: 11 existing v5 indicators + `pine-script-rest-management` skill + TradingView MCP
  `pine_*` tools (confirmed live: CDP connected).

### Add (net-new, all $0, no new services)
- `signal_agent.py` money-flow Money Line in `pandas_ta` (the heart of the product).
- `dashboard.py` Streamlit + Plotly (UX approved).
- `backtester.py` on vectorbt.
- `logging_config.py` loguru.
- `utils/fees.py` per-exchange fee calculator; watchlist import/export in `helpers.py`.
- CCXT abstraction wrapping the executor (generalizes bot.js's exchange-specific signing).
- `indicators/money_line_pine.txt` and `indicators/money_scanner_pine.txt`.
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
     -> executor_agent (paper fill via risk_manager + fees)
     -> store (SQLite) + alert_agent (Telegram/Discord/email + chart image)
  -> dashboard reads store and renders (Streamlit/Plotly)
```

---

## 6. Repository layout

```
CryptoChucker-Agents/
├── README.md                  # setup, API keys, customization, backtesting, screenshots, manual Pine-add steps
├── STRATEGY.md                # transparent, independently-implemented Money Line / Money Scanner math
├── BUILD_REPORT.md            # final summary + Codex gate verdicts + MEDIUM/LOW disposition (written at Gate 6)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example               # key NAMES only, never values
├── config.yaml                # all user-editable settings (pydantic-validated)
├── setup.sh                   # *nix bootstrap
├── setup.ps1                  # Windows bootstrap
├── .pre-commit-config.yaml    # gitleaks (or detect-secrets) + ruff, run before every commit
├── main.py                    # orchestrator
├── agents/
│   ├── signal_agent.py        # Money Line                       [FRESH; ref: bot.js math]
│   ├── scanner_agent.py       # multi-symbol scanner             [port: morning.js / scanner.service.ts]
│   ├── executor_agent.py      # CCXT paper executor, live-gated  [port: bot.js]
│   ├── alert_agent.py         # Telegram/Discord/email + chart   [port: gravity-claw + JMS webhook]
│   ├── dashboard.py           # Streamlit + Plotly               [FRESH; UX approved]
│   └── backtester.py          # vectorbt + grid search           [FRESH]
├── indicators/
│   ├── money_line_pine.txt    # CryptoChucker - Money Line v1    [FRESH]
│   └── money_scanner_pine.txt # CryptoChucker - Money Scanner v1 [FRESH]
├── utils/
│   ├── data_fetcher.py        # CCXT public OHLCV + rate-limit   [ref: bot.js fetchCandles]
│   ├── risk_manager.py        # sizing + caps + drawdown stop    [port: bot.js checkTradeLimits]
│   ├── fees.py                # per-exchange fee calculator       [FRESH; master-brief item]
│   ├── llm_copilot.py         # validator, OFF by default        [port: gravity-claw llm.ts + JMS gateway]
│   ├── logging_config.py      # loguru                           [FRESH]
│   ├── store.py               # SQLite default / Supabase opt    [ref: gravity-claw tier-1 + JMS admin]
│   ├── config_schema.py       # pydantic models for config.yaml  [FRESH improvement]
│   └── helpers.py             # watchlist import/export CSV/JSON, misc
├── tests/                     # unit tests + deterministic paper smoke + live-safety tests
│   └── fixtures/              # fixed OHLCV CSV for the smoke test
├── reviews/                   # gate-0..6-codex.md verdicts
├── docs/
│   ├── superpowers/specs/      # this design spec
│   └── mockup/                 # runnable Streamlit UX reference (synthetic data)
├── .github/workflows/ci.yml   # lint (ruff) + secret scan (gitleaks) + paper smoke test on push
└── logs/                      # .gitignore'd
```

---

## 7. Component specifications

Each unit lists: purpose, public interface, key dependencies, reuse source.

- **`utils/config_schema.py`** — pydantic models validating `config.yaml`; fail-fast with a clear message on bad config.
  Interface: `load_config(path) -> Config`. Deps: pydantic, pyyaml.
- **`utils/logging_config.py`** — loguru setup: colored console, rotating file sink, optional JSON sink. Interface:
  `setup_logging(cfg)`. Imported once; all agents inherit. **Never logs secret values** (Section 11).
- **`utils/data_fetcher.py`** — `fetch_ohlcv(symbol, timeframe, limit) -> DataFrame`, `top_volume_symbols(n) -> list`.
  CCXT public endpoints (no auth) with retry, reconnect, rate-limit handling. Deps: ccxt, pandas.
- **`utils/fees.py`** — `fee(exchange, side, notional, maker=False) -> float`; per-exchange maker/taker rates from
  `config.yaml` with sane defaults. Used by executor for net-of-fees profit-target logic and P&L.
- **`utils/helpers.py`** — watchlist `load_watchlist(path)` / `save_watchlist(items, path)` for **CSV and JSON**; small
  shared utilities.
- **`agents/signal_agent.py`** — `get_money_line(df) -> DataFrame[money_line, state, flip_detected, signal_strength]`.
  Cumulative typical-price x volume money flow, EMA/VWMA-smoothed; `state` from smoothed slope; `flip_detected` on state
  change; `signal_strength` 0-100 from normalized volume + momentum. `confirm(symbol, primary_tf, confirm_tf)` for
  multi-timeframe. Optional filters: volume surge, RSI, ADX. Deps: pandas_ta.
- **`agents/scanner_agent.py`** — scans watchlist every N minutes (APScheduler), runs `signal_agent` per symbol, applies
  blacklist/whitelist + advanced filters (volume > 2x avg, price vs VWAP), ranks top-10 flips, emits events. Interface:
  `scan() -> list[SignalEvent]`.
- **`utils/risk_manager.py`** — `position_size(account, risk_pct, entry, stop) -> float`, `check_limits(state) -> bool`
  (daily cap, max single-trade, max exposure), `drawdown_stop(equity_curve) -> bool`. Defaults from `config.yaml`.
- **`agents/executor_agent.py`** — consumes signals, applies `risk_manager` + `fees`, simulates fills in paper mode,
  logs P&L. **Live path is unreachable unless the Section 11 double gate is satisfied**; otherwise every order routes to
  the paper simulator and any direct live call raises a guard error. Rules (config-driven): buy on bullish flip +
  optional dip; sell at profit target after fees OR on bearish flip; optional trailing stop, time exit, max hold.
  Interface: `on_signal(event)`, `paper_fill(...)`, `_live_order(...)` (guarded). Deps: ccxt.
- **`agents/alert_agent.py`** — `send(event)` fan-out to Telegram (python-telegram-bot), Discord (webhook), email
  (smtplib); per-channel toggle, rich formatting; scanner alerts attach a **Plotly chart image (kaleido)** with a
  **TradingView chart-link fallback** if image generation is unavailable. Reuses existing `TELEGRAM_BOT_TOKEN` by name.
- **`utils/llm_copilot.py`** — `validate(signal) -> {decision, confidence, reason}`, multi-provider failover
  (Anthropic/OpenAI/Ollama), redaction pre-check, schema-validated output. **OFF by default.** Deps: anthropic, openai.
- **`agents/dashboard.py`** — Streamlit + Plotly per the approved mockup (Section 10).
- **`agents/backtester.py`** — vectorbt run; metrics (Sharpe, Sortino, max drawdown, win rate, profit factor); CSV +
  Plotly equity curve; simple grid search. Interface: `run_backtest(cfg) -> Result`, `grid_search(cfg, grid) -> DataFrame`.
- **`utils/store.py`** — SQLite default (tables: signals, scans, positions, trades, equity); Supabase optional via flag.
- **`main.py`** — loads config, sets up logging, instantiates agents, schedules them, graceful shutdown, per-agent error
  isolation.

---

## 8. TradingView Pine indicators

Two Pine v6 indicators are first-class deliverables. Source is committed to `indicators/` and compile-verified; saving
into the user's TradingView account is best-effort (Section 1, item 4). Both are saved as **new script slots** (the 11
existing "JMS AI" scripts are never touched).

### `CryptoChucker - Money Line v1` (overlay)
A trend-following money-flow line that flips bullish/bearish, with flip markers and `alertcondition`s for native
TradingView alerts. Works on whatever symbol the chart shows. Mirrors the Python `get_money_line` logic so on-chart and
in-suite signals agree.

### `CryptoChucker - Money Scanner v1` (screener table)
An on-chart table of **exactly 30 watchlist symbols (capped by design)**, each with current Money Line state (bull/bear),
strength, and a recent-flip flag, via `request.security`. The 30 cap is a deliberate design limit chosen to stay within
TradingView's per-indicator `request.security` budget; compile verification is run against the **full default 30-symbol
watchlist** (not a reduced set). The Python `scanner_agent` handles hundreds-scale scanning with push alerts.

### Deployment mechanism and fallback evidence
For each indicator: write Pine v6 source, **compile-verify against live TradingView** via the MCP (`pine_smart_compile` /
`pine_check`) until error-free, capture the compile log/screenshot, then save as a new slot. If MCP automation cannot
create the slot (the 2026 floating-dialog UI is unreliable for new slots), the accepted fallback is: committed source +
compile evidence + one-click manual-save steps documented in the README. This fallback satisfies done.

---

## 9. Data flow (paper mode)

`APScheduler tick -> scanner_agent -> data_fetcher (CCXT public) -> signal_agent.get_money_line -> rank flips ->
[optional llm_copilot.validate] -> executor_agent (paper fill via risk_manager + fees) -> store (SQLite) + alert_agent
(Telegram/Discord/email + chart image) -> dashboard reads store and renders`.

---

## 10. Dashboard UX (approved)

The front-end is the real Streamlit + Plotly stack, validated via a runnable mockup (committed under `docs/mockup/`) the
user reviewed and approved. Layout: left sidebar (brand, PAPER pill, per-agent start/stop toggles incl. LLM co-pilot off
by default, exchange + timeframe selectors, scan interval, emergency stop); main area with three tabs:
- **Overview**: KPI cards (equity, today's P&L, open positions, win rate, active signals); candlestick with Money Line
  overlay + flip markers; top signals column; equity curve; open positions with color-coded P&L; alerts feed; logs.
- **Scanner**: state/strength/symbol filters; green/red state; strength heat.
- **Backtest**: parameter inputs + Run; metric cards; equity curve.

Dark theme, mobile-friendly (cards stack, sidebar collapses).

---

## 11. Configuration, secrets, and live-trading safety

### Configuration
`config.yaml` (pydantic-validated) drives everything: exchange, watchlist (+ import/export path), timeframes (primary +
confirmation), scan interval, risk (`risk_pct`, max exposure, daily cap, drawdown stop), executor rules (profit target,
dip filter, trailing stop, max hold), per-exchange fees, alert channel toggles, persistence backend, LLM co-pilot toggle
+ provider, Pine scanner watchlist. **No hard-coded values anywhere.**

### Secrets handling (strict, for a public repo)
- **During implementation**, no secret *value* is ever read, printed, copied, committed, or reused. Only environment
  variable **names** are referenced. Existing `.env` files in other projects are off-limits as value sources.
- `.env` (and all key/secret files) are git-ignored; **`.env.example` contains key names only**.
- A concrete secret scanner (**`gitleaks`**, fallback `detect-secrets`) runs in **both** the **pre-commit** hook **and**
  **CI**, scanning the working tree and full history. A clean gitleaks run over history is a definition-of-done item.

### Live-trading safety (fail-closed, defense in depth)
- Default config is **paper**: `PAPER_TRADING=true`.
- The live `create_order` path is **unreachable** unless **both** `PAPER_TRADING=false` **and** a separate
  `ENABLE_LIVE_TRADING=true` are explicitly set. With either unset, the executor routes to the paper simulator and a
  direct live call raises a guard error.
- **Tests prove** that: (a) under default config, the order path never calls the ccxt `create_order` (mocked, asserted
  not-called); (b) setting only `PAPER_TRADING=false` (without `ENABLE_LIVE_TRADING`) still blocks live; (c) the live
  exchange adapter is **not instantiated** under test/CI, and **CI/test environments carry no exchange credentials**, so
  live cannot be exercised even accidentally.

---

## 12. Error handling and resilience

loguru with rotation + JSON sink; CCXT rate-limit and reconnect handling; graceful shutdown on SIGINT/SIGTERM; each
agent runs in an isolated task so a single failure does not crash the orchestrator; auto-restart for transient
data-source errors; clear, actionable messages on config/credential problems (without echoing secret values).

---

## 13. Testing and verification

- **Unit tests** (pytest): signal math, risk sizing, fee math, config validation, store round-trips, alert payload
  formatting (mocked transports), backtester metrics, watchlist import/export.
- **Live-trading safety tests** (Section 11): the three assertions above.
- **Deterministic paper smoke test**: full pipeline on a fixed OHLCV fixture (CI-able), asserting zero errors and
  expected event shapes.
- **Live smoke run** at Gate 6: one real run on public data; dashboard started headless and asserted to serve; backtest
  produces metrics. Evidence recorded in `BUILD_REPORT.md`. Verification is runtime, not just compile.
- **CI**: GitHub Actions runs ruff lint + gitleaks secret scan + the deterministic smoke test on push.

---

## 14. Codex review-gate workflow (the spine of this build)

**Mechanic per gate.** Implement the slice, `git add` it (stage), then run Codex **against the staged diff** with a
read-only sandbox: `codex exec review` for code stages, or piped rubric for Gate 0. The staged diff contains **no
secrets** (enforced by `.gitignore` + the pre-commit secret scan). Codex returns findings classified **BLOCKING /
MEDIUM / LOW**. Every BLOCKING is fixed and re-reviewed until clean. Every **MEDIUM/LOW is either fixed now or recorded
in `BUILD_REPORT.md` with owner and rationale.** Each gate's verdict is saved to `reviews/gate-N-codex.md` and surfaced
to the user. Only a **PASS (no BLOCKING)** advances the build.

| Gate | Slice reviewed |
|---|---|
| 0 | This spec + the proposed additions in Section 15. Codex signs off on direction. |
| 1 | Scaffold + config + pydantic loader + utils (logging, helpers, fees, data_fetcher, risk_manager, store) + Docker + pre-commit/CI secret scan. |
| 2 | signal_agent + Money Line Pine (compile-verified) + STRATEGY.md + unit tests. |
| 3 | scanner_agent + alert_agent (incl. chart image) + Money Scanner Pine (compile-verified) + tests. |
| 4 | executor_agent (CCXT, paper-default, live double-gated) + risk_manager + fees wiring + live-safety tests. |
| 5 | dashboard + backtester + llm_copilot (OFF) + tests. |
| 6 | main.py orchestrator + end-to-end paper smoke test + README + setup scripts + CI. Final PASS, then live smoke run. |

---

## 15. Proposed additions beyond the master prompt (Codex Gate 0 sign-off)

The master prompt is the requirements baseline. These additions/improvements require Codex approval at Gate 0:

1. Frame Money Line / Money Scanner as an **independently-implemented faithful equivalent** (no clone/trademark claims).
2. **Money Scanner Pine indicator** + **best-effort live deployment** of both Pine indicators to TradingView (prompt
   listed only a Money Line `.txt`). Brittleness mitigated by the committed-source + compile-evidence + manual fallback.
3. **pydantic** config validation (fail-fast).
4. **CCXT abstraction** generalizing bot.js's exchange-specific signing.
5. **SQLite-default persistence** (`store.py`) for a self-contained repo.
6. **`setup.ps1`** for Windows alongside `setup.sh`.
7. **Deterministic paper smoke test** + **GitHub Actions CI** (lint + secret scan + smoke).
8. **`STRATEGY.md`** documenting the indicator math transparently and independently.
9. **`gitleaks`/`detect-secrets` secret scanning in BOTH pre-commit AND CI** + secrets hygiene for the public repo.

---

## 16. Deployment and delivery

- Docker + docker-compose (Python 3.11 base); one-command bring-up; Railway-ready (env-driven; any cloud token is
  supplied by the user at deploy time and never committed).
- Published to `github.com/cryptochucker/CryptoChucker-Agents`. At push time, switch active gh account with
  `gh auth switch --user cryptochucker` (already authenticated; scopes `repo`, `gist`, `read:org`).

---

## 17. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Money Line is not a literal clone of a closed-source indicator | Independently-implemented faithful equivalent; STRATEGY.md states this; no trademark claims |
| Pine `request.security` budget | Scanner capped at 30 by design; compile-verified against the full 30-symbol watchlist |
| New-script auto-add to chart unreliable (2026 UI) | Committed source + compile evidence + manual-save steps satisfy done |
| Secret leakage to public repo | `.gitignore` + gitleaks in pre-commit AND CI + history scan as a DoD item + names-only `.env.example` |
| Live trading risk | Fail-closed double gate (`PAPER_TRADING=false` AND `ENABLE_LIVE_TRADING=true`); safety tests; no creds in CI |
| Reusable code is TypeScript, not Python | Reference logic/architecture only (never secret values); Python is net-new but de-risked |
| Scope creep / endless refinement | Fixed definition of done (Section 1); stop when met |

---

## 18. Build stages summary

Stage 1 -> Gate 1: scaffolding + utils + Docker + pre-commit/CI secret scan.
Stage 2 -> Gate 2: signal engine + Money Line Pine.
Stage 3 -> Gate 3: scanner + alerts (chart image) + Money Scanner Pine.
Stage 4 -> Gate 4: paper executor + risk manager + fees + live-safety tests.
Stage 5 -> Gate 5: dashboard + backtester + LLM co-pilot (off).
Stage 6 -> Gate 6: orchestrator + end-to-end paper smoke test + README/CI + publish.

Each gate requires a Codex PASS. When Stage 6 passes and the definition of done is met, the build stops and the repo is
handed to the user for formal approval.

---

## 19. Gate 0 review resolution log (r1 -> r2)

| Codex finding (severity) | Resolution in r2 |
|---|---|
| Missing master "must include all" items (BLOCKING) | Added watchlist import/export (CSV/JSON), per-exchange fee calculator (`utils/fees.py`), and scanner alert chart image + link fallback to Sections 2, 6, 7. |
| Secrets handling too loose for public repo (BLOCKING) | New Section 11 secrets rules: names-only, never read/print/copy/commit values; gitleaks in pre-commit AND CI + history scan as a DoD item. Reworded Section 4 to "patterns only, never values". |
| Live-order safety underspecified (BLOCKING) | Section 11 fail-closed **double gate** (`PAPER_TRADING=false` AND `ENABLE_LIVE_TRADING=true`); guard error on direct live call; three safety tests; no creds in CI. Wired into Sections 1, 2, 7, 14. |
| TV "saved to account" over-asserted (MEDIUM) | DoD item 4 softened to compile-verified + committed source + compile evidence; live save best-effort with manual fallback (Section 8). |
| `request.security` "about 40" too loose (MEDIUM) | Scanner capped at **30 by design**; compile-verify against full 30-symbol watchlist (Section 8). |
| Walk-forward/Monte Carlo deferral vs brief (MEDIUM) | Marked an **approved scope reduction**; grid search is the Gate-0-accepted optimizer (Section 2). |
| `docs/mockup/` not in layout (MEDIUM) | Added `docs/` subtree to Section 6 layout. |
| "stage it in git" ambiguous (MEDIUM) | Section 14 clarified: review staged diffs, no secrets, MEDIUM/LOW recorded in BUILD_REPORT.md. |
| "all six stages" wording (LOW) | Changed to "Gates 0 through 6" (Section 1). |
| Live-run evidence unspecified (LOW) | DoD item 3 now names command, UTC timestamp, symbols, dashboard URL/status, artifacts. |
| STRATEGY.md independence/trademark (LOW) | Section 15.1 + 17 require independent-implementation wording, no trademark claims. |
| Items 2 and 9 add most risk (LOW) | Item 2 mitigated by fallback evidence; item 9 strengthened to pre-commit AND CI scanning. |
