from datetime import datetime, timezone

import pytest

from cryptotrader.config import CurrencyConfig, ThresholdParams
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.threshold import ThresholdStrategy
from cryptotrader.strategy.registry import get


def make_tick(pair: str, bid: float, ask: float, last: float) -> PriceTick:
    return PriceTick(pair=pair, bid=bid, ask=ask, last=last, timestamp=datetime.now(timezone.utc))


def make_cfg(buy: float, sell: float) -> CurrencyConfig:
    return CurrencyConfig(strategy="threshold", threshold=ThresholdParams(buy_trigger=buy, sell_trigger=sell), quantity=0.001)


def test_buy_signal_when_ask_at_trigger():
    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    tick = make_tick("BTC/USD", bid=49900, ask=50000, last=49950)
    assert strategy.evaluate(tick) == Signal.BUY


def test_buy_signal_when_ask_below_trigger():
    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    tick = make_tick("BTC/USD", bid=49800, ask=49900, last=49850)
    assert strategy.evaluate(tick) == Signal.BUY


def test_no_signal_above_buy_trigger():
    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    tick = make_tick("BTC/USD", bid=50100, ask=50200, last=50150)
    assert strategy.evaluate(tick) is None


def test_sell_signal_after_buy():
    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    # First buy
    strategy.evaluate(make_tick("BTC/USD", bid=49900, ask=49999, last=49950))
    # Now sell
    tick = make_tick("BTC/USD", bid=60000, ask=60100, last=60050)
    assert strategy.evaluate(tick) == Signal.SELL


def test_no_sell_without_position():
    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    tick = make_tick("BTC/USD", bid=65000, ask=65100, last=65050)
    assert strategy.evaluate(tick) is None


def test_registry_returns_threshold():
    cls = get("threshold")
    assert cls is ThresholdStrategy


def test_registry_raises_on_unknown():
    with pytest.raises(KeyError):
        get("nonexistent")
