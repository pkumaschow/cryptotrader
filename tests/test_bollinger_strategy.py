from datetime import datetime, timezone

from cryptotrader.config import BollingerParams, CurrencyConfig
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.bollinger import BollingerStrategy


def make_tick(price: float, hour: int, minute: int = 0) -> PriceTick:
    ts = datetime(2024, 1, 1, hour, minute, 0, tzinfo=timezone.utc)
    return PriceTick(pair="BTC/USD", bid=price, ask=price, last=price, timestamp=ts)


def make_cfg(period: int = 3, std_dev: float = 2.0) -> CurrencyConfig:
    return CurrencyConfig(quantity=0.001, bollinger=BollingerParams(period=period, std_dev=std_dev))


def test_returns_none_during_warmup():
    strategy = BollingerStrategy(make_cfg(period=3))
    # period+2=5 candles needed; 5 ticks produce 4 completed candles
    results = [strategy.evaluate(make_tick(50000.0, h)) for h in range(5)]
    assert all(r is None for r in results)


def test_buy_signal_when_price_breaks_upper_band():
    """Tiny std_dev makes the band narrow so a spike easily exceeds upper."""
    strategy = BollingerStrategy(make_cfg(period=3, std_dev=0.1))
    # Warm up with flat prices
    for h in range(5):
        strategy.evaluate(make_tick(50.0, h))
    # Spike inside h5 boundary (updates close to 500), then cross to h6
    strategy.evaluate(make_tick(50.0, 5))
    strategy.evaluate(make_tick(500.0, 5, minute=30))
    result = strategy.evaluate(make_tick(50.0, 6))
    assert result == Signal.BUY


def test_sell_signal_when_price_drops_below_midline():
    strategy = BollingerStrategy(make_cfg(period=3, std_dev=2.0))
    strategy._in_position = True
    # Warm up with high prices, then spike low to pull close below mid
    for h in range(5):
        strategy.evaluate(make_tick(100.0, h))
    strategy.evaluate(make_tick(100.0, 5))
    strategy.evaluate(make_tick(10.0, 5, minute=30))  # h5 closes at 10
    result = strategy.evaluate(make_tick(100.0, 6))
    assert result == Signal.SELL


def test_no_sell_without_position():
    strategy = BollingerStrategy(make_cfg(period=3, std_dev=0.1))
    results = [strategy.evaluate(make_tick(50.0, h)) for h in range(10)]
    assert Signal.SELL not in results


def test_strategy_name():
    assert BollingerStrategy(make_cfg()).name == "bollinger"
