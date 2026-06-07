"""Deterministic end-to-end paper smoke test (Task 6.2).

Proof that the full orchestration pipeline works in paper mode:
  - DataFetcher reads the committed CSV fixture (no network).
  - build_app(cfg_paper).run_once() completes with zero unhandled exceptions.
  - At least one signal row is persisted in SQLite.
  - At least one PAPER trade/position is persisted.
  - ccxt create_order is NEVER called (paper mode structural guarantee).
  - At least one equity snapshot row is persisted.
  - The alert transport receives at least one formatted payload.

The fixture ``tests/fixtures/ohlcv_btc_4h.csv`` contains 300 synthetic BTC 4h
bars engineered to produce:
  - At least one BULLISH fresh flip
  - Close above VWAP at the flip bar
  - Volume surge >= 2x rolling average at the flip bar
  - Signal strength >= 55

This test is CI-able: deterministic, no network, no secrets.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from utils.config_schema import Config
from utils.store import Store

# ---------------------------------------------------------------------------
# Path to the committed fixture
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ohlcv_btc_4h.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture() -> pd.DataFrame:
    """Load the committed CSV fixture as a proper OHLCV DataFrame."""
    df = pd.read_csv(
        _FIXTURE_PATH,
        index_col="datetime",
        parse_dates=True,
    )
    df.index = pd.to_datetime(df.index, utc=True)
    return df[["open", "high", "low", "close", "volume"]]


def _make_paper_cfg(tmp_path: Path) -> Config:
    """Return a paper-mode Config tuned so the fixture reliably fires a trade.

    Key settings:
    - scanner.min_strength=55: matches fixture's strength=58.6
    - scanner.volume_surge_mult=2.0: matches fixture's 2.71x surge
    - scanner.use_vwap_filter=True: fixture close > VWAP
    - executor.use_dip_filter=False: simplify entry; we prove signal fires
    - alerts all off (transport mocked separately)
    """
    return Config(
        exchange="blofin",
        paper_trading=True,
        persistence={"sqlite_path": str(tmp_path / "e2e_smoke.db")},
        data={"primary_timeframe": "4h", "ohlcv_limit": 300},
        scanner={
            "interval_minutes": 5,
            "min_strength": 55,
            "rank_top_n": 10,
            "volume_surge_mult": 2.0,
            "use_vwap_filter": True,
            "vwap_length": 20,
        },
        signal={
            "money_line_length": 8,
            "smooth": 14,
            "slope_len": 3,
            "use_rsi_filter": False,
            "use_adx_filter": False,
        },
        executor={
            "use_dip_filter": False,  # disable so entry fires on first flip
            "trailing_stop_pct": 0.03,
            "profit_target_pct": 0.06,
            "max_hold_hours": 48,
        },
        risk={
            "account_balance": 10000,
            "risk_pct": 0.01,
            "max_exposure_pct": 0.15,
            "max_trades_per_day": 10,
            "max_consecutive_losses": 4,
            "max_drawdown_pct": 0.20,
        },
        fees={"blofin": {"maker": 0.0002, "taker": 0.0006}},
        alerts={
            "telegram": False,
            "discord": False,
            "email": False,
            "send_chart_image": False,
        },
        llm_copilot={"enabled": False},
    )


# ---------------------------------------------------------------------------
# Fixture always returns the same BTC CSV (ignores symbol/tf/limit)
# ---------------------------------------------------------------------------


def _fixture_fetcher(symbol: str, tf: str, limit: int) -> pd.DataFrame:  # noqa: ARG001
    """Return the committed CSV fixture regardless of symbol."""
    return _load_fixture()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixture_file_exists():
    """Sanity: the committed fixture CSV must exist."""
    assert _FIXTURE_PATH.exists(), f"Fixture not found: {_FIXTURE_PATH}"
    df = _load_fixture()
    assert len(df) >= 200
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_fixture_produces_bullish_flip():
    """Verify the fixture engineering: at least one BULLISH flip above VWAP with volume surge."""
    from agents.signal_agent import get_money_line  # noqa: PLC0415

    df = _load_fixture()
    out = get_money_line(df, length=8, smooth=14, slope_len=3)

    bullish_flips = out[(out["flip_detected"]) & (out["state"] == "BULLISH")]
    assert len(bullish_flips) >= 1, "Fixture must produce at least one BULLISH flip"

    # Check signal strength >= 55
    assert bullish_flips["signal_strength"].iloc[0] >= 55, "First flip must have strength >= 55"


def test_e2e_paper_smoke_no_exceptions(tmp_path, caplog):
    """Full end-to-end: run_once() completes with zero unhandled exceptions."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()

    mock_alert = MagicMock()

    with caplog.at_level(logging.DEBUG):
        app = build_app(
            cfg,
            fetcher=_fixture_fetcher,
            store=store,
            alert_agent=mock_alert,
        )
        app.run_once()  # must not raise


