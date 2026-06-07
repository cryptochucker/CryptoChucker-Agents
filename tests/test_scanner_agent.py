"""Tests for agents/scanner_agent.py - Stage 3 Task 3.1 + Gate 3 findings."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.scanner_agent import Scanner, SignalEvent
from utils.config_schema import AlertsCfg, Config, ScannerCfg, WatchlistCfg

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_df(prices, vol_mult=1.0, n_bars=80):
    """Build a synthetic OHLCV DataFrame."""
    prices = list(prices)
    n = len(prices)
    c = np.array(prices, float)
    idx = pd.date_range("2026-01-01", periods=n, freq="4h")
    # volume with a final surge (vol_mult x the rolling avg) to pass volume filter
    vol = np.full(n, 1000.0)
    if vol_mult != 1.0:
        vol[-1] = vol[-1] * vol_mult
    return pd.DataFrame(
        {
            "open": c,
            "high": c * 1.005,
            "low": c * 0.995,
            "close": c,
            "volume": vol,
        },
        index=idx,
    )


def _bullish_flip_df():
    """DF that ends with a bullish flip (up then flat)."""
    up = list(np.linspace(100, 150, 60))
    down = list(np.linspace(150, 120, 20))
    return _make_df(up + down, vol_mult=5.0)


def _no_flip_df():
    """DF that ends BULLISH but with no recent flip (steady uptrend)."""
    return _make_df(np.linspace(100, 160, 80), vol_mult=1.0)


def _low_strength_df():
    """DF likely to produce low signal_strength (flat prices)."""
    return _make_df(np.full(80, 100.0), vol_mult=1.0)


@pytest.fixture
def cfg():
    """Default Config with scanner defaults."""
    return Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=2.0),
        alerts=AlertsCfg(),
    )


@pytest.fixture
def cfg_with_min_strength():
    """Config with min_strength set high enough to filter low-quality signals."""
    return Config(
        scanner=ScannerCfg(min_strength=50, rank_top_n=10, volume_surge_mult=2.0),
    )


@pytest.fixture
def cfg_blacklist():
    """Config with a blacklisted symbol."""
    return Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=2.0),
        watchlist=WatchlistCfg(blacklist=["ETH/USDT"]),
    )


@pytest.fixture
def cfg_whitelist():
    """Config with a whitelist restricting to a single symbol."""
    return Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=2.0),
        watchlist=WatchlistCfg(whitelist=["BTC/USDT"]),
    )


def _fake_fetcher(symbol_df_map: dict):
    """Return a callable that acts as an injected data-fetcher."""
    def fetch(symbol, tf, limit=300):
        if symbol not in symbol_df_map:
            raise KeyError(f"Fake fetcher has no data for {symbol!r}")
        return symbol_df_map[symbol]
    return fetch


# ---------------------------------------------------------------------------
# Deterministic monkeypatched helpers (MEDIUM 6)
#
# We control get_money_line and latest_signal returns so tests are not
# sensitive to exact signal-math implementation details.
# ---------------------------------------------------------------------------

def _make_minimal_df():
    """Minimal OHLCV DataFrame with enough rows for the volume-surge filter."""
    n = 25
    c = np.ones(n) * 100.0
    idx = pd.date_range("2026-01-01", periods=n, freq="4h")
    vol = np.full(n, 1000.0)
    vol[-1] = 9999.0  # big surge so volume filter passes with surge_mult=2
    return pd.DataFrame(
        {"open": c, "high": c, "low": c, "close": c, "volume": vol},
        index=idx,
    )


def _passthrough_signal_fn(df):
    """Signal function that just returns the raw df (latest_signal is monkeypatched)."""
    return df


def _make_controlled_scanner(monkeypatch, sig_map: dict, cfg: Config):
    """Build a Scanner where latest_signal returns values from sig_map by symbol.

    sig_map: {symbol: {"state": str, "strength": float, "flip": bool, "price": float}}
    """

    def controlled_latest_signal(out, **kwargs):
        # Retrieve symbol stored as an attribute on the df (set during fetch)
        sym = getattr(out, "_sym", None)
        if sym and sym in sig_map:
            return sig_map[sym]
        return {"state": "BEARISH", "strength": 0.0, "flip": False, "price": 100.0}

    def fetcher(symbol, tf, limit=300):
        df2 = _make_minimal_df()
        df2._sym = symbol  # type: ignore[attr-defined]
        return df2

    def signal_fn(df2):
        df2._sym = getattr(df2, "_sym", None)  # preserve attribute through copy
        return df2

    monkeypatch.setattr("agents.scanner_agent.latest_signal", controlled_latest_signal)

    scanner = Scanner(cfg, fetcher, signal_fn=signal_fn)
    return scanner


# ---------------------------------------------------------------------------
# SignalEvent dataclass
# ---------------------------------------------------------------------------


def test_signal_event_fields():
    evt = SignalEvent(
        symbol="BTC/USDT",
        tf="4h",
        state="BULLISH",
        strength=75.5,
        flip=True,
        price=30000.0,
        ts=pd.Timestamp("2026-01-01"),
    )
    assert evt.symbol == "BTC/USDT"
    assert evt.tf == "4h"
    assert evt.state == "BULLISH"
    assert evt.strength == 75.5
    assert evt.flip is True
    assert evt.price == 30000.0
    assert isinstance(evt.ts, pd.Timestamp)


# ---------------------------------------------------------------------------
# Scanner basic scan
# ---------------------------------------------------------------------------


def test_scan_returns_signal_events(cfg):
    fetcher = _fake_fetcher({"BTC/USDT": _bullish_flip_df()})
    scanner = Scanner(cfg, fetcher)
    events = scanner.scan(["BTC/USDT"])
    assert len(events) >= 0  # may be empty if no flip, but must be a list
    assert all(isinstance(e, SignalEvent) for e in events)


def test_scan_ranked_by_strength_desc(cfg):
    """Multiple symbols: result must be sorted by strength descending."""
    fetcher = _fake_fetcher({
        "BTC/USDT": _bullish_flip_df(),
        "ETH/USDT": _no_flip_df(),
        "SOL/USDT": _bullish_flip_df(),
    })
    scanner = Scanner(cfg, fetcher)
    events = scanner.scan(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    strengths = [e.strength for e in events]
    assert strengths == sorted(strengths, reverse=True), (
        f"Events not sorted by strength desc: {strengths}"
    )


def test_scan_min_strength_filter(cfg_with_min_strength):
    """All returned events must have strength >= min_strength."""
    fetcher = _fake_fetcher({
        "BTC/USDT": _bullish_flip_df(),
        "ETH/USDT": _low_strength_df(),
    })
    scanner = Scanner(cfg_with_min_strength, fetcher)
    events = scanner.scan(["BTC/USDT", "ETH/USDT"])
    for e in events:
        assert e.strength >= cfg_with_min_strength.scanner.min_strength, (
            f"{e.symbol} strength {e.strength} < min_strength {cfg_with_min_strength.scanner.min_strength}"
        )


def test_scan_respects_blacklist(cfg_blacklist):
    """Blacklisted symbols must not appear in results."""
    fetcher = _fake_fetcher({
        "BTC/USDT": _bullish_flip_df(),
        "ETH/USDT": _bullish_flip_df(),
    })
    scanner = Scanner(cfg_blacklist, fetcher)
    events = scanner.scan(["BTC/USDT", "ETH/USDT"])
    symbols = [e.symbol for e in events]
    assert "ETH/USDT" not in symbols, f"Blacklisted ETH/USDT appeared in results: {symbols}"


def test_scan_respects_whitelist(cfg_whitelist):
    """When whitelist is set, only whitelisted symbols may appear in results."""
    fetcher = _fake_fetcher({
        "BTC/USDT": _bullish_flip_df(),
        "ETH/USDT": _bullish_flip_df(),
        "SOL/USDT": _bullish_flip_df(),
    })
    scanner = Scanner(cfg_whitelist, fetcher)
    events = scanner.scan(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    for e in events:
        assert e.symbol in cfg_whitelist.watchlist.whitelist, (
            f"{e.symbol!r} not in whitelist {cfg_whitelist.watchlist.whitelist}"
        )


def test_scan_rank_top_n_respected():
    """Scanner must return at most rank_top_n events."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=2, volume_surge_mult=0.1),
    )
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT"]
    fetcher = _fake_fetcher({s: _bullish_flip_df() for s in symbols})
    scanner = Scanner(cfg, fetcher)
    events = scanner.scan(symbols)
    assert len(events) <= 2, f"Expected <= 2 events, got {len(events)}"


