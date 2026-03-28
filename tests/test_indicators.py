from datetime import datetime, timezone

import pytest

from cryptotrader.models import Candle
from cryptotrader.strategy._indicators import atr, bollinger_bands, ema


def make_candle(close: float, high: float = None, low: float = None) -> Candle:
    h = high if high is not None else close
    lo = low if low is not None else close
    return Candle(
        pair="BTC/USD", timeframe=60,
        open=close, high=h, low=lo, close=close,
        tick_count=1, timestamp=datetime.now(timezone.utc),
    )


# --- ema ---

def test_ema_too_few_values_returns_empty():
    assert ema([1.0, 2.0], period=5) == []


def test_ema_exact_period():
    result = ema([50.0, 50.0, 50.0], period=3)
    assert result == [50.0]


def test_ema_smoothing():
    # k = 2/(3+1) = 0.5; seed = mean(50,50,50) = 50; next = 100*0.5 + 50*0.5 = 75
    result = ema([50.0, 50.0, 50.0, 100.0], period=3)
    assert len(result) == 2
    assert result[0] == pytest.approx(50.0)
    assert result[1] == pytest.approx(75.0)


def test_ema_fast_higher_than_slow_after_spike():
    values = [50.0] * 6 + [100.0]
    fast = ema(values, period=3)
    slow = ema(values, period=5)
    assert fast[-1] > slow[-1]


# --- atr ---

def test_atr_too_few_candles_returns_none():
    candles = [make_candle(50.0)] * 3  # period=3 requires period+1=4
    assert atr(candles, period=3) is None


def test_atr_flat_prices_zero():
    candles = [make_candle(50.0)] * 10
    assert atr(candles, period=5) == pytest.approx(0.0)


def test_atr_with_range():
    # high=60, low=40, close=50 → TR = max(20, |60-50|, |40-50|) = 20
    candles = [
        Candle("BTC/USD", 60, 50.0, 60.0, 40.0, 50.0, 1, datetime.now(timezone.utc))
    ] * 10
    assert atr(candles, period=5) == pytest.approx(20.0)


# --- bollinger_bands ---

def test_bollinger_too_few_values_returns_none():
    assert bollinger_bands([1.0, 2.0], period=5, std_dev=2.0) is None


def test_bollinger_flat_prices_no_spread():
    upper, mid, lower = bollinger_bands([50.0] * 5, period=5, std_dev=2.0)
    assert upper == pytest.approx(50.0)
    assert mid == pytest.approx(50.0)
    assert lower == pytest.approx(50.0)


def test_bollinger_upper_mid_lower_ordering():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    upper, mid, lower = bollinger_bands(values, period=5, std_dev=2.0)
    assert mid == pytest.approx(30.0)
    assert upper > mid
    assert lower < mid


def test_bollinger_uses_last_period_values():
    # Adding old values should not change result if window is the same
    values_a = [50.0] * 3
    values_b = [999.0] * 100 + [50.0] * 3
    assert bollinger_bands(values_a, period=3, std_dev=2.0) == bollinger_bands(values_b, period=3, std_dev=2.0)
