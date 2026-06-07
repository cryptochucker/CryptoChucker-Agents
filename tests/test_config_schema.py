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
