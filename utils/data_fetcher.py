from __future__ import annotations

import time
from typing import Any

import ccxt
import pandas as pd

_COLUMNS = ["open", "high", "low", "close", "volume"]
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds


class DataFetcher:
    """Public CCXT data fetcher with retry on transient network errors.

    Args:
        exchange: Exchange name string (e.g. "blofin"). Used only when no
            exchange_obj is supplied.
        exchange_obj: Pre-constructed ccxt exchange instance (useful for testing).
    """

    def __init__(self, exchange: str = "blofin", exchange_obj: Any = None) -> None:
        if exchange_obj is not None:
            self._ex = exchange_obj
        else:
            klass = getattr(ccxt, exchange)
            self._ex = klass({"enableRateLimit": True})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_ohlcv(self, symbol: str, timeframe: str = "4h", limit: int = 300) -> pd.DataFrame:
        """Fetch OHLCV bars with up to _MAX_RETRIES retries on NetworkError.

        Returns:
            DataFrame indexed by datetime with columns [open, high, low, close, volume].
        """
        raw = self._retry(lambda: self._ex.fetch_ohlcv(symbol, timeframe, limit=limit))
        return self._to_df(raw)

    def top_volume_symbols(self, n: int = 50) -> list[str]:
        """Return the top-n symbols ranked by 24h quote volume."""
        tickers = self._retry(lambda: self._ex.fetch_tickers())
        ranked = sorted(
            tickers.values(),
            key=lambda t: t.get("quoteVolume") or 0,
            reverse=True,
        )
        return [t["symbol"] for t in ranked[:n]]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _retry(self, fn, retries: int = _MAX_RETRIES, backoff: float = _BACKOFF_BASE):
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                return fn()
            except ccxt.NetworkError as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(backoff * (2**attempt))
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _to_df(raw: list[list]) -> pd.DataFrame:
        df = pd.DataFrame(raw, columns=["ts", *_COLUMNS])
        df.index = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
        df.index.name = "datetime"
        return df[_COLUMNS]
