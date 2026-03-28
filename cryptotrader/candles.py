from __future__ import annotations
from cryptotrader.models import Candle, PriceTick


class CandleBuilder:
    def __init__(self, timeframe_minutes: int) -> None:
        self._tf = timeframe_minutes
        self._current: Candle | None = None
        self._completed: list[Candle] = []

    def add_tick(self, tick: PriceTick) -> Candle | None:
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
        return self._completed

    @property
    def count(self) -> int:
        return len(self._completed)
