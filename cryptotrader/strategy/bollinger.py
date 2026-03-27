from __future__ import annotations
from typing import Optional
from cryptotrader.candles import CandleBuilder
from cryptotrader.config import CurrencyConfig
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy._indicators import bollinger_bands
from cryptotrader.strategy.base import Strategy


class BollingerStrategy(Strategy):
    @property
    def name(self) -> str:
        return "bollinger"

    def __init__(self, config: CurrencyConfig) -> None:
        p = config.bollinger
        self._period = p.period
        self._std_dev = p.std_dev
        self._candles = CandleBuilder(timeframe_minutes=60)
        self._in_position = False

    def evaluate(self, tick: PriceTick) -> Optional[Signal]:
        completed = self._candles.add_tick(tick)
        if completed is None:
            return None
        candles = self._candles.candles
        if len(candles) < self._period + 2:
            return None
        closes = [c.close for c in candles]
        curr = bollinger_bands(closes, self._period, self._std_dev)
        prev = bollinger_bands(closes[:-1], self._period, self._std_dev)
        if curr is None or prev is None:
            return None
        curr_upper, curr_mid, curr_lower = curr
        prev_upper, _, prev_lower = prev
        curr_width = curr_upper - curr_lower
        prev_width = prev_upper - prev_lower
        last_close = candles[-1].close
        if not self._in_position:
            if last_close > curr_upper and curr_width > prev_width:
                self._in_position = True
                return Signal.BUY
        else:
            if last_close < curr_mid:
                self._in_position = False
                return Signal.SELL
        return None