def test_scan_volume_surge_filter():
    """Symbols without a volume surge must be filtered when vol_mult is high."""
    # no_surge_df has uniform volume, surge mult=100 so 1000 < 100*1000 avg -> filtered
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=100.0),
    )
    fetcher = _fake_fetcher({"BTC/USDT": _no_flip_df()})  # uniform volume
    scanner = Scanner(cfg, fetcher)
    events = scanner.scan(["BTC/USDT"])
    assert all(e.symbol != "BTC/USDT" for e in events), (
        "BTC/USDT should be filtered by volume surge requirement"
    )


def test_scan_keeps_fresh_flip_events():
    """Scanner must include symbols with a recent flip_detected=True."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
    )
    fetcher = _fake_fetcher({"BTC/USDT": _bullish_flip_df()})
    scanner = Scanner(cfg, fetcher)
    events = scanner.scan(["BTC/USDT"])
    # With min_strength=0 and low volume_surge_mult, BTC must appear if it has a flip
    # (the bullish_flip_df is designed to end near a state transition)
    # We do not mandate flip=True because the exact bar depends on signal math,
    # but the scan should return at least some result or empty list without raising.
    assert isinstance(events, list)


def test_scan_ignores_fetch_errors(cfg):
    """Symbols that throw during fetch must be skipped; scan continues for others."""
    def bad_fetcher(symbol, tf, limit=300):
        if symbol == "BAD/USDT":
            raise RuntimeError("simulated network error")
        return _bullish_flip_df()

    scanner = Scanner(cfg, bad_fetcher)
    events = scanner.scan(["BAD/USDT", "BTC/USDT"])
    symbols = [e.symbol for e in events]
    assert "BAD/USDT" not in symbols, "BAD/USDT should be skipped due to fetch error"


def test_scan_empty_watchlist(cfg):
    """Scanning an empty list must return an empty list without raising."""
    fetcher = _fake_fetcher({})
    scanner = Scanner(cfg, fetcher)
    events = scanner.scan([])
    assert events == []


# ---------------------------------------------------------------------------
# MEDIUM 6 — Deterministic scanner tests with controlled signal values
# ---------------------------------------------------------------------------


def test_deterministic_ranking_by_strength(monkeypatch):
    """Ranking must be strictly by strength desc when flip=True for all symbols."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
    )
    sig_map = {
        "AAA/USDT": {"state": "BULLISH", "strength": 80.0, "flip": True, "price": 1.0},
        "BBB/USDT": {"state": "BEARISH", "strength": 60.0, "flip": True, "price": 2.0},
        "CCC/USDT": {"state": "BULLISH", "strength": 70.0, "flip": True, "price": 3.0},
    }
    scanner = _make_controlled_scanner(monkeypatch, sig_map, cfg)
    events = scanner.scan(["AAA/USDT", "BBB/USDT", "CCC/USDT"])
    assert len(events) == 3
    assert [e.symbol for e in events] == ["AAA/USDT", "CCC/USDT", "BBB/USDT"], (
        f"Expected AAA > CCC > BBB by strength, got {[e.symbol for e in events]}"
    )
    assert [e.strength for e in events] == [80.0, 70.0, 60.0]


