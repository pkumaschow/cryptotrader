from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class Signal(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class PriceTick:
    pair: str
    bid: float
    ask: float
    last: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Candle:
    pair: str
    timeframe: int
    open: float
    high: float
    low: float
    close: float
    tick_count: int
    timestamp: datetime


@dataclass
class Trade:
    pair: str
    side: Side
    price: float
    quantity: float
    mode: str
    strategy: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    pnl: float | None = None
    txid: str | None = None
    band_width: float | None = None
    id: int | None = None


@dataclass
class Deposit:
    aud_amount: float
    usd_amount: float
    fee_usd: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: str | None = None
    rate_mid: float | None = None
    id: int | None = None


@dataclass
class StatsResult:
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_gain: float
    avg_loss: float
    buys: int = 0
    sells: int = 0
    pair: str | None = None
    strategy: str | None = None
