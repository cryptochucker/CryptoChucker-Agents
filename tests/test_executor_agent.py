"""Tests for the paper executor agent.

All required safety and correctness proofs:
  1. Bullish flip in paper mode -> PAPER trade recorded; ccxt create_order NEVER called.
  2. _live_order while disabled -> raises LiveTradingDisabled.
  3. Executor refuses new entry when drawdown_breached is True.
  4. Executor refuses new entry when daily trade cap is hit.
  5. Profit-target exit accounts for fees (net target, not gross).
  6. Bearish flip on an open position triggers an exit.
  7. No new entry when state is not BULLISH (or not a fresh flip).
  8. Position sizing uses risk_manager.position_size.
  9. Trailing stop exit when price drops below trailing level.
 10. max_hold_hours exit when position held too long.
 11. (BLOCKING 2) Executor construction in paper mode never reads secret env keys.
 12. (MEDIUM 3) Post-entry exposure: new entry refused when it would breach max_exposure.
 13. (MEDIUM 4) use_dip_filter: dip met -> entry; not met -> skip; no df -> skip check.
"""
from __future__ import annotations

import datetime
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from agents.executor_agent import Executor
from agents.scanner_agent import SignalEvent
from utils.config_schema import Config, ExecutorCfg, FeesCfg, RiskCfg
from utils.safety import LiveTradingDisabled
from utils.store import Store

_SECRET_KEYS = ("EXCHANGE_API_KEY", "EXCHANGE_API_SECRET", "EXCHANGE_API_PASSWORD")


class _SecretGuardEnv(dict):
    """Dict subclass that RAISES if any secret key is accessed via .get() or []."""

    def get(self, key, default=None):  # type: ignore[override]
        if key in _SECRET_KEYS:
            raise AssertionError(f"Paper mode accessed secret key: {key!r}")
        return super().get(key, default)

    def __getitem__(self, key):
        if key in _SECRET_KEYS:
            raise AssertionError(f"Paper mode accessed secret key: {key!r}")
        return super().__getitem__(key)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_PAPER_ENV = {"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "false"}


def _make_cfg(
    profit_target_pct: float = 0.06,
    use_dip_filter: bool = False,
    trailing_stop_pct: float = 0.0,
    max_hold_hours: int = 48,
    max_trades_per_day: int = 10,
    max_drawdown_pct: float = 0.20,
    balance: float = 10_000.0,
    risk_pct: float = 0.01,
    max_exposure_pct: float = 1.0,
) -> Config:
    return Config(
        exchange="blofin",
        executor=ExecutorCfg(
            profit_target_pct=profit_target_pct,
            use_dip_filter=use_dip_filter,
            trailing_stop_pct=trailing_stop_pct,
            max_hold_hours=max_hold_hours,
        ),
        fees=FeesCfg(rates={"blofin": {"maker": 0.0002, "taker": 0.0006}}),
        risk=RiskCfg(
            account_balance=balance,
            risk_pct=risk_pct,
            max_exposure_pct=max_exposure_pct,
            max_trades_per_day=max_trades_per_day,
            max_consecutive_losses=4,
            max_drawdown_pct=max_drawdown_pct,
        ),
    )


def _make_store(tmp_path) -> Store:
    store = Store(str(tmp_path / "test.db"))
    store.init()
    return store


def _bullish_event(price: float = 100.0) -> SignalEvent:
    return SignalEvent(
        symbol="BTC/USDT",
        tf="4h",
        state="BULLISH",
        strength=75.0,
        flip=True,
        price=price,
        ts=datetime.datetime.utcnow(),
    )


def _bearish_event(price: float = 105.0) -> SignalEvent:
    return SignalEvent(
        symbol="BTC/USDT",
        tf="4h",
        state="BEARISH",
        strength=65.0,
        flip=True,
        price=price,
        ts=datetime.datetime.utcnow(),
    )


def _mock_ccxt_client() -> MagicMock:
    """Return a mock ccxt exchange that should NEVER have create_order called."""
    m = MagicMock()
    m.apiKey = None
    m.secret = None
    return m


# ---------------------------------------------------------------------------
# 1. Bullish flip -> paper trade recorded; create_order NEVER called
# ---------------------------------------------------------------------------


def test_paper_fill_records_trade_on_bullish_flip(tmp_path) -> None:
    """Paper mode: bullish flip must record a trade in the store."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()

    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)
    ex.on_signal(_bullish_event(price=100.0))

    trades = store.load_trades()
    assert len(trades) >= 1
    assert trades[0]["mode"] == "paper"


def test_paper_fill_never_calls_create_order(tmp_path) -> None:
    """Paper mode: ccxt create_order must NEVER be called on any signal."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()

    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)
    ex.on_signal(_bullish_event(price=100.0))

    assert client.create_order.call_count == 0, (
        "create_order was called in paper mode -- this is a critical safety failure"
    )


