"""Dual EMA crossover with an ATR volatility filter.

Buys when the fast EMA crosses above the slow one, sells on the reverse. The
ATR filter refuses signals when recent range is below `atr_min_pct`, which is
what keeps it out of flat markets where a crossover means nothing.
"""

from __future__ import annotations

from cryptotrader.candles import CandleBuilder
from cryptotrader.config import CurrencyConfig
from cryptotrader.db import database
from cryptotrader.models import PriceTick, Side, Signal
from cryptotrader.strategy._indicators import atr, ema
from cryptotrader.strategy.base import Strategy


class EMAStrategy(Strategy):
    """Dual EMA crossover, filtered by recent volatility."""
    @property
    def name(self) -> str:
        """Identifier written to the trade log, and the key used in config."""
        return "ema"

    def __init__(self, config: CurrencyConfig) -> None:
        """Args:
        config: Per-pair settings; strategy parameters are read from the
        matching sub-table.
        """
        p = config.ema
        self._fast = p.fast_period
        self._slow = p.slow_period
        self._atr_period = p.atr_period
        self._atr_min_pct = p.atr_min_pct
        self._candles = CandleBuilder(timeframe_minutes=60)
        self._in_position = False
        self._db_path: str | None = None

    def restore(self, db_path: str, pair: str) -> None:
        """Rebuild indicator history and position state from the database.

        Called once at startup. Without it a strategy would need hours of live
        ticks before its indicators were usable, and would have forgotten whether
        it holds a position.
        """
        self._db_path = db_path
        candles = database.query_candles(db_path, pair, 60, self._slow + 10)
        if candles:
            self._candles.load(candles)
        trades = database.query_trades(db_path, pair=pair, strategy=self.name)
        if trades and trades[-1].side == Side.BUY:
            self._in_position = True

    def evaluate(self, tick: PriceTick) -> Signal | None:
        """Decide on a completed candle.

        Buys when the fast EMA crosses above the slow one and recent range
        clears `atr_min_pct`; sells on the reverse cross.

        Returns:
        A signal to propose, or None. Most ticks return None — a decision is
        only made when a candle completes.
        """
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
                self._arm_rollback()
                self._in_position = True
                return Signal.BUY
        else:
            if prev_fast >= prev_slow and curr_fast < curr_slow:
                self._arm_rollback()
                self._in_position = False
                return Signal.SELL
        return None
