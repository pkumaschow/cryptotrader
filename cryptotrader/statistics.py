from __future__ import annotations

from datetime import UTC, datetime

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, StatsResult, Trade


def compute(pair: str | None = None, mode: str = "test",
            strategy: str | None = None,
            since: datetime | None = None,
            until: datetime | None = None,
            db_path: str | None = None) -> StatsResult:
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


def daily_pnl(mode: str = "test", db_path: str | None = None) -> float:
    """Return realized P&L for completed round-trips since UTC midnight today."""
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return compute(mode=mode, since=today_start, db_path=db_path).total_pnl


def all_strategies(mode: str = "test") -> list[str]:
    settings = get_settings()
    trades = database.query_trades(settings.database.path, mode=mode)
    return sorted({t.strategy for t in trades})
