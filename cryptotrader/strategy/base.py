from abc import ABC, abstractmethod

from cryptotrader.models import PriceTick, Signal


class Strategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(self, tick: PriceTick) -> Signal | None: ...

    def restore(self, db_path: str, pair: str) -> None:  # noqa: B027
        """Reload candle history and position state from DB. No-op by default."""
