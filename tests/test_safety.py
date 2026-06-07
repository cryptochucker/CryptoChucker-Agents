"""Tests for the live-trading double-gate safety guard.

These are the most critical tests in the codebase.  They prove that:
  1. Default environment -> live_enabled is False.
  2. Only PAPER_TRADING=false (ENABLE_LIVE_TRADING still false/unset) -> still False.
  3. PAPER_TRADING=true + ENABLE_LIVE_TRADING=true -> still False.
  4. Both gates set correctly -> True.
  5. In paper mode make_exchange_client never loads credentials (apiKey is None or "").
  6. guard_live raises LiveTradingDisabled in paper mode.
  7. Case-insensitivity: TRUE/FALSE/True/False all work.
"""
from __future__ import annotations

import pytest

from utils.safety import LiveTradingDisabled, guard_live, live_enabled, make_exchange_client

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
_PAPER = {"PAPER_TRADING": "true", "ENABLE_LIVE_TRADING": "false"}
_LIVE = {"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": "true"}


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
    """Both PAPER_TRADING=false AND ENABLE_LIVE_TRADING=true -> True."""
    assert live_enabled(_LIVE) is True


def test_case_insensitive_true() -> None:
    """TRUE / True / true all treated the same."""
    assert live_enabled({"PAPER_TRADING": "FALSE", "ENABLE_LIVE_TRADING": "TRUE"}) is True
    assert live_enabled({"PAPER_TRADING": "False", "ENABLE_LIVE_TRADING": "True"}) is True


def test_case_insensitive_false() -> None:
    """FALSE / False / false all treated the same."""
    assert live_enabled({"PAPER_TRADING": "FALSE", "ENABLE_LIVE_TRADING": "FALSE"}) is False


def test_garbage_values_treated_as_false() -> None:
    """Non-true/false junk -> treated as falsy -> live stays off."""
    # PAPER_TRADING=junk -> _truthy("junk") is False -> paper_false is False -> overall False
    assert live_enabled({"PAPER_TRADING": "yes", "ENABLE_LIVE_TRADING": "true"}) is False
    assert live_enabled({"PAPER_TRADING": "false", "ENABLE_LIVE_TRADING": "1"}) is False


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
