from __future__ import annotations

from cryptotrader.candles import CandleBuilder
from cryptotrader.config import CurrencyConfig
from cryptotrader.db import database
from cryptotrader.models import PriceTick, Side, Signal
from cryptotrader.strategy._indicators import bollinger_bands, ema
from cryptotrader.strategy.base import Strategy


class BollingerStrategy(Strategy):
    @property
    def name(self) -> str:
        return "bollinger"

    def __init__(self, config: CurrencyConfig) -> None:
        p = config.bollinger
        self._period = p.period
        self._std_dev = p.std_dev
        self._min_bw_pct = p.min_band_width_pct
        self._fee_per_trade = p.fee_per_trade_usd
        self._stop_loss_pct = p.stop_loss_pct
        self._quantity = config.quantity
        self._candles = CandleBuilder(timeframe_minutes=60)
        self._trend_filter = p.trend_filter_enabled
        self._trend_period = p.trend_ema_period
        self._trend_tf = p.trend_timeframe_minutes
        self._trend_candles = (
            CandleBuilder(timeframe_minutes=self._trend_tf) if self._trend_filter else None
        )
        self._in_position = False
        self._entry_price: float | None = None
        self._db_path: str | None = None
        self.last_band_width: float | None = None

    def restore(self, db_path: str, pair: str) -> None:
        self._db_path = db_path
        candles = database.query_candles(db_path, pair, 60, self._period + 10)
        if candles:
            self._candles.load(candles)
        if self._trend_candles is not None:
            trend_candles = database.query_candles(
                db_path, pair, self._trend_tf, self._trend_period + 10
            )
            if trend_candles:
                self._trend_candles.load(trend_candles)
        trades = database.query_trades(db_path, pair=pair, strategy=self.name)
        if trades and trades[-1].side == Side.BUY:
            self._in_position = True
            self._entry_price = trades[-1].price

    def _trend_is_up(self) -> bool:
        """True when the higher-timeframe trend EMA is rising. Conservative during warmup."""
        if self._trend_candles is None:
            return True
        closes = [c.close for c in self._trend_candles.candles]
        trend = ema(closes, self._trend_period)
        if len(trend) < 2:
            return False
        return trend[-1] > trend[-2]

    def evaluate(self, tick: PriceTick) -> Signal | None:
        completed = self._candles.add_tick(tick)
        if completed is not None and self._db_path is not None:
            database.insert_candle(self._db_path, completed)
        if self._trend_candles is not None:
            trend_completed = self._trend_candles.add_tick(tick)
            if trend_completed is not None and self._db_path is not None:
                database.insert_candle(self._db_path, trend_completed)
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
        curr_bw_pct = curr_width / curr_mid * 100 if self._min_bw_pct else 0.0
        last_close = candles[-1].close
        if not self._in_position:
            if (
                last_close > curr_upper
                and curr_width > prev_width
                and curr_bw_pct >= self._min_bw_pct
                and self._trend_is_up()
            ):
                self._in_position = True
                self._entry_price = last_close
                self.last_band_width = round(curr_width, 4)
                return Signal.BUY
        else:
            # Stop-loss: cut a losing position regardless of the small-profit gate below.
            # Without this, the gate blocks every loss-making exit and bags are held forever.
            if (
                self._stop_loss_pct > 0
                and self._entry_price is not None
                and last_close <= self._entry_price * (1 - self._stop_loss_pct / 100)
            ):
                self._in_position = False
                self._entry_price = None
                self.last_band_width = round(curr_width, 4)
                return Signal.SELL
            if last_close < curr_mid:
                if (
                    self._fee_per_trade > 0
                    and self._entry_price is not None
                    and (last_close - self._entry_price) * self._quantity < self._fee_per_trade * 2
                ):
                    return None
                self._in_position = False
                self._entry_price = None
                self.last_band_width = round(curr_width, 4)
                return Signal.SELL
        return None
