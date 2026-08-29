"""Pure indicator maths: EMA, ATR and Bollinger bands.

No state and no I/O, so these are cheap to test and safe to reuse — the
backtest harness calls exactly the same functions the live strategies do, which
is what lets a replay reproduce real decisions.
"""

from __future__ import annotations

from cryptotrader.models import Candle


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average.

    Seeded with a simple average of the first `period` values, so the result
    is shorter than the input by `period - 1`.

    Returns:
    Successive EMA values, or an empty list when history is too short.
    Callers must handle the empty case rather than indexing blindly.
    """
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def atr(candles: list[Candle], period: int) -> float | None:
    """Average true range over the last `period` candles.

    Returns:
    The ATR, or None when history is too short. Used as a volatility
    floor — a crossover in a flat market means little.
    """
    if len(candles) < period + 1:
        return None
    trs: list[float] = []
    for i in range(max(1, len(candles) - period - 1), len(candles)):
        prev_close = candles[i - 1].close
        c = candles[i]
        tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
        trs.append(tr)
    recent = trs[-period:]
    return sum(recent) / len(recent)


def bollinger_bands(
    values: list[float], period: int, std_dev: float
) -> tuple[float, float, float] | None:
    """Upper, middle and lower band over the most recent `period` values.

    Uses the population standard deviation, matching the conventional
    definition of the indicator.

    Returns:
    `(upper, middle, lower)`, or None when history is too short.
    """
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    variance = sum((v - mid) ** 2 for v in window) / period
    sigma = variance ** 0.5
    return mid + std_dev * sigma, mid, mid - std_dev * sigma
