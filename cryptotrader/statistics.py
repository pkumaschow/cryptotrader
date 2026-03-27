from __future__ import annotations

from typing import Optional

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, StatsResult, Trade


def compute(pair: Optional[str] = None, mode: str = "test") -> StatsResult:
    settings = get_settings()
    trades = database.query_trades(settings.database.path, pair=pair, mode=mode)

    if not trades:
        return StatsResult(total_trades=0, win_rate=0.0, total_pnl=0.0, avg_gain=0.0, avg_loss=0.0, pair=pair)

    # Pair BUY+SELL into completed positions to compute P&L
    gains: list[float] = []
    losses: list[float] = []
    open_buys: dict[str, list[Trade]] = {}

    for trade in trades:
        p = trade.pair
        if trade.side == Side.BUY:
            open_buys.setdefault(p, []).append(trade)
        elif trade.side == Side.SELL and open_buys.get(p):
            buy = open_buys[p].pop(0)
            pnl = (trade.price - buy.price) * trade.quantity
            if pnl >= 0:
                gains.append(pnl)
            else:
                losses.append(pnl)

    completed = len(gains) + len(losses)
    win_rate = (len(gains) / completed * 100) if completed > 0 else 0.0
    total_pnl = sum(gains) + sum(losses)
    avg_gain = sum(gains) / len(gains) if gains else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    return StatsResult(
        total_trades=completed,
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_gain=avg_gain,
        avg_loss=avg_loss,
        pair=pair,
    )
