"""CryptoChucker Agents orchestrator.

Wires all agents together, runs one scan->execute->persist->alert cycle via
``run_once()``, and schedules it on repeat via APScheduler.

Usage
-----
    python main.py                    # start the scheduler (Ctrl-C to stop)
    python -c "from main import build_app; ..."   # programmatic / test use

Per-agent isolation
-------------------
Every agent call inside ``run_once()`` is wrapped in its own try/except so that
a single agent failure (network outage, bad data, alert transport down) is
logged and skipped without aborting the cycle.  The cycle always records an
equity snapshot at the end regardless of partial failures.
"""
from __future__ import annotations

import logging
import signal
import sys
from typing import Any, Callable

import pandas as pd

from utils.config_schema import Config, load_config
from utils.logging_config import setup_logging
from utils.store import Store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Watchlist helper (fall back to a tiny default when watchlist.json missing)
# ---------------------------------------------------------------------------

_DEFAULT_WATCHLIST = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]


def _load_watchlist(cfg: Config) -> list[str]:
    """Return the watchlist from config, falling back gracefully."""
    try:
        from utils.helpers import load_watchlist  # noqa: PLC0415

        wl_cfg = cfg.watchlist
        if wl_cfg.source == "file":
            return load_watchlist(wl_cfg.file)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Watchlist load failed (%s), using default symbols", exc)
    return list(_DEFAULT_WATCHLIST)


# ---------------------------------------------------------------------------
# App class
# ---------------------------------------------------------------------------


