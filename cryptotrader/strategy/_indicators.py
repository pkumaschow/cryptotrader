from __future__ import annotations
from cryptotrader.models import Candle


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1.0 - k))
    return result


def atr(candles: list[Candle], period: int) -> float | None:
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


def bollinger_bands(values: list[float], period: int, std_dev: float) -> tuple[float, float, float] | None:
    if len(values) < period:
        return None
    window = values[-period:]
    mid = sum(window) / period
    variance = sum((v - mid) ** 2 for v in window) / period
    sigma = variance ** 0.5
    return mid + std_dev * sigma, mid, mid - std_dev * sigma
