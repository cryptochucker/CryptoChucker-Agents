from utils.store import Store


def test_signal_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.init()
    s.save_signal({"symbol": "BTC/USDT", "tf": "4h", "state": "BULLISH", "strength": 80})
    rows = s.load_signals()
    assert rows[0]["symbol"] == "BTC/USDT"
