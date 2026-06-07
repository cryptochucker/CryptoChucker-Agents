from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def position_size(balance: float, risk_pct: float, entry: float, stop: float) -> float:
    """Calculate position size in units based on fixed fractional risk.

    Args:
        balance: Account balance in quote currency.
        risk_pct: Fraction of balance to risk (e.g. 0.01 = 1%).
        entry: Entry price.
        stop: Stop-loss price.

    Returns:
        Number of units to trade.
    """
    risk_amount = balance * risk_pct
    return risk_amount / abs(entry - stop)


def drawdown_breached(equity: list[float], max_dd_pct: float) -> bool:
    """Check whether the running drawdown from peak exceeds max_dd_pct.

    Args:
        equity: Sequence of equity values (e.g. mark-to-market balance over time).
        max_dd_pct: Maximum allowable drawdown as a fraction (e.g. 0.20 = 20%).

    Returns:
        True if any drawdown from a prior peak exceeds max_dd_pct.
    """
    peak = float("-inf")
    for val in equity:
        if val > peak:
            peak = val
        if peak > 0 and (peak - val) / peak > max_dd_pct:
            return True
    return False


@dataclass
class LimitCheckResult:
    allowed: bool
    reason: str


def check_limits(
    trades_today: int,
    consecutive_losses: int,
    exposure_pct: float,
    cfg: Any,
) -> LimitCheckResult:
    """Verify whether opening a new trade is within risk limits.

    Args:
        trades_today: Number of trades already placed today.
        consecutive_losses: Current streak of consecutive losing trades.
        exposure_pct: Current total exposure as a fraction of balance.
        cfg: Config object with a .risk sub-model (RiskCfg).

    Returns:
        LimitCheckResult(allowed, reason).
    """
    r = cfg.risk
    if trades_today >= r.max_trades_per_day:
        return LimitCheckResult(False, f"Daily trade cap reached ({trades_today}/{r.max_trades_per_day})")
    if consecutive_losses >= r.max_consecutive_losses:
        return LimitCheckResult(False, f"Consecutive loss cap reached ({consecutive_losses})")
    if exposure_pct >= r.max_exposure_pct:
        return LimitCheckResult(False, f"Max exposure reached ({exposure_pct:.1%}/{r.max_exposure_pct:.1%})")
    return LimitCheckResult(True, "OK")
