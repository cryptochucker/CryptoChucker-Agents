from __future__ import annotations

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator


class DataCfg(BaseModel):
    primary_timeframe: str = "4h"
    confirm_timeframe: str = "1h"
    ohlcv_limit: int = 300


class RiskCfg(BaseModel):
    account_balance: float = 10000
    risk_pct: float = Field(0.01, gt=0, le=0.5)
    max_exposure_pct: float = Field(0.15, gt=0, le=1)
    max_trades_per_day: int = 10
    max_consecutive_losses: int = 4
    max_drawdown_pct: float = Field(0.20, gt=0, le=1)


class SignalCfg(BaseModel):
    """Parameters for the Money Line signal engine."""

    money_line_length: int = Field(8, ge=1)
    smooth: int = Field(14, ge=1)
    slope_len: int = Field(3, ge=1)
    use_rsi_filter: bool = False
    use_adx_filter: bool = False


class Config(BaseModel):
    exchange: str = "blofin"
    paper_trading: bool = True
    data: DataCfg = DataCfg()
    risk: RiskCfg = RiskCfg()
    signal: SignalCfg = SignalCfg()
    # remaining sections kept permissive dicts for the sample; tighten per stage as used
    model_config = {"extra": "allow"}

    @field_validator("exchange")
    @classmethod
    def known_exchange(cls, v):
        if v not in {"blofin", "bitget", "binance", "bybit", "kraken", "coinbase"}:
            raise ValueError(f"unsupported exchange: {v}")
        return v


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    try:
        return Config(**raw)
    except ValidationError as e:
        raise ValueError(f"Invalid config.yaml: {e}") from e
