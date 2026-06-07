"""Multi-symbol scanner agent.

Iterates a watchlist, computes Money Line signals for each symbol, applies
blacklist/whitelist, volume-surge, and minimum-strength filters, then returns
the top-N events ranked by strength descending.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from agents.signal_agent import get_money_line, latest_signal
from utils.config_schema import Config

logger = logging.getLogger(__name__)


@dataclass
class SignalEvent:
    """Lightweight signal descriptor produced by the scanner."""

    symbol: str
    tf: str
    state: str
    strength: float
    flip: bool
    price: float
    ts: pd.Timestamp


class Scanner:
    """Scan a list of symbols and return ranked SignalEvents.

    Parameters
    ----------
    cfg:
        Application config.  The ``scanner`` and ``watchlist`` sub-models drive
        filtering logic; ``data.primary_timeframe`` is used for the ``tf`` field.
    fetcher:
        Callable ``(symbol: str, tf: str, limit: int) -> pd.DataFrame`` that
        returns an OHLCV DataFrame.  Injected so tests can pass a fake without
        network access.
    signal_fn:
        Optional override for the Money Line computation.  Defaults to
        ``agents.signal_agent.get_money_line``.  Injected for testing.
    """

    def __init__(
        self,
        cfg: Config,
        fetcher: Callable,
        signal_fn: Callable = None,
    ) -> None:
        self._cfg = cfg
        self._fetcher = fetcher
        self._signal_fn = signal_fn if signal_fn is not None else get_money_line

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scan(self, symbols: list[str]) -> list[SignalEvent]:
        """Scan *symbols* and return filtered, ranked SignalEvents.

        Processing per symbol (BLOCKING 2: fresh-flip gate; BLOCKING 3: per-symbol isolation):
        1. Apply blacklist / whitelist.
        2. Fetch OHLCV.
        3. Compute Money Line.
        4. Apply volume-surge filter (last bar volume > surge_mult * rolling avg).
        5. Apply fresh-flip gate: skip the symbol if ``latest_signal(out)["flip"]``
           is not True.  The scanner contract is to surface RECENT direction
           changes; symbols in a sustained trend are excluded here.
        6. Apply min_strength filter.
        7. Collect the event.

        Steps 2-7 are wrapped in a single try/except so that one malformed or
        problematic symbol cannot abort the entire scan.

        Returns events sorted by strength descending, capped at rank_top_n.
        """
        scanner_cfg = self._cfg.scanner
        watchlist_cfg = getattr(self._cfg, "watchlist", None)
        blacklist: list[str] = getattr(watchlist_cfg, "blacklist", []) if watchlist_cfg else []
        whitelist: list[str] = getattr(watchlist_cfg, "whitelist", []) if watchlist_cfg else []
        tf = self._cfg.data.primary_timeframe
        limit = self._cfg.data.ohlcv_limit

        events: list[SignalEvent] = []

        for sym in symbols:
            # ---- Blacklist / whitelist guard --------------------------------
            if sym in blacklist:
                continue
            if whitelist and sym not in whitelist:
                continue

            # ---- Per-symbol isolation (BLOCKING 3) -------------------------
            # Any exception from fetch, signal computation, or filtering logs
            # a warning and moves on to the next symbol.
            try:
                # ---- Fetch OHLCV -------------------------------------------
                df = self._fetcher(sym, tf, limit)

                # ---- Money Line computation (config-driven) -----------------
                cfg = self._cfg
                out = self._signal_fn(
                    df,
                    length=cfg.signal.money_line_length,
                    smooth=cfg.signal.smooth,
                    slope_len=cfg.signal.slope_len,
                )

                # ---- Volume-surge filter ------------------------------------
                # Last bar volume must exceed surge_mult * rolling-20 mean.
                # We compute the mean on the window *excluding* the last bar so
                # that a single high-volume bar cannot inflate its own baseline.
                vol = out["volume"]
                if len(vol) >= 2:
                    rolling_avg = vol.iloc[:-1].rolling(min(20, len(vol) - 1)).mean().iloc[-1]
                    if pd.isna(rolling_avg) or rolling_avg <= 0:
                        # Fall back to simple mean of all bars if window too short
                        rolling_avg = vol.mean()
                    last_vol = vol.iloc[-1]
                    if last_vol <= scanner_cfg.volume_surge_mult * rolling_avg:
                        continue

                # ---- Fresh-flip gate (BLOCKING 2) ---------------------------
                sig = latest_signal(
                    out,
                    use_rsi_filter=cfg.signal.use_rsi_filter,
                    use_adx_filter=cfg.signal.use_adx_filter,
                )
                if not sig["flip"]:
                    continue

                # ---- min_strength filter ------------------------------------
                if sig["strength"] < scanner_cfg.min_strength:
                    continue

                # ---- VWAP price-position filter -----------------------------
                # Bullish flips require close > VWAP; bearish flips require
                # close < VWAP.  Computed over vwap_length bars using typical
                # price (H+L+C)/3 volume-weighted, matching spec exactly.
                if scanner_cfg.use_vwap_filter:
                    vlen = scanner_cfg.vwap_length
                    tp = (out["high"] + out["low"] + out["close"]) / 3.0
                    vwap = (
                        (tp * out["volume"]).rolling(vlen).sum()
                        / out["volume"].rolling(vlen).sum()
                    )
                    last_close = out["close"].iloc[-1]
                    last_vwap = vwap.iloc[-1]
                    if not pd.isna(last_vwap):
                        if sig["state"] == "BULLISH" and last_close <= last_vwap:
                            continue
                        if sig["state"] == "BEARISH" and last_close >= last_vwap:
                            continue

                events.append(
                    SignalEvent(
                        symbol=sym,
                        tf=tf,
                        state=sig["state"],
                        strength=sig["strength"],
                        flip=sig["flip"],
                        price=sig["price"],
                        ts=out.index[-1] if isinstance(out.index, pd.DatetimeIndex) else pd.Timestamp.utcnow(),
                    )
                )

            except Exception as exc:  # noqa: BLE001
                logger.warning("Scanner: skipping %s - error: %s", sym, exc)
                continue

        # ---- Rank by strength descending, cap at top-N ---------------------
        events.sort(key=lambda e: e.strength, reverse=True)
        return events[: scanner_cfg.rank_top_n]
