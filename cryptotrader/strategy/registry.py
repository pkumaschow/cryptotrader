"""Maps strategy names in config to their classes.

`ALL_STRATEGIES` is what test mode runs simultaneously for comparison; `get()`
resolves the single strategy named per pair in production.
"""

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
    """Resolve a strategy name from config to its class.

    Raises:
    KeyError: If the name is unknown. A typo in `settings.toml` should
    fail loudly at startup rather than silently trade with the
    wrong logic.
    """
    if name not in _REGISTRY:
        raise KeyError(f"Unknown strategy {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]
