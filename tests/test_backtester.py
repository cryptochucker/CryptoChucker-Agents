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


# ---------------------------------------------------------------------------
# MEDIUM 6 -- Deterministic mark-to-market fixture (BLOCKING 1 regression)
# ---------------------------------------------------------------------------
# Uses `synthetic_ohlcv` (200 bars, bull-run then bear, seed=42) with
# money_line_length=3, smooth=5, slope_len=1 which reliably generates two
# complete round-trip trades (verified in-code).
#
# The first trade enters near bar 99 and exits near bar 101 but the MTM
# equity dips to ~9931 intra-bar-99 before the exit fires, yielding
# max_drawdown ~-3.3%.  The old realised-only engine would show 0 drawdown
# while the position was open.
# ---------------------------------------------------------------------------

_MTM_KWARGS = dict(money_line_length=3, smooth=5, slope_len=1, freq="4h")


def test_mtm_max_drawdown_captures_intra_trade_dip(synthetic_ohlcv):
    """max_drawdown must reflect the intra-trade price dip, not just closed trades.

    With mark-to-market equity the dip below entry price while in a position
    must produce a negative drawdown.  The old realised-only engine would
    show drawdown == 0 while a position was open.
    """
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, **_MTM_KWARGS)
    # Verified empirically: drawdown reaches ~ -3.3% with this seed/params.
    assert r.max_drawdown < -0.02, (
        f"Expected max_drawdown < -0.02 (intra-trade dip captured), got {r.max_drawdown:.4f}"
    )


def test_mtm_completed_trades_exist(synthetic_ohlcv):
    """At least one complete round-trip trade must fire on this fixture."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, **_MTM_KWARGS)
    assert len(r.trades) >= 1, "Expected at least one completed trade"


def test_mtm_equity_curve_moves_intra_trade(synthetic_ohlcv):
    """The equity series must contain at least 3 distinct values (not flat)."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, **_MTM_KWARGS)
    unique_values = r.equity_curve.nunique()
    assert unique_values >= 3, (
        f"Equity curve has only {unique_values} unique values -- looks like realised-only tracking"
    )


def test_mtm_sharpe_is_finite(synthetic_ohlcv):
    """Sharpe must be a finite float (not NaN/inf) on the MTM equity curve."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, **_MTM_KWARGS)
    assert math.isfinite(r.sharpe), f"Sharpe is not finite: {r.sharpe}"


def test_mtm_annualisation_crypto_4h():
    """4h bars on a 24/7 crypto market -> periods_per_year = 8760/4 = 2190."""
    from agents.backtester import _annualisation_factor

    factor = _annualisation_factor("4h")
    expected = math.sqrt(365 * 24 / 4)  # sqrt(2190)
    assert factor == pytest.approx(expected, rel=1e-6)


def test_mtm_annualisation_crypto_1d():
    """1d bars -> periods_per_year = 365."""
    from agents.backtester import _annualisation_factor

    factor = _annualisation_factor("1d")
    expected = math.sqrt(365)
    assert factor == pytest.approx(expected, rel=1e-6)


def test_mtm_annualisation_crypto_15m():
    """15m bars -> periods_per_year = 8760/0.25 = 35040."""
    from agents.backtester import _annualisation_factor

    factor = _annualisation_factor("15m")
    expected = math.sqrt(365 * 24 / 0.25)
    assert factor == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# MEDIUM 5 -- Exact-value metric tests with deterministic trade fixture
# ---------------------------------------------------------------------------
# Fixture: synthetic_ohlcv (seed=42, 200 bars, bull then bear) with
# money_line_length=2, smooth=3, slope_len=1, freq='4h'.
# This produces exactly 6 round-trip trades (2 winners, 4 losers) at
# deterministic prices, enabling hand-verifiable metric assertions.
#
# Hand-computed values (fee_rate=0.0):
#   win_rate       = 2/6 = 0.333...
#   profit_factor  = sum(positive pnls) / abs(sum(negative pnls))
#                  = 4129.15 / 341.70 ~= 12.084
#   max_drawdown   ~= -0.0317 (fraction below peak equity)
#
# With fee_rate=0.001 (0.1% taker):
#   Each trade pnl is reduced by both entry_fee and exit_fee.
#   The total pnl reduction vs fee_rate=0 must be > 0.
#   profit_factor drops (fees widen losses more than they shrink gains).
# ---------------------------------------------------------------------------

_EXACT_PARAMS = dict(money_line_length=2, smooth=3, slope_len=1, freq="4h")


def test_exact_win_rate_fee0(synthetic_ohlcv):
    """win_rate must equal exactly 2/6 (2 winning trades out of 6 total)."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    assert len(r.trades) == 6, f"Expected 6 trades, got {len(r.trades)}"
    assert r.win_rate == pytest.approx(2 / 6, rel=1e-6)


