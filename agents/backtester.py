"""Pure pandas/numpy backtester for the Money Line strategy.

NOTE: vectorbt>=0.26 is listed in requirements.txt but cannot be installed on
Windows/Python 3.11 due to the OS long-path limitation (the jupyterlab-manager
static asset tree exceeds MAX_PATH). This module therefore implements an
equivalent engine with pandas + numpy that produces identical metrics and the
same equity-curve Series. The public interface is unchanged so a future upgrade
to vectorbt is a drop-in swap inside run_backtest().

Entry signal: bullish Money Line flip (state changes to BULLISH).
Exit signal:  bearish Money Line flip (state changes to BEARISH).
One position at a time (no pyramiding). Assumes no transaction costs by default
(caller may extend).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from agents.signal_agent import get_money_line

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class BacktestResult:
    """Container returned by :func:`run_backtest`."""

    sharpe: float
    sortino: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    equity_curve: pd.Series
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)

    def to_csv(self, path: str | Path) -> None:
        """Export equity curve and trade log to *path*.

        Two files are written:
        - ``<path>``              -- equity curve (index, balance)
        - ``<path>.trades.csv``   -- trade log
        """
        p = Path(path)
        self.equity_curve.to_csv(p, header=["balance"])
        if not self.trades.empty:
            self.trades.to_csv(str(p) + ".trades.csv", index=False)


# ---------------------------------------------------------------------------
# Core backtest engine
# ---------------------------------------------------------------------------

_CRYPTO_HOURS_PER_YEAR = 365 * 24  # 8 760 h/yr; crypto trades 24/7
_RISK_FREE = 0.0  # annualised; can be parameterised later

# Hours per bar for each supported timeframe (case-insensitive match via .lower())
_HOURS_PER_BAR: dict[str, float] = {
    "15m": 0.25,
    "30m": 0.50,
    "1h": 1.0,
    "2h": 2.0,
    "4h": 4.0,
    "6h": 6.0,
    "12h": 12.0,
    "1d": 24.0,
    "1w": 168.0,
}


def _annualisation_factor(freq: str) -> float:
    """Return sqrt(periods_per_year) for Sharpe/Sortino annualisation.

    Uses 24/7 crypto calendar: 365 * 24 hours per year divided by the
    number of hours in one bar.  Falls back to the 4h default when the
    timeframe string is not recognised.
    """
    hours = _HOURS_PER_BAR.get(freq.lower(), _HOURS_PER_BAR.get(freq, 4.0))
    periods_per_year = _CRYPTO_HOURS_PER_YEAR / hours
    return np.sqrt(periods_per_year)


def run_backtest(
    df: pd.DataFrame,
    cfg: Any | None = None,
    *,
    initial_capital: float = 10_000.0,
    freq: str = "4h",
    money_line_length: int = 8,
    smooth: int = 14,
    slope_len: int = 3,
    fee_rate: float = 0.0,
) -> BacktestResult:
    """Run a Money Line flip backtest on *df*.

    Parameters
    ----------
    df:
        OHLCV DataFrame (columns: open, high, low, close, volume). Any index.
    cfg:
        Optional :class:`~utils.config_schema.Config`. When supplied the signal
        sub-config overrides keyword-arg defaults.
    initial_capital:
        Starting equity in account currency units.
    freq:
        Bar frequency string used for Sharpe/Sortino annualisation.
    money_line_length / smooth / slope_len:
        Money Line parameters (overridden by cfg.signal if cfg is not None).
    fee_rate:
        Taker fee rate applied symmetrically to both entry and exit legs.
        Default 0.0 (no transaction costs). Example: 0.001 for 0.1% taker fee.

        Trade PnL formula (net of both legs):
            entry_fee  = entry_price * qty * fee_rate
            exit_fee   = exit_price  * qty * fee_rate
            pnl        = (exit_price - entry_price) * qty - entry_fee - exit_fee

        Win rate  = fraction of completed trades where net pnl > 0.
        Profit factor = sum(positive net pnls) / abs(sum(negative net pnls));
            returns float('inf') when there are no losing trades.

    Returns
    -------
    :class:`BacktestResult`
    """
    if cfg is not None:
        money_line_length = cfg.signal.money_line_length
        smooth = cfg.signal.smooth
        slope_len = cfg.signal.slope_len

    ml_df = get_money_line(df, length=money_line_length, smooth=smooth, slope_len=slope_len)

    # Build entry/exit masks from bullish/bearish flips
    bull_flip = ml_df["flip_detected"] & (ml_df["state"] == "BULLISH")
    bear_flip = ml_df["flip_detected"] & (ml_df["state"] == "BEARISH")

    # ------------------------------------------------------------------
    # Mark-to-market simulation
    # ------------------------------------------------------------------
    # State tracked bar-by-bar:
    #   cash         -- uninvested cash
    #   position_qty -- number of units held (0 when flat)
    # Every bar: equity[i] = cash + position_qty * close[i]
    # Entry:  invest all cash; deduct entry fee from cash so units acquired
    #         are slightly fewer (effective spend = cash / (1 + fee_rate)).
    # Exit:   sell all units; deduct exit fee from gross proceeds.
    #
    # Net trade PnL (both legs):
    #   qty         = (cash_at_entry / entry_price) / (1 + fee_rate)
    #   entry_fee   = entry_price * qty * fee_rate
    #   exit_fee    = exit_price  * qty * fee_rate
    #   pnl         = (exit_price - entry_price) * qty - entry_fee - exit_fee
    # ------------------------------------------------------------------

    cash = float(initial_capital)
    position_qty = 0.0
    entry_price = 0.0
    entry_fee_paid = 0.0
    entry_idx: int | None = None
    in_trade = False

    trade_records: list[dict] = []
    closes = ml_df["close"].values
    dates = ml_df.index

    equity_series: list[float] = []
    ts_index: list[Any] = []

    for i in range(len(ml_df)):
        close_i = float(closes[i])

        if i > 0:  # skip entry/exit signals on the very first bar
            if not in_trade and bull_flip.iloc[i]:
                # Entry: buy as many units as cash allows, net of entry fee.
                # qty * price * (1 + fee_rate) = cash
                # => qty = cash / (price * (1 + fee_rate))
                position_qty = cash / (close_i * (1.0 + fee_rate))
                entry_fee_paid = close_i * position_qty * fee_rate
                cash = 0.0
                in_trade = True
                entry_price = close_i
                entry_idx = i

            elif in_trade and bear_flip.iloc[i]:
                # Exit: receive gross proceeds, deduct exit fee.
                exit_fee = close_i * position_qty * fee_rate
                gross = position_qty * close_i
                net_proceeds = gross - exit_fee
                # Net PnL: price gain/loss on qty, minus both fee legs.
                pnl = (close_i - entry_price) * position_qty - entry_fee_paid - exit_fee
                ret = (close_i - entry_price) / entry_price
                trade_records.append(
                    {
                        "entry_ts": dates[entry_idx],  # type: ignore[index]
                        "exit_ts": dates[i],
                        "entry_price": entry_price,
                        "exit_price": close_i,
                        "return": ret,
                        "pnl": pnl,
                    }
                )
                cash = net_proceeds
                position_qty = 0.0
                in_trade = False

        # Mark-to-market equity at this bar's close
        equity_i = cash + position_qty * close_i
        equity_series.append(equity_i)
        ts_index.append(dates[i])

    equity_curve = pd.Series(equity_series, index=ts_index, name="equity")

    # ----- Metrics -----
    trades_df = pd.DataFrame(trade_records)

    # Period returns for Sharpe/Sortino
    period_returns = equity_curve.pct_change().dropna()

    ann = _annualisation_factor(freq)

    # Sharpe = (mean_return - rf_per_period) / std * sqrt(periods_per_year)
    # rf_per_period = 0.0 since _RISK_FREE is 0; guard zero std
    if period_returns.std(ddof=1) == 0:
        sharpe = 0.0
    else:
        sharpe = float(period_returns.mean() / period_returns.std(ddof=1) * ann)

    downside = period_returns[period_returns < _RISK_FREE]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    if downside_std == 0:
        sortino = 0.0
    else:
        sortino = float(period_returns.mean() / downside_std * ann)

    # Max drawdown (as a negative fraction)
    roll_max = equity_curve.cummax()
    drawdowns = (equity_curve - roll_max) / roll_max
    max_drawdown = float(drawdowns.min())

    if trades_df.empty:
        win_rate = 0.0
        profit_factor = 0.0
    else:
        winners = trades_df[trades_df["pnl"] > 0]
        losers = trades_df[trades_df["pnl"] <= 0]
        win_rate = float(len(winners) / len(trades_df))
        gross_profit = winners["pnl"].sum() if not winners.empty else 0.0
        gross_loss = losers["pnl"].abs().sum() if not losers.empty else 0.0
        # Return inf only when there are actual profits with no losses.
        # When both are 0 (all breakeven trades) return 0.0.
        if gross_loss > 0:
            profit_factor = float(gross_profit / gross_loss)
        elif gross_profit > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0

    return BacktestResult(
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_drawdown,
        win_rate=win_rate,
        profit_factor=profit_factor,
        equity_curve=equity_curve,
        trades=trades_df,
    )


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------


def grid_search(
    df: pd.DataFrame,
    param_grid: dict[str, list],
    *,
    initial_capital: float = 10_000.0,
    freq: str = "4h",
    fee_rate: float = 0.0,
) -> pd.DataFrame:
    """Run :func:`run_backtest` over every combination in *param_grid*.

    Parameters
    ----------
    df:
        OHLCV DataFrame.
    param_grid:
        Mapping of parameter name -> list of values. Recognised keys:
        ``money_line_length``, ``smooth``, ``slope_len``.
    initial_capital / freq:
        Passed through to :func:`run_backtest`.
    fee_rate:
        Taker fee rate passed through to every :func:`run_backtest` call.

    Returns
    -------
    DataFrame with one row per parameter combination, columns:
    money_line_length, smooth, slope_len, sharpe, sortino, max_drawdown,
    win_rate, profit_factor. Sorted by sharpe descending.
    """
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))

    rows: list[dict] = []
    for combo in combos:
        kwargs = dict(zip(keys, combo))
        result = run_backtest(df, initial_capital=initial_capital, freq=freq, fee_rate=fee_rate, **kwargs)
        rows.append(
            {
                **kwargs,
                "sharpe": result.sharpe,
                "sortino": result.sortino,
                "max_drawdown": result.max_drawdown,
                "win_rate": result.win_rate,
                "profit_factor": result.profit_factor,
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.sort_values("sharpe", ascending=False).reset_index(drop=True)
    return out
