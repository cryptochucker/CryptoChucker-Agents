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


# ---- Stage 4: ExecutorCfg and FeesCfg ----

from utils.config_schema import ExecutorCfg, FeesCfg  # noqa: E402


def test_executor_cfg_defaults():
    """ExecutorCfg must have correct defaults."""
    e = ExecutorCfg()
    assert e.profit_target_pct == pytest.approx(0.06)
    assert e.use_dip_filter is True
    assert e.trailing_stop_pct == pytest.approx(0.03)
    assert e.max_hold_hours == 48


def test_executor_cfg_profit_target_zero_raises():
    """profit_target_pct=0 must raise (gt=0 constraint)."""
    with pytest.raises((ValueError, ValidationError)):
        ExecutorCfg(profit_target_pct=0)


def test_executor_cfg_profit_target_negative_raises():
    """profit_target_pct < 0 must raise."""
    with pytest.raises((ValueError, ValidationError)):
        ExecutorCfg(profit_target_pct=-0.01)


def test_executor_cfg_trailing_stop_negative_raises():
    """trailing_stop_pct < 0 must raise (ge=0 constraint)."""
    with pytest.raises((ValueError, ValidationError)):
        ExecutorCfg(trailing_stop_pct=-0.01)


def test_executor_cfg_trailing_stop_zero_allowed():
    """trailing_stop_pct=0 means disabled; must be allowed (ge=0)."""
    e = ExecutorCfg(trailing_stop_pct=0.0)
    assert e.trailing_stop_pct == 0.0


def test_executor_cfg_max_hold_hours_zero_raises():
    """max_hold_hours=0 must raise (ge=1 constraint)."""
    with pytest.raises((ValueError, ValidationError)):
        ExecutorCfg(max_hold_hours=0)


def test_executor_cfg_valid_custom_values():
    """Custom valid values must be accepted."""
    e = ExecutorCfg(profit_target_pct=0.10, use_dip_filter=False, trailing_stop_pct=0.05, max_hold_hours=24)
    assert e.profit_target_pct == pytest.approx(0.10)
    assert e.use_dip_filter is False
    assert e.trailing_stop_pct == pytest.approx(0.05)
    assert e.max_hold_hours == 24


def test_fees_cfg_defaults():
    """FeesCfg must accept an empty mapping (no exchanges configured)."""
    f = FeesCfg()
    assert isinstance(f.rates, dict)


def test_fees_cfg_valid_entry():
    """FeesCfg must accept a valid exchange -> {maker, taker} mapping."""
    f = FeesCfg(rates={"blofin": {"maker": 0.0002, "taker": 0.0006}})
    assert f.rates["blofin"]["maker"] == pytest.approx(0.0002)
    assert f.rates["blofin"]["taker"] == pytest.approx(0.0006)


def test_fees_cfg_multiple_exchanges():
    """FeesCfg must accept multiple exchanges."""
    f = FeesCfg(rates={
        "blofin": {"maker": 0.0002, "taker": 0.0006},
        "binance": {"maker": 0.0002, "taker": 0.0004},
    })
    assert "binance" in f.rates


def test_config_has_executor_and_fees_fields(tmp_path):
    """Config must expose executor and fees sub-models after load_config."""
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin",
        "executor": {"profit_target_pct": 0.08, "use_dip_filter": False},
        "fees": {"blofin": {"maker": 0.0002, "taker": 0.0006}},
    }))
    cfg = load_config(str(p))
    assert cfg.executor.profit_target_pct == pytest.approx(0.08)
    assert cfg.executor.use_dip_filter is False
    assert cfg.fees.rates["blofin"]["taker"] == pytest.approx(0.0006)


# ---- MEDIUM 5: FeesCfg validates per-exchange entries via _ExchangeFeeCfg ----


def test_fees_cfg_negative_maker_raises():
    """MEDIUM 5: negative maker fee must raise a ValidationError."""
    with pytest.raises((ValueError, ValidationError)):
        FeesCfg(rates={"blofin": {"maker": -0.001, "taker": 0.0006}})


