from __future__ import annotations
from typing import Optional
from cryptotrader.candles import CandleBuilder
from cryptotrader.config import CurrencyConfig
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy._indicators import ema
from cryptotrader.strategy.base import Strategy


class TrendPullbackStrategy(Strategy):
    @property
    def name(self) -> str:
        return "trend_pullback"

    def __init__(self, config: CurrencyConfig) -> None:
        p = config.trend_pullback
        self._trend_period = p.trend_ema_period
        self._pullback_period = p.pullback_ema_period
        self._candles_1h = CandleBuilder(timeframe_minutes=60)
        self._candles_4h = CandleBuilder(timeframe_minutes=240)
        self._in_position = False

    def evaluate(self, tick: PriceTick) -> Optional[Signal]:
        completed_1h = self._candles_1h.add_tick(tick)
        self._candles_4h.add_tick(tick)
        if completed_1h is None:
            return None
        candles_4h = self._candles_4h.candles
        candles_1h = self._candles_1h.candles
        if len(candles_4h) < self._trend_period + 2:
            return None
        if len(candles_1h) < self._pullback_period + 2:
            return None
        closes_4h = [c.close for c in candles_4h]
        trend_ema = ema(closes_4h, self._trend_period)
        if len(trend_ema) < 2:
            return None
        trend_up = trend_ema[-1] > trend_ema[-2]
        closes_1h = [c.close for c in candles_1h]
        pb_ema = ema(closes_1h, self._pullback_period)
        if len(pb_ema) < 2:
            return None
        curr_close = candles_1h[-1].close
        prev_close = candles_1h[-2].close
        curr_pb = pb_ema[-1]
        prev_pb = pb_ema[-2]
        if not self._in_position:
            if trend_up and prev_close <= prev_pb and curr_close > curr_pb:
                self._in_position = True
                return Signal.BUY
        else:
            if not trend_up or curr_close < curr_pb:
                self._in_position = False
                return Signal.SELL
        return None
