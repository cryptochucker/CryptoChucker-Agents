import pytest
import yaml
from pydantic import ValidationError

from utils.config_schema import Config, SignalCfg, load_config


def test_load_valid_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin", "paper_trading": True,
        "data": {"primary_timeframe": "4h", "confirm_timeframe": "1h", "ohlcv_limit": 300},
        "risk": {"account_balance": 10000, "risk_pct": 0.01, "max_exposure_pct": 0.15,
                 "max_trades_per_day": 10, "max_consecutive_losses": 4, "max_drawdown_pct": 0.2},
    }))
    cfg = load_config(str(p))
    assert isinstance(cfg, Config)
    assert cfg.risk.risk_pct == 0.01


def test_invalid_config_raises_clear_error(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"exchange": "blofin", "risk": {"risk_pct": 5}}))
    with pytest.raises(ValueError) as e:
        load_config(str(p))
    assert "risk_pct" in str(e.value)


def test_signal_cfg_defaults():
    s = SignalCfg()
    assert s.money_line_length == 8
    assert s.smooth == 14
    assert s.slope_len == 3
    assert s.use_rsi_filter is False
    assert s.use_adx_filter is False


def test_signal_cfg_out_of_type_raises():
    """Passing a string where int is required must raise ValidationError/ValueError."""
    with pytest.raises((ValueError, Exception)):
        SignalCfg(money_line_length="not_an_int")


def test_config_has_signal_field(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin",
        "signal": {"money_line_length": 10, "smooth": 20},
    }))
    cfg = load_config(str(p))
    assert cfg.signal.money_line_length == 10
    assert cfg.signal.smooth == 20
    assert cfg.signal.slope_len == 3  # default


# ---- Gate 2 code-review findings ----


def test_signal_cfg_money_line_length_zero_raises():
    """BLOCKING 2: money_line_length=0 is an invalid window size; must raise."""
    with pytest.raises((ValueError, ValidationError)):
        SignalCfg(money_line_length=0)


def test_signal_cfg_money_line_length_negative_raises():
    """BLOCKING 2: negative window length is invalid; must raise."""
    with pytest.raises((ValueError, ValidationError)):
        SignalCfg(money_line_length=-5)


def test_signal_cfg_smooth_zero_raises():
    """BLOCKING 2: smooth=0 is an invalid EMA span; must raise."""
    with pytest.raises((ValueError, ValidationError)):
        SignalCfg(smooth=0)


def test_signal_cfg_slope_len_zero_raises():
    """BLOCKING 2: slope_len=0 is an invalid rolling window; must raise."""
    with pytest.raises((ValueError, ValidationError)):
        SignalCfg(slope_len=0)


def test_signal_cfg_via_config_money_line_length_zero_raises(tmp_path):
    """BLOCKING 2: money_line_length=0 via Config/load_config must also raise."""
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin",
        "signal": {"money_line_length": 0},
    }))
    with pytest.raises((ValueError, ValidationError)):
        load_config(str(p))


def test_signal_cfg_min_valid_window_accepted():
    """Window lengths of 1 are the minimum valid value and must not raise."""
    cfg = SignalCfg(money_line_length=1, smooth=1, slope_len=1)
    assert cfg.money_line_length == 1
    assert cfg.smooth == 1
    assert cfg.slope_len == 1


# ---- Stage 3: ScannerCfg, AlertsCfg, WatchlistCfg ----

from utils.config_schema import AlertsCfg, ScannerCfg, WatchlistCfg  # noqa: E402


def test_scanner_cfg_defaults():
    s = ScannerCfg()
    assert s.interval_minutes == 5
    assert s.min_strength == 55.0
    assert s.rank_top_n == 10
    assert s.volume_surge_mult == 2.0


def test_scanner_cfg_rank_top_n_zero_raises():
    with pytest.raises((ValueError, ValidationError)):
        ScannerCfg(rank_top_n=0)


def test_scanner_cfg_min_strength_too_high_raises():
    with pytest.raises((ValueError, ValidationError)):
        ScannerCfg(min_strength=150)


def test_scanner_cfg_min_strength_negative_raises():
    with pytest.raises((ValueError, ValidationError)):
        ScannerCfg(min_strength=-1)


def test_scanner_cfg_volume_surge_mult_zero_raises():
    with pytest.raises((ValueError, ValidationError)):
        ScannerCfg(volume_surge_mult=0.0)


def test_scanner_cfg_interval_minutes_zero_raises():
    with pytest.raises((ValueError, ValidationError)):
        ScannerCfg(interval_minutes=0)


def test_alerts_cfg_defaults():
    a = AlertsCfg()
    assert a.telegram is True
    assert a.discord is False
    assert a.email is False
    assert a.send_chart_image is True


def test_watchlist_cfg_defaults():
    w = WatchlistCfg()
    assert w.source == "file"
    assert w.file == "watchlist.json"
    assert w.top_volume_n == 50
    assert w.blacklist == []
    assert w.whitelist == []


def test_watchlist_cfg_invalid_source_raises():
    with pytest.raises((ValueError, ValidationError)):
        WatchlistCfg(source="invalid_source")


def test_watchlist_cfg_top_volume_n_zero_raises():
    with pytest.raises((ValueError, ValidationError)):
        WatchlistCfg(top_volume_n=0)


def test_config_has_scanner_alerts_watchlist_fields(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin",
        "scanner": {"interval_minutes": 10, "min_strength": 60, "rank_top_n": 5, "volume_surge_mult": 1.5},
        "alerts": {"telegram": False, "discord": True},
        "watchlist": {"source": "file", "file": "my_list.json", "blacklist": ["SHIB/USDT"]},
    }))
    cfg = load_config(str(p))
    assert cfg.scanner.interval_minutes == 10
    assert cfg.scanner.rank_top_n == 5
    assert cfg.alerts.discord is True
    assert cfg.alerts.telegram is False
    assert cfg.watchlist.blacklist == ["SHIB/USDT"]


# ---- Gate 3: MEDIUM 7 — typed list[str] for blacklist/whitelist ----


def test_watchlist_blacklist_rejects_non_string_entry():
    """MEDIUM 7: Non-string entries in blacklist must raise a validation error."""
    with pytest.raises((ValueError, ValidationError)):
        WatchlistCfg(blacklist=[123])


def test_watchlist_whitelist_rejects_non_string_entry():
    """MEDIUM 7: Non-string entries in whitelist must raise a validation error."""
    with pytest.raises((ValueError, ValidationError)):
        WatchlistCfg(whitelist=[{"bad": "value"}])


def test_watchlist_blacklist_accepts_string_list():
    """MEDIUM 7: A list of strings must be accepted without error."""
    w = WatchlistCfg(blacklist=["BTC/USDT", "ETH/USDT"])
    assert w.blacklist == ["BTC/USDT", "ETH/USDT"]


def test_watchlist_whitelist_accepts_string_list():
    """MEDIUM 7: A list of strings must be accepted without error."""
    w = WatchlistCfg(whitelist=["SOL/USDT"])
    assert w.whitelist == ["SOL/USDT"]
