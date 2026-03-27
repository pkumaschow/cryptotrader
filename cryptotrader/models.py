from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class Signal(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class PriceTick:
    pair: str
    bid: float
    ask: float
    last: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Trade:
    pair: str
    side: Side
    price: float
    quantity: float
    mode: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    pnl: Optional[float] = None
    txid: Optional[str] = None
    id: Optional[int] = None


@dataclass
class StatsResult:
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_gain: float
    avg_loss: float
    pair: Optional[str] = None
