from __future__ import annotations

from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


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


class ScannerCfg(BaseModel):
    """Parameters for the multi-symbol scanner."""

    interval_minutes: int = Field(5, ge=1)
    min_strength: float = Field(55.0, ge=0, le=100)
    rank_top_n: int = Field(10, ge=1)
    volume_surge_mult: float = Field(2.0, gt=0)
    use_vwap_filter: bool = True
    vwap_length: int = Field(20, ge=1)


class AlertsCfg(BaseModel):
    """Alert channel toggles and options."""

    telegram: bool = True
    discord: bool = False
    email: bool = False
    send_chart_image: bool = True


class WatchlistCfg(BaseModel):
    """Watchlist source configuration."""

    source: Literal["file", "top_volume"] = "file"
    file: str = "watchlist.json"
    top_volume_n: int = Field(50, ge=1)
    blacklist: list[str] = Field(default_factory=list)
    whitelist: list[str] = Field(default_factory=list)


class ExecutorCfg(BaseModel):
    """Paper/live executor trade-management parameters."""

    profit_target_pct: float = Field(0.06, gt=0, description="Net profit target as a fraction (e.g. 0.06 = 6%)")
    use_dip_filter: bool = True
    trailing_stop_pct: float = Field(0.03, ge=0, description="Trailing stop distance as a fraction; 0 disables it")
    max_hold_hours: int = Field(48, ge=1, description="Maximum hours to hold a position before forced exit")


class _ExchangeFeeCfg(BaseModel):
    """Per-exchange fee rates."""

    maker: float = Field(default=0.0005, ge=0)
    taker: float = Field(default=0.001, ge=0)


class FeesCfg(BaseModel):
    """Validated fee table: exchange name -> {maker, taker} rates.

    Config YAML format::

        fees:
          blofin: {maker: 0.0002, taker: 0.0006}
          binance: {maker: 0.0002, taker: 0.0004}

    Internally stored as ``rates: dict[str, dict[str, float]]`` so callers
    can do ``cfg.fees.rates.get(exchange, DEFAULT)``.
    """

    rates: dict[str, dict[str, float]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _accept_flat_dict(cls, data: object) -> object:
        """Allow the YAML to supply the fee mapping directly at the FeesCfg level.

        When ``config.yaml`` writes::

            fees:
              blofin: {maker: 0.0002, taker: 0.0006}

        pydantic receives ``{"blofin": {"maker": 0.0002, "taker": 0.0006}}``
        as the value for the ``fees`` field.  We normalise that into
        ``{"rates": <the dict>}`` so the model validates cleanly.
        """
        if isinstance(data, dict) and "rates" not in data:
            # Treat the whole dict as the rates mapping
            return {"rates": data}
        return data


class Config(BaseModel):
    exchange: str = "blofin"
    paper_trading: bool = True
    data: DataCfg = Field(default_factory=DataCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    signal: SignalCfg = Field(default_factory=SignalCfg)
    scanner: ScannerCfg = Field(default_factory=ScannerCfg)
    alerts: AlertsCfg = Field(default_factory=AlertsCfg)
    watchlist: WatchlistCfg = Field(default_factory=WatchlistCfg)
    executor: ExecutorCfg = Field(default_factory=ExecutorCfg)
    fees: FeesCfg = Field(default_factory=FeesCfg)
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
