"""Live-trading double-gate safety guard.

This module is the ONLY place where the decision to allow live trading is made.
It is deliberately minimal and must stay that way.

Rules
-----
- ``live_enabled`` returns True ONLY when BOTH:
    1. PAPER_TRADING is explicitly "false" (case-insensitive), AND
    2. ENABLE_LIVE_TRADING is explicitly "true" (case-insensitive).
  Any other combination returns False.  Missing keys default to the safe values
  (PAPER_TRADING -> "true", ENABLE_LIVE_TRADING -> "false").

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


def _is_true(value: str) -> bool:
    """Return True iff *value* is exactly 'true' (case-insensitive)."""
    return str(value).strip().lower() == "true"


def _is_false(value: str) -> bool:
    """Return True iff *value* is exactly 'false' (case-insensitive).

    Anything that is not explicitly 'false' is treated as the safe default
    (i.e. paper mode stays ON).  This means garbage values like 'yes' or '0'
    do NOT disable paper trading -- they are treated as if PAPER_TRADING=true.
    """
    return str(value).strip().lower() == "false"


def live_enabled(env: dict[str, str] | None = None) -> bool:
    """Return True ONLY when both live-trading gates are explicitly open.

    Gates:
      1. PAPER_TRADING must be explicitly "false"  (default: "true" -> closed).
         Any value that is not exactly "false" (case-insensitive) keeps paper ON.
      2. ENABLE_LIVE_TRADING must be explicitly "true" (default: "false" -> closed).
         Any value that is not exactly "true" (case-insensitive) keeps live OFF.

    Both must be satisfied simultaneously; either gate alone is insufficient.
    Garbage / unknown values always resolve to the safe (paper) direction.

    Args:
        env: Explicit environment mapping.  ``None`` uses ``os.environ``.

    Returns:
        True only when both conditions hold; False for every other combination.
    """
    e: dict[str, str] = env if env is not None else dict(os.environ)
    paper_is_false = _is_false(e.get("PAPER_TRADING", "true"))
    live_is_true = _is_true(e.get("ENABLE_LIVE_TRADING", "false"))
    return paper_is_false and live_is_true


def make_exchange_client(exchange: str, env: dict[str, str] | None = None) -> ccxt.Exchange:
    """Construct a ccxt exchange client appropriate for the current mode.

    In PAPER mode (default / either gate closed):
        Returns a PUBLIC, unauthenticated client -- no apiKey, no secret,
        no password.  Credentials are never read, never passed.

    In LIVE mode (both gates open):
        Reads EXCHANGE_API_KEY, EXCHANGE_API_SECRET, EXCHANGE_API_PASSWORD
        from the environment and constructs an authenticated client.

    Args:
        exchange: ccxt exchange identifier (e.g. "blofin", "binance").
        env: Explicit environment mapping.  ``None`` uses ``os.environ``.

    Returns:
        ccxt Exchange instance -- unauthenticated in paper mode,
        authenticated in live mode.

    Raises:
        AttributeError: If *exchange* is not a valid ccxt exchange name.
    """
    e: dict[str, str] = env if env is not None else dict(os.environ)
    klass = getattr(ccxt, exchange)

    if live_enabled(e):
        # Both gates open -- load credentials from env var NAMES only.
        # Secret values are read here but never logged or stored.
        return klass(
            {
                "apiKey": e.get("EXCHANGE_API_KEY", ""),
                "secret": e.get("EXCHANGE_API_SECRET", ""),
                "password": e.get("EXCHANGE_API_PASSWORD", ""),
                "enableRateLimit": True,
            }
        )

    # Paper mode: public client, zero credentials.
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
