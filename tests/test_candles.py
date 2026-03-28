from datetime import datetime, timezone

from cryptotrader.candles import CandleBuilder
from cryptotrader.models import PriceTick


def make_tick(price: float, hour: int, minute: int = 0) -> PriceTick:
    ts = datetime(2024, 1, 1, hour, minute, 0, tzinfo=timezone.utc)
    return PriceTick(pair="BTC/USD", bid=price, ask=price, last=price, timestamp=ts)


def test_first_tick_returns_none():
    b = CandleBuilder(timeframe_minutes=60)
    assert b.add_tick(make_tick(50000.0, 0)) is None
    assert b.count == 0


def test_second_tick_same_boundary_returns_none():
    b = CandleBuilder(timeframe_minutes=60)
    b.add_tick(make_tick(50000.0, 0))
    assert b.add_tick(make_tick(51000.0, 0, minute=30)) is None
    assert b.count == 0


def test_new_boundary_returns_completed_candle():
    b = CandleBuilder(timeframe_minutes=60)
    b.add_tick(make_tick(50000.0, 0))
    b.add_tick(make_tick(51000.0, 0, minute=30))
    completed = b.add_tick(make_tick(52000.0, 1))
    assert completed is not None
    assert completed.open == 50000.0
    assert completed.high == 51000.0
    assert completed.low == 50000.0
    assert completed.close == 51000.0
    assert b.count == 1


def test_high_low_close_tracked_across_ticks():
    b = CandleBuilder(timeframe_minutes=60)
    b.add_tick(make_tick(50000.0, 0))
    b.add_tick(make_tick(55000.0, 0, minute=10))
    b.add_tick(make_tick(48000.0, 0, minute=50))
    completed = b.add_tick(make_tick(52000.0, 1))
    assert completed.high == 55000.0
    assert completed.low == 48000.0
    assert completed.close == 48000.0
    assert completed.tick_count == 3


def test_multiple_candles_accumulate():
    b = CandleBuilder(timeframe_minutes=60)
    for h in range(5):
        b.add_tick(make_tick(float(50000 + h * 1000), h))
    assert b.count == 4
    assert len(b.candles) == 4


def test_candles_property_reflects_completed():
    b = CandleBuilder(timeframe_minutes=60)
    b.add_tick(make_tick(50000.0, 0))
    b.add_tick(make_tick(51000.0, 1))
    candles = b.candles
    assert len(candles) == 1
    assert candles[0].close == 50000.0


def test_4h_candle_boundary_groups_hours():
    b = CandleBuilder(timeframe_minutes=240)
    b.add_tick(make_tick(50000.0, 0))
    assert b.add_tick(make_tick(51000.0, 1)) is None
    assert b.add_tick(make_tick(52000.0, 2)) is None
    assert b.add_tick(make_tick(53000.0, 3)) is None
    completed = b.add_tick(make_tick(54000.0, 4))
    assert completed is not None
    assert completed.close == 53000.0
    assert completed.tick_count == 4
    assert b.count == 1
