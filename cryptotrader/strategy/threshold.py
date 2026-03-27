from typing import Optional

from cryptotrader.config import CurrencyConfig
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.base import Strategy


class ThresholdStrategy(Strategy):
    """
    Simple price-threshold strategy.
    Signals BUY when ask price falls at or below buy_trigger.
    Signals SELL when bid price rises at or above sell_trigger.
    """

    def __init__(self, config: CurrencyConfig) -> None:
        self._buy_trigger = config.buy_trigger
        self._sell_trigger = config.sell_trigger
        self._in_position = False

    def evaluate(self, tick: PriceTick) -> Optional[Signal]:
        if not self._in_position and tick.ask <= self._buy_trigger:
            self._in_position = True
            return Signal.BUY
        if self._in_position and tick.bid >= self._sell_trigger:
            self._in_position = False
            return Signal.SELL
        return None
