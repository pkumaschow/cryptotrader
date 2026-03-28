from abc import ABC, abstractmethod
from typing import Optional
from cryptotrader.models import PriceTick, Signal


class Strategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(self, tick: PriceTick) -> Optional[Signal]: ...

    def restore(self, db_path: str, pair: str) -> None:
        """Reload candle history and position state from DB. No-op by default."""
