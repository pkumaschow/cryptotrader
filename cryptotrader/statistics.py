"""Derived views over the trade log: P&L, win rate, and open positions.

`open_position_quantity` is the authority on what is currently held, and floors
the running total at zero on each sell so a historical over-sell cannot carry a
negative balance forward and swallow the next buy. Anything else computing
holdings should match it.

P&L is FIFO-matched on the closing leg and **gross of fees**.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, StatsResult, Trade


def compute(pair: str | None = None, mode: str = "test",
            strategy: str | None = None,
            since: datetime | None = None,
            until: datetime | None = None,
            db_path: str | None = None) -> StatsResult:
    """Aggregate realized performance over the trade log.

    Round trips are FIFO-matched: each sell closes the oldest open buy. P&L is
    **gross of fees**, so subtract roughly 1.6% of notional per round trip at
    Kraken's low-volume taker rate.

    Args:
    mode: Which trade set to measure — 'production' or 'test'.
    strategy: Restrict to one strategy, or None for all.
    pair: Restrict to one pair, or None for all.
    since: Only count trades at or after this time.
    db_path: Database to read; defaults to the configured path.
    """
    path = db_path if db_path is not None else get_settings().database.path
    trades = database.query_trades(
        path, pair=pair, mode=mode,
        strategy=strategy, since=since, until=until,
    )
    if not trades:
        return StatsResult(total_trades=0, win_rate=0.0, total_pnl=0.0,
                           avg_gain=0.0, avg_loss=0.0, pair=pair, strategy=strategy)
    gains: list[float] = []
    losses: list[float] = []
    open_buys: dict[str, list[Trade]] = {}
    buys = 0
    sells = 0
    for trade in trades:
        p = trade.pair
        if trade.side == Side.BUY:
            buys += 1
            open_buys.setdefault(p, []).append(trade)
        elif trade.side == Side.SELL:
            sells += 1
            if open_buys.get(p):
                buy = open_buys[p].pop(0)
                pnl = (trade.price - buy.price) * trade.quantity
                (gains if pnl >= 0 else losses).append(pnl)
    completed = len(gains) + len(losses)
    win_rate = (len(gains) / completed * 100) if completed > 0 else 0.0
    return StatsResult(
        total_trades=completed, win_rate=win_rate,
        total_pnl=sum(gains) + sum(losses),
        avg_gain=sum(gains) / len(gains) if gains else 0.0,
        avg_loss=sum(losses) / len(losses) if losses else 0.0,
        buys=buys, sells=sells,
        pair=pair, strategy=strategy,
    )


def realized_pnl_for_sell(
    pair: str,
    mode: str,
    sell_price: float,
    sell_quantity: float,
    strategy: str | None = None,
    db_path: str | None = None,
) -> float | None:
    """Realized P&L for a sell about to be recorded.

    FIFO-matched against the oldest still-open buy for this pair/mode(/strategy),
    using the same convention as compute(): gross of fees,
    pnl = (sell_price - entry_price) * sell_quantity. Returns None when there is
    no open buy to close (so the caller stores NULL rather than a bogus 0.0).
    """
    path = db_path if db_path is not None else get_settings().database.path
    prior = database.query_trades(path, pair=pair, mode=mode, strategy=strategy)
    open_buys: list[Trade] = []
    for t in prior:
        if t.side == Side.BUY:
            open_buys.append(t)
        elif t.side == Side.SELL and open_buys:
            open_buys.pop(0)
    if not open_buys:
        return None
    return (sell_price - open_buys[0].price) * sell_quantity


def open_position_quantity(
    pair: str,
    mode: str,
    strategy: str | None = None,
    db_path: str | None = None,
) -> float:
    """Quantity of `pair` currently held according to the trade log.

    Walks the trades in order: buys add, sells subtract. The running total is
    floored at zero on each sell so that a historical over-sell — the sizing bug
    that let sells use the static config lot while buys used `budget_usd` — does
    not carry a negative balance forward and silently swallow the next buy.

    Rounded down to 8 dp so float drift can never ask the exchange to sell a
    hair more than is actually held.
    """
    path = db_path if db_path is not None else get_settings().database.path
    prior = database.query_trades(path, pair=pair, mode=mode, strategy=strategy)
    qty = 0.0
    for t in prior:
        if t.side == Side.BUY:
            qty += t.quantity
        else:
            qty = max(0.0, qty - t.quantity)
    return math.floor(qty * 1e8) / 1e8


def daily_pnl(mode: str = "test", db_path: str | None = None) -> float:
    """Return realized P&L for completed round-trips since UTC midnight today."""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return compute(mode=mode, since=today_start, db_path=db_path).total_pnl


def all_strategies(mode: str = "test") -> list[str]:
    """Distinct strategy names appearing in the trade log for `mode`."""
    settings = get_settings()
    trades = database.query_trades(settings.database.path, mode=mode)
    return sorted({t.strategy for t in trades})
