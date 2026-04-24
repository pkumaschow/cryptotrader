from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class ThresholdParams(BaseModel):
    buy_trigger: float = 0.0
    sell_trigger: float = 0.0


class EMAParams(BaseModel):
    fast_period: int = 20
    slow_period: int = 50
    atr_period: int = 14
    atr_min_pct: float = 0.5


class BollingerParams(BaseModel):
    period: int = 20
    std_dev: float = 2.0
    min_band_width_pct: float = Field(default=0.0, ge=0.0)
    fee_per_trade_usd: float = Field(default=0.0, ge=0.0)


class TrendPullbackParams(BaseModel):
    trend_ema_period: int = 50
    pullback_ema_period: int = 20


class CurrencyConfig(BaseModel):
    strategy: str = "ema"
    quantity: float = Field(gt=0, le=100000.0)
    # Production only: spend this USD amount per buy (overrides quantity)
    budget_usd: float | None = None
    # Hard cap — refuse to place any order exceeding this USD value
    max_order_usd: float
    threshold: ThresholdParams = ThresholdParams()
    ema: EMAParams = EMAParams()
    bollinger: BollingerParams = BollingerParams()
    trend_pullback: TrendPullbackParams = TrendPullbackParams()


class ModeConfig(BaseModel):
    active: str
    max_daily_loss_usd: float

    @field_validator("active")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in ("test", "production"):
            raise ValueError(f"mode.active must be 'test' or 'production', got {v!r}")
        return v


class DatabaseConfig(BaseModel):
    path: str = "cryptotrader.db"


class WebsocketConfig(BaseModel):
    stale_threshold: int = 30
    stats_refresh_interval: int = 5


class Settings(BaseModel):
    mode: ModeConfig
    database: DatabaseConfig = DatabaseConfig()
    websocket: WebsocketConfig = WebsocketConfig()
    currencies: dict[str, CurrencyConfig]


class KrakenSecrets(BaseSettings):
    kraken_api_key: str = ""
    kraken_api_secret: SecretStr = SecretStr("")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


class _AppConfig(BaseSettings):
    cryptotrader_config: str = str(Path(__file__).parent.parent / "config" / "settings.toml")
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

_CONFIG_PATH = Path(_AppConfig().cryptotrader_config)


@lru_cache(maxsize=1)
def get_settings(config_path: str = str(_CONFIG_PATH)) -> Settings:
    with open(config_path, "rb") as f:
        raw: dict[str, Any] = tomllib.load(f)
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_secrets() -> KrakenSecrets:
    return KrakenSecrets()
