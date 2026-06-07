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
    """Average True Range computed with Wilder smoothing (ewm alpha = 1/length)."""
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
    # Guard all three zero-denominator cases with np.where to stay vectorized:
    #   pos > 0, neg == 0 -> MFI = 100
    #   pos == 0, neg > 0 -> MFI = 0  (mfr = 0 -> 100 - 100/1 = 0, natural)
    #   both == 0         -> MFI = 50 (neutral, no trend information)
    safe_neg = neg_sum.where(neg_sum != 0, np.nan)
    mfr = pos_sum / safe_neg  # NaN where neg_sum == 0
    normal_mfi = 100.0 - 100.0 / (1.0 + mfr)
    result = np.where(
        neg_sum == 0,
        np.where(pos_sum > 0, 100.0, 50.0),
        normal_mfi,
    )
    # fillna(50) covers rolling-window warmup rows (insufficient data -> neutral)
    return pd.Series(result, index=pos_sum.index).fillna(50.0)


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    """Relative Strength Index (0-100) with Wilder smoothing."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False).mean()
    # Guard all three zero-denominator cases with np.where to stay vectorized:
    #   gain > 0, loss == 0 -> RSI = 100
    #   gain == 0, loss > 0 -> RSI = 0  (rs = 0 -> 100 - 100/1 = 0, natural)
    #   both == 0           -> RSI = 50 (neutral, flat series)
    safe_loss = avg_loss.where(avg_loss != 0, np.nan)
    rs = avg_gain / safe_loss  # NaN where avg_loss == 0
    normal_rsi = 100.0 - 100.0 / (1.0 + rs)
    result = np.where(
        avg_loss == 0,
        np.where(avg_gain > 0, 100.0, 50.0),
        normal_rsi,
    )
    # fillna(50) covers any residual NaN (e.g. from NaN input rows)
    return pd.Series(result, index=avg_gain.index).fillna(50.0)


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

    # Flip: state change from prior bar.
    # NOTE: state.ne(state.shift()) would make the first row True because
    # "BULLISH" != NaN evaluates to True in pandas.  A flip requires a real
    # prior bar, so we force row 0 to False.
    flip = out["state"].ne(out["state"].shift())
    flip.iloc[0] = False
    out["flip_detected"] = flip.astype(bool)

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
        Output of get_money_line().  Must contain 'close' (and 'high', 'low')
        columns if the RSI/ADX filters are enabled.
    use_rsi_filter:
        When True, downgrade state to BEARISH if RSI >= rsi_overbought.
        Rationale: avoid entering a long into exhausted/overbought conditions.
        Only downgrades BULLISH; a BEARISH base state is unchanged.
    use_adx_filter:
        When True, downgrade state to BEARISH if ADX < adx_min (weak/no trend).
        Rationale: the Money Line trend call is unreliable without directional
        conviction; ADX < adx_min means the trend signal should not be trusted.
        A strong trend (ADX >= adx_min) preserves the base state unchanged.
        Only downgrades BULLISH; a BEARISH base state is unchanged.
    rsi_overbought:
        RSI threshold (0-100).  Bars at or above this level are overbought.
        Default 70.
    adx_min:
        Minimum ADX (0-100) required to trust a trend signal.  Default 20.

    Returns
    -------
    dict with keys:
        state  (str)   -- 'BULLISH' or 'BEARISH' after optional filter downgrades.
        strength (float) -- signal_strength from get_money_line() [0-100].
        flip   (bool)  -- flip_detected on the latest bar.
        price  (float) -- close price of the latest bar.

    Gating contract (both filters only downgrade BULLISH; BEARISH is never upgraded):
        RSI filter: BULLISH + RSI >= rsi_overbought  -> BEARISH
        ADX filter: BULLISH + ADX <  adx_min         -> BEARISH (weak trend)
                    BULLISH + ADX >= adx_min          -> BULLISH preserved
        Filter order: RSI applied first; ADX applied second on surviving state.
    """
    last = df.iloc[-1]
    state = str(last["state"])

    # Filters only downgrade BULLISH -> BEARISH; they never upgrade BEARISH.
    if use_rsi_filter and state == "BULLISH" and "close" in df.columns:
        rsi_series = _rsi(df["close"], length=14)
        if rsi_series.iloc[-1] >= rsi_overbought:
            state = "BEARISH"

    if use_adx_filter and state == "BULLISH" and all(c in df.columns for c in ("high", "low", "close")):
        adx_series = _adx(df["high"], df["low"], df["close"], length=14)
        if adx_series.iloc[-1] < adx_min:
            state = "BEARISH"

    return {
        "state": state,
        "strength": float(last["signal_strength"]),
        "flip": bool(last["flip_detected"]),
        "price": float(last["close"]),
    }