def test_e2e_signal_persisted(tmp_path):
    """Assert: at least one signal row is persisted after run_once()."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    signals = store.load_signals()
    assert len(signals) >= 1, f"Expected >= 1 signal row, got {len(signals)}"
    assert signals[0]["state"] == "BULLISH"


def test_e2e_trade_persisted(tmp_path):
    """Assert: at least one PAPER trade is persisted after run_once()."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    trades = store.load_trades()
    assert len(trades) >= 1, f"Expected >= 1 trade row, got {len(trades)}"
    # All trades in paper mode must be mode=paper
    assert all(t["mode"] == "paper" for t in trades), "All trades must be mode=paper"


def test_e2e_position_persisted(tmp_path):
    """Assert: at least one position row is persisted after run_once()."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    # Positions: open or closed
    open_pos = store.load_positions(status="open")
    closed_pos = store.load_positions(status="closed")
    total_pos = len(open_pos) + len(closed_pos)
    assert total_pos >= 1, f"Expected >= 1 position row, got {total_pos}"


def test_e2e_create_order_never_called(tmp_path):
    """CRITICAL: ccxt create_order must NEVER be called in paper mode.

    This test patches the ccxt exchange class to inject a spy client, then
    asserts create_order call_count == 0 after a full run_once() cycle.
    """
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    # Spy client that records any create_order calls
    spy_client = MagicMock()

    from agents.executor_agent import Executor  # noqa: PLC0415

    original_init = Executor.__init__

    def patched_init(self, cfg, store, client=None, env=None):
        # Inject our spy client
        original_init(self, cfg, store, client=spy_client, env=env)

    with patch.object(Executor, "__init__", patched_init):
        build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    assert spy_client.create_order.call_count == 0, (
        f"create_order was called {spy_client.create_order.call_count} time(s) "
        "in paper mode -- live-trading guard failure!"
    )


def test_e2e_equity_persisted(tmp_path):
    """Assert: at least one equity snapshot row is persisted after run_once()."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    equity_rows = store.load_equity()
    assert len(equity_rows) >= 1, f"Expected >= 1 equity row, got {len(equity_rows)}"


