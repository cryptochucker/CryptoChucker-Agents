"""Money Line signal engine.

Independent implementation of a volume-weighted, EMA-smoothed trend-line that
classifies market state as BULLISH or BEARISH and emits flip signals.

No pandas_ta dependency: ATR and MFI are computed directly via pandas rolling
arithmetic, which is equivalent to the pandas_ta implementations for the purposes
of this indicator. See STRATEGY.md for the full math explanation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Internal helpers (pure pandas, no external TA library required)
# ---------------------------------------------------------------------------


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average True Range computed with pandas ewm (Wilder's smoothing = span=length)."""
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder smoothing: ewm with alpha = 1/length
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


def _mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    length: int = 14,
) -> pd.Series:
    """Money Flow Index (0-100) computed directly from price/volume data."""
    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    direction = tp.diff()
    pos_mf = raw_mf.where(direction > 0, 0.0)
    neg_mf = raw_mf.where(direction < 0, 0.0)
    pos_sum = pos_mf.rolling(length).sum()
    neg_sum = neg_mf.rolling(length).sum().abs()
    mfr = pos_sum / neg_sum.replace(0, np.nan)
    return (100 - 100 / (1 + mfr)).fillna(50.0)


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index (0-100) with Wilder smoothing."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
    """Average Directional Index (0-100) indicating trend strength."""
    atr = _atr(high, low, close, length)
    up_move = high.diff()
    down_move = -low.diff()
    pos_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    neg_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    smoothed_pos = pos_dm.ewm(alpha=1.0 / length, adjust=False).mean()
    smoothed_neg = neg_dm.ewm(alpha=1.0 / length, adjust=False).mean()
    safe_atr = atr.replace(0, np.nan)
    di_pos = 100 * smoothed_pos / safe_atr
    di_neg = 100 * smoothed_neg / safe_atr
    dx = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / length, adjust=False).mean().fillna(0.0)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_money_line(
    df: pd.DataFrame,
    length: int = 8,
    smooth: int = 14,
    slope_len: int = 3,
) -> pd.DataFrame:
    """Volume-weighted, EMA-smoothed money-flow trend line that flips BULLISH/BEARISH.

    Independently implemented faithful equivalent (see STRATEGY.md).

    Parameters
    ----------
    df:
        OHLCV DataFrame with columns open, high, low, close, volume.
    length:
        VWMA lookback window.
    smooth:
        EMA span applied to the VWMA.
    slope_len:
        Rolling window for slope SMA (controls flip sensitivity).

    Returns
    -------
    DataFrame (same index as input) with added columns:
        money_line      float   the smoothed VWMA value
        state           str     'BULLISH' or 'BEARISH'
        flip_detected   bool    True on the bar where state changed
        signal_strength float   0-100 composite strength score
    """
    out = df.copy()

    # Typical price and VWMA
    tp = (out["high"] + out["low"] + out["close"]) / 3.0
    vwma = (tp * out["volume"]).rolling(length).sum() / out["volume"].rolling(length).sum()

    # EMA smoothing of the VWMA
    ml = vwma.ewm(span=smooth, adjust=False).mean().bfill()
    out["money_line"] = ml

    # State: sign of the rolling-average slope
    slope = ml.diff().rolling(slope_len).mean().fillna(0.0)
    out["state"] = np.where(slope >= 0, "BULLISH", "BEARISH")

    # Flip: state change from prior bar
    out["flip_detected"] = out["state"].ne(out["state"].shift()).fillna(False)

    # Composite strength (0-100)
    atr = _atr(out["high"], out["low"], out["close"], length=14).bfill()
    safe_atr = atr.replace(0, np.nan)
    slope_norm = (slope.abs() / safe_atr).fillna(0.0)
    vol_surge = (out["volume"] / out["volume"].rolling(20).mean().bfill()).fillna(1.0)
    mfi = _mfi(out["high"], out["low"], out["close"], out["volume"], length=14)

    raw = (
        40 * np.tanh(slope_norm * 8)
        + 30 * np.tanh(vol_surge - 1)
        + 30 * (np.abs(mfi - 50) / 50)
    )
    out["signal_strength"] = raw.clip(0, 100).round(1)

    return out


def confirm(primary_df: pd.DataFrame, confirm_df: pd.DataFrame) -> bool:
    """Return True only when BOTH DataFrames' latest state is BULLISH.

    Parameters
    ----------
    primary_df:
        Output of get_money_line() for the primary timeframe.
    confirm_df:
        Output of get_money_line() for the confirmation timeframe.
    """
    return (
        str(primary_df["state"].iloc[-1]) == "BULLISH"
        and str(confirm_df["state"].iloc[-1]) == "BULLISH"
    )


def latest_signal(
    df: pd.DataFrame,
    use_rsi_filter: bool = False,
    use_adx_filter: bool = False,
    rsi_overbought: float = 70.0,
    adx_min: float = 20.0,
) -> dict:
    """Return a summary dict for the most recent bar.

    Parameters
    ----------
    df:
        Output of get_money_line().
    use_rsi_filter:
        When True, downgrade state to BEARISH if RSI >= rsi_overbought.
    use_adx_filter:
        When True, downgrade state to BEARISH if ADX < adx_min (weak trend).
    rsi_overbought:
        RSI threshold above which the signal is considered overbought.
    adx_min:
        Minimum ADX for a valid trend signal.

    Returns
    -------
    dict with keys: state (str), strength (float), flip (bool), price (float).
    """
    last = df.iloc[-1]
    state = str(last["state"])

    if use_rsi_filter and "close" in df.columns:
        rsi_series = _rsi(df["close"], length=14)
        if rsi_series.iloc[-1] >= rsi_overbought:
            state = "BEARISH"

    if use_adx_filter and all(c in df.columns for c in ("high", "low", "close")):
        adx_series = _adx(df["high"], df["low"], df["close"], length=14)
        if adx_series.iloc[-1] < adx_min:
            state = "BEARISH"

    return {
        "state": state,
        "strength": float(last["signal_strength"]),
        "flip": bool(last["flip_detected"]),
        "price": float(last["close"]),
    }
