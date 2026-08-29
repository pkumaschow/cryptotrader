"""Typed configuration, loaded from TOML and validated by pydantic.

`get_settings()` is cached, so config is read once per process. Point it at a
different file with the `CRYPTOTRADER_CONFIG` environment variable — that is how
one host runs production and staging side by side.

Secrets live in `.env` and are loaded separately by `get_secrets()`; they are
only required in production mode.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings


class ThresholdParams(BaseModel):
    """Fixed price triggers for the `threshold` strategy."""
    buy_trigger: float = 0.0
    sell_trigger: float = 0.0


class EMAParams(BaseModel):
    """Dual-EMA crossover settings, with an ATR volatility floor.

    `atr_min_pct` refuses signals in flat markets, where a crossover carries
    little information.
    """
    fast_period: int = 20
    slow_period: int = 50
    atr_period: int = 14
    atr_min_pct: float = 0.5


class BollingerParams(BaseModel):
    """Bollinger breakout settings.

    Two of these decide whether the strategy can lose money indefinitely.
    `stop_loss_pct` at 0 disables the only exit that can realize a loss — the
    small-profit gate blocks the others — so a losing position is held until it
    recovers or you intervene. `fee_per_trade_usd` is a flat figure while real
    fees are a percentage of notional, so it is only correct at one position
    size; revisit it whenever position size changes.
    """
    period: int = 20
    std_dev: float = 2.0
    min_band_width_pct: float = Field(default=0.0, ge=0.0)
    fee_per_trade_usd: float = Field(default=0.0, ge=0.0)
    # Stop-loss: exit a losing position when close falls this % below entry, regardless of the
    # small-profit gate. 0.0 = disabled. Prevents indefinite bag-holding in a downtrend.
    stop_loss_pct: float = Field(default=0.0, ge=0.0)
    # Gate breakout entries on a rising higher-timeframe trend EMA. Off by default;
    # enable per-currency for trending large-caps, leave off for high-volatility pairs.
    trend_filter_enabled: bool = False
    trend_timeframe_minutes: int = 240
    trend_ema_period: int = 50


class TrendPullbackParams(BaseModel):
    """Trend EMA plus a shorter pullback EMA, for entering on a retracement
    within an established trend rather than chasing a breakout.
    """
    trend_ema_period: int = 50
    pullback_ema_period: int = 20


class CurrencyConfig(BaseModel):
    """Per-pair trading settings.

    `quantity` and `budget_usd` interact and the interaction has bitten before:
    `budget_usd` sizes buys only, and sells are sized from the open position in
    the trade log. `max_order_usd` is a hard cap — an order above it is refused
    and the trading loop aborts rather than continuing quietly.
    """
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
    """Trading mode and the daily loss circuit breaker.

    `max_daily_loss_usd` is evaluated on **realized** P&L since UTC midnight,
    so an open position falling in value does not trip it — that is what
    `stop_loss_pct` covers.
    """
    active: str
    max_daily_loss_usd: float

    @field_validator("active")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        """Reject any mode other than 'test' or 'production'.

        A typo here would otherwise be the difference between paper trading and
        spending real money, so it fails at load rather than at first signal.
        """
        if v not in ("test", "production"):
            raise ValueError(f"mode.active must be 'test' or 'production', got {v!r}")
        return v


class DatabaseConfig(BaseModel):
    """Where the SQLite trade log lives."""
    path: str = "cryptotrader.db"


class WebsocketConfig(BaseModel):
    """Price feed tuning.

    `stale_threshold` is a safety control, not a display setting: once the feed
    goes quiet for that long, orders are suspended rather than placed against
    a price that may no longer exist.
    """
    stale_threshold: int = 30
    stats_refresh_interval: int = 5


class ExecutionConfig(BaseModel):
    """How orders reach the exchange.

    Kraken charges 0.80% taker and 0.40% maker at this account's volume tier, so
    a resting post-only limit halves the fee on any leg that fills. The catch is
    that a breakout entry is bought *into* upward movement, and a resting order
    may never fill.

    Entries only. Exits stay market orders deliberately: skipping an unfilled buy
    costs an opportunity, but skipping an unfilled *sell* means holding a position
    the strategy decided to close — which is how a stop-loss turns back into
    bag-holding.

    Defaults are off, so production behaviour is unchanged unless a config opts in.
    """

    maker_entries: bool = False
    #: Seconds to leave the limit resting before cancelling and skipping the signal.
    maker_wait_seconds: int = Field(default=300, gt=0)
    #: Cancel early if price runs this far from the decision price. Bounds how
    #: stale a fill can be, which is the thing that actually matters — elapsed
    #: time is only a proxy for it.
    maker_max_drift_pct: float = Field(default=0.5, gt=0)


class Settings(BaseModel):
    """The whole configuration, as loaded from TOML and validated."""
    mode: ModeConfig
    database: DatabaseConfig = DatabaseConfig()
    websocket: WebsocketConfig = WebsocketConfig()
    execution: ExecutionConfig = ExecutionConfig()
    currencies: dict[str, CurrencyConfig]


class KrakenSecrets(BaseSettings):
    """API credentials, read from `.env` and never from the TOML config.

    Only required in production mode. The key needs trade and query
    permissions — never withdrawal.
    """
    kraken_api_key: str = ""
    kraken_api_secret: SecretStr = SecretStr("")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


class _AppConfig(BaseSettings):
    cryptotrader_config: str = str(Path(__file__).parent.parent / "config" / "settings.toml")
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

_CONFIG_PATH = Path(_AppConfig().cryptotrader_config)


@lru_cache(maxsize=1)
def get_settings(config_path: str = str(_CONFIG_PATH)) -> Settings:
    """Load and validate configuration, cached for the process lifetime.

    The path comes from `CRYPTOTRADER_CONFIG`, which is how one host runs
    production and staging side by side. Cached, so tests that override
    config must call `get_settings.cache_clear()` first.
    """
    with open(config_path, "rb") as f:
        raw: dict[str, Any] = tomllib.load(f)
    return Settings.model_validate(raw)


@lru_cache(maxsize=1)
def get_secrets() -> KrakenSecrets:
    """Load API credentials from the environment, cached.

    Returns empty credentials in test mode rather than raising, since paper
    trading never reaches the exchange.
    """
    return KrakenSecrets()
