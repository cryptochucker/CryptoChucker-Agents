"""Tests for agents/signal_agent.py - Stage 2."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.signal_agent import confirm, get_money_line, latest_signal


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
