from typing import Type

from cryptotrader.strategy.base import Strategy
from cryptotrader.strategy.threshold import ThresholdStrategy

_REGISTRY: dict[str, Type[Strategy]] = {
    "threshold": ThresholdStrategy,
}


def get(name: str) -> Type[Strategy]:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]
