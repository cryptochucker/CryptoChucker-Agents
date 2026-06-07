from __future__ import annotations

DEFAULT = {"maker": 0.0005, "taker": 0.001}


def fee(notional: float, exchange: str, taker: bool = True, table: dict | None = None) -> float:
    """Calculate the exchange fee for a given notional trade value.

    Args:
        notional: Trade value in quote currency.
        exchange: Exchange name (e.g. "blofin").
        taker: True for taker fee, False for maker fee.
        table: Fee table mapping exchange -> {maker, taker}. Defaults to built-in DEFAULT.

    Returns:
        Fee amount in quote currency.
    """
    rates = (table or {}).get(exchange, DEFAULT)
    return abs(notional) * rates["taker" if taker else "maker"]
