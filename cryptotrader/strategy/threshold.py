from typing import Optional
from cryptotrader.config import CurrencyConfig
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.base import Strategy


class ThresholdStrategy(Strategy):
    @property
    def name(self) -> str:
        return "threshold"

    def __init__(self, config: CurrencyConfig) -> None:
        self._buy_trigger = config.threshold.buy_trigger
        self._sell_trigger = config.threshold.sell_trigger
        self._in_position = False

    def evaluate(self, tick: PriceTick) -> Optional[Signal]:
        if not self._in_position and tick.ask <= self._buy_trigger:
            self._in_position = True
            return Signal.BUY
        if self._in_position and tick.bid >= self._sell_trigger:
            self._in_position = False
            return Signal.SELL
        return None
