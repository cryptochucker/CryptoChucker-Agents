"""Tests for the live-trading double-gate safety guard.

These are the most critical tests in the codebase.  They prove that:
  1. Default environment -> live_enabled is False.
  2. Only PAPER_TRADING=false (ENABLE_LIVE_TRADING still false/unset) -> still False.
  3. PAPER_TRADING=true + ENABLE_LIVE_TRADING=true -> still False.
  4. Both gates set EXACTLY to lowercase "false"/"true" -> True.
  5. In paper mode make_exchange_client never loads credentials (apiKey is None or "").
  6. guard_live raises LiveTradingDisabled in paper mode.
  7. BLOCKING: case-SENSITIVE gate -- "False"/"True"/"FALSE"/"TRUE" all BLOCKED.
  8. BLOCKING: secret env vars NEVER accessed in paper mode.
  9. BLOCKING: DEFAULT PATH (env=None) -- monkeypatching os.environ to a guard mapping
     proves that make_exchange_client("binance") and Executor + bullish signal NEVER
     read a secret key even when os.environ is the live environment dict.
"""
from __future__ import annotations

import pytest

from utils.safety import LiveTradingDisabled, guard_live, live_enabled, make_exchange_client

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
_PAPER = {"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "false"}
_LIVE = {"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": "true"}

_SECRET_KEYS = ("EXCHANGE_API_KEY", "EXCHANGE_API_SECRET", "EXCHANGE_API_PASSWORD")


class _SecretGuardEnv(dict):
    """Dict subclass that RAISES if any secret key is accessed via get() or []."""

    def get(self, key, default=None):  # type: ignore[override]
        if key in _SECRET_KEYS:
            raise AssertionError(f"Paper mode accessed secret key: {key!r}")
        return super().get(key, default)

    def __getitem__(self, key):
        if key in _SECRET_KEYS:
            raise AssertionError(f"Paper mode accessed secret key: {key!r}")
        return super().__getitem__(key)


# ---------------------------------------------------------------------------
# live_enabled -- double gate
# ---------------------------------------------------------------------------


def test_default_env_blocks_live() -> None:
    """Default values (PAPER=true, ENABLE=false) must return False."""
    assert live_enabled({"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "false"}) is False


def test_missing_keys_default_to_paper() -> None:
    """Empty env dict -> defaults (PAPER=true, ENABLE=false) -> False."""
    assert live_enabled({}) is False


def test_single_flag_paper_false_alone_blocks() -> None:
    """PAPER_TRADING=false alone (ENABLE_LIVE_TRADING still false/unset) -> still False."""
    assert live_enabled({"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": "false"}) is False
    assert live_enabled({"PAPER_TRADING": "false"}) is False


def test_single_flag_enable_true_alone_blocks() -> None:
    """ENABLE_LIVE_TRADING=true alone (PAPER_TRADING still true/unset) -> still False."""
    assert live_enabled({"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "true"}) is False
    assert live_enabled({"ENABLE_LIVE_TRADING": "true"}) is False


def test_both_gates_set_correctly_enables_live() -> None:
    """Both PAPER_TRADING=false AND ENABLE_LIVE_TRADING=true (exact lowercase) -> True."""
    assert live_enabled(_LIVE) is True


# ---------------------------------------------------------------------------
# BLOCKING 1: exact lowercase-only gate (case-SENSITIVE)
# ---------------------------------------------------------------------------


def test_mixed_case_false_true_blocked() -> None:
    """BLOCKING: 'False'/'True' (Python bool str) must be BLOCKED -- not live."""
    assert live_enabled({"PAPER_TRADING": "False", "ENABLE_LIVE_TRADING": "True"}) is False


def test_upper_case_false_true_blocked() -> None:
    """BLOCKING: 'FALSE'/'TRUE' must be BLOCKED -- not live."""
    assert live_enabled({"PAPER_TRADING": "FALSE", "ENABLE_LIVE_TRADING": "TRUE"}) is False


def test_exact_lowercase_enables_live() -> None:
    """Only exact lowercase 'false'/'true' opens the gate."""
    assert live_enabled({"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": "true"}) is True


def test_garbage_values_treated_as_blocked() -> None:
    """Non-exact junk -> live stays off."""
    assert live_enabled({"PAPER_TRADING": "yes", "ENABLE_LIVE_TRADING": "true"}) is False
    assert live_enabled({"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": "1"}) is False
    assert live_enabled({"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": ""}) is False
    assert live_enabled({"PAPER_TRADING": "", "ENABLE_LIVE_TRADING": "true"}) is False


# ---------------------------------------------------------------------------
# make_exchange_client -- credential isolation
# ---------------------------------------------------------------------------


def test_paper_client_has_no_api_key() -> None:
    """In paper mode the client must NOT have credentials loaded."""
    client = make_exchange_client("blofin", env=_PAPER)
    assert client.apiKey in (None, "")


def test_paper_client_has_no_secret() -> None:
    """In paper mode the secret must NOT be loaded."""
    client = make_exchange_client("blofin", env=_PAPER)
    assert client.secret in (None, "")


def test_paper_client_with_empty_env() -> None:
    """Empty env dict (all defaults -> paper) -> public client."""
    client = make_exchange_client("blofin", env={})
    assert client.apiKey in (None, "")


def test_paper_client_returns_ccxt_exchange() -> None:
    """The returned object must be a real ccxt exchange instance."""
    import ccxt

    client = make_exchange_client("blofin", env=_PAPER)
    assert isinstance(client, ccxt.Exchange)


# ---------------------------------------------------------------------------
# BLOCKING 2: strict credential isolation -- secret keys NEVER accessed in paper
# ---------------------------------------------------------------------------


def test_paper_mode_never_accesses_secret_keys() -> None:
    """BLOCKING: make_exchange_client in paper mode must NEVER call .get() on secret keys.

    Uses a guard dict that RAISES on any secret-key access.  If paper mode
    accidentally reads EXCHANGE_API_KEY / EXCHANGE_API_SECRET / EXCHANGE_API_PASSWORD
    the test will fail with AssertionError from inside the mapping.
    """
    guard_env = _SecretGuardEnv(_PAPER)
    # Must NOT raise -- paper path never touches secret keys
    client = make_exchange_client("blofin", env=guard_env)
    assert client.apiKey in (None, "")


def test_paper_mode_with_secret_guard_and_empty_gate_env() -> None:
    """BLOCKING: paper mode with empty env also must not access secrets."""
    guard_env = _SecretGuardEnv({})  # all defaults -> paper
    client = make_exchange_client("blofin", env=guard_env)
    assert client.apiKey in (None, "")


# ---------------------------------------------------------------------------
# guard_live -- raises in paper mode
# ---------------------------------------------------------------------------


def test_guard_live_raises_in_paper_mode() -> None:
    """guard_live must raise LiveTradingDisabled when live is not enabled."""
    with pytest.raises(LiveTradingDisabled):
        guard_live(env=_PAPER)


def test_guard_live_raises_with_empty_env() -> None:
    """guard_live must raise with empty/default env."""
    with pytest.raises(LiveTradingDisabled):
        guard_live(env={})


def test_guard_live_raises_single_flag() -> None:
    """guard_live raises when only one gate is open."""
    with pytest.raises(LiveTradingDisabled):
        guard_live(env={"PAPER_TRADING": "false"})
    with pytest.raises(LiveTradingDisabled):
        guard_live(env={"ENABLE_LIVE_TRADING": "true"})


def test_guard_live_does_not_raise_when_fully_enabled() -> None:
    """guard_live must NOT raise when both gates are open."""
    # Should complete without raising
    guard_live(env=_LIVE)


def test_live_trading_disabled_is_runtime_error() -> None:
    """LiveTradingDisabled must be a RuntimeError subclass."""
    assert issubclass(LiveTradingDisabled, RuntimeError)


# ---------------------------------------------------------------------------
# BLOCKING 9: DEFAULT PATH (env=None) -- os.environ monkeypatched to guard
# ---------------------------------------------------------------------------


class _DefaultPathGuardEnv(dict):
    """Mimics os.environ: has PAPER_TRADING defaulting to paper mode but RAISES
    on any access to a secret credential key.  Used to verify that the default
    (env=None) code path in make_exchange_client and live_enabled never touches
    secret keys when operating in paper mode.
    """

    def get(self, key, default=None):  # type: ignore[override]
        if key in _SECRET_KEYS:
            raise AssertionError(f"Default path accessed secret env key: {key!r}")
        return super().get(key, default)

    def __getitem__(self, key):
        if key in _SECRET_KEYS:
            raise AssertionError(f"Default path accessed secret env key: {key!r}")
        return super().__getitem__(key)


def test_default_path_make_exchange_client_never_reads_secrets(monkeypatch) -> None:
    """BLOCKING 9: env=None path -- make_exchange_client('binance') must not access secret keys.

    Monkeypatches utils.safety.os.environ to a guard mapping that contains only
    the paper-mode gate values (PAPER_TRADING=true).  Any .get() or [] call on
    a secret key raises AssertionError.  The test passes only if no secret key
    is accessed during the paper-mode default path.
    """
    import utils.safety as safety_mod

    guard = _DefaultPathGuardEnv({"PAPER_TRADING": "true"})
    monkeypatch.setattr(safety_mod.os, "environ", guard)

    # env=None -> falls through to os.environ (which is now the guard)
    client = make_exchange_client("binance")  # env=None -- default path
    assert client.apiKey in (None, ""), "Default-path paper client must be unauthenticated"


def test_default_path_live_enabled_never_reads_secrets(monkeypatch) -> None:
    """BLOCKING 9: env=None path -- live_enabled() must not access secret keys."""
    import utils.safety as safety_mod

    guard = _DefaultPathGuardEnv({"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "false"})
    monkeypatch.setattr(safety_mod.os, "environ", guard)

    result = live_enabled()  # env=None -- default path
    assert result is False, "Default path must resolve to paper mode"


def test_default_path_executor_construction_and_signal_never_reads_secrets(monkeypatch, tmp_path) -> None:
    """BLOCKING 9: constructing Executor(env=None) + processing a bullish signal must not read secrets.

    This is the ultimate end-to-end proof: the entire default production path
    (Executor with no env arg, no injected client) runs without ever touching
    EXCHANGE_API_KEY, EXCHANGE_API_SECRET, or EXCHANGE_API_PASSWORD.
    """
    import datetime

    import utils.safety as safety_mod
    from agents.executor_agent import Executor
    from agents.scanner_agent import SignalEvent
    from utils.config_schema import Config, ExecutorCfg, FeesCfg, RiskCfg
    from utils.store import Store

    guard = _DefaultPathGuardEnv({"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "false"})
    monkeypatch.setattr(safety_mod.os, "environ", guard)

    cfg = Config(
        exchange="binance",
        executor=ExecutorCfg(profit_target_pct=0.06, use_dip_filter=False,
                             trailing_stop_pct=0.0, max_hold_hours=48),
        fees=FeesCfg(rates={"binance": {"maker": 0.001, "taker": 0.001}}),
        risk=RiskCfg(
            account_balance=10_000.0,
            risk_pct=0.01,
            max_exposure_pct=1.0,
            max_trades_per_day=10,
            max_consecutive_losses=4,
            max_drawdown_pct=0.20,
        ),
    )
    store = Store(str(tmp_path / "default_path.db"))
    store.init()

    # env=None is the default -- this is the exact production call signature
    ex = Executor(cfg, store)
    assert ex._client.apiKey in (None, ""), "Default-path client must be unauthenticated"

    # Process a bullish paper signal -- must not touch secrets
    signal = SignalEvent(
        symbol="BTC/USDT", tf="4h", state="BULLISH", strength=75.0,
        flip=True, price=100.0, ts=datetime.datetime.utcnow(),
    )
    ex.on_signal(signal)  # must not raise

    trades = store.load_trades()
    assert len(trades) >= 1, "Paper signal must record a trade on the default path"
