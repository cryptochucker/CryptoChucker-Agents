"""
CryptoChucker Agents - Dashboard PROTOTYPE (design mockup only).

This is a throwaway visual prototype to validate the front-end UX before the real
build. It renders the real Streamlit + Plotly stack the product will use, with
synthetic mock data. No live data, no trading, no secrets.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# --------------------------------------------------------------------------- #
# Page + theme
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="CryptoChucker Agents",
    page_icon="🐊",
    layout="wide",
    initial_sidebar_state="expanded",
)

BULL = "#16c784"   # green
BEAR = "#ea3943"   # red
ACCENT = "#3b82f6" # blue
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

rng = np.random.default_rng(7)

# --------------------------------------------------------------------------- #
# Mock data
# --------------------------------------------------------------------------- #
@st.cache_data
def make_candles(n: int = 170, start: float = 61000.0) -> pd.DataFrame:
    drift = np.concatenate([
        np.full(60, 0.0009), np.full(45, -0.0016), np.full(65, 0.0017)
    ])[:n]
    rets = drift + rng.normal(0, 0.010, n)
    close = start * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = np.concatenate([[start], close[:-1]])
    vol = rng.uniform(800, 2600, n) * (1 + 0.5 * np.abs(rets) / 0.01)
    idx = pd.date_range("2026-05-01", periods=n, freq="4h")
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )
    tp = (df.high + df.low + df.close) / 3
    # volume-weighted smoothed trend line in price space: hugs the candles and
    # flips bull/bear with the trend (a stand-in for the real Money Line math).
    vwma = (tp * df.volume).rolling(8).sum() / df.volume.rolling(8).sum()
    df["money_line"] = vwma.ewm(span=14).mean().bfill()
    slope = df.money_line.diff().rolling(3).mean().fillna(0)
    df["state"] = np.where(slope >= 0, "BULL", "BEAR")
    df["flip"] = df.state.ne(df.state.shift())
    return df


def candle_fig(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df.open, high=df.high, low=df.low, close=df.close,
        increasing_line_color=BULL, decreasing_line_color=BEAR, name="BTC/USDT",
        increasing_fillcolor=BULL, decreasing_fillcolor=BEAR, opacity=0.9,
    ))
    bull = df.money_line.where(df.state.eq("BULL"))
    bear = df.money_line.where(df.state.eq("BEAR"))
    fig.add_trace(go.Scatter(x=df.index, y=bull, mode="lines",
                             line=dict(color=BULL, width=2.6), name="Money Line (bull)"))
    fig.add_trace(go.Scatter(x=df.index, y=bear, mode="lines",
                             line=dict(color=BEAR, width=2.6), name="Money Line (bear)"))
    flips = df[df.flip]
    for ts, row in flips.iterrows():
        up = row.state == "BULL"
        fig.add_trace(go.Scatter(
            x=[ts], y=[row.money_line], mode="markers",
            marker=dict(symbol="triangle-up" if up else "triangle-down",
                        size=14, color=BULL if up else BEAR,
                        line=dict(color="#0b0f17", width=1)),
            showlegend=False, hovertext=f"{row.state} flip", hoverinfo="text",
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


def equity_fig() -> go.Figure:
    n = 90
    base = np.linspace(10000, 12480, n)
    noise = np.cumsum(rng.normal(0, 60, n))
    eq = base + noise - noise[0]
    eq[40:52] -= np.linspace(0, 380, 12)  # a drawdown
    idx = pd.date_range("2026-03-09", periods=n, freq="D")
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
    fig.update_yaxes(range=[9600, eq.max() * 1.01], gridcolor="#161d2b", tickprefix="$")
    fig.update_xaxes(gridcolor="#161d2b")
    return fig


SCANNER = pd.DataFrame([
    ("SOL/USDT", "4h", "BULL", 86, "12m", 2.9, 168.40),
    ("WIF/USDT", "1h", "BULL", 81, "8m", 3.4, 2.14),
    ("INJ/USDT", "4h", "BULL", 78, "21m", 2.1, 27.85),
    ("TIA/USDT", "1h", "BULL", 74, "5m", 2.6, 9.42),
    ("ARB/USDT", "4h", "BULL", 69, "34m", 1.8, 1.18),
    ("ETH/USDT", "4h", "BEAR", 72, "17m", 2.2, 3120.0),
    ("LINK/USDT", "1h", "BEAR", 66, "9m", 1.9, 18.30),
    ("AVAX/USDT", "4h", "BULL", 63, "41m", 1.6, 41.20),
    ("OP/USDT", "1h", "BEAR", 61, "26m", 1.7, 2.41),
    ("SEI/USDT", "4h", "BULL", 58, "53m", 1.5, 0.612),
    ("DOGE/USDT", "4h", "BULL", 77, "3m", 2.8, 0.0991),
    ("BTC/USDT", "4h", "BULL", 70, "1m", 1.9, 66120.0),
], columns=["Symbol", "TF", "State", "Strength", "Flip Age", "Vol x avg", "Price"])

POSITIONS = pd.DataFrame([
    ("DOGE/USDT", "LONG 10x", 0.09664, 0.0991, 250.0, 6.5, "1d 4h"),
    ("SOL/USDT", "LONG", 161.20, 168.40, 300.0, 4.5, "9h"),
    ("ETH/USDT", "SHORT", 3185.0, 3120.0, 200.0, 2.0, "5h"),
], columns=["Symbol", "Side", "Entry", "Mark", "Size $", "P&L %", "Age"])

ALERTS = [
    (BULL, "21:46", "🟢 BULLISH flip  SOL/USDT 4h  str 86  vol 2.9x"),
    (BULL, "21:44", "🟢 BULLISH flip  DOGE/USDT 4h  str 77  vol 2.8x"),
    (ACCENT, "21:41", "📈 PAPER FILL  SOL/USDT LONG @ 161.20  size $300"),
    (BEAR, "21:38", "🔴 BEARISH flip  ETH/USDT 4h  str 72  vol 2.2x"),
    (MUTE, "21:35", "🔎 Scanner pass complete  127 symbols  7 flips"),
]

LOGS = """2026-06-07 21:46:02 | INFO     | scanner_agent  | pass complete: 127 symbols in 3.1s, 7 flips
2026-06-07 21:46:02 | SUCCESS  | signal_agent   | SOL/USDT 4h -> BULL (strength=86)
2026-06-07 21:44:55 | INFO     | alert_agent    | telegram + discord delivered (2 channels)
2026-06-07 21:41:10 | SUCCESS  | executor_agent | PAPER fill SOL/USDT LONG 300.0 @ 161.20
2026-06-07 21:41:10 | INFO     | risk_manager   | size ok: 2.4% equity, exposure 6.0%/15% cap
2026-06-07 21:38:31 | WARNING  | signal_agent   | ETH/USDT 4h -> BEAR (strength=72)
2026-06-07 21:35:00 | INFO     | data_fetcher   | ohlcv refreshed (ccxt:blofin, 1m rate-limit ok)"""


def strength_bar(v: int, color: str) -> str:
    return f'<div class="bar"><span style="width:{v}%;background:{color}"></span></div>'


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown('<p class="brand">🐊 CryptoChucker</p>', unsafe_allow_html=True)
    st.markdown('<p class="brand-sub">Personal Trading Suite</p>', unsafe_allow_html=True)
    st.markdown('<span class="pill pill-paper">● PAPER MODE</span>', unsafe_allow_html=True)
    st.markdown("")
    st.markdown("**Agents**")
    st.toggle("Signal engine", value=True)
    st.toggle("Scanner", value=True)
    st.toggle("Executor (paper)", value=True)
    st.toggle("Alerts", value=True)
    st.toggle("LLM co-pilot", value=False, help="Optional signal validator (off by default)")
    st.divider()
    st.selectbox("Exchange", ["BloFin", "Binance", "Bybit", "Kraken", "Coinbase"], index=0)
    st.selectbox("Primary timeframe", ["15m", "1h", "4h", "1D"], index=2)
    st.selectbox("Confirmation TF", ["1h", "4h", "1D"], index=1)
    st.slider("Scan interval (min)", 1, 15, 5)
    st.divider()
    st.button("⛔  Emergency stop all", use_container_width=True)

# --------------------------------------------------------------------------- #
# Header + KPIs
# --------------------------------------------------------------------------- #
left, right = st.columns([0.7, 0.3])
with left:
    st.markdown("### CryptoChucker Agents")
    st.markdown(
        f'<span style="color:{MUTE};font-size:.85rem">'
        f'<span class="dot" style="background:{BULL}"></span>LIVE (paper)  ·  '
        f'updated 21:46:04  ·  exchange BloFin  ·  watchlist 127</span>',
        unsafe_allow_html=True,
    )
with right:
    st.markdown(
        '<div style="text-align:right"><span class="pill pill-paper">'
        'No capital at risk</span></div>', unsafe_allow_html=True)

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Account equity", "$12,480", "+3.2%")
k2.metric("Today's P&L", "+$184", "+1.5%")
k3.metric("Open positions", "3", "paper")
k4.metric("Win rate (30d)", "64%", "+4%")
k5.metric("Active signals", "7", "+2")

tab_overview, tab_scanner, tab_backtest = st.tabs(["📊  Overview", "🔎  Scanner", "🧪  Backtest"])

# --------------------------------------------------------------------------- #
# Overview
# --------------------------------------------------------------------------- #
with tab_overview:
    c_chart, c_sigs = st.columns([0.68, 0.32])
    with c_chart:
        st.markdown("#### BTC/USDT · 4h · Money Line")
        st.plotly_chart(candle_fig(make_candles()), use_container_width=True,
                        config={"displayModeBar": False})
    with c_sigs:
        st.markdown("#### Top signals")
        top = SCANNER.sort_values("Strength", ascending=False).head(5)
        for _, r in top.iterrows():
            color = BULL if r.State == "BULL" else BEAR
            st.markdown(
                f'<div class="sig-card"><span class="sig-sym">{r.Symbol}</span>'
                f'<span style="float:right;color:{color};font-weight:700">{r.State}</span>'
                f'<div class="sig-meta">{r.TF} · {r["Flip Age"]} ago · vol {r["Vol x avg"]}x</div>'
                f'{strength_bar(int(r.Strength), color)}'
                f'<div class="sig-meta" style="margin-top:3px">strength {r.Strength}/100</div>'
                f'</div>', unsafe_allow_html=True)

    st.markdown("#### Equity curve (paper)")
    st.plotly_chart(equity_fig(), use_container_width=True, config={"displayModeBar": False})

    c_pos, c_alert = st.columns([0.62, 0.38])
    with c_pos:
        st.markdown("#### Open positions")
        sty = POSITIONS.style.map(
            lambda v: f"color:{BULL}" if isinstance(v, (int, float)) and v >= 0 else f"color:{BEAR}",
            subset=["P&L %"],
        ).format({"Entry": "{:.5f}", "Mark": "{:.5f}", "Size $": "{:.0f}", "P&L %": "{:+.1f}%"})
        st.dataframe(sty, use_container_width=True, hide_index=True)
    with c_alert:
        st.markdown("#### Recent alerts")
        for color, t, msg in ALERTS:
            st.markdown(
                f'<div class="alert-row" style="border-left-color:{color}">'
                f'<span style="color:{MUTE}">{t}</span>&nbsp;&nbsp;{msg}</div>',
                unsafe_allow_html=True)

    with st.expander("Live logs  (loguru)", expanded=False):
        st.code(LOGS, language="log")

# --------------------------------------------------------------------------- #
# Scanner
# --------------------------------------------------------------------------- #
with tab_scanner:
    f1, f2, f3 = st.columns([0.25, 0.25, 0.5])
    f1.selectbox("State filter", ["All", "BULL only", "BEAR only"])
    f2.slider("Min strength", 0, 100, 55)
    f3.text_input("Search symbol", placeholder="e.g. SOL")
    st.markdown("#### Scanner results · 127 symbols · 7 fresh flips")

    def color_state(v):
        return f"color:{BULL};font-weight:700" if v == "BULL" else f"color:{BEAR};font-weight:700"

    def strength_bg(v):
        a = max(0.0, min(1.0, (v - 40) / 60))
        return f"background-color: rgba(22,199,132,{0.12 + a * 0.5:.2f}); color:#eaf2ff"

    sc = SCANNER.sort_values("Strength", ascending=False)
    sty = (sc.style
           .map(color_state, subset=["State"])
           .map(strength_bg, subset=["Strength"])
           .format({"Price": "{:,.4f}", "Vol x avg": "{:.1f}x"}))
    st.dataframe(sty, use_container_width=True, hide_index=True, height=460)

# --------------------------------------------------------------------------- #
# Backtest
# --------------------------------------------------------------------------- #
with tab_backtest:
    b1, b2, b3, b4 = st.columns(4)
    b1.selectbox("Symbol", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    b2.selectbox("Timeframe", ["1h", "4h", "1D"], index=1)
    b3.slider("Money Line span", 8, 50, 21)
    b4.slider("Profit target %", 1, 20, 6)
    st.button("▶  Run backtest", type="primary")

    st.markdown("#### Results · BTC/USDT 4h · 2024-01 → 2026-06")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Sharpe", "1.84")
    m2.metric("Sortino", "2.41")
    m3.metric("Max drawdown", "-11.3%")
    m4.metric("Win rate", "61%")
    m5.metric("Profit factor", "1.92")
    st.plotly_chart(equity_fig(), use_container_width=True, config={"displayModeBar": False})
    st.caption("Mockup values. The real backtester runs on vectorbt and exports CSV + this equity curve.")

st.caption("⚠  Design mockup with synthetic data. Not the product build; no live data or trading.")