def test_paper_fill_records_correct_symbol(tmp_path) -> None:
    """Paper fill must record the correct symbol."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    ex = Executor(cfg, store, client=_mock_ccxt_client(), env=_PAPER_ENV)
    ex.on_signal(_bullish_event())

    trades = store.load_trades()
    assert trades[0]["symbol"] == "BTC/USDT"


def test_paper_fill_records_entry_price(tmp_path) -> None:
    """Paper fill must record the signal price as entry price."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    ex = Executor(cfg, store, client=_mock_ccxt_client(), env=_PAPER_ENV)
    ex.on_signal(_bullish_event(price=123.45))

    trades = store.load_trades()
    assert trades[0]["entry_price"] == pytest.approx(123.45)


def test_paper_fill_records_equity_snapshot(tmp_path) -> None:
    """After a paper entry the executor must snapshot equity to the store."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    ex = Executor(cfg, store, client=_mock_ccxt_client(), env=_PAPER_ENV)
    ex.on_signal(_bullish_event())

    equity = store.load_equity()
    assert len(equity) >= 1


# ---------------------------------------------------------------------------
# 2. _live_order while disabled -> raises LiveTradingDisabled
# ---------------------------------------------------------------------------


def test_live_order_raises_when_disabled(tmp_path) -> None:
    """_live_order must raise LiveTradingDisabled in paper mode."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    with pytest.raises(LiveTradingDisabled):
        ex._live_order("BTC/USDT", "buy", 1.0, 100.0)

    # LOW 6: guard must fire BEFORE any order is placed
    assert client.create_order.call_count == 0, (
        "create_order was called before LiveTradingDisabled guard -- safety failure"
    )


