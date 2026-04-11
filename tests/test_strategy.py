from datetime import UTC, datetime

import pytest

from cryptotrader.config import CurrencyConfig, ThresholdParams
from cryptotrader.db import database
from cryptotrader.models import PriceTick, Side, Signal, Trade
from cryptotrader.strategy.registry import get
from cryptotrader.strategy.threshold import ThresholdStrategy


def make_tick(pair: str, bid: float, ask: float, last: float) -> PriceTick:
    return PriceTick(pair=pair, bid=bid, ask=ask, last=last, timestamp=datetime.now(UTC))


def make_cfg(buy: float, sell: float) -> CurrencyConfig:
    return CurrencyConfig(
        strategy="threshold",
        threshold=ThresholdParams(buy_trigger=buy, sell_trigger=sell),
        quantity=0.001,
    )


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


def test_restore_sets_in_position_after_buy(tmp_path):
    """Restart with an open position must not trigger a duplicate BUY."""
    db_path = str(tmp_path / "restore_test.db")
    database.init_db(db_path)
    database.insert_trade(db_path, Trade(
        pair="BTC/USD", side=Side.BUY, price=49000.0, quantity=0.001,
        mode="production", strategy="threshold", timestamp=datetime.now(UTC),
    ))

    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    strategy.restore(db_path, "BTC/USD")

    # Position restored — tick below buy trigger must NOT fire another BUY
    tick = make_tick("BTC/USD", bid=48900, ask=49000, last=48950)
    assert strategy.evaluate(tick) is None


def test_restore_clears_position_after_sell(tmp_path):
    """Restart after a completed sell must allow a fresh BUY."""
    db_path = str(tmp_path / "restore_sell_test.db")
    database.init_db(db_path)
    database.insert_trade(db_path, Trade(
        pair="BTC/USD", side=Side.BUY, price=49000.0, quantity=0.001,
        mode="production", strategy="threshold", timestamp=datetime.now(UTC),
    ))
    database.insert_trade(db_path, Trade(
        pair="BTC/USD", side=Side.SELL, price=61000.0, quantity=0.001,
        mode="production", strategy="threshold", timestamp=datetime.now(UTC),
    ))

    strategy = ThresholdStrategy(make_cfg(buy=50000, sell=60000))
    strategy.restore(db_path, "BTC/USD")

    # Last trade was SELL — position not held, BUY should fire
    tick = make_tick("BTC/USD", bid=48900, ask=49000, last=48950)
    assert strategy.evaluate(tick) == Signal.BUY


def test_registry_returns_threshold():
    cls = get("threshold")
    assert cls is ThresholdStrategy


def test_registry_raises_on_unknown():
    with pytest.raises(KeyError):
        get("nonexistent")
