from datetime import datetime, timezone

from cryptotrader.config import CurrencyConfig, EMAParams
from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.ema import EMAStrategy


def make_tick(price: float, hour: int) -> PriceTick:
    ts = datetime(2024, 1, 1, hour, 0, 0, tzinfo=timezone.utc)
    return PriceTick(pair="BTC/USD", bid=price, ask=price, last=price, timestamp=ts)


def make_cfg(fast: int = 3, slow: int = 5, atr_period: int = 3, atr_min_pct: float = 0.0) -> CurrencyConfig:
    return CurrencyConfig(
        quantity=0.001,
        ema=EMAParams(fast_period=fast, slow_period=slow, atr_period=atr_period, atr_min_pct=atr_min_pct),
    )


def test_returns_none_during_warmup():
    strategy = EMAStrategy(make_cfg())
    # slow=5 → needs slow+2=7 completed candles; 7 ticks produce only 6
    results = [strategy.evaluate(make_tick(50000.0, h)) for h in range(7)]
    assert all(r is None for r in results)


def test_buy_signal_on_fast_slow_crossover():
    """Flat prices then a spike causes fast EMA to cross above slow."""
    strategy = EMAStrategy(make_cfg(fast=3, slow=5, atr_period=3, atr_min_pct=0.0))
    # 9 ticks: flat at 50, spike at h7, close spike at h8
    prices = [50.0] * 7 + [100.0, 50.0]
    results = [strategy.evaluate(make_tick(p, h)) for h, p in enumerate(prices)]
    assert Signal.BUY in results


def test_no_signal_when_prices_flat():
    strategy = EMAStrategy(make_cfg())
    results = [strategy.evaluate(make_tick(50000.0, h)) for h in range(20)]
    assert Signal.BUY not in results
    assert Signal.SELL not in results


def test_sell_signal_after_buy():
    """After a BUY, price drop eventually causes fast EMA to cross below slow."""
    strategy = EMAStrategy(make_cfg(fast=3, slow=5, atr_period=3, atr_min_pct=0.0))
    # Trigger BUY
    prices_up = [50.0] * 7 + [100.0, 50.0]
    for h, p in enumerate(prices_up):
        strategy.evaluate(make_tick(p, h))
    assert strategy._in_position

    # Drive prices very low to force fast EMA below slow
    base = len(prices_up)
    got_sell = False
    for h in range(30):
        result = strategy.evaluate(make_tick(1.0, base + h))
        if result == Signal.SELL:
            got_sell = True
            break
    assert got_sell


def test_atr_filter_suppresses_buy():
    """With atr_min_pct=99.0 and flat prices, ATR% is near zero — BUY is blocked."""
    strategy = EMAStrategy(make_cfg(fast=3, slow=5, atr_period=3, atr_min_pct=99.0))
    prices = [50.0] * 7 + [100.0, 50.0]
    results = [strategy.evaluate(make_tick(p, h)) for h, p in enumerate(prices)]
    assert Signal.BUY not in results


def test_strategy_name():
    assert EMAStrategy(make_cfg()).name == "ema"
