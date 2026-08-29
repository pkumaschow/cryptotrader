"""Aggregate price ticks into fixed-timeframe OHLC candles.

Strategies evaluate on *completed* candles, so this is what paces the bot: with
the default 60-minute timeframe a strategy makes at most one decision per hour
per pair, on that candle's closing price. A spike between closes is invisible.

`timestamp` on a candle is its **open** time. A candle completes when the first
tick of the next boundary arrives, which is why a decision is recorded a moment
after the hour rather than exactly on it.
"""

from __future__ import annotations

from cryptotrader.models import Candle, PriceTick


class CandleBuilder:
    """Accumulates ticks into candles of a single timeframe.

    Holds one in-progress candle plus the completed history. Completion is
    driven by tick timestamps rather than a clock, so replaying stored ticks
    reproduces exactly the candles the live bot saw.
    """
    def __init__(self, timeframe_minutes: int) -> None:
        """Args:
        timeframe_minutes: Candle width. Should divide evenly into an hour so
        boundaries align with wall-clock hours.
        """
        self._tf = timeframe_minutes
        self._current: Candle | None = None
        self._completed: list[Candle] = []

    def add_tick(self, tick: PriceTick) -> Candle | None:
        """Fold a tick in, returning a candle if this tick started a new one.

        Returns:
        The completed candle, or None while the current one is still open.
        A caller that discards this never learns a candle closed — the only
        moment a strategy acts.
        """
        boundary = self._candle_open(tick.timestamp)
        price = tick.last
        if self._current is None:
            self._current = Candle(pair=tick.pair, timeframe=self._tf,
                open=price, high=price, low=price, close=price, tick_count=1, timestamp=boundary)
            return None
        if self._current.timestamp == boundary:
            c = self._current
            c.high = max(c.high, price)
            c.low = min(c.low, price)
            c.close = price
            c.tick_count += 1
            return None
        completed = self._current
        self._completed.append(completed)
        self._current = Candle(pair=tick.pair, timeframe=self._tf,
            open=price, high=price, low=price, close=price, tick_count=1, timestamp=boundary)
        return completed

    def _candle_open(self, ts):
        total_minutes = ts.hour * 60 + ts.minute
        aligned = (total_minutes // self._tf) * self._tf
        return ts.replace(hour=aligned // 60, minute=aligned % 60, second=0, microsecond=0)

    def load(self, candles: list[Candle]) -> None:
        """Pre-populate completed candle history (called on service restart)."""
        self._completed = list(candles)

    @property
    def candles(self) -> list[Candle]:
        """Completed candles, oldest first. Excludes the one still open."""
        return self._completed

    @property
    def count(self) -> int:
        """How many candles have completed."""
        return len(self._completed)