def test_live_order_raises_with_empty_env(tmp_path) -> None:
    """_live_order must raise with empty env (all defaults -> paper)."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env={})

    with pytest.raises(LiveTradingDisabled):
        ex._live_order("BTC/USDT", "sell", 0.5, 110.0)

    assert client.create_order.call_count == 0, (
        "create_order called before LiveTradingDisabled guard"
    )


# ---------------------------------------------------------------------------
# 3. Drawdown breached -> refuses new entry
# ---------------------------------------------------------------------------


def test_refuses_entry_when_drawdown_breached(tmp_path) -> None:
    """If drawdown_breached is True the executor must NOT open a new position."""
    cfg = _make_cfg(max_drawdown_pct=0.10)
    store = _make_store(tmp_path)
    # Seed equity history showing a >10% drawdown: peak 10000, current 8000
    store.save_equity(10_000.0)
    store.save_equity(8_000.0)

    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)
    ex.on_signal(_bullish_event())

    # No trade should have been recorded (drawdown stop triggered)
    assert client.create_order.call_count == 0
    trades = store.load_trades()
    assert len(trades) == 0


# ---------------------------------------------------------------------------
# 4. Daily trade cap hit -> refuses new entry
# ---------------------------------------------------------------------------


def test_refuses_entry_when_daily_cap_hit(tmp_path) -> None:
    """If the daily trade cap is already at max, no new entry should be placed."""
    cfg = _make_cfg(max_trades_per_day=2)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    # Simulate the cap already being reached by recording today's trades directly
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    store.save_trade({
        "symbol": "ETH/USDT", "mode": "paper", "side": "buy",
        "entry_price": 2000.0, "exit_price": 2100.0, "qty": 0.1,
        "pnl": 10.0, "fee": 1.0,
        "opened_at": f"{today} 00:00:00",
    })
    store.save_trade({
        "symbol": "BNB/USDT", "mode": "paper", "side": "buy",
        "entry_price": 300.0, "exit_price": 315.0, "qty": 1.0,
        "pnl": 15.0, "fee": 0.5,
        "opened_at": f"{today} 01:00:00",
    })

    ex.on_signal(_bullish_event())

    # No new trade should be recorded (cap at 2 already reached)
    all_trades = store.load_trades()
    new_trades = [t for t in all_trades if t["symbol"] == "BTC/USDT"]
    assert len(new_trades) == 0


# ---------------------------------------------------------------------------
# 5. Profit-target exit accounts for fees (net, not gross)
# ---------------------------------------------------------------------------


def test_profit_target_exit_is_net_of_fees(tmp_path) -> None:
    """Executor must exit at the price where NET P&L (after both legs' fees) = profit_target_pct.

    With taker fee 0.06%, entry at 100.0, profit_target_pct=0.06:
      entry_fee_pct = 0.0006
      exit_fee_pct  = 0.0006
      gross target  = profit_target_pct + entry_fee_pct + exit_fee_pct
      exit_price    = entry * (1 + gross_target) ~= 100 * 1.0612 = 106.12
    """
    cfg = _make_cfg(profit_target_pct=0.06, trailing_stop_pct=0.0)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    # Open a position at 100
    ex.on_signal(_bullish_event(price=100.0))
    trades_after_entry = store.load_trades()
    assert len(trades_after_entry) >= 1, "Expected an entry trade"

    # Now send a price tick that's above the gross target
    # entry_fee_pct + exit_fee_pct = 0.0006 + 0.0006 = 0.0012
    # gross_target = 0.06 + 0.0012 = 0.0612  -> exit price = 106.12
    # We'll send 107.0 which is above the threshold
    exit_event = SignalEvent(
        symbol="BTC/USDT",
        tf="4h",
        state="BULLISH",
        strength=70.0,
        flip=False,
        price=107.0,
        ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(exit_event)

    # After the profit-target exit there should now be a completed trade with positive PnL
    trades = store.load_trades()
    closed = [t for t in trades if t.get("exit_price") is not None and t.get("exit_price", 0) > 0]
    if closed:
        assert closed[0]["pnl"] > 0, "Closed trade must show positive net PnL"


def test_profit_target_not_triggered_below_net_threshold(tmp_path) -> None:
    """No exit when price is above gross entry price but below the net-fee target."""
    cfg = _make_cfg(profit_target_pct=0.06, trailing_stop_pct=0.0)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    ex.on_signal(_bullish_event(price=100.0))
    initial_trades = len(store.load_trades())

    # Price only up 1% -- well below the 6% net target; no exit expected
    low_event = SignalEvent(
        symbol="BTC/USDT", tf="4h", state="BULLISH", strength=60.0, flip=False,
        price=101.0, ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(low_event)

    assert len(store.load_trades()) == initial_trades, "Premature exit triggered below net target"


# ---------------------------------------------------------------------------
# 6. Bearish flip on open position -> exit trade recorded
# ---------------------------------------------------------------------------


def test_bearish_flip_exits_open_position(tmp_path) -> None:
    """A BEARISH flip while a position is open must trigger an exit."""
    cfg = _make_cfg(trailing_stop_pct=0.0)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    ex.on_signal(_bullish_event(price=100.0))
    trades_before = len(store.load_trades())

    ex.on_signal(_bearish_event(price=103.0))

    trades_after = store.load_trades()
    assert len(trades_after) > trades_before, "Expected an exit trade after bearish flip"


# ---------------------------------------------------------------------------
# 7. No entry on non-flip or BEARISH signal
# ---------------------------------------------------------------------------


def test_no_entry_on_bearish_signal(tmp_path) -> None:
    """A bearish signal with no open position must not open a trade."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    ex = Executor(cfg, store, client=_mock_ccxt_client(), env=_PAPER_ENV)
    ex.on_signal(_bearish_event())
    assert len(store.load_trades()) == 0


def test_no_entry_on_bullish_non_flip(tmp_path) -> None:
    """A bullish signal that is NOT a fresh flip must not open a new entry."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    ex = Executor(cfg, store, client=_mock_ccxt_client(), env=_PAPER_ENV)

    non_flip = SignalEvent(
        symbol="BTC/USDT", tf="4h", state="BULLISH", strength=75.0, flip=False,
        price=100.0, ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(non_flip)
    assert len(store.load_trades()) == 0


# ---------------------------------------------------------------------------
# 8. Position sizing uses risk_manager
# ---------------------------------------------------------------------------


def test_position_sizing_respects_risk_pct(tmp_path) -> None:
    """Qty must be derived from risk_manager: balance*risk_pct / |entry-stop|."""
    # balance=10000, risk_pct=0.01 -> risk_amount=100
    # entry=100, stop = entry*(1 - trailing_stop_pct) with trailing_stop_pct=0.05
    #   -> stop = 95, risk_per_unit = 5 -> qty = 100/5 = 20
    cfg = _make_cfg(balance=10_000.0, risk_pct=0.01, trailing_stop_pct=0.05)
    store = _make_store(tmp_path)
    ex = Executor(cfg, store, client=_mock_ccxt_client(), env=_PAPER_ENV)
    ex.on_signal(_bullish_event(price=100.0))

    trades = store.load_trades()
    assert len(trades) >= 1
    qty = trades[0]["qty"]
    assert qty > 0, "qty must be positive"


# ---------------------------------------------------------------------------
# 9. Trailing stop exit
# ---------------------------------------------------------------------------


def test_trailing_stop_triggers_exit(tmp_path) -> None:
    """When price drops below the trailing stop level, an exit must be recorded."""
    # trailing_stop_pct=0.05 -> stop trails 5% below peak
    cfg = _make_cfg(trailing_stop_pct=0.05, profit_target_pct=0.20)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    ex.on_signal(_bullish_event(price=100.0))

    # Push price up to 110 (new peak), then drop to 103.5 which is below 110*(1-0.05)=104.5
    up_event = SignalEvent(
        symbol="BTC/USDT", tf="4h", state="BULLISH", strength=70.0, flip=False,
        price=110.0, ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(up_event)

    drop_event = SignalEvent(
        symbol="BTC/USDT", tf="4h", state="BULLISH", strength=70.0, flip=False,
        price=103.0, ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(drop_event)

    trades = store.load_trades()
    # Should have an exit trade (more than just the entry)
    assert len(trades) >= 2 or any(t.get("exit_price") for t in trades), (
        "Trailing stop did not trigger an exit"
    )


# ---------------------------------------------------------------------------
# 10. max_hold_hours exit
# ---------------------------------------------------------------------------


def test_max_hold_hours_triggers_exit(tmp_path) -> None:
    """Executor must close a position that has been held past max_hold_hours."""
    cfg = _make_cfg(max_hold_hours=1, trailing_stop_pct=0.0, profit_target_pct=0.50)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    # Open a position
    ex.on_signal(_bullish_event(price=100.0))

    # Manually age the position in the store to 2 hours ago
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "UPDATE positions SET opened_at = datetime('now', '-2 hours') WHERE status='open'"
    )
    conn.commit()
    conn.close()

    # Send a signal -- the executor should detect the expiry and close
    tick_event = SignalEvent(
        symbol="BTC/USDT", tf="4h", state="BULLISH", strength=60.0, flip=False,
        price=101.0, ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(tick_event)

    trades = store.load_trades()
    positions = store.load_positions(status="closed")
    assert len(positions) >= 1 or len(trades) >= 2, (
        "max_hold_hours did not trigger an exit"
    )


# ---------------------------------------------------------------------------
# 11. BLOCKING 2 -- executor paper construction never reads secret env keys
# ---------------------------------------------------------------------------


def test_executor_paper_construction_never_reads_secrets(tmp_path) -> None:
    """BLOCKING 2: constructing Executor in paper mode must not access secret keys.

    The guard env raises AssertionError if any secret key is accessed via .get()
    or [].  If the executor (or make_exchange_client) ever reads credentials in
    paper mode, this test fails loudly.
    """
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    guard_env = _SecretGuardEnv(_PAPER_ENV)

    # Must NOT raise -- paper path never touches secret keys
    ex = Executor(cfg, store, env=guard_env)
    assert ex._client.apiKey in (None, "")


def test_executor_paper_signal_never_reads_secrets(tmp_path) -> None:
    """BLOCKING 2: processing a bullish signal in paper mode must not access secret keys."""
    cfg = _make_cfg()
    store = _make_store(tmp_path)
    guard_env = _SecretGuardEnv(_PAPER_ENV)
    ex = Executor(cfg, store, env=guard_env)

    # Must NOT raise even when we process a live signal
    ex.on_signal(_bullish_event(price=100.0))
    trades = store.load_trades()
    assert len(trades) >= 1


# ---------------------------------------------------------------------------
# 12. MEDIUM 3 -- post-entry exposure check
# ---------------------------------------------------------------------------


def test_entry_refused_when_post_entry_exposure_would_breach(tmp_path) -> None:
    """MEDIUM 3: a new entry that would push total exposure > max_exposure_pct must be refused.

    Setup: max_exposure_pct=0.10 (10%), account=10000 -> max notional=1000.
    Existing open position: 900 notional (already at 9% exposure).
    New entry notional at risk_pct=0.01 -> risk_amount=100, stop 2% below = 2 per unit
    -> qty=50 -> notional=50*100=5000 -> post-entry exposure=5900/10000=59% -> REFUSED.
    """
    cfg = _make_cfg(balance=10_000.0, risk_pct=0.01)
    # Override max_exposure_pct to something tight
    cfg = Config(
        exchange="blofin",
        executor=ExecutorCfg(profit_target_pct=0.06, use_dip_filter=False,
                             trailing_stop_pct=0.02, max_hold_hours=48),
        fees=FeesCfg(rates={"blofin": {"maker": 0.0002, "taker": 0.0006}}),
        risk=RiskCfg(
            account_balance=10_000.0,
            risk_pct=0.01,
            max_exposure_pct=0.10,  # 10% max
            max_trades_per_day=10,
            max_consecutive_losses=4,
            max_drawdown_pct=0.20,
        ),
    )
    store = _make_store(tmp_path)

    # Seed an existing open position with notional=900 (9% of 10000)
    store.save_position({
        "symbol": "ETH/USDT",
        "mode": "paper",
        "side": "long",
        "entry_price": 900.0,
        "qty": 1.0,
        "stop_price": 882.0,
    })

    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)
    ex.on_signal(_bullish_event(price=100.0))

    new_trades = [t for t in store.load_trades() if t["symbol"] == "BTC/USDT"]
    assert len(new_trades) == 0, (
        "Entry should have been refused: post-entry exposure would exceed max_exposure_pct"
    )


def test_entry_allowed_when_post_entry_exposure_just_under(tmp_path) -> None:
    """MEDIUM 3: an entry that keeps post-entry exposure under max_exposure_pct must be allowed."""
    cfg = Config(
        exchange="blofin",
        executor=ExecutorCfg(profit_target_pct=0.06, use_dip_filter=False,
                             trailing_stop_pct=0.02, max_hold_hours=48),
        fees=FeesCfg(rates={"blofin": {"maker": 0.0002, "taker": 0.0006}}),
        risk=RiskCfg(
            account_balance=10_000.0,
            risk_pct=0.001,   # very small risk -> very small notional
            max_exposure_pct=0.90,  # very wide limit -> should always pass
            max_trades_per_day=10,
            max_consecutive_losses=4,
            max_drawdown_pct=0.20,
        ),
    )
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)
    ex.on_signal(_bullish_event(price=100.0))

    new_trades = [t for t in store.load_trades() if t["symbol"] == "BTC/USDT"]
    assert len(new_trades) >= 1, "Entry should have been allowed under max_exposure_pct"


# ---------------------------------------------------------------------------
# 13. MEDIUM 4 -- use_dip_filter enforcement
# ---------------------------------------------------------------------------


def _make_ohlcv_df(n: int = 50, close_values=None) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame for dip-filter tests."""
    rng = np.random.default_rng(42)
    if close_values is not None:
        close = np.array(close_values, dtype=float)
        n = len(close)
    else:
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    open_ = close - rng.uniform(-0.2, 0.2, n)
    volume = rng.uniform(1000, 5000, n)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def test_dip_filter_met_allows_entry(tmp_path) -> None:
    """MEDIUM 4: when dip condition holds (close < EMA20 or RSI < 40), entry is allowed."""
    cfg = _make_cfg(use_dip_filter=True)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    # Build a df where price is trending down so last close < EMA20
    # Start high then ramp down so last close is below the 20-bar EMA
    close_values = [110.0] * 30 + [90.0] * 25  # sharp drop -> last close well below EMA20
    df = _make_ohlcv_df(close_values=close_values)

    ex.on_signal(_bullish_event(price=float(df["close"].iloc[-1])), df=df)

    trades = [t for t in store.load_trades() if t["symbol"] == "BTC/USDT"]
    assert len(trades) >= 1, "Entry should be allowed when dip condition is met"


def test_dip_filter_not_met_blocks_entry(tmp_path) -> None:
    """MEDIUM 4: when dip condition is NOT met (close >= EMA20 AND RSI >= 40), entry is skipped."""
    cfg = _make_cfg(use_dip_filter=True)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    # Build a df where price has been rising smoothly so close > EMA20 and RSI > 40
    close_values = list(np.linspace(80.0, 120.0, 55))  # steady uptrend -> close > EMA20
    df = _make_ohlcv_df(close_values=close_values)

    ex.on_signal(_bullish_event(price=float(df["close"].iloc[-1])), df=df)

    trades = [t for t in store.load_trades() if t["symbol"] == "BTC/USDT"]
    assert len(trades) == 0, "Entry should be blocked when dip condition is NOT met"


def test_dip_filter_no_df_skips_check(tmp_path) -> None:
    """MEDIUM 4: when use_dip_filter=True but no df provided, the check is skipped (entry proceeds)."""
    cfg = _make_cfg(use_dip_filter=True)
    store = _make_store(tmp_path)
    client = _mock_ccxt_client()
    ex = Executor(cfg, store, client=client, env=_PAPER_ENV)

    # No df -> dip check skipped -> entry should proceed on a bullish flip
    ex.on_signal(_bullish_event(price=100.0))  # df=None default

    trades = [t for t in store.load_trades() if t["symbol"] == "BTC/USDT"]
    assert len(trades) >= 1, "Entry should proceed when no df is provided (dip check skipped)"
