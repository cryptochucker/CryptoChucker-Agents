"""Tests for the main orchestrator (Task 6.1).

TDD: these tests were written before main.py was implemented.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from utils.config_schema import Config
from utils.store import Store

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cfg(tmp_path) -> Config:
    """Return a minimal paper-mode Config pointing to a temp SQLite DB."""
    return Config(
        exchange="blofin",
        paper_trading=True,
        persistence={"sqlite_path": str(tmp_path / "smoke.db")},
        scanner={"interval_minutes": 5, "min_strength": 0, "volume_surge_mult": 0.001},
        alerts={"telegram": False, "discord": False, "email": False, "send_chart_image": False},
        llm_copilot={"enabled": False},
    )


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    """Return a minimal synthetic OHLCV DataFrame."""
    idx = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
    rng = np.random.default_rng(42)
    close = 40000 + np.cumsum(rng.normal(0, 200, n))
    close = np.abs(close)
    volume = rng.uniform(500, 1500, n)
    return pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": volume,
        },
        index=idx,
    )


# ---------------------------------------------------------------------------
# build_app import test
# ---------------------------------------------------------------------------


def test_build_app_importable():
    """build_app must be importable from main."""
    from main import build_app  # noqa: PLC0415

    assert callable(build_app)


# ---------------------------------------------------------------------------
# build_app wiring
# ---------------------------------------------------------------------------


def test_build_app_returns_app_with_run_once(tmp_path):
    """build_app(cfg) returns an object with a run_once() method."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_cfg(tmp_path)
    fake_fetcher = MagicMock(return_value=_make_ohlcv())
    mock_alert = MagicMock()
    store = Store(str(tmp_path / "smoke.db"))
    store.init()

    app = build_app(cfg, fetcher=fake_fetcher, store=store, alert_agent=mock_alert)
    assert hasattr(app, "run_once")
    assert callable(app.run_once)


# ---------------------------------------------------------------------------
# run_once completes without raising
# ---------------------------------------------------------------------------


def test_run_once_does_not_raise(tmp_path):
    """run_once() completes without raising even with a canned fetcher."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_cfg(tmp_path)
    fake_fetcher = MagicMock(return_value=_make_ohlcv())
    mock_alert = MagicMock()
    store = Store(str(tmp_path / "smoke.db"))
    store.init()

    app = build_app(cfg, fetcher=fake_fetcher, store=store, alert_agent=mock_alert)
    # Must not raise
    app.run_once()


# ---------------------------------------------------------------------------
# Per-agent isolation: a crashing agent does NOT abort the cycle
# ---------------------------------------------------------------------------


def test_per_agent_isolation_alert_exception(tmp_path, caplog):
    """A crashing AlertAgent must be caught; run_once() still completes."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_cfg(tmp_path)
    fake_fetcher = MagicMock(return_value=_make_ohlcv())

    # AlertAgent that always raises
    exploding_alert = MagicMock()
    exploding_alert.send.side_effect = RuntimeError("boom!")

    store = Store(str(tmp_path / "smoke.db"))
    store.init()

    app = build_app(cfg, fetcher=fake_fetcher, store=store, alert_agent=exploding_alert)
    with caplog.at_level(logging.ERROR):
        app.run_once()  # must not propagate


def test_per_agent_isolation_fetcher_exception(tmp_path, caplog):
    """A crashing fetcher (per symbol) must be caught; run_once() still completes."""
    from main import build_app  # noqa: PLC0415

    cfg = _make_cfg(tmp_path)

    # Fetcher that always raises
    exploding_fetcher = MagicMock(side_effect=RuntimeError("network down"))
    mock_alert = MagicMock()

    store = Store(str(tmp_path / "smoke.db"))
    store.init()

    app = build_app(cfg, fetcher=exploding_fetcher, store=store, alert_agent=mock_alert)
    with caplog.at_level(logging.WARNING):
        app.run_once()  # must not propagate


# ---------------------------------------------------------------------------
# run() scheduler API exists (not started in tests)
# ---------------------------------------------------------------------------


def test_run_callable(tmp_path):
    """main module must expose a run() function (scheduler entry point)."""
    import main as m  # noqa: PLC0415

    assert callable(m.run)
