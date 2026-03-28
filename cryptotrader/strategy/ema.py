from __future__ import annotations
from typing import Optional
from cryptotrader.candles import CandleBuilder
from cryptotrader.config import CurrencyConfig
from cryptotrader.db import database
from cryptotrader.models import PriceTick, Side, Signal
from cryptotrader.strategy._indicators import atr, ema
from cryptotrader.strategy.base import Strategy


class EMAStrategy(Strategy):
    @property
    def name(self) -> str:
        return "ema"

    def __init__(self, config: CurrencyConfig) -> None:
        p = config.ema
        self._fast = p.fast_period
        self._slow = p.slow_period
        self._atr_period = p.atr_period
        self._atr_min_pct = p.atr_min_pct
        self._candles = CandleBuilder(timeframe_minutes=60)
        self._in_position = False
        self._db_path: Optional[str] = None

    def restore(self, db_path: str, pair: str) -> None:
        self._db_path = db_path
        candles = database.query_candles(db_path, pair, 60, self._slow + 10)
        if candles:
            self._candles.load(candles)
        trades = database.query_trades(db_path, pair=pair, strategy=self.name)
        if trades and trades[-1].side == Side.BUY:
            self._in_position = True

    def evaluate(self, tick: PriceTick) -> Optional[Signal]:
        completed = self._candles.add_tick(tick)
        if completed is not None and self._db_path is not None:
            database.insert_candle(self._db_path, completed)
        if completed is None:
            return None
        candles = self._candles.candles
        if len(candles) < self._slow + 2:
            return None
        closes = [c.close for c in candles]
        fast_s = ema(closes, self._fast)
        slow_s = ema(closes, self._slow)
        if len(fast_s) < 2 or len(slow_s) < 2:
            return None
        curr_fast, prev_fast = fast_s[-1], fast_s[-2]
        curr_slow, prev_slow = slow_s[-1], slow_s[-2]
        current_atr = atr(candles, self._atr_period)
        if current_atr is None or tick.last == 0:
            return None
        atr_pct = (current_atr / tick.last) * 100.0
        if not self._in_position:
            if prev_fast <= prev_slow and curr_fast > curr_slow and atr_pct >= self._atr_min_pct:
                self._in_position = True
                return Signal.BUY
        else:
            if prev_fast >= prev_slow and curr_fast < curr_slow:
                self._in_position = False
                return Signal.SELL
        return None
