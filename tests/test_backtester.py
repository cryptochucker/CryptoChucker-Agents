"""Tests for agents/backtester.py (Task 5.1 + 5.2)."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from agents.backtester import BacktestResult, grid_search, run_backtest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    """Fixed synthetic OHLCV with a clear bull then bear trend to guarantee flips."""
    rng = np.random.default_rng(42)
    n = 200
    # Bull run for first half, bear for second — ensures at least one entry + exit
    drift = np.concatenate([np.full(100, 0.004), np.full(100, -0.004)])
    rets = drift + rng.normal(0, 0.005, n)
    close = 10_000.0 * np.cumprod(1 + rets)
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = np.concatenate([[10_000.0], close[:-1]])
    volume = rng.uniform(500, 2000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture
def flat_ohlcv() -> pd.DataFrame:
    """Flat price series with minimal volume variance to stress the zero-trade path."""
    n = 60
    idx = pd.date_range("2024-01-01", periods=n, freq="4h")
    price = np.full(n, 100.0)
    vol = np.ones(n) * 1000.0
    return pd.DataFrame(
        {"open": price, "high": price + 0.01, "low": price - 0.01,
         "close": price, "volume": vol},
        index=idx,
    )


# ---------------------------------------------------------------------------
# BacktestResult type
# ---------------------------------------------------------------------------


def test_result_is_dataclass(synthetic_ohlcv):
    result = run_backtest(synthetic_ohlcv)
    assert isinstance(result, BacktestResult)


def test_equity_curve_is_series(synthetic_ohlcv):
    result = run_backtest(synthetic_ohlcv)
    assert isinstance(result.equity_curve, pd.Series)


def test_equity_curve_length_matches_input(synthetic_ohlcv):
    result = run_backtest(synthetic_ohlcv)
    assert len(result.equity_curve) == len(synthetic_ohlcv)


# ---------------------------------------------------------------------------
# Metrics are finite
# ---------------------------------------------------------------------------


def test_sharpe_is_finite(synthetic_ohlcv):
    r = run_backtest(synthetic_ohlcv)
    assert math.isfinite(r.sharpe)


def test_sortino_is_finite(synthetic_ohlcv):
    r = run_backtest(synthetic_ohlcv)
    assert math.isfinite(r.sortino)


def test_max_drawdown_is_finite_and_nonpositive(synthetic_ohlcv):
    r = run_backtest(synthetic_ohlcv)
    assert math.isfinite(r.max_drawdown)
    assert r.max_drawdown <= 0.0


def test_win_rate_in_range(synthetic_ohlcv):
    r = run_backtest(synthetic_ohlcv)
    assert 0.0 <= r.win_rate <= 1.0


def test_profit_factor_is_finite_or_inf(synthetic_ohlcv):
    r = run_backtest(synthetic_ohlcv)
    assert r.profit_factor >= 0.0


def test_equity_curve_starts_at_initial_capital(synthetic_ohlcv):
    cap = 15_000.0
    r = run_backtest(synthetic_ohlcv, initial_capital=cap)
    assert r.equity_curve.iloc[0] == pytest.approx(cap)


# ---------------------------------------------------------------------------
# Zero-trade path (flat market)
# ---------------------------------------------------------------------------


def test_flat_market_no_crash(flat_ohlcv):
    r = run_backtest(flat_ohlcv)
    assert isinstance(r, BacktestResult)
    assert math.isfinite(r.sharpe) or r.sharpe == 0.0


def test_flat_market_equity_stays_at_initial(flat_ohlcv):
    cap = 10_000.0
    r = run_backtest(flat_ohlcv, initial_capital=cap)
    assert r.equity_curve.iloc[-1] == pytest.approx(cap, rel=1e-6)


# ---------------------------------------------------------------------------
# to_csv
# ---------------------------------------------------------------------------


def test_to_csv_creates_file(synthetic_ohlcv, tmp_path):
    r = run_backtest(synthetic_ohlcv)
    out = tmp_path / "equity.csv"
    r.to_csv(out)
    assert out.exists()


def test_to_csv_readable(synthetic_ohlcv, tmp_path):
    r = run_backtest(synthetic_ohlcv)
    out = tmp_path / "equity.csv"
    r.to_csv(out)
    df = pd.read_csv(out, index_col=0)
    assert "balance" in df.columns
    assert len(df) == len(r.equity_curve)


# ---------------------------------------------------------------------------
# Config override
# ---------------------------------------------------------------------------


def test_run_backtest_accepts_cfg(synthetic_ohlcv):
    from utils.config_schema import Config

    cfg = Config()
    cfg.signal.money_line_length = 10
    r = run_backtest(synthetic_ohlcv, cfg)
    assert isinstance(r, BacktestResult)


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------


@pytest.fixture
def small_param_grid():
    return {
        "money_line_length": [6, 8],
        "smooth": [10, 14],
    }


def test_grid_search_returns_dataframe(synthetic_ohlcv, small_param_grid):
    df = grid_search(synthetic_ohlcv, small_param_grid)
    assert isinstance(df, pd.DataFrame)


def test_grid_search_row_count(synthetic_ohlcv, small_param_grid):
    df = grid_search(synthetic_ohlcv, small_param_grid)
    # 2 lengths x 2 smooth values = 4 combos
    assert len(df) == 4


def test_grid_search_sorted_by_sharpe_desc(synthetic_ohlcv, small_param_grid):
    df = grid_search(synthetic_ohlcv, small_param_grid)
    if len(df) > 1:
        assert list(df["sharpe"]) == sorted(df["sharpe"], reverse=True)


def test_grid_search_has_required_columns(synthetic_ohlcv, small_param_grid):
    df = grid_search(synthetic_ohlcv, small_param_grid)
    for col in ("sharpe", "sortino", "max_drawdown", "win_rate", "profit_factor"):
        assert col in df.columns


def test_grid_search_single_combo(synthetic_ohlcv):
    df = grid_search(synthetic_ohlcv, {"money_line_length": [8]})
    assert len(df) == 1


def test_grid_search_all_sharpes_finite(synthetic_ohlcv, small_param_grid):
    df = grid_search(synthetic_ohlcv, small_param_grid)
    assert df["sharpe"].apply(math.isfinite).all()
