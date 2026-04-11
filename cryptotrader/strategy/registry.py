
from cryptotrader.strategy.base import Strategy
from cryptotrader.strategy.bollinger import BollingerStrategy
from cryptotrader.strategy.ema import EMAStrategy
from cryptotrader.strategy.threshold import ThresholdStrategy
from cryptotrader.strategy.trend_pullback import TrendPullbackStrategy

_REGISTRY: dict[str, type[Strategy]] = {
    "threshold": ThresholdStrategy,
    "ema": EMAStrategy,
    "bollinger": BollingerStrategy,
    "trend_pullback": TrendPullbackStrategy,
}

ALL_STRATEGIES: list[type[Strategy]] = list(_REGISTRY.values())


def get(name: str) -> type[Strategy]:
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]
