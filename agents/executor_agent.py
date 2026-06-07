"""Paper executor agent with fail-closed live-trading guard.

Architecture
------------
``Executor`` consumes ``SignalEvent`` objects (or compatible dicts) from the
scanner and applies config-driven trade-management rules:

Entry rules
~~~~~~~~~~~
- Only on a BULLISH fresh flip (``event.flip is True`` and ``event.state == "BULLISH"``).
- Optional dip filter (``use_dip_filter``): if enabled, the price must be
  below the 20-bar EMA of the last session (TODO: wired in Stage 6 when the
  executor receives a DataFrame; currently accepted as a flag but not computed
  here without OHLCV context).  The filter is skipped gracefully when no OHLCV
  is provided.
- Blocked when any of these hold: ``drawdown_breached``, daily trade cap hit,
  max exposure reached, consecutive-loss cap hit.

Exit rules
~~~~~~~~~~
- Profit target: exit when the current price yields NET P&L >= profit_target_pct
  (gross target = profit_target_pct + entry_fee_pct + exit_fee_pct).
- Bearish flip: exit immediately on a BEARISH flip while holding.
- Trailing stop (when trailing_stop_pct > 0): exit when price drops more than
  trailing_stop_pct below the running peak since entry.
- Max hold: exit when the position has been open longer than max_hold_hours.

Paper vs live
~~~~~~~~~~~~~
- Paper mode (default / double gate not fully open):
  ``paper_fill`` simulates the fill and writes trade/position/equity rows to
  ``Store``.  The ccxt client is never called; ``create_order`` is never
  invoked.
- Live path: ``_live_order`` calls ``guard_live()`` as its FIRST statement.
  If the guard raises ``LiveTradingDisabled`` the call stack unwinds immediately
  and no exchange interaction occurs.  The live path is therefore structurally
  unreachable in paper mode even if called directly.

Credential isolation
~~~~~~~~~~~~~~~~~~~~
The executor accepts an injected ``client`` object.  When not injected it calls
``make_exchange_client(exchange, env)`` which returns a public/unauthenticated
client in paper mode.  Credentials are NEVER loaded or passed in paper mode.
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

from utils.config_schema import Config
from utils.fees import fee
from utils.risk_manager import check_limits, drawdown_breached, position_size
from utils.safety import guard_live, make_exchange_client
from utils.store import Store

logger = logging.getLogger(__name__)


@dataclass
class _Position:
    """In-memory representation of an open position."""

    symbol: str
    side: str          # "long" | "short"
    entry_price: float
    qty: float
    stop_price: float  # initial stop / floor for trailing
    peak_price: float  # highest price seen since entry (for trailing stop)
    opened_at: datetime.datetime
    store_id: int      # FK to positions.id


class Executor:
    """Paper/live executor with fail-closed live-trading guard.

    Parameters
    ----------
    cfg:
        Application config with ``.executor``, ``.fees``, ``.risk``, and
        ``.exchange`` sub-models.
    store:
        Initialised ``Store`` instance for persisting fills/equity.
    client:
        Optional injected ccxt exchange object.  When ``None``,
        ``make_exchange_client`` is called with the resolved env; in paper mode
        this always returns a public/unauthenticated client.
    env:
        Explicit environment dict for the safety gate.  ``None`` uses
        ``os.environ`` (production).  Pass a dict in tests to avoid relying on
        the real process environment.
    """

    def __init__(
        self,
        cfg: Config,
        store: Store,
        client: Any = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._cfg = cfg
        self._store = store
        # Store env as-is (may be None).  Never copy os.environ -- the safety
        # functions accept None and read only the two gate keys from os.environ
        # directly, so secret credential vars are never touched on the default path.
        self._env: dict[str, str] | None = env
        # Credential isolation: in paper mode this is always a public client.
        self._client = client if client is not None else make_exchange_client(cfg.exchange, self._env)
        # In-memory state (reset across runs; store is the source of truth for persistence)
        self._positions: dict[str, _Position] = {}  # symbol -> Position
        self._consecutive_losses: int = 0
        self._today: str = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def on_signal(self, event: Any, df: "pd.DataFrame | None" = None) -> None:
        """Process one signal event (SignalEvent or compatible dict).

        Dispatch order:
          1. Check max-hold expiry on any open position for this symbol.
          2. If holding: check trailing stop, profit target, bearish-flip exit.
          3. If not holding and signal is a fresh bullish flip: attempt entry.

        Parameters
        ----------
        event:
            A SignalEvent or dict-like object with symbol/state/flip/price.
        df:
            Optional OHLCV DataFrame (columns: open, high, low, close, volume).
            Required for the dip filter (``cfg.executor.use_dip_filter``).
            When ``None``, the dip filter is skipped gracefully even if enabled.

        All exceptions are caught and logged so one bad signal cannot crash
        the orchestrator loop.
        """
        try:
            symbol = _attr(event, "symbol")
            state = _attr(event, "state")
            flip = _attr(event, "flip")
            price = float(_attr(event, "price"))

            # 1. Check time-based exit for existing position
            self._check_max_hold(symbol, price)

            # 2. Manage open position
            if symbol in self._positions:
                self._manage_position(symbol, state, flip, price)
                return

            # 3. Entry gate
            if state == "BULLISH" and flip:
                self._attempt_entry(symbol, price, event, df=df)

        except Exception:  # noqa: BLE001
            logger.exception("Executor error processing signal for %s", _attr(event, "symbol", "?"))

    # ------------------------------------------------------------------
    # Private: entry
    # ------------------------------------------------------------------

    def _attempt_entry(self, symbol: str, price: float, event: Any, df: "pd.DataFrame | None" = None) -> None:
        """Evaluate all entry guards and open a paper fill if all pass.

        Parameters
        ----------
        symbol:
            Market symbol (e.g. "BTC/USDT").
        price:
            Current price from the signal event.
        event:
            Original signal event (for logging).
        df:
            Optional OHLCV DataFrame for the dip filter.  When ``None`` the dip
            filter is skipped even if ``cfg.executor.use_dip_filter`` is True
            (documented graceful skip -- no OHLCV context available).
        """
        cfg = self._cfg
        exc_cfg = cfg.executor
        risk_cfg = cfg.risk

        # --- Drawdown guard ---
        equity_history = [r["balance"] for r in reversed(self._store.load_equity())]
        if equity_history and drawdown_breached(equity_history, risk_cfg.max_drawdown_pct):
            logger.warning("Executor: entry blocked for %s -- drawdown limit breached", symbol)
            return

        # --- Dip filter (optional; skipped gracefully when df is None) ---
        # When use_dip_filter is True AND an OHLCV DataFrame is provided, only
        # enter on a bullish flip when the dip condition holds:
        #   last close < EMA(close, 20)  OR  RSI(close, 14) < 40
        # If no df is provided the check is skipped (OHLCV context not available).
        if exc_cfg.use_dip_filter and df is not None:
            close = df["close"]
            ema20 = close.ewm(span=20, adjust=False).mean()
            delta = close.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = (-delta).where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1.0 / 14, adjust=False).mean()
            avg_loss = loss.ewm(alpha=1.0 / 14, adjust=False).mean()
            safe_loss = avg_loss.where(avg_loss != 0, float("nan"))
            rs = avg_gain / safe_loss
            rsi_series = (100.0 - 100.0 / (1.0 + rs)).fillna(50.0)
            last_close = float(close.iloc[-1])
            last_ema20 = float(ema20.iloc[-1])
            last_rsi = float(rsi_series.iloc[-1])
            dip_condition = last_close < last_ema20 or last_rsi < 40
            if not dip_condition:
                logger.info(
                    "Executor: dip filter blocked entry for %s "
                    "(close=%.6f ema20=%.6f rsi=%.1f)",
                    symbol, last_close, last_ema20, last_rsi,
                )
                return

        # --- Position sizing (needed for post-entry exposure check below) ---
        trailing_stop_pct = exc_cfg.trailing_stop_pct if exc_cfg.trailing_stop_pct > 0 else 0.02
        stop_price = price * (1.0 - trailing_stop_pct)
        qty = position_size(risk_cfg.account_balance, risk_cfg.risk_pct, price, stop_price)
        new_notional = price * qty

        # --- Daily cap + consecutive losses + POST-ENTRY exposure ---
        # Always re-read trades_today from the store so the cap is accurate
        # even if trades were added externally or the executor was restarted.
        trades_today = self._count_trades_today()
        # Exposure: sum open position notional / account balance AFTER this entry
        open_positions = self._store.load_positions(status="open")
        current_exposure_notional = sum(
            (pos.get("qty") or 0) * (pos.get("entry_price") or 0) for pos in open_positions
        )
        # Refuse when adding this position would EXCEED max_exposure_pct
        post_entry_exposure_pct = (current_exposure_notional + new_notional) / max(risk_cfg.account_balance, 1.0)

        limit = check_limits(trades_today, self._consecutive_losses, post_entry_exposure_pct, cfg)
        if not limit.allowed:
            logger.warning("Executor: entry blocked for %s -- %s", symbol, limit.reason)
            return

        # --- Paper fill ---
        self._paper_fill_entry(symbol, price, qty, stop_price)

    # ------------------------------------------------------------------
    # Private: position management (exit logic)
    # ------------------------------------------------------------------

    def _manage_position(self, symbol: str, state: str, flip: bool, price: float) -> None:
        """Evaluate exit conditions for an open position."""
        pos = self._positions[symbol]
        exc_cfg = self._cfg.executor

        # Update trailing peak
        if price > pos.peak_price:
            pos.peak_price = price

        # --- Bearish flip exit ---
        if state == "BEARISH" and flip:
            logger.info("Executor: bearish flip exit for %s at %.6f", symbol, price)
            self._paper_fill_exit(symbol, price, reason="bearish_flip")
            return

        # --- Profit target exit (net of fees) ---
        # Formula derivation (both legs taker-fee, per-unit basis):
        #   net_pnl / entry_price = exit_price*(1-t)/entry_price - (1+t) >= target
        #   => exit_price = entry_price * (1 + target + t) / (1 - t)
        # where t = taker rate.  This guarantees realized net PnL >= profit_target_pct
        # after BOTH entry and exit taker fees are deducted.
        fee_table = self._cfg.fees.rates
        taker = fee_table.get(self._cfg.exchange, {"taker": 0.001})["taker"]
        target = exc_cfg.profit_target_pct
        target_price = pos.entry_price * (1.0 + target + taker) / (1.0 - taker)
        if price >= target_price:
            logger.info("Executor: profit target exit for %s at %.6f (target %.6f)", symbol, price, target_price)
            self._paper_fill_exit(symbol, price, reason="profit_target")
            return

        # --- Trailing stop exit ---
        if exc_cfg.trailing_stop_pct > 0:
            trail_stop = pos.peak_price * (1.0 - exc_cfg.trailing_stop_pct)
            if price <= trail_stop:
                logger.info("Executor: trailing stop exit for %s at %.6f (trail %.6f)", symbol, price, trail_stop)
                self._paper_fill_exit(symbol, price, reason="trailing_stop")
                return

    def _check_max_hold(self, symbol: str, price: float) -> None:
        """Exit a position that has been held past max_hold_hours.

        Always cross-references the store's ``opened_at`` timestamp so that
        database-level changes (e.g. test time-travel via SQL UPDATE) are
        respected even when the position is already cached in memory.
        """
        max_hours = self._cfg.executor.max_hold_hours

        # Always check the DB authoritative timestamp for open positions
        open_db = self._store.load_positions(status="open")
        for row in open_db:
            if row["symbol"] != symbol:
                continue
            opened_at_str = row.get("opened_at", "")
            try:
                opened_at = datetime.datetime.strptime(opened_at_str, "%Y-%m-%d %H:%M:%S")
                age_hours = (datetime.datetime.utcnow() - opened_at).total_seconds() / 3600
                if age_hours > max_hours:
                    logger.info(
                        "Executor: max_hold_hours exit for %s at %.6f (held %.1fh)",
                        symbol, price, age_hours,
                    )
                    # Ensure in-memory position exists for the exit handler
                    if symbol not in self._positions:
                        self._positions[symbol] = _Position(
                            symbol=symbol,
                            side=row.get("side", "long"),
                            entry_price=row.get("entry_price", price),
                            qty=row.get("qty", 0.0),
                            stop_price=row.get("stop_price", 0.0),
                            peak_price=price,
                            opened_at=opened_at,
                            store_id=row["id"],
                        )
                    else:
                        # Update the cached opened_at from DB (handles test time-travel)
                        self._positions[symbol].opened_at = opened_at
                    self._paper_fill_exit(symbol, price, reason="max_hold")
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------
    # Private: paper fill
    # ------------------------------------------------------------------

    def _paper_fill_entry(self, symbol: str, price: float, qty: float, stop_price: float) -> None:
        """Simulate a paper buy fill and persist to store."""
        now = datetime.datetime.utcnow()
        fee_table = self._cfg.fees.rates
        notional = price * qty
        entry_fee_amt = fee(notional, self._cfg.exchange, taker=True, table=fee_table)

        # Write an open position to the store
        pos_id = self._store.save_position({
            "symbol": symbol,
            "mode": "paper",
            "side": "long",
            "entry_price": price,
            "qty": qty,
            "stop_price": stop_price,
        })

        # Write an entry trade row (side=buy, no exit_price yet)
        self._store.save_trade({
            "symbol": symbol,
            "mode": "paper",
            "side": "buy",
            "entry_price": price,
            "exit_price": None,
            "qty": qty,
            "pnl": None,
            "fee": entry_fee_amt,
            "opened_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        })

        # Snapshot equity
        self._store.save_equity(self._cfg.risk.account_balance)

        # Track in memory
        self._positions[symbol] = _Position(
            symbol=symbol,
            side="long",
            entry_price=price,
            qty=qty,
            stop_price=stop_price,
            peak_price=price,
            opened_at=now,
            store_id=pos_id,
        )
        logger.info("Executor PAPER BUY %s qty=%.4f at %.6f", symbol, qty, price)

    def _paper_fill_exit(self, symbol: str, price: float, reason: str = "exit") -> None:
        """Simulate a paper sell fill and persist to store."""
        if symbol not in self._positions:
            return

        pos = self._positions.pop(symbol)
        fee_table = self._cfg.fees.rates
        exit_notional = price * pos.qty
        exit_fee_amt = fee(exit_notional, self._cfg.exchange, taker=True, table=fee_table)
        entry_fee_amt = fee(pos.entry_price * pos.qty, self._cfg.exchange, taker=True, table=fee_table)

        gross_pnl = (price - pos.entry_price) * pos.qty
        net_pnl = gross_pnl - entry_fee_amt - exit_fee_amt

        # Close the position record
        self._store.close_position(pos.store_id)

        # Write an exit trade row
        self._store.save_trade({
            "symbol": symbol,
            "mode": "paper",
            "side": "sell",
            "entry_price": pos.entry_price,
            "exit_price": price,
            "qty": pos.qty,
            "pnl": net_pnl,
            "fee": exit_fee_amt,
            "opened_at": pos.opened_at.strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,
        })

        # Snapshot equity
        new_balance = self._cfg.risk.account_balance + net_pnl
        self._store.save_equity(new_balance)

        # Update consecutive loss counter
        if net_pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0

        logger.info(
            "Executor PAPER SELL %s qty=%.4f at %.6f net_pnl=%.4f reason=%s",
            symbol, pos.qty, price, net_pnl, reason,
        )

    # ------------------------------------------------------------------
    # Private: live order (BLOCKED in paper mode)
    # ------------------------------------------------------------------

    def _live_order(self, symbol: str, side: str, qty: float, price: float) -> dict:
        """Place a live order via ccxt.

        This method MUST call ``guard_live`` as its very first statement.
        It is therefore structurally unreachable in paper mode -- the guard
        raises ``LiveTradingDisabled`` before any exchange interaction.

        Args:
            symbol: Market symbol (e.g. "BTC/USDT").
            side:   "buy" or "sell".
            qty:    Order quantity.
            price:  Reference price (used for market orders; passed for logging).

        Returns:
            ccxt order dict.

        Raises:
            LiveTradingDisabled: Always raised in paper mode.
        """
        guard_live(self._env)  # MUST be first -- unreachable in paper mode
        return self._client.create_order(symbol, "market", side, qty)

    # ------------------------------------------------------------------
    # Private: helpers
    # ------------------------------------------------------------------

    def _count_trades_today(self) -> int:
        """Count trades opened today from the store (survives restarts)."""
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            all_trades = self._store.load_trades(limit=1000)
            return sum(
                1 for t in all_trades
                if (t.get("opened_at") or "").startswith(today)
            )
        except Exception:  # noqa: BLE001
            return 0


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Get an attribute from a dataclass or dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
