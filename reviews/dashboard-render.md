# Dashboard runtime render verification (Stage 5)

The real Streamlit dashboard (`agents/dashboard.py`) was launched headless against an EMPTY store and its rendered DOM
was queried (screenshotting Streamlit via the headless tool times out on the persistent websocket; querying the
rendered text is the authoritative check, per the "validate runtime, not just compile" rule).

- Server: `streamlit run agents/dashboard.py` on 127.0.0.1:8534. Server logs: no Python traceback (only cosmetic
  `use_container_width` deprecation warnings).
- Rendered DOM: `document.title == "CryptoChucker Agents"`, `hasError == false` (no Traceback/Exception/Error text).
- Rendered content (empty store): sidebar (brand, PAPER MODE pill, agent toggles incl. LLM co-pilot, BloFin exchange,
  timeframes, scan interval, emergency stop); KPI cards (Account equity $10,000 +0.0%, Today's P&L $+0, Open positions 0,
  Win rate 0% / 0 trades, Active signals 0); Overview / Scanner / Backtest tabs; BTC/USDT 4h Money Line chart.

Controller fix applied: added a `sys.path` bootstrap at the top of `agents/dashboard.py` so the lazy
`from utils.store import Store` / `from agents.signal_agent import get_money_line` imports resolve regardless of the
cwd `streamlit run` uses (streamlit puts the script's own dir on `sys.path`, not the package root).

A populated-store screenshot is captured in Stage 6 after the end-to-end paper smoke run writes real rows.
