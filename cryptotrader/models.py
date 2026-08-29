"""Dataclasses passed between components.

`PriceTick` and `Candle` flow from the exchange toward the strategies; `Trade`
and `RejectedOrder` flow back out toward the database and the TUI. `Signal` is
what a strategy returns — a proposal, not an order.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Side(StrEnum):
    """Which way an order goes. Stored as the literal string in the trade log."""
    BUY = "buy"
    SELL = "sell"


class Signal(StrEnum):
    """What a strategy proposes. A signal is not an order — the executor decides."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class PriceTick:
    """One quote from the exchange feed.

    `last` is what strategies act on; `bid` and `ask` matter when deciding
    where to rest a limit order.
    """
    pair: str
    bid: float
    ask: float
    last: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Candle:
    """Aggregated OHLC over one timeframe.

    `timestamp` is the candle's **open** time, not its close. A candle is
    complete once the first tick of the next boundary arrives, which is why a
    decision lands a moment after the hour rather than exactly on it.
    """
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
    """An order the exchange accepted.

    `pnl` is set on the closing leg only, FIFO-matched and gross of fees. It
    stays None when a sell had no matching buy — honest, rather than a
    fabricated zero. `txid` is the exchange's order id, which is what lets a
    fill be matched back to this row during reconciliation.
    """
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


class RejectReason(StrEnum):
    """Why an order the strategy asked for never reached the exchange."""

    INSUFFICIENT_BALANCE = "insufficient_balance"
    MAX_ORDER_EXCEEDED = "max_order_exceeded"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    NO_OPEN_POSITION = "no_open_position"
    BALANCE_CHECK_FAILED = "balance_check_failed"
    MAKER_NO_FILL = "maker_no_fill"


@dataclass
class RejectedOrder:
    """An order the strategy signalled that the executor refused to place.

    Persisted, not just queued: a rejection is not a non-event. A declined buy
    leaves the strategy believing it is long, which is what produced the unbacked
    sell on 2026-08-22 — and that stayed invisible for weeks because it existed
    only as a journald line.
    """

    pair: str
    side: Side
    price: float
    quantity: float
    reason: RejectReason
    mode: str
    detail: str = ""
    strategy: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class Deposit:
    """Funds added to the account, so returns can be measured against what was
    actually put in rather than against the current balance.
    """
    aud_amount: float
    usd_amount: float
    fee_usd: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    notes: str | None = None
    rate_mid: float | None = None
    id: int | None = None


@dataclass
class StatsResult:
    """Aggregated performance over a set of trades. Gross of fees."""
    total_trades: int
    win_rate: float
    total_pnl: float
    avg_gain: float
    avg_loss: float
    buys: int = 0
    sells: int = 0
    pair: str | None = None
    strategy: str | None = None


# The trade log shows filled trades, deposits, and orders that were refused.
LogItem = Trade | Deposit | RejectedOrder
