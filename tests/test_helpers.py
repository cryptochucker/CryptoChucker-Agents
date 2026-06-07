from utils.helpers import load_watchlist, save_watchlist


def test_roundtrip_json(tmp_path):
    p = tmp_path / "w.json"
    save_watchlist(["BTC/USDT", "ETH/USDT"], str(p))
    assert load_watchlist(str(p)) == ["BTC/USDT", "ETH/USDT"]


def test_roundtrip_csv(tmp_path):
    p = tmp_path / "w.csv"
    save_watchlist(["BTC/USDT"], str(p))
    assert load_watchlist(str(p)) == ["BTC/USDT"]