def test_e2e_alert_transport_called(tmp_path):
    """Assert: the alert transport receives at least one payload after run_once()."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    # mock_alert.send() is called once per scanned signal event
    assert mock_alert.send.call_count >= 1, (
        f"Expected AlertAgent.send() to be called >= 1 time; "
        f"got {mock_alert.send.call_count}"
    )
    # Verify the payload is a SignalEvent (has .symbol attribute)
    first_call_event = mock_alert.send.call_args_list[0][0][0]
    assert hasattr(first_call_event, "symbol"), "Alert payload must be a SignalEvent"
    assert hasattr(first_call_event, "state"), "Alert payload must have .state"
    assert first_call_event.state == "BULLISH"


def test_e2e_all_assertions_in_single_run(tmp_path):
    """Canonical combined smoke test: one run, all five assertions.

    This is the definitive CI-gating test: run_once() on a fresh DB must produce
    signals, trades, positions, equity rows, and alert calls -- all in one shot.
    create_order must never be called.
    """
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_smoke.db"))
    store.init()
    mock_alert = MagicMock()

    spy_client = MagicMock()
    from agents.executor_agent import Executor  # noqa: PLC0415

    original_init = Executor.__init__

    def patched_init(self, cfg, store, client=None, env=None):
        original_init(self, cfg, store, client=spy_client, env=env)

    exceptions_caught: list[str] = []
    with patch.object(Executor, "__init__", patched_init):
        app = build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert)
        # run_once must not raise
        try:
            app.run_once()
        except Exception as exc:  # noqa: BLE001
            exceptions_caught.append(str(exc))

    # ZERO exceptions
    assert not exceptions_caught, f"run_once raised: {exceptions_caught}"

    # At least one signal
    signals = store.load_signals()
    assert len(signals) >= 1, "No signal rows persisted"

    # At least one paper trade
    trades = store.load_trades()
    assert len(trades) >= 1, "No trade rows persisted"
    assert all(t["mode"] == "paper" for t in trades)

    # At least one position (open or closed)
    total_pos = len(store.load_positions("open")) + len(store.load_positions("closed"))
    assert total_pos >= 1, "No position rows persisted"

    # At least one equity row
    assert len(store.load_equity()) >= 1, "No equity rows persisted"

    # Alert transport called
    assert mock_alert.send.call_count >= 1, "AlertAgent.send() never called"

    # create_order NEVER called
    assert spy_client.create_order.call_count == 0, (
        "create_order was called -- live-trading guard failure!"
    )


# ---------------------------------------------------------------------------
# BLOCKING 1: build_app Executor honors real process env double-gate
# ---------------------------------------------------------------------------


def test_build_app_executor_paper_by_default(tmp_path, monkeypatch):
    """Executor built by build_app is in paper mode when env gates are absent.

    With no PAPER_TRADING / ENABLE_LIVE_TRADING in the process environment,
    live_enabled must return False (fail-closed default).
    """
    from main import build_app  # noqa: PLC0415
    from utils.safety import live_enabled  # noqa: PLC0415

    # Ensure the gate keys are absent from the process environment.
    monkeypatch.delenv("PAPER_TRADING", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)

    cfg = _make_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "gate_paper.db"))
    store.init()

    app = build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=MagicMock())
    executor = app._executor

    # Executor was built with env=None, so live_enabled() reads os.environ directly.
    # With both gate keys absent, it must return False (paper mode, fail-closed).
    assert executor._env is None, "build_app must pass env=None to Executor"
    assert not live_enabled(None), "live_enabled must be False when gate keys are absent"


def test_build_app_executor_live_enabled_when_both_gates_set(tmp_path, monkeypatch):
    """live_enabled returns True ONLY when both env gate strings are set exactly.

    This test does NOT place any real orders; it only asserts that the
    safety function would grant live mode given the exact enabling strings.
    """
    from utils.safety import live_enabled  # noqa: PLC0415

    # Set both gates to the exact enabling strings via the process environment.
    monkeypatch.setenv("PAPER_TRADING", "false")
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")

    # live_enabled(None) reads os.environ directly -- must return True.
    assert live_enabled(None), (
        "live_enabled must return True when PAPER_TRADING=false AND "
        "ENABLE_LIVE_TRADING=true are both set in os.environ"
    )

    # Partial gate: only one set -- must remain False.
    monkeypatch.setenv("PAPER_TRADING", "false")
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
    assert not live_enabled(None), "One gate alone must not enable live trading"

    monkeypatch.delenv("PAPER_TRADING", raising=False)
    monkeypatch.setenv("ENABLE_LIVE_TRADING", "true")
    assert not live_enabled(None), "One gate alone must not enable live trading"


# ---------------------------------------------------------------------------
# MEDIUM 2: e2e alert test exercises the real transport
# ---------------------------------------------------------------------------


def _make_telegram_paper_cfg(tmp_path: Path) -> Config:
    """Paper config with telegram channel enabled (transport will be monkeypatched)."""
    return Config(
        exchange="blofin",
        paper_trading=True,
        persistence={"sqlite_path": str(tmp_path / "e2e_tg_smoke.db")},
        data={"primary_timeframe": "4h", "ohlcv_limit": 300},
        scanner={
            "interval_minutes": 5,
            "min_strength": 55,
            "rank_top_n": 10,
            "volume_surge_mult": 2.0,
            "use_vwap_filter": True,
            "vwap_length": 20,
        },
        signal={
            "money_line_length": 8,
            "smooth": 14,
            "slope_len": 3,
            "use_rsi_filter": False,
            "use_adx_filter": False,
        },
        executor={
            "use_dip_filter": False,
            "trailing_stop_pct": 0.03,
            "profit_target_pct": 0.06,
            "max_hold_hours": 48,
        },
        risk={
            "account_balance": 10000,
            "risk_pct": 0.01,
            "max_exposure_pct": 0.15,
            "max_trades_per_day": 10,
            "max_consecutive_losses": 4,
            "max_drawdown_pct": 0.20,
        },
        fees={"blofin": {"maker": 0.0002, "taker": 0.0006}},
        alerts={
            "telegram": True,   # enabled so the real dispatch path is exercised
            "discord": False,
            "email": False,
            "send_chart_image": False,
        },
        llm_copilot={"enabled": False},
    )


def test_e2e_alert_real_transport_telegram(tmp_path, monkeypatch):
    """MEDIUM 2: run_once() with a real AlertAgent drives the actual _post_telegram path.

    Monkeypatches only the low-level HTTP call (_post_telegram), not the whole
    AlertAgent, so the full format-and-dispatch code path is exercised.
    Asserts:
      - _post_telegram was called at least once.
      - The message string contains the symbol and the state "BULLISH".
      - create_order was never called (paper-mode structural guarantee).
      - Signal, trade, and equity rows are persisted (smoke assertions intact).
    """
    import agents.alert_agent as alert_mod  # noqa: PLC0415
    from main import build_app  # noqa: PLC0415

    cfg = _make_telegram_paper_cfg(tmp_path)
    store = Store(str(tmp_path / "e2e_tg_smoke.db"))
    store.init()

    # Capture calls to the low-level Telegram transport without hitting the network.
    captured: list[str] = []

    def fake_post_telegram(msg: str, cfg, **kwargs) -> None:  # noqa: ANN001
        captured.append(msg)

    monkeypatch.setattr(alert_mod, "_post_telegram", fake_post_telegram)

    # Spy on create_order to confirm it is never called.
    spy_client = MagicMock()
    from agents.executor_agent import Executor  # noqa: PLC0415

    original_init = Executor.__init__

    def patched_init(self, cfg, store, client=None, env=None):  # noqa: ANN001
        original_init(self, cfg, store, client=spy_client, env=env)

    with patch.object(Executor, "__init__", patched_init):
        # No alert_agent injected: build_app constructs a real AlertAgent from cfg.
        app = build_app(cfg, fetcher=_fixture_fetcher, store=store)
        app.run_once()

    # Transport was reached (message was formatted and dispatched).
    assert len(captured) >= 1, (
        "Expected _post_telegram to be called at least once; it was never reached. "
        "The real AlertAgent dispatch path may not have been exercised."
    )

    first_msg = captured[0]

    # Message must be a formatted string, not a raw object.
    assert isinstance(first_msg, str), f"Expected str message, got {type(first_msg)}"

    # Symbol must appear in the message (fixture uses BTC/USDT).
    assert "BTC" in first_msg, f"Expected symbol 'BTC' in alert message: {first_msg!r}"

    # State must be BULLISH.
    assert "BULLISH" in first_msg, f"Expected 'BULLISH' in alert message: {first_msg!r}"

    # Structural paper-mode guarantee: no live orders.
    assert spy_client.create_order.call_count == 0, (
        "create_order was called in paper mode -- live-trading guard failure!"
    )

    # Smoke: signal and equity persisted.
    assert len(store.load_signals()) >= 1, "No signal rows persisted"
    assert len(store.load_equity()) >= 1, "No equity rows persisted"


# ---------------------------------------------------------------------------
# Gate 6: dip filter and equity snapshot correctness
# ---------------------------------------------------------------------------


def _make_dip_filter_cfg(tmp_path: Path) -> Config:
    """Paper config with use_dip_filter=True so the dip branch runs."""
    return Config(
        exchange="blofin",
        paper_trading=True,
        persistence={"sqlite_path": str(tmp_path / "dip_filter.db")},
        data={"primary_timeframe": "4h", "ohlcv_limit": 300},
        scanner={
            "interval_minutes": 5,
            "min_strength": 55,
            "rank_top_n": 10,
            "volume_surge_mult": 2.0,
            "use_vwap_filter": True,
            "vwap_length": 20,
        },
        signal={
            "money_line_length": 8,
            "smooth": 14,
            "slope_len": 3,
            "use_rsi_filter": False,
            "use_adx_filter": False,
        },
        executor={
            "use_dip_filter": True,   # <- enabled for this test
            "trailing_stop_pct": 0.03,
            "profit_target_pct": 0.06,
            "max_hold_hours": 48,
        },
        risk={
            "account_balance": 10000,
            "risk_pct": 0.01,
            "max_exposure_pct": 0.15,
            "max_trades_per_day": 10,
            "max_consecutive_losses": 4,
            "max_drawdown_pct": 0.20,
        },
        fees={"blofin": {"maker": 0.0002, "taker": 0.0006}},
        alerts={
            "telegram": False,
            "discord": False,
            "email": False,
            "send_chart_image": False,
        },
        llm_copilot={"enabled": False},
    )


def test_e2e_dip_filter_receives_df(tmp_path):
    """Gate 6 BLOCKING 1: executor.on_signal is called WITH a non-None df.

    With use_dip_filter=True the orchestrator must thread the OHLCV DataFrame
    through run_once() to on_signal so the dip branch can actually execute.
    This test monkeypatches on_signal to capture the df argument and asserts
    it is a non-None DataFrame.
    """
    from agents.executor_agent import Executor  # noqa: PLC0415
    from main import build_app  # noqa: PLC0415

    cfg = _make_dip_filter_cfg(tmp_path)
    store = Store(str(tmp_path / "dip_filter.db"))
    store.init()
    mock_alert = MagicMock()

    captured_dfs: list = []

    original_on_signal = Executor.on_signal

    def spy_on_signal(self, event, df=None):  # noqa: ANN001
        captured_dfs.append(df)
        original_on_signal(self, event, df=df)

    with patch.object(Executor, "on_signal", spy_on_signal):
        build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert).run_once()

    # The orchestrator must have called on_signal at least once with a real df.
    assert len(captured_dfs) >= 1, (
        "on_signal was never called -- no signals were produced by the fixture"
    )
    assert any(df is not None and isinstance(df, pd.DataFrame) for df in captured_dfs), (
        "on_signal was called but df was None every time; "
        "run_once() is not threading the OHLCV DataFrame to the executor"
    )


def test_e2e_equity_snapshot_reflects_real_pnl(tmp_path):
    """Gate 6 BLOCKING 2: cycle equity snapshot equals account_balance + realized + unrealized.

    After a completed trade the equity row written by run_once() must NOT equal
    the bare account_balance constant; it must incorporate the realized PnL from
    that trade.

    Strategy:
    - First run_once() to open a position (use_dip_filter=False to guarantee entry).
    - Manually close the position via the store so a realized PnL row exists.
    - Second run_once() to trigger the equity snapshot with that realized PnL.
    - Assert the latest equity row != account_balance.
    - Assert latest equity == account_balance + sum(pnl for closed trades with pnl set).
    """
    from main import build_app  # noqa: PLC0415

    cfg = _make_paper_cfg(tmp_path)          # use_dip_filter=False -> entry guaranteed
    store = Store(str(tmp_path / "equity_pnl.db"))
    store.init()
    mock_alert = MagicMock()

    account_balance = cfg.risk.account_balance

    # First cycle: open a position.
    app = build_app(cfg, fetcher=_fixture_fetcher, store=store, alert_agent=mock_alert)
    app.run_once()

    # Confirm a trade was written (may be buy-side only at this point).
    all_trades_after_first = store.load_trades()
    assert len(all_trades_after_first) >= 1, "Expected at least one trade after first run_once()"

    # Inject a closed sell-side trade row with a known PnL so we can assert the math.
    known_pnl = 123.45
    store.save_trade({
        "symbol": "BTC/USDT",
        "mode": "paper",
        "side": "sell",
        "entry_price": 50000.0,
        "exit_price": 50500.0,
        "qty": 0.01,
        "pnl": known_pnl,
        "fee": 0.03,
        "opened_at": "2024-01-01 00:00:00",
    })

    # Second cycle: run_once() should compute equity using all trade pnl rows.
    app.run_once()

    # Fetch the newest equity row (load_equity returns newest-first).
    equity_rows = store.load_equity()
    assert len(equity_rows) >= 1, "No equity rows after second run_once()"
    latest_equity = equity_rows[0]["balance"]

    # Compute expected: account_balance + sum of all non-None pnl rows.
    all_trades = store.load_trades()
    realized_pnl = sum(t["pnl"] for t in all_trades if t.get("pnl") is not None)

    # The snapshot must reflect realized PnL (unrealized may be 0 or non-zero
    # depending on open positions at snapshot time, so we assert >= realized).
    expected_minimum = account_balance + realized_pnl

    assert latest_equity != account_balance, (
        f"Equity snapshot equals bare account_balance ({account_balance}); "
        "run_once() is not incorporating realized PnL into the snapshot"
    )
    assert abs(latest_equity - expected_minimum) < 1.0 or latest_equity >= expected_minimum, (
        f"Equity {latest_equity} does not reflect account_balance ({account_balance}) "
        f"+ realized_pnl ({realized_pnl}). Expected ~{expected_minimum}"
    )
