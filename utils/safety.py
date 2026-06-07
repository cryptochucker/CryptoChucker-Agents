"""Live-trading double-gate safety guard.

This module is the ONLY place where the decision to allow live trading is made.
It is deliberately minimal and must stay that way.

Rules
-----
- ``live_enabled`` returns True ONLY when BOTH:
    1. PAPER_TRADING is EXACTLY the string "false" (case-SENSITIVE), AND
    2. ENABLE_LIVE_TRADING is EXACTLY the string "true" (case-SENSITIVE).
  Any other combination returns False.  Missing keys default to the safe values
  (PAPER_TRADING -> "true", ENABLE_LIVE_TRADING -> "false").

  IMPORTANT: "False", "FALSE", "True", "TRUE", "yes", "1", "" are ALL treated
  as the safe/blocked direction.  Only the exact lowercase strings open a gate.

- ``make_exchange_client`` returns a PUBLIC/unauthenticated ccxt client in paper
  mode (no apiKey, no secret, no password).  It only loads env-var credentials
  when BOTH gates are open.  In paper mode it must NEVER read or pass secret values.

- ``guard_live`` raises ``LiveTradingDisabled`` unless both gates are open.
  The executor calls this before every live order so the live path is unreachable
  in paper mode even if called directly.

Security invariant
------------------
The ``env`` parameter is accepted as an explicit dict so that tests can inject
a controlled environment WITHOUT the real process environment being involved.
When ``env=None`` (production call), ``os.environ`` is used.  In CI/test the
env var names for exchange credentials are never set, so live cannot be
exercised even accidentally.
"""
from __future__ import annotations

import os

import ccxt


class LiveTradingDisabled(RuntimeError):
    """Raised when a live-order call is attempted but the double gate is not open."""


def live_enabled(env: dict[str, str] | None = None) -> bool:
    """Return True ONLY when both live-trading gates are explicitly open.

    Gates (case-SENSITIVE exact string match -- no .lower(), no strip()):
      1. PAPER_TRADING must be EXACTLY "false"  (default: "true" -> closed).
         "False", "FALSE", "yes", "0", "" all keep paper ON.
      2. ENABLE_LIVE_TRADING must be EXACTLY "true" (default: "false" -> closed).
         "True", "TRUE", "yes", "1", "" all keep live OFF.

    Both must be satisfied simultaneously; either gate alone is insufficient.
    Any value other than the exact lowercase strings resolves to the safe
    (paper) direction.

    Args:
        env: Explicit environment mapping.  ``None`` uses ``os.environ``.

    Returns:
        True only when both conditions hold; False for every other combination.
    """
    # Read ONLY the two gate keys; never copy or iterate os.environ.
    # When env is None we call os.environ.get() for those two keys only,
    # so secret credential vars are never touched on the default path.
    if env is not None:
        paper_is_false = str(env.get("PAPER_TRADING", "true")) == "false"
        live_is_true = str(env.get("ENABLE_LIVE_TRADING", "false")) == "true"
    else:
        paper_is_false = str(os.environ.get("PAPER_TRADING", "true")) == "false"
        live_is_true = str(os.environ.get("ENABLE_LIVE_TRADING", "false")) == "true"
    return paper_is_false and live_is_true


def make_exchange_client(exchange: str, env: dict[str, str] | None = None) -> ccxt.Exchange:
    """Construct a ccxt exchange client appropriate for the current mode.

    In PAPER mode (default / either gate closed):
        Returns a PUBLIC, unauthenticated client -- no apiKey, no secret,
        no password.  The secret env vars (EXCHANGE_API_KEY, EXCHANGE_API_SECRET,
        EXCHANGE_API_PASSWORD) are NEVER read, never accessed.

    In LIVE mode (both gates open):
        Reads EXCHANGE_API_KEY, EXCHANGE_API_SECRET, EXCHANGE_API_PASSWORD
        from the environment and constructs an authenticated client.

    Credential isolation guarantee: the paper path calls ``klass({"enableRateLimit": True})``
    and touches NO other keys from ``env``.  A caller may pass a mapping that raises
    on secret-key access; paper mode will never trigger it.

    Args:
        exchange: ccxt exchange identifier (e.g. "blofin", "binance").
        env: Explicit environment mapping.  ``None`` uses ``os.environ``.

    Returns:
        ccxt Exchange instance -- unauthenticated in paper mode,
        authenticated in live mode.

    Raises:
        AttributeError: If *exchange* is not a valid ccxt exchange name.
    """
    # Do NOT copy os.environ -- pass env (or None) to live_enabled so that
    # only the two gate keys are read in paper mode; secret keys are never touched.
    klass = getattr(ccxt, exchange)

    if live_enabled(env):
        # Both gates open -- read credentials ONLY here, never in the paper path.
        # Secret values are read here but never logged or stored.
        src = env if env is not None else os.environ
        return klass(
            {
                "apiKey": src.get("EXCHANGE_API_KEY", ""),
                "secret": src.get("EXCHANGE_API_SECRET", ""),
                "password": src.get("EXCHANGE_API_PASSWORD", ""),
                "enableRateLimit": True,
            }
        )

    # Paper mode: public client -- ZERO credential access.
    return klass({"enableRateLimit": True})


def guard_live(env: dict[str, str] | None = None) -> None:
    """Assert that live trading is enabled; raise if not.

    Call this as the FIRST line of every live-order path.  It makes the live
    path structurally unreachable in paper mode -- even if called directly.

    Args:
        env: Explicit environment mapping.  ``None`` uses ``os.environ``.

    Raises:
        LiveTradingDisabled: If ``live_enabled(env)`` is False.
    """
    if not live_enabled(env):
        raise LiveTradingDisabled(
            "Live trading is disabled. "
            "Both PAPER_TRADING=false AND ENABLE_LIVE_TRADING=true must be set explicitly."
        )
