from abc import ABC, abstractmethod
from typing import Optional

from cryptotrader.models import PriceTick, Signal


class Strategy(ABC):
    @abstractmethod
    def evaluate(self, tick: PriceTick) -> Optional[Signal]:
        """Return BUY, SELL, or None based on the price tick."""
        ...
