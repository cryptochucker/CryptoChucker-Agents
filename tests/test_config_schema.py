import pytest
import yaml

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
