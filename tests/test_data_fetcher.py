from unittest.mock import MagicMock

import pandas as pd

from utils.data_fetcher import DataFetcher


def test_fetch_ohlcv_shape():
    ex = MagicMock()
    ex.fetch_ohlcv.return_value = [[1_700_000_000_000, 1, 2, 0.5, 1.5, 100]] * 5
    df = DataFetcher(exchange_obj=ex).fetch_ohlcv("BTC/USDT", "4h", 5)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"] and len(df) == 5


def test_fetch_ohlcv_retry_on_network_error():
    """Verify that a transient NetworkError is retried and eventually succeeds."""
    import ccxt
    ex = MagicMock()
    # Fail twice then succeed
    ex.fetch_ohlcv.side_effect = [
        ccxt.NetworkError("timeout"),
        ccxt.NetworkError("timeout"),
        [[1_700_000_000_000, 1, 2, 0.5, 1.5, 100]] * 3,
    ]
    df = DataFetcher(exchange_obj=ex).fetch_ohlcv("BTC/USDT", "4h", 3)
    assert len(df) == 3
    assert ex.fetch_ohlcv.call_count == 3


def test_public_client_has_no_credentials():
    """DataFetcher constructed without API keys must have an unauthenticated client."""
    fetcher = DataFetcher(exchange="binance")
    client = fetcher._ex
    assert client.apiKey in (None, "")
    assert client.secret in (None, "")