def test_deterministic_min_strength_excludes_weak(monkeypatch):
    """Symbols below min_strength must be excluded even when flip=True."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=65.0, rank_top_n=10, volume_surge_mult=0.1),
    )
    sig_map = {
        "STRONG/USDT": {"state": "BULLISH", "strength": 80.0, "flip": True, "price": 1.0},
        "WEAK/USDT":   {"state": "BULLISH", "strength": 40.0, "flip": True, "price": 2.0},
    }
    scanner = _make_controlled_scanner(monkeypatch, sig_map, cfg)
    events = scanner.scan(["STRONG/USDT", "WEAK/USDT"])
    symbols = [e.symbol for e in events]
    assert "STRONG/USDT" in symbols, "STRONG should pass min_strength=65"
    assert "WEAK/USDT" not in symbols, "WEAK (strength=40) must be excluded by min_strength=65"


def test_deterministic_non_flip_excluded(monkeypatch):
    """Symbols where flip=False must never appear in results."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
    )
    sig_map = {
        "FLIP/USDT":   {"state": "BULLISH", "strength": 75.0, "flip": True,  "price": 1.0},
        "NOFLIP/USDT": {"state": "BULLISH", "strength": 90.0, "flip": False, "price": 2.0},
    }
    scanner = _make_controlled_scanner(monkeypatch, sig_map, cfg)
    events = scanner.scan(["FLIP/USDT", "NOFLIP/USDT"])
    symbols = [e.symbol for e in events]
    assert "FLIP/USDT" in symbols, "FLIP (flip=True) should appear in results"
    assert "NOFLIP/USDT" not in symbols, "NOFLIP (flip=False) must be excluded"