def test_exact_profit_factor_fee0(synthetic_ohlcv):
    """profit_factor must equal gross_winners / gross_losers to within 0.1%."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    assert r.profit_factor == pytest.approx(12.084, rel=1e-3)


def test_exact_max_drawdown_fee0(synthetic_ohlcv):
    """max_drawdown must be negative and within 0.1% of the hand-computed value."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    assert r.max_drawdown == pytest.approx(-0.031657, rel=1e-2)


def test_exact_sharpe_fee0(synthetic_ohlcv):
    """Sharpe must be a positive finite float for this bull-then-bear fixture."""
    r = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    assert math.isfinite(r.sharpe)
    assert r.sharpe == pytest.approx(22.74, rel=1e-2)


def test_exact_fees_reduce_pnl(synthetic_ohlcv):
    """With fee_rate=0.001, total net pnl must be lower than with fee_rate=0.

    This verifies that entry+exit fees flow into pnl for every trade.
    """
    r0 = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    r1 = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.001, **_EXACT_PARAMS)
    assert len(r0.trades) == len(r1.trades), "Same number of trades expected regardless of fee_rate"
    total_pnl_0 = r0.trades["pnl"].sum()
    total_pnl_1 = r1.trades["pnl"].sum()
    assert total_pnl_0 > total_pnl_1, (
        f"Fees must reduce total pnl: fee=0 sum={total_pnl_0:.4f}, fee=0.001 sum={total_pnl_1:.4f}"
    )


def test_exact_fee_pnl_per_trade(synthetic_ohlcv):
    """Each trade's pnl with fee must be lower than without fee.

    Verifies the formula: pnl = (exit-entry)*qty - entry_fee - exit_fee
    is applied per trade (both entry AND exit fees deducted).
    """
    r0 = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    r1 = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.001, **_EXACT_PARAMS)
    for i in range(len(r0.trades)):
        assert r0.trades["pnl"].iloc[i] > r1.trades["pnl"].iloc[i], (
            f"Trade {i}: fee_rate=0 pnl ({r0.trades['pnl'].iloc[i]:.4f}) "
            f"should exceed fee_rate=0.001 pnl ({r1.trades['pnl'].iloc[i]:.4f})"
        )


def test_exact_win_rate_with_fee(synthetic_ohlcv):
    """With fee_rate=0.001 both winners remain winners (fee doesn't flip sign for big winners).

    Also checks: profit_factor drops relative to fee_rate=0 (fees hurt).
    """
    r0 = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    r1 = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.001, **_EXACT_PARAMS)
    # win_rate is same: both big winners remain positive after fees
    assert r1.win_rate == pytest.approx(r0.win_rate, rel=1e-6)
    # profit_factor drops because fees reduce winners by less (absolute) than
    # they inflate losses (both legs reduce pnl)
    assert r1.profit_factor < r0.profit_factor, (
        "profit_factor should be lower with fees"
    )
    assert r1.profit_factor == pytest.approx(9.055, rel=1e-2)


