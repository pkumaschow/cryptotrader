from datetime import datetime, timezone

import pytest

from cryptotrader.config import CurrencyConfig, TrendPullbackParams
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.trend_pullback import TrendPullbackStrategy


def make_tick(price: float, hour: int) -> PriceTick:
    ts = datetime(2024, 1, 1, hour, 0, 0, tzinfo=timezone.utc)
    return PriceTick(pair="BTC/USD", bid=price, ask=price, last=price, timestamp=ts)


def make_cfg(trend_period: int = 3, pullback_period: int = 3) -> CurrencyConfig:
    return CurrencyConfig(
        quantity=0.001,
        trend_pullback=TrendPullbackParams(
            trend_ema_period=trend_period,
            pullback_ema_period=pullback_period,
        ),
    )


def test_returns_none_during_warmup():
    """Not enough 4h candles yet → always None."""
    strategy = TrendPullbackStrategy(make_cfg(trend_period=3, pullback_period=3))
    # trend_period+2=5 4h-candles = 20 hours; check first 10
    results = [strategy.evaluate(make_tick(50000.0, h)) for h in range(10)]
    assert all(r is None for r in results)


def test_sell_when_trend_down():
    """With _in_position=True and declining prices, trend_up=False → SELL."""
    strategy = TrendPullbackStrategy(make_cfg(trend_period=3, pullback_period=3))
    strategy._in_position = True
    got_sell = False
    for h in range(40):
        price = 10000.0 - h * 200  # steadily declining
        result = strategy.evaluate(make_tick(price, h))
        if result == Signal.SELL:
            got_sell = True
            break
    assert got_sell


def test_sell_when_price_below_pullback_ema():
    """With _in_position=True and price crashing below pullback EMA → SELL."""
    strategy = TrendPullbackStrategy(make_cfg(trend_period=3, pullback_period=3))
    strategy._in_position = True
    prices = [10000.0] * 25 + [1.0] * 15  # flat then sudden crash
    got_sell = False
    for h, price in enumerate(prices):
        result = strategy.evaluate(make_tick(price, h))
        if result == Signal.SELL:
            got_sell = True
            break
    assert got_sell


def test_strategy_name():
    assert TrendPullbackStrategy(make_cfg()).name == "trend_pullback"
