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
        llm_copilot_enabled: bool = False,
    ) -> None:
        self._cfg = cfg
        self._scanner = scanner
        self._executor = executor
        self._store = store
        self._alert_agent = alert_agent
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
           c. Run the Executor (paper fill / exit logic).
           d. Send an alert (per-agent isolated).
        4. Record an equity snapshot row.

        Any exception at any step is caught and logged; the cycle does not abort.
        """
        logger.info("run_once: starting cycle")

        # 1. Watchlist
        try:
            symbols = _load_watchlist(self._cfg)
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
                    verdict = validate(sig_dict, self._cfg)
                    if verdict.get("decision", "SKIP").upper() == "AVOID":
                        logger.info(
                            "run_once: LLM co-pilot AVOID for %s (reason: %s)",
                            event.symbol,
                            verdict.get("reason", ""),
                        )
                        continue
                except Exception as exc:  # noqa: BLE001
                    logger.warning("run_once: LLM co-pilot error for %s: %s", event.symbol, exc)

            # 3c. Executor
            try:
                self._executor.on_signal(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once: executor failed for %s: %s", event.symbol, exc)

            # 3d. Alert
            try:
                self._alert_agent.send(event)
            except Exception as exc:  # noqa: BLE001
                logger.error("run_once: alert failed for %s: %s", event.symbol, exc)

        # 4. Equity snapshot (always, even if no events)
        try:
            self._store.save_equity(self._cfg.risk.account_balance)
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