def test_fees_cfg_negative_taker_raises():
    """MEDIUM 5: negative taker fee must raise a ValidationError."""
    with pytest.raises((ValueError, ValidationError)):
        FeesCfg(rates={"blofin": {"maker": 0.0002, "taker": -0.001}})


def test_fees_cfg_zero_maker_allowed():
    """MEDIUM 5: zero maker fee is valid (ge=0)."""
    f = FeesCfg(rates={"blofin": {"maker": 0.0, "taker": 0.001}})
    assert f.rates["blofin"]["maker"] == pytest.approx(0.0)


def test_fees_cfg_zero_taker_allowed():
    """MEDIUM 5: zero taker fee is valid (ge=0)."""
    f = FeesCfg(rates={"blofin": {"maker": 0.001, "taker": 0.0}})
    assert f.rates["blofin"]["taker"] == pytest.approx(0.0)


def test_fees_cfg_negative_fee_via_flat_dict_raises():
    """MEDIUM 5: negative fee through the flat-dict YAML path must also raise."""
    with pytest.raises((ValueError, ValidationError)):
        FeesCfg(**{"blofin": {"maker": -0.0001, "taker": 0.0006}})


# ---- Stage 5: PersistenceCfg, LlmCopilotCfg, PineCfg ----

from utils.config_schema import LlmCopilotCfg, PersistenceCfg, PineCfg  # noqa: E402


def test_persistence_cfg_defaults():
    p = PersistenceCfg()
    assert p.backend == "sqlite"
    assert p.sqlite_path == "data/cryptochucker.db"


def test_persistence_cfg_invalid_backend_raises():
    with pytest.raises((ValueError, ValidationError)):
        PersistenceCfg(backend="redis")


def test_persistence_cfg_supabase_accepted():
    p = PersistenceCfg(backend="supabase")
    assert p.backend == "supabase"


def test_persistence_cfg_sqlite_path_custom():
    p = PersistenceCfg(sqlite_path="/tmp/test.db")
    assert p.sqlite_path == "/tmp/test.db"


def test_llm_copilot_cfg_defaults():
    lc = LlmCopilotCfg()
    assert lc.enabled is False
    assert lc.provider == "anthropic"


def test_llm_copilot_cfg_invalid_provider_raises():
    with pytest.raises((ValueError, ValidationError)):
        LlmCopilotCfg(provider="gemini")


def test_llm_copilot_cfg_openai_accepted():
    lc = LlmCopilotCfg(enabled=True, provider="openai")
    assert lc.provider == "openai"
    assert lc.enabled is True


def test_llm_copilot_cfg_ollama_accepted():
    lc = LlmCopilotCfg(provider="ollama")
    assert lc.provider == "ollama"


def test_pine_cfg_defaults():
    p = PineCfg()
    assert p.scanner_symbols == []


def test_pine_cfg_accepts_symbol_list():
    p = PineCfg(scanner_symbols=["BTC/USDT", "ETH/USDT"])
    assert "BTC/USDT" in p.scanner_symbols


def test_config_has_persistence_llm_copilot_pine_fields(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "exchange": "blofin",
        "persistence": {"backend": "sqlite", "sqlite_path": "data/test.db"},
        "llm_copilot": {"enabled": False, "provider": "anthropic"},
        "pine": {"scanner_symbols": ["BTC/USDT"]},
    }))
    cfg = load_config(str(p))
    assert cfg.persistence.backend == "sqlite"
    assert cfg.llm_copilot.enabled is False
    assert cfg.pine.scanner_symbols == ["BTC/USDT"]


# ---- LOW 3: PineCfg.scanner_symbols capped at 30 ----


def test_pine_cfg_30_symbols_accepted():
    """Exactly 30 symbols must be accepted (boundary value)."""
    syms = [f"SYM{i}/USDT" for i in range(30)]
    p = PineCfg(scanner_symbols=syms)
    assert len(p.scanner_symbols) == 30


def test_pine_cfg_31_symbols_raises():
    """31 symbols must raise a ValidationError (Pine Money Scanner hard limit is 30)."""
    syms = [f"SYM{i}/USDT" for i in range(31)]
    with pytest.raises((ValueError, ValidationError)):
        PineCfg(scanner_symbols=syms)
