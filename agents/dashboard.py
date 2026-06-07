"""CryptoChucker Agents - Real Streamlit Dashboard (Task 5.4).

Ported from the approved design mockup at docs/mockup/app.py.
Reads live data from utils.store.Store (signals, positions, trades, equity, scans).
Uses agents.signal_agent.get_money_line for the candlestick+Money Line chart.
Guards for empty store (fresh DB) so it renders without data.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Ensure the repo root is importable no matter how streamlit launches this script
# (streamlit puts the script's own dir on sys.path, not the package root), so the
# lazy `from utils.store import Store` / `from agents...` imports below resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Page config (must be first Streamlit call)
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="CryptoChucker Agents",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Theme tokens (matching approved mockup)
# ---------------------------------------------------------------------------
BULL = "#16c784"
BEAR = "#ea3943"
ACCENT = "#3b82f6"
MUTE = "#8b95a7"
CARD = "#121722"
BG = "#0b0f17"

st.markdown(
    f"""
    <style>
      .stApp {{ background: radial-gradient(1200px 600px at 80% -10%, #16203020, {BG} 55%); }}
      #MainMenu, header, footer {{ visibility: hidden; }}
      .block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1500px; }}
      section[data-testid="stSidebar"] {{ background: #0d1320; border-right: 1px solid #1c2536; }}
      div[data-testid="stMetric"] {{
          background: {CARD}; border: 1px solid #1f2a3c; border-radius: 14px;
          padding: 14px 16px 10px 16px;
      }}
      div[data-testid="stMetricLabel"] p {{ color: {MUTE}; font-size: 0.78rem; letter-spacing:.02em; }}
      .pill {{ display:inline-block; padding:3px 10px; border-radius:999px; font-size:.72rem;
               font-weight:700; letter-spacing:.03em; }}
      .pill-paper {{ background:#0f2e22; color:{BULL}; border:1px solid #1c5c45; }}
      .pill-live  {{ background:#2e0f12; color:{BEAR}; border:1px solid #5c1c22; }}
      .brand {{ font-size:1.35rem; font-weight:800; margin-bottom:0; }}
      .brand-sub {{ color:{MUTE}; font-size:.78rem; margin-top:-4px; }}
      .sig-card {{ background:{CARD}; border:1px solid #1f2a3c; border-radius:12px;
                  padding:10px 12px; margin-bottom:8px; }}
      .sig-sym {{ font-weight:700; font-size:.95rem; }}
      .sig-meta {{ color:{MUTE}; font-size:.74rem; }}
      .bar {{ height:6px; border-radius:4px; background:#1f2a3c; margin-top:6px; overflow:hidden; }}
      .bar > span {{ display:block; height:100%; }}
      .alert-row {{ border-left:3px solid #1f2a3c; padding:4px 10px; margin-bottom:6px;
                    font-size:.82rem; }}
      .dot {{ height:9px; width:9px; border-radius:50%; display:inline-block; margin-right:6px; }}
      h3 {{ margin-top:.2rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Config + store
# ---------------------------------------------------------------------------


@st.cache_resource
def _get_store():
    """Return an initialised Store instance."""
    from utils.store import Store

    db_path = os.environ.get("STORE_PATH", "data/cryptochucker.db")
    s = Store(path=db_path)
    try:
        s.init()
    except Exception:
        pass
    return s


@st.cache_resource
def _get_config():
    """Load config.yaml if present, else return defaults."""
    try:
        from utils.config_schema import load_config

        return load_config("config.yaml")
    except Exception:
        from utils.config_schema import Config

        return Config()


store = _get_store()
cfg = _get_config()
paper = cfg.paper_trading

# ---------------------------------------------------------------------------
# Data loaders (guarded against empty store)
# ---------------------------------------------------------------------------


def _load_signals(limit: int = 200) -> list[dict]:
    try:
        return store.load_signals(limit=limit)
    except Exception:
        return []


def _load_positions() -> list[dict]:
    try:
        return store.load_positions(status="open")
    except Exception:
        return []


def _load_trades(limit: int = 500) -> list[dict]:
    try:
        return store.load_trades(limit=limit)
    except Exception:
        return []


def _load_equity(limit: int = 1000) -> list[dict]:
    try:
        return store.load_equity(limit=limit)
    except Exception:
        return []


def _load_scans(limit: int = 50) -> list[dict]:
    try:
        return store.load_scans(limit=limit)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------


@st.cache_data(ttl=60)
def _fetch_ohlcv(exchange: str, symbol: str, tf: str, limit: int = 200) -> pd.DataFrame | None:
    """Fetch real OHLCV via DataFetcher, cached for 60 s.

    Returns None on any failure so callers can show an empty-state message
    instead of crashing.
    """
    try:
        from utils.data_fetcher import DataFetcher

        fetcher = DataFetcher(exchange=exchange.lower())
        return fetcher.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
    except Exception:
        return None


def _make_money_line_df(
    symbol: str = "BTC/USDT",
    tf: str = "4h",
    exchange: str = "blofin",
    n: int = 200,
) -> pd.DataFrame | None:
    """Return a real OHLCV + Money Line DataFrame.

    Fetches via DataFetcher (cached 60 s).  Returns None when the exchange
    is unreachable or returns no data so the caller can render an empty state
    instead of fabricated candles.
    """
    raw_df = _fetch_ohlcv(exchange, symbol, tf, limit=n)
    if raw_df is None or raw_df.empty:
        return None

    from agents.signal_agent import get_money_line

    ml = get_money_line(
        raw_df,
        length=cfg.signal.money_line_length,
        smooth=cfg.signal.smooth,
        slope_len=cfg.signal.slope_len,
    )
    return ml


def _candle_fig(df: pd.DataFrame, symbol: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color=BULL, decreasing_line_color=BEAR, name=symbol,
        increasing_fillcolor=BULL, decreasing_fillcolor=BEAR, opacity=0.9,
    ))
    bull_ml = df["money_line"].where(df["state"] == "BULLISH")
    bear_ml = df["money_line"].where(df["state"] == "BEARISH")
    fig.add_trace(go.Scatter(
        x=df.index, y=bull_ml, mode="lines",
        line=dict(color=BULL, width=2.6), name="Money Line (bull)",
    ))
    fig.add_trace(go.Scatter(
        x=df.index, y=bear_ml, mode="lines",
        line=dict(color=BEAR, width=2.6), name="Money Line (bear)",
    ))
    flips = df[df["flip_detected"]]
    for ts, row in flips.iterrows():
        up = row["state"] == "BULLISH"
        fig.add_trace(go.Scatter(
            x=[ts], y=[row["money_line"]], mode="markers",
            marker=dict(
                symbol="triangle-up" if up else "triangle-down",
                size=14, color=BULL if up else BEAR,
                line=dict(color="#0b0f17", width=1),
            ),
            showlegend=False,
            hovertext=f"{'BULL' if up else 'BEAR'} flip",
            hoverinfo="text",
        ))
    fig.update_layout(
        template="plotly_dark", height=430, margin=dict(l=8, r=8, t=10, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.04, x=0),
        font=dict(color="#c7d0de"),
    )
    fig.update_xaxes(gridcolor="#161d2b")
    fig.update_yaxes(gridcolor="#161d2b")
    return fig


def _equity_fig(equity_rows: list[dict], initial: float = 10_000.0) -> go.Figure:
    """Build an equity-curve chart from stored equity rows.

    When there are no stored rows the chart shows a flat line at *initial*
    (account balance).  No synthetic random data is ever generated.
    """
    if equity_rows:
        eq_df = pd.DataFrame(equity_rows[::-1])
        try:
            idx = pd.to_datetime(eq_df["ts"])
        except Exception:
            idx = pd.RangeIndex(len(eq_df))
        eq = eq_df["balance"].astype(float)
    else:
        # Empty store: show a flat reference line at the configured balance.
        idx = pd.to_datetime(
            [datetime.now(tz=timezone.utc).isoformat()]
        )
        eq = pd.Series([initial])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=idx, y=eq, mode="lines", line=dict(color=ACCENT, width=2),
        fill="tozeroy", fillcolor="rgba(59,130,246,0.12)", name="Equity",
    ))
    fig.update_layout(
        template="plotly_dark", height=240, margin=dict(l=8, r=8, t=10, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#c7d0de"), showlegend=False,
    )
    try:
        y_max = float(eq.max()) * 1.01
        y_min = min(float(eq.min()) * 0.97, initial * 0.96)
        fig.update_yaxes(range=[y_min, y_max], gridcolor="#161d2b", tickprefix="$")
    except Exception:
        fig.update_yaxes(gridcolor="#161d2b", tickprefix="$")
    fig.update_xaxes(gridcolor="#161d2b")
    return fig


def _strength_bar(v: int, color: str) -> str:
    return f'<div class="bar"><span style="width:{v}%;background:{color}"></span></div>'


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<p class="brand">CryptoChucker</p>', unsafe_allow_html=True)
    st.markdown('<p class="brand-sub">Personal Trading Suite</p>', unsafe_allow_html=True)
    pill_cls = "pill-paper" if paper else "pill-live"
    pill_label = "PAPER MODE" if paper else "LIVE MODE"
    st.markdown(f'<span class="pill {pill_cls}">{"o"} {pill_label}</span>', unsafe_allow_html=True)
    st.markdown("")
    st.markdown("**Agents**")
    st.toggle("Signal engine", value=True)
    st.toggle("Scanner", value=True)
    st.toggle("Executor (paper)" if paper else "Executor (live)", value=True)
    st.toggle("Alerts", value=True)
    st.toggle("LLM co-pilot", value=cfg.llm_copilot.enabled, help="Optional signal validator (off by default)")
    st.divider()

    exchange_opts = ["BloFin", "Binance", "Bybit", "Kraken", "Coinbase"]
    exchange_default = {
        "blofin": 0, "binance": 1, "bybit": 2, "kraken": 3, "coinbase": 4,
    }.get(cfg.exchange.lower(), 0)
    sel_exchange = st.selectbox("Exchange", exchange_opts, index=exchange_default)
    sel_tf = st.selectbox("Primary timeframe", ["15m", "1h", "4h", "1D"], index=2)
    sel_confirm_tf = st.selectbox("Confirmation TF", ["1h", "4h", "1D"], index=1)
    st.slider("Scan interval (min)", 1, 15, cfg.scanner.interval_minutes)
    st.divider()
    emergency = st.button("Emergency stop all", use_container_width=True)
    if emergency:
        st.error("Emergency stop triggered. All agents halted.")

# ---------------------------------------------------------------------------
# Load data (after sidebar selection, before rendering)
# ---------------------------------------------------------------------------
signals_raw = _load_signals()
positions_raw = _load_positions()
trades_raw = _load_trades()
equity_raw = _load_equity()
scans_raw = _load_scans()

# KPI derivations
current_equity = equity_raw[0]["balance"] if equity_raw else cfg.risk.account_balance
prev_equity = equity_raw[-1]["balance"] if len(equity_raw) > 1 else current_equity
equity_delta_pct = (current_equity - prev_equity) / prev_equity * 100 if prev_equity else 0
n_open = len(positions_raw)
n_signals = len([s for s in signals_raw if s.get("state") == "BULLISH"])

wins = [t for t in trades_raw if (t.get("pnl") or 0) > 0]
win_rate_pct = int(len(wins) / len(trades_raw) * 100) if trades_raw else 0

today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
today_pnl = sum(
    (t.get("pnl") or 0)
    for t in trades_raw
    if (t.get("closed_at") or "").startswith(today_str)
)

# ---------------------------------------------------------------------------
# Header + KPIs
# ---------------------------------------------------------------------------
left, right = st.columns([0.7, 0.3])
with left:
    st.markdown("### CryptoChucker Agents")
    now_str = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
    st.markdown(
        f'<span style="color:{MUTE};font-size:.85rem">'
        f'<span class="dot" style="background:{BULL}"></span>'
        f'{"LIVE (paper)" if paper else "LIVE"}  &middot;  '
        f'updated {now_str}  &middot;  exchange {sel_exchange}</span>',
        unsafe_allow_html=True,
    )
with right:
    pill_cls = "pill-paper" if paper else "pill-live"
    label = "No capital at risk" if paper else "LIVE TRADING"
    st.markdown(
        f'<div style="text-align:right"><span class="pill {pill_cls}">'
        f'{label}</span></div>',
        unsafe_allow_html=True,
    )

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Account equity", f"${current_equity:,.0f}", f"{equity_delta_pct:+.1f}%")
k2.metric("Today's P&L", f"${today_pnl:+,.0f}", "paper" if paper else "live")
k3.metric("Open positions", str(n_open), "paper" if paper else "live")
k4.metric("Win rate (all-time)", f"{win_rate_pct}%", f"{len(trades_raw)} trades")
k5.metric("Active signals", str(n_signals), "BULL" if n_signals > 0 else "--")

tab_overview, tab_scanner, tab_backtest = st.tabs(["Overview", "Scanner", "Backtest"])

# ---------------------------------------------------------------------------
# Overview tab
# ---------------------------------------------------------------------------
with tab_overview:
    c_chart, c_sigs = st.columns([0.68, 0.32])

    with c_chart:
        st.markdown(f"#### BTC/USDT  {sel_tf}  Money Line")
        if st.button("Load live chart", key="load_live_chart"):
            st.session_state["live_chart_requested"] = True
        if st.session_state.get("live_chart_requested"):
            ml_df = _make_money_line_df(
                symbol="BTC/USDT",
                tf=sel_tf,
                exchange=cfg.exchange,
            )
            if ml_df is not None:
                try:
                    st.plotly_chart(
                        _candle_fig(ml_df, "BTC/USDT"),
                        use_container_width=True,
                        config={"displayModeBar": False},
                    )
                except Exception as exc:
                    st.info(f"Chart render error: {exc}")
            else:
                st.info("No chart data available. Check exchange connectivity.")
        else:
            st.info("Click 'Load live chart' to fetch live OHLCV.")

    with c_sigs:
        st.markdown("#### Top signals")
        if signals_raw:
            top = signals_raw[:5]
            for row in top:
                state = row.get("state", "BEARISH")
                color = BULL if state == "BULLISH" else BEAR
                sym = row.get("symbol", "?")
                tf = row.get("tf", "?")
                strength = int(row.get("strength") or 0)
                price = row.get("price") or 0
                st.markdown(
                    f'<div class="sig-card">'
                    f'<span class="sig-sym">{sym}</span>'
                    f'<span style="float:right;color:{color};font-weight:700">{state}</span>'
                    f'<div class="sig-meta">{tf} &middot; ${price:,.4f}</div>'
                    f'{_strength_bar(strength, color)}'
                    f'<div class="sig-meta" style="margin-top:3px">strength {strength}/100</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No signals yet. Run the scanner to populate.")

    st.markdown("#### Equity curve (paper)" if paper else "#### Equity curve")
    st.plotly_chart(_equity_fig(equity_raw, cfg.risk.account_balance),
                    use_container_width=True, config={"displayModeBar": False})

    c_pos, c_alert = st.columns([0.62, 0.38])

    with c_pos:
        st.markdown("#### Open positions")
        if positions_raw:
            pos_df = pd.DataFrame(positions_raw)[
                ["symbol", "mode", "side", "entry_price", "qty", "opened_at"]
            ].rename(columns={
                "symbol": "Symbol", "mode": "Mode", "side": "Side",
                "entry_price": "Entry", "qty": "Qty", "opened_at": "Opened",
            })
            st.dataframe(pos_df, use_container_width=True, hide_index=True)
        else:
            st.info("No open positions.")

    with c_alert:
        st.markdown("#### Recent signals")
        if signals_raw:
            for row in signals_raw[:8]:
                state = row.get("state", "BEARISH")
                color = BULL if state == "BULLISH" else BEAR
                sym = row.get("symbol", "?")
                tf = row.get("tf", "?")
                ts = str(row.get("ts", ""))[:16]
                st.markdown(
                    f'<div class="alert-row" style="border-left-color:{color}">'
                    f'<span style="color:{MUTE}">{ts}</span>&nbsp;&nbsp;'
                    f'{state} {sym} {tf}</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.info("No recent signals.")

# ---------------------------------------------------------------------------
# Scanner tab
# ---------------------------------------------------------------------------
with tab_scanner:
    f1, f2, f3 = st.columns([0.25, 0.25, 0.5])
    state_filter = f1.selectbox("State filter", ["All", "BULL only", "BEAR only"])
    min_strength = f2.slider("Min strength", 0, 100, int(cfg.scanner.min_strength))
    search_sym = f3.text_input("Search symbol", placeholder="e.g. SOL")

    # Prefer stored scan rows; fall back to signal rows when scans are absent.
    if scans_raw:
        st.markdown("#### Stored scans")
        # Decode JSON payload column into flattened fields.
        # Store.save_scan() stores arbitrary dicts as JSON in the `payload` column.
        # Each row may contain {symbol, tf, state, strength, price} inside payload.
        import json as _json
        decoded_rows: list[dict] = []
        for row in scans_raw:
            base = dict(row)
            raw_payload = base.pop("payload", None)
            if raw_payload:
                try:
                    payload_obj = _json.loads(raw_payload)
                except Exception:
                    payload_obj = {}
                if isinstance(payload_obj, dict):
                    for field in ("symbol", "tf", "state", "strength", "price"):
                        if field not in base and field in payload_obj:
                            base[field] = payload_obj[field]
            decoded_rows.append(base)
        scan_df = pd.DataFrame(decoded_rows)
        # Rename common scan columns; tolerate varying schema from store
        scan_df = scan_df.rename(columns={
            "symbol": "Symbol", "tf": "TF", "state": "State",
            "strength": "Strength", "price": "Price", "ts": "Timestamp",
            "scanned_at": "Timestamp",
        })
        if "State" in scan_df.columns:
            scan_df["State"] = (
                scan_df["State"].astype(str).str.upper()
                .str.replace("BULLISH", "BULL", regex=False)
                .str.replace("BEARISH", "BEAR", regex=False)
            )
            if state_filter == "BULL only":
                scan_df = scan_df[scan_df["State"] == "BULL"]
            elif state_filter == "BEAR only":
                scan_df = scan_df[scan_df["State"] == "BEAR"]
        if min_strength > 0 and "Strength" in scan_df.columns:
            scan_df = scan_df[scan_df["Strength"].fillna(0) >= min_strength]
        if search_sym and "Symbol" in scan_df.columns:
            scan_df = scan_df[scan_df["Symbol"].str.contains(search_sym.upper(), na=False)]

        show_cols = [c for c in ["Symbol", "TF", "State", "Strength", "Price", "Timestamp"] if c in scan_df.columns]
        if show_cols:
            scan_df = scan_df[show_cols]
        if "Strength" in scan_df.columns:
            scan_df = scan_df.sort_values("Strength", ascending=False)

        def _color_state(v: str) -> str:
            return f"color:{BULL};font-weight:700" if "BULL" in str(v) else f"color:{BEAR};font-weight:700"

        state_col = ["State"] if "State" in scan_df.columns else []
        sty = scan_df.style.map(_color_state, subset=state_col)
        st.dataframe(sty, use_container_width=True, hide_index=True, height=460)
        st.caption(f"{len(scan_df)} scan rows shown")

    elif signals_raw:
        st.markdown("#### Scanner results (from signals)")
        sc_df = pd.DataFrame(signals_raw)
        sc_df = sc_df.rename(columns={
            "symbol": "Symbol", "tf": "TF", "state": "State",
            "strength": "Strength", "price": "Price", "ts": "Timestamp",
        })
        if "State" in sc_df.columns:
            sc_df["State"] = (
                sc_df["State"].astype(str).str.upper()
                .str.replace("BULLISH", "BULL", regex=False)
                .str.replace("BEARISH", "BEAR", regex=False)
            )
            if state_filter == "BULL only":
                sc_df = sc_df[sc_df["State"] == "BULL"]
            elif state_filter == "BEAR only":
                sc_df = sc_df[sc_df["State"] == "BEAR"]
        if min_strength > 0 and "Strength" in sc_df.columns:
            sc_df = sc_df[sc_df["Strength"].fillna(0) >= min_strength]
        if search_sym and "Symbol" in sc_df.columns:
            sc_df = sc_df[sc_df["Symbol"].str.contains(search_sym.upper(), na=False)]

        show_cols = [c for c in ["Symbol", "TF", "State", "Strength", "Price", "Timestamp"] if c in sc_df.columns]
        sc_df = sc_df[show_cols].sort_values("Strength", ascending=False) if "Strength" in sc_df.columns else sc_df[show_cols]

        def _color_state_sig(v: str) -> str:
            return f"color:{BULL};font-weight:700" if "BULL" in str(v) else f"color:{BEAR};font-weight:700"

        sty = sc_df.style.map(_color_state_sig, subset=["State"] if "State" in sc_df.columns else [])
        st.dataframe(sty, use_container_width=True, hide_index=True, height=460)
        st.caption(f"{len(sc_df)} rows shown")
    else:
        st.info("Scanner has not run yet. No scan or signal data in the store.")

# ---------------------------------------------------------------------------
# Backtest tab
# ---------------------------------------------------------------------------
with tab_backtest:
    b1, b2, b3, b4 = st.columns(4)
    bt_sym = b1.selectbox("Symbol", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    bt_tf = b2.selectbox("Timeframe", ["1h", "4h", "1D"], index=1)
    bt_ml = b3.slider("Money Line span", 4, 50, cfg.signal.money_line_length)
    bt_smooth = b4.slider("EMA smooth", 5, 50, cfg.signal.smooth)

    run_bt = st.button("Run backtest", type="primary")

    if run_bt or "bt_result" in st.session_state:
        if run_bt:
            with st.spinner("Running backtest..."):
                try:
                    from agents.backtester import run_backtest

                    bt_raw = _fetch_ohlcv(cfg.exchange, bt_sym, bt_tf, limit=300)
                    if bt_raw is None or bt_raw.empty:
                        st.error("No OHLCV data available for the selected symbol/timeframe.")
                        st.session_state.pop("bt_result", None)
                    else:
                        result = run_backtest(
                            bt_raw,
                            initial_capital=cfg.risk.account_balance,
                            freq=bt_tf,
                            money_line_length=bt_ml,
                            smooth=bt_smooth,
                            slope_len=cfg.signal.slope_len,
                        )
                        st.session_state["bt_result"] = result
                except Exception as exc:
                    st.error(f"Backtest error: {exc}")
                    st.session_state.pop("bt_result", None)

        result = st.session_state.get("bt_result")
        if result is not None:
            st.markdown(f"#### Results  {bt_sym}  {bt_tf}")
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("Sharpe", f"{result.sharpe:.2f}")
            m2.metric("Sortino", f"{result.sortino:.2f}")
            dd_pct = result.max_drawdown * 100
            m3.metric("Max drawdown", f"{dd_pct:.1f}%")
            m4.metric("Win rate", f"{result.win_rate * 100:.0f}%")
            pf = result.profit_factor
            m5.metric("Profit factor", f"{pf:.2f}" if pf != float("inf") else "inf")

            eq_rows = [
                {"ts": str(ts), "balance": float(val)}
                for ts, val in result.equity_curve.items()
            ]
            st.plotly_chart(
                _equity_fig(eq_rows[::-1], cfg.risk.account_balance),
                use_container_width=True,
                config={"displayModeBar": False},
            )

            if not result.trades.empty:
                with st.expander(f"Trade log ({len(result.trades)} trades)"):
                    fmt = {
                        "entry_price": "{:.4f}", "exit_price": "{:.4f}",
                        "return": "{:+.2%}", "pnl": "${:+.2f}",
                    }
                    st.dataframe(
                        result.trades.style.format(
                            {k: v for k, v in fmt.items() if k in result.trades.columns}
                        ),
                        use_container_width=True, hide_index=True,
                    )

            dl_col, _ = st.columns([0.2, 0.8])
            with dl_col:
                csv_bytes = result.equity_curve.to_csv(header=["balance"]).encode()
                st.download_button(
                    "Download equity CSV",
                    data=csv_bytes,
                    file_name=f"equity_{bt_sym.replace('/', '')}_{bt_tf}.csv",
                    mime="text/csv",
                )
    else:
        st.info("Configure parameters above and click Run backtest.")
