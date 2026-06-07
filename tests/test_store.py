from utils.store import Store


def test_signal_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.init()
    s.save_signal({"symbol": "BTC/USDT", "tf": "4h", "state": "BULLISH", "strength": 80})
    rows = s.load_signals()
    assert rows[0]["symbol"] == "BTC/USDT"


def test_scan_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.init()
    payload = {"symbols": ["BTC/USDT", "ETH/USDT"], "count": 2}
    s.save_scan(payload)
    rows = s.load_scans()
    assert len(rows) == 1
    import json
    assert json.loads(rows[0]["payload"])["count"] == 2


def test_position_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.init()
    pos_data = {
        "symbol": "ETH/USDT",
        "mode": "paper",
        "side": "long",
        "entry_price": 2000.0,
        "qty": 0.5,
        "stop_price": 1900.0,
    }
    row_id = s.save_position(pos_data)
    assert isinstance(row_id, int) and row_id > 0
    rows = s.load_positions(status="open")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "ETH/USDT"
    assert rows[0]["entry_price"] == 2000.0


def test_trade_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.init()
    trade_data = {
        "symbol": "SOL/USDT",
        "mode": "paper",
        "side": "long",
        "entry_price": 150.0,
        "exit_price": 160.0,
        "qty": 10.0,
        "pnl": 100.0,
        "fee": 0.5,
        "opened_at": "2024-01-01T00:00:00",
    }
    s.save_trade(trade_data)
    rows = s.load_trades()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "SOL/USDT"
    assert rows[0]["pnl"] == 100.0


def test_equity_roundtrip(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    s.init()
    s.save_equity(10500.75)
    rows = s.load_equity()
    assert len(rows) == 1
    assert rows[0]["balance"] == 10500.75