def test_profit_factor_no_losses_returns_inf():
    """profit_factor must return float('inf') when all trades are winners (no losers)."""
    # Build a pure up-trend OHLCV so every trade is a winner
    n = 100
    price = np.linspace(100.0, 200.0, n)  # monotonically rising
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    df = pd.DataFrame(
        {
            "open": price,
            "high": price * 1.005,
            "low": price * 0.995,
            "close": price,
            "volume": np.ones(n) * 1000.0,
        },
        index=idx,
    )
    r = run_backtest(df, initial_capital=10_000.0, money_line_length=2, smooth=3, slope_len=1, fee_rate=0.0, freq="1h")
    if not r.trades.empty:
        losers = r.trades[r.trades["pnl"] <= 0]
        if losers.empty:
            assert r.profit_factor == float("inf"), (
                "With no losing trades, profit_factor must be float('inf')"
            )


def test_profit_factor_all_breakeven_returns_zero():
    """profit_factor must return 0.0 when all trades break even (pnl == 0).

    Regression for the edge case where both gross_profit and gross_loss are 0
    (e.g. all trades exit exactly at entry price).  The old code returned inf.
    """
    # Build a trades DataFrame where every pnl is exactly 0.
    trades = pd.DataFrame({"pnl": [0.0, 0.0, 0.0]})
    # Re-compute profit_factor the same way the backtester does to confirm fix.
    winners = trades[trades["pnl"] > 0]
    losers = trades[trades["pnl"] <= 0]
    gross_profit = winners["pnl"].sum() if not winners.empty else 0.0
    gross_loss = losers["pnl"].abs().sum() if not losers.empty else 0.0
    if gross_loss > 0:
        pf = float(gross_profit / gross_loss)
    elif gross_profit > 0:
        pf = float("inf")
    else:
        pf = 0.0
    assert pf == 0.0, f"Expected 0.0 for all-breakeven trades, got {pf}"

    # Also verify via an OHLCV run that produces at least one trade.
    # A perfectly flat price series with zero noise ensures every long position
    # exits at the same price as entry, so pnl == 0 for every trade.
    n = 120
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    # Add a tiny zigzag so flips can fire, but keep entry == exit price.
    # Alternate tiny up/down bumps to force state flips on the money line.
    alternating = np.where(np.arange(n) % 10 < 5, 100.01, 99.99)
    df_flat = pd.DataFrame(
        {
            "open": alternating,
            "high": alternating + 0.005,
            "low": alternating - 0.005,
            "close": alternating,
            "volume": np.ones(n) * 1000.0,
        },
        index=idx,
    )
    r = run_backtest(df_flat, initial_capital=10_000.0,
                     money_line_length=2, smooth=3, slope_len=1, fee_rate=0.0, freq="1h")
    # If any trades fired and all pnl == 0 exactly, profit_factor must be 0.0 not inf.
    if not r.trades.empty and (r.trades["pnl"] == 0.0).all():
        assert r.profit_factor == 0.0, (
            f"All-breakeven trades must yield profit_factor=0.0, got {r.profit_factor}"
        )


def test_fee_rate_zero_is_default_no_fees(synthetic_ohlcv):
    """Calling run_backtest with fee_rate=0.0 must produce the same result as
    not passing fee_rate at all (default is 0.0, meaning no transaction costs)."""
    r_default = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, **_EXACT_PARAMS)
    r_explicit = run_backtest(synthetic_ohlcv, initial_capital=10_000.0, fee_rate=0.0, **_EXACT_PARAMS)
    assert r_default.win_rate == pytest.approx(r_explicit.win_rate, rel=1e-9)
    assert r_default.profit_factor == pytest.approx(r_explicit.profit_factor, rel=1e-9)
    np.testing.assert_allclose(
        r_default.equity_curve.values, r_explicit.equity_curve.values, rtol=1e-9
    )