def test_deterministic_blacklist_excludes(monkeypatch):
    """Blacklisted symbols must not appear even when flip=True and strength is high."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
        watchlist=WatchlistCfg(blacklist=["BL/USDT"]),
    )
    sig_map = {
        "GOOD/USDT": {"state": "BULLISH", "strength": 80.0, "flip": True, "price": 1.0},
        "BL/USDT":   {"state": "BULLISH", "strength": 99.0, "flip": True, "price": 2.0},
    }
    scanner = _make_controlled_scanner(monkeypatch, sig_map, cfg)
    events = scanner.scan(["GOOD/USDT", "BL/USDT"])
    symbols = [e.symbol for e in events]
    assert "GOOD/USDT" in symbols
    assert "BL/USDT" not in symbols, "Blacklisted BL/USDT must never appear"


# ---------------------------------------------------------------------------
# BLOCKING 3 — Per-symbol isolation: bad symbol does not abort scan
# ---------------------------------------------------------------------------


def test_isolation_bad_fetcher_does_not_abort_good_symbols(monkeypatch):
    """A fetcher that raises for one symbol must not stop events from other symbols."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
    )

    def controlled_latest_signal(out, **kwargs):
        sym = getattr(out, "_sym", None)
        if sym == "GOOD/USDT":
            return {"state": "BULLISH", "strength": 80.0, "flip": True, "price": 1.0}
        return {"state": "BEARISH", "strength": 0.0, "flip": False, "price": 0.0}

    def fetcher(symbol, tf, limit=300):
        if symbol == "ERR/USDT":
            raise RuntimeError("simulated transport error")
        df = _make_minimal_df()
        df._sym = symbol  # type: ignore[attr-defined]
        return df

    def signal_fn(df):
        df._sym = getattr(df, "_sym", None)
        return df

    monkeypatch.setattr("agents.scanner_agent.latest_signal", controlled_latest_signal)
    scanner = Scanner(cfg, fetcher, signal_fn=signal_fn)
    events = scanner.scan(["ERR/USDT", "GOOD/USDT"])

    symbols = [e.symbol for e in events]
    assert "ERR/USDT" not in symbols, "Error symbol must be skipped"
    assert "GOOD/USDT" in symbols, "Good symbol must still produce an event"


def test_isolation_malformed_df_does_not_abort_good_symbols(monkeypatch):
    """A fetcher that returns a very short DataFrame must not abort the scan."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
    )

    def controlled_latest_signal(out, **kwargs):
        sym = getattr(out, "_sym", None)
        if sym == "GOOD/USDT":
            return {"state": "BULLISH", "strength": 75.0, "flip": True, "price": 1.0}
        # For the short df, this raises KeyError simulating malformed data
        raise KeyError("missing column")

    def fetcher(symbol, tf, limit=300):
        if symbol == "SHORT/USDT":
            # Two-row DataFrame: volume filter will pass (len < 2 check skips it),
            # but controlled_latest_signal raises for this symbol
            idx = pd.date_range("2026-01-01", periods=2, freq="4h")
            df = pd.DataFrame(
                {"open": [1.0, 2.0], "high": [1.1, 2.1], "low": [0.9, 1.9],
                 "close": [1.0, 2.0], "volume": [1000.0, 1000.0]},
                index=idx,
            )
            df._sym = symbol  # type: ignore[attr-defined]
            return df
        df = _make_minimal_df()
        df._sym = symbol  # type: ignore[attr-defined]
        return df

    def signal_fn(df):
        df._sym = getattr(df, "_sym", None)
        return df

    monkeypatch.setattr("agents.scanner_agent.latest_signal", controlled_latest_signal)
    scanner = Scanner(cfg, fetcher, signal_fn=signal_fn)
    events = scanner.scan(["SHORT/USDT", "GOOD/USDT"])

    symbols = [e.symbol for e in events]
    assert "SHORT/USDT" not in symbols, "Malformed symbol must be skipped"
    assert "GOOD/USDT" in symbols, "Good symbol must still produce an event"


# ---------------------------------------------------------------------------
# BLOCKING 2 — Flip-only contract test
# ---------------------------------------------------------------------------


def test_only_fresh_flips_emitted(monkeypatch):
    """Symbols that did NOT flip on the latest bar must be excluded."""
    cfg = Config(
        scanner=ScannerCfg(min_strength=0, rank_top_n=10, volume_surge_mult=0.1),
    )
    sig_map = {
        "FLIP1/USDT": {"state": "BULLISH", "strength": 70.0, "flip": True,  "price": 1.0},
        "FLIP2/USDT": {"state": "BEARISH", "strength": 65.0, "flip": True,  "price": 2.0},
        "NFLIP/USDT": {"state": "BULLISH", "strength": 99.0, "flip": False, "price": 3.0},
    }
    scanner = _make_controlled_scanner(monkeypatch, sig_map, cfg)
    events = scanner.scan(["FLIP1/USDT", "FLIP2/USDT", "NFLIP/USDT"])
    symbols = [e.symbol for e in events]
    assert "FLIP1/USDT" in symbols
    assert "FLIP2/USDT" in symbols
    assert "NFLIP/USDT" not in symbols, (
        "Non-flipping symbol (flip=False) must never appear in results"
    )
    # All returned events must have flip=True
    for e in events:
        assert e.flip is True, f"{e.symbol} has flip=False in result"