class _App:
    """Orchestrator application object returned by ``build_app()``.

    Parameters
    ----------
    cfg:
        Validated application config.
    scanner:
        Configured Scanner instance.
    executor:
        Configured Executor instance.
    store:
        Initialised Store instance.
    alert_agent:
        AlertAgent (or compatible mock) for fan-out notifications.
    llm_copilot_enabled:
        Whether the optional LLM co-pilot is enabled.
    """

    def __init__(
        self,
        cfg: Config,
        scanner: Any,
        executor: Any,
        store: Store,
        alert_agent: Any,
        fetcher: Callable,
        llm_copilot_enabled: bool = False,
    ) -> None:
        self._cfg = cfg
        self._scanner = scanner
        self._executor = executor
        self._store = store
        self._alert_agent = alert_agent
        self._fetcher = fetcher
        self._llm_copilot_enabled = llm_copilot_enabled

    # ------------------------------------------------------------------
    # Public: single cycle
    # ------------------------------------------------------------------

    def run_once(self) -> None:
        """Execute ONE full orchestration cycle.

        Steps
        -----
        1. Load watchlist symbols.
        2. Scan all symbols via the Scanner (per-symbol isolation is inside Scanner).
        3. For each ranked SignalEvent:
           a. Persist the signal row.
           b. (Optional) LLM co-pilot validation gate.
           c. Fetch fresh OHLCV for this symbol so the dip filter can run.
           d. Run the Executor with the OHLCV df (paper fill / exit logic).
           e. Send an alert (per-agent isolated).
        4. Record a cycle equity snapshot that reflects real PnL.

        Any exception at any step is caught and logged; the cycle does not abort.
        """
        logger.info("run_once: starting cycle")

        cfg = self._cfg
        tf = cfg.data.primary_timeframe
        limit = cfg.data.ohlcv_limit

        # 1. Watchlist
        try:
            symbols = _load_watchlist(cfg)
        except Exception as exc:  # noqa: BLE001
            logger.error("run_once: watchlist load failed: %s", exc)
            symbols = list(_DEFAULT_WATCHLIST)

        # 2. Scan
        try:
            events = self._scanner.scan(symbols)
            logger.info("run_once: scanner returned %d signal(s)", len(events))
        except Exception as exc:  # noqa: BLE001
            logger.error("run_once: scanner failed: %s", exc)
            events = []

        # Track the most recently fetched df per symbol so the equity calculation
        # can use a fresh price without an extra network round-trip.
        latest_dfs: dict[str, pd.DataFrame] = {}

        # 3. Process each event
        for event in events:
            # 3a. Persist signal
            try:
                self._store.save_signal(
                    {
                        "symbol": event.symbol,
                        "tf": event.tf,
                        "state": event.state,
                        "strength": event.strength,
                        "price": event.price,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once: save_signal failed for %s: %s", event.symbol, exc)

            # 3b. Optional LLM co-pilot gate (skip if disabled or on error)
            if self._llm_copilot_enabled:
                try:
                    from utils.llm_copilot import validate  # noqa: PLC0415

                    sig_dict = {
                        "state": event.state,
                        "strength": event.strength,
                        "flip": event.flip,
                        "price": event.price,
                    }
                    verdict = validate(sig_dict, cfg)
                    if verdict.get("decision", "SKIP").upper() == "AVOID":
                        logger.info(
                            "run_once: LLM co-pilot AVOID for %s (reason: %s)",
                            event.symbol,
                            verdict.get("reason", ""),
                        )
                        continue
                except Exception as exc:  # noqa: BLE001
                    logger.warning("run_once: LLM co-pilot error for %s: %s", event.symbol, exc)

            # 3c. Fetch OHLCV so the executor's dip filter can run.
            # The scanner already fetched data for this symbol, but it does not
            # expose the raw DataFrames through its public API.  A small extra
            # fetch per ranked event is acceptable (events are top-N).
            event_df: pd.DataFrame | None = None
            try:
                event_df = self._fetcher(event.symbol, tf, limit)
                latest_dfs[event.symbol] = event_df
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "run_once: OHLCV fetch failed for %s (dip filter will be skipped): %s",
                    event.symbol,
                    exc,
                )

            # 3d. Executor -- pass the df so the dip filter actually runs.
            try:
                self._executor.on_signal(event, df=event_df)
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once: executor failed for %s: %s", event.symbol, exc)

            # 3e. Alert
            try:
                self._alert_agent.send(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once: alert failed for %s: %s", event.symbol, exc)

        # 4. Equity snapshot (always, even if no events).
        # Compute CURRENT equity = account_balance + realized_pnl + unrealized_pnl
        # so the dashboard reflects real PnL rather than the bare config constant.
        #
        # IMPORTANT: unrealized PnL must cover ALL open positions, not just those
        # whose symbol produced a signal this cycle (latest_dfs only contains
        # symbols that fired events).  For every open position whose symbol is NOT
        # already in latest_dfs we fetch a fresh OHLCV bar now so quiet-cycle
        # positions are still marked to market.
        try:
            account_balance = cfg.risk.account_balance

            # Realized PnL: sum pnl column over all closed trade rows (buy-side rows
            # have pnl=None; sell-side rows carry the net figure).
            realized_pnl = sum(
                t["pnl"] for t in self._store.load_trades() if t.get("pnl") is not None
            )

            # Unrealized PnL: for each open position, mark to the latest close.
            # Prefer prices already fetched this cycle (latest_dfs); for symbols not
            # in latest_dfs, fetch now so quiet cycles still reflect all open exposure.
            unrealized_pnl = 0.0
            open_positions = self._store.load_positions(status="open")
            for pos in open_positions:
                sym = pos.get("symbol")
                entry_price = pos.get("entry_price") or 0.0
                qty = pos.get("qty") or 0.0
                if not sym:
                    continue
                # Use already-fetched df when available; otherwise fetch a fresh one.
                if sym not in latest_dfs:
                    try:
                        fetched_df = self._fetcher(sym, tf, limit)
                        latest_dfs[sym] = fetched_df
                    except Exception as fetch_exc:  # noqa: BLE001
                        logger.warning(
                            "run_once: equity mark fetch failed for %s (contributing 0): %s",
                            sym,
                            fetch_exc,
                        )
                        # contribute 0 for this position; do not abort
                try:
                    last_close = float(latest_dfs[sym]["close"].iloc[-1])
                    unrealized_pnl += (last_close - entry_price) * qty
                except Exception:  # noqa: BLE001
                    pass  # no price available; contribute 0

            cycle_equity = account_balance + realized_pnl + unrealized_pnl
            self._store.save_equity(cycle_equity)
        except Exception as exc:  # noqa: BLE001
            logger.error("run_once: equity snapshot failed: %s", exc)

        logger.info("run_once: cycle complete")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_app(
    cfg: Config,
    fetcher: Callable | None = None,
    store: Store | None = None,
    alert_agent: Any | None = None,
) -> _App:
    """Wire all agents and return the orchestrator app.

    Parameters
    ----------
    cfg:
        Validated application config.
    fetcher:
        Optional injected callable ``(symbol, tf, limit) -> pd.DataFrame``.
        When ``None`` a real ``DataFetcher`` is constructed (requires network).
    store:
        Optional pre-initialised ``Store``.  When ``None`` a new Store is
        created at ``cfg.persistence.sqlite_path`` and ``init()`` is called.
    alert_agent:
        Optional injected alert agent (for testing / mocking).  When ``None``
        a real ``AlertAgent`` is constructed from config.

    Returns
    -------
    _App
        Orchestrator object with a ``run_once()`` method.
    """
    # Store
    if store is None:
        store = Store(cfg.persistence.sqlite_path)
        store.init()

    # DataFetcher
    if fetcher is None:
        from utils.data_fetcher import DataFetcher  # noqa: PLC0415

        _df_obj = DataFetcher(exchange=cfg.exchange)
        fetcher = _df_obj.fetch_ohlcv

    # Scanner
    from agents.scanner_agent import Scanner  # noqa: PLC0415

    scanner = Scanner(cfg, fetcher)

    # Executor: pass env=None so it reads the real process environment via the
    # existing safety functions (live_enabled / make_exchange_client / guard_live).
    # Those functions default PAPER_TRADING -> "true" and ENABLE_LIVE_TRADING -> "false"
    # when the keys are absent, so the system is paper-by-default without any
    # hard-coding here.  Live mode requires BOTH env vars to be set to their exact
    # enabling strings in the process environment at run time.
    from agents.executor_agent import Executor  # noqa: PLC0415

    executor = Executor(cfg, store, env=None)

    # AlertAgent
    if alert_agent is None:
        from agents.alert_agent import AlertAgent  # noqa: PLC0415

        alert_agent = AlertAgent(cfg)

    # LLM co-pilot flag
    llm_enabled = cfg.llm_copilot.enabled

    return _App(
        cfg=cfg,
        scanner=scanner,
        executor=executor,
        store=store,
        alert_agent=alert_agent,
        fetcher=fetcher,
        llm_copilot_enabled=llm_enabled,
    )


# ---------------------------------------------------------------------------
# Scheduler entry point
# ---------------------------------------------------------------------------


def run(cfg: Config | None = None) -> None:
    """Start the APScheduler loop; block until SIGINT/SIGTERM.

    Parameters
    ----------
    cfg:
        Application config.  When ``None`` ``load_config("config.yaml")`` is called.
    """
    if cfg is None:
        cfg = load_config("config.yaml")

    setup_logging()
    logger.info("CryptoChucker Agents starting (paper=%s)", cfg.paper_trading)

    app = build_app(cfg)

    from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: PLC0415

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        app.run_once,
        "interval",
        minutes=cfg.scanner.interval_minutes,
        id="run_once",
    )

    # Graceful shutdown
    def _shutdown(signum, frame):  # noqa: ANN001, ARG001
        logger.info("Shutdown signal received, stopping scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info(
        "Scheduler started: run_once every %d minutes",
        cfg.scanner.interval_minutes,
    )

    # Run once immediately on startup then wait for interval
    app.run_once()
    scheduler.start()


# ---------------------------------------------------------------------------
# __main__ block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run()
