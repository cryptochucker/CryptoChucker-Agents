"""Tests for agents/signal_agent.py - Stage 2."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.signal_agent import _mfi, _rsi, confirm, get_money_line, latest_signal


def _df(prices, vol=None):
    n = len(prices)
    idx = pd.date_range("2026-01-01", periods=n, freq="4h")
    c = np.array(prices, float)
    return pd.DataFrame(
        {
            "open": c,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": c,
            "volume": (vol if vol is not None else np.full(n, 1000.0)),
        },
        index=idx,
    )


# ---- Task 2.1 tests ----

def test_columns_and_flip():
    up = list(np.linspace(100, 140, 40))
    down = list(np.linspace(140, 100, 40))
    out = get_money_line(_df(up + down))
    assert set(["money_line", "state", "flip_detected", "signal_strength"]).issubset(out.columns)
    assert out["state"].isin(["BULLISH", "BEARISH"]).all()
    assert out["flip_detected"].sum() >= 1
    assert out["signal_strength"].between(0, 100).all()


def test_uptrend_is_bullish_at_end():
    out = get_money_line(_df(list(np.linspace(100, 160, 80))))
    assert out["state"].iloc[-1] == "BULLISH"


# ---- Task 2.2 tests ----

def test_confirm_both_bullish():
    prices = list(np.linspace(100, 160, 80))
    primary = get_money_line(_df(prices))
    confirm_df = get_money_line(_df(prices))
    assert confirm(primary, confirm_df) is True


def test_confirm_mixed_returns_false():
    up = list(np.linspace(100, 160, 80))
    down = list(np.linspace(160, 100, 80))
    primary = get_money_line(_df(up))
    confirm_df = get_money_line(_df(down))
    assert confirm(primary, confirm_df) is False


def test_latest_signal_keys():
    prices = list(np.linspace(100, 160, 80))
    out = get_money_line(_df(prices))
    sig = latest_signal(out)
    assert set(["state", "strength", "flip", "price"]).issubset(sig.keys())
    assert sig["state"] in ("BULLISH", "BEARISH")
    assert 0 <= sig["strength"] <= 100
    assert isinstance(sig["flip"], bool)
    assert sig["price"] > 0


def test_latest_signal_with_rsi_filter_true():
    """RSI filter enabled should not raise; just returns a dict."""
    prices = list(np.linspace(100, 160, 80))
    out = get_money_line(_df(prices))
    sig = latest_signal(out, use_rsi_filter=True)
    assert sig["state"] in ("BULLISH", "BEARISH")


def test_latest_signal_with_adx_filter_true():
    """ADX filter enabled should not raise; just returns a dict."""
    prices = list(np.linspace(100, 160, 80))
    out = get_money_line(_df(prices))
    sig = latest_signal(out, use_adx_filter=True)
    assert sig["state"] in ("BULLISH", "BEARISH")


# ---- Gate 2 zero-denominator edge-case tests ----


def _ohlcv_df(prices, volumes=None):
    """Build a minimal OHLCV DataFrame from a price list."""
    n = len(prices)
    c = np.array(prices, float)
    v = np.full(n, 1000.0) if volumes is None else np.array(volumes, float)
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    return pd.DataFrame(
        {"open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "volume": v},
        index=idx,
    )


def test_rsi_strictly_increasing_equals_100():
    """Strictly increasing prices -> avg_loss == 0 -> RSI must be 100, no NaN/inf."""
    prices = list(range(50, 100))  # 50 bars, always rising
    close = pd.Series(prices, dtype=float)
    result = _rsi(close, length=14)
    last = result.iloc[-1]
    assert np.isfinite(last), f"RSI is not finite: {last}"
    assert last == pytest.approx(100.0, abs=1e-6), f"Expected 100, got {last}"


def test_rsi_strictly_decreasing_equals_0():
    """Strictly decreasing prices -> avg_gain == 0 -> RSI must be 0, no NaN/inf."""
    prices = list(range(100, 50, -1))  # 50 bars, always falling
    close = pd.Series(prices, dtype=float)
    result = _rsi(close, length=14)
    last = result.iloc[-1]
    assert np.isfinite(last), f"RSI is not finite: {last}"
    assert last == pytest.approx(0.0, abs=1e-6), f"Expected 0, got {last}"


def test_rsi_flat_equals_50():
    """Flat price series -> both avg_gain and avg_loss == 0 -> RSI must be 50, no NaN/inf."""
    prices = [100.0] * 30
    close = pd.Series(prices, dtype=float)
    result = _rsi(close, length=14)
    last = result.iloc[-1]
    assert np.isfinite(last), f"RSI is not finite: {last}"
    assert last == pytest.approx(50.0, abs=1e-6), f"Expected 50, got {last}"


def test_mfi_strictly_increasing_equals_100():
    """Strictly increasing prices -> neg_mf == 0 -> MFI must be 100, no NaN/inf."""
    prices = list(range(50, 110))  # 60 bars, always rising
    df = _ohlcv_df(prices)
    result = _mfi(df["high"], df["low"], df["close"], df["volume"], length=14)
    last = result.iloc[-1]
    assert np.isfinite(last), f"MFI is not finite: {last}"
    assert last == pytest.approx(100.0, abs=1e-6), f"Expected 100, got {last}"


def test_mfi_strictly_decreasing_equals_0():
    """Strictly decreasing prices -> pos_mf == 0 -> MFI must be 0, no NaN/inf."""
    prices = list(range(110, 50, -1))  # 60 bars, always falling
    df = _ohlcv_df(prices)
    result = _mfi(df["high"], df["low"], df["close"], df["volume"], length=14)
    last = result.iloc[-1]
    assert np.isfinite(last), f"MFI is not finite: {last}"
    assert last == pytest.approx(0.0, abs=1e-6), f"Expected 0, got {last}"


def test_mfi_flat_equals_50():
    """Flat prices -> both pos_mf and neg_mf == 0 -> MFI must be 50, no NaN/inf."""
    prices = [100.0] * 30
    df = _ohlcv_df(prices)
    result = _mfi(df["high"], df["low"], df["close"], df["volume"], length=14)
    last = result.iloc[-1]
    assert np.isfinite(last), f"MFI is not finite: {last}"
    assert last == pytest.approx(50.0, abs=1e-6), f"Expected 50, got {last}"


def test_get_money_line_flat_signal_strength_no_nan():
    """Flat price/volume -> signal_strength column must be in [0,100] with no NaN."""
    prices = [100.0] * 50
    df = _ohlcv_df(prices)
    out = get_money_line(df)
    ss = out["signal_strength"]
    assert ss.notna().all(), "signal_strength contains NaN on flat series"
    assert ss.between(0, 100).all(), f"signal_strength out of [0,100]: {ss.describe()}"
