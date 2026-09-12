from datetime import UTC, datetime

from cryptotrader.config import BollingerParams, CurrencyConfig
from cryptotrader.models import Candle, PriceTick, Signal
from cryptotrader.strategy.bollinger import BollingerStrategy


def make_tick(price: float, hour: int, minute: int = 0) -> PriceTick:
    ts = datetime(2024, 1, 1, hour, minute, 0, tzinfo=UTC)
    return PriceTick(pair="BTC/USD", bid=price, ask=price, last=price, timestamp=ts)


def make_cfg(
    period: int = 3,
    std_dev: float = 2.0,
    min_band_width_pct: float = 0.0,
    trend_filter_enabled: bool = False,
    trend_ema_period: int = 3,
    trend_timeframe_minutes: int = 240,
    fee_pct: float = 0.0,
    stop_loss_pct: float = 0.0,
) -> CurrencyConfig:
    params = BollingerParams(
        period=period,
        std_dev=std_dev,
        min_band_width_pct=min_band_width_pct,
        trend_filter_enabled=trend_filter_enabled,
        trend_ema_period=trend_ema_period,
        trend_timeframe_minutes=trend_timeframe_minutes,
        fee_pct=fee_pct,
        stop_loss_pct=stop_loss_pct,
    )
    return CurrencyConfig(quantity=0.001, max_order_usd=500.0, bollinger=params)


def trend_candles(closes: list[float]) -> list[Candle]:
    """Build a chronological list of 4h trend candles with the given closes."""
    return [
        Candle(
            pair="BTC/USD", timeframe=240, open=c, high=c, low=c, close=c,
            tick_count=1, timestamp=datetime(2023, 12, 31, (i * 4) % 24, 0, tzinfo=UTC),
        )
        for i, c in enumerate(closes)
    ]


def drive_breakout(strategy: BollingerStrategy) -> Signal | None:
    """Warm up flat, then spike inside the h5 candle to break the upper band at h6."""
    for h in range(5):
        strategy.evaluate(make_tick(50.0, h))
    strategy.evaluate(make_tick(50.0, 5))
    strategy.evaluate(make_tick(500.0, 5, minute=30))
    return strategy.evaluate(make_tick(50.0, 6))


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


def test_min_band_width_suppresses_buy():
    """BUY suppressed when min_band_width_pct exceeds the actual band width at signal time."""
    strategy = BollingerStrategy(make_cfg(period=3, std_dev=0.1, min_band_width_pct=999.0))
    for h in range(5):
        strategy.evaluate(make_tick(50.0, h))
    strategy.evaluate(make_tick(50.0, 5))
    strategy.evaluate(make_tick(500.0, 5, minute=30))
    result = strategy.evaluate(make_tick(50.0, 6))
    assert result is None


def test_min_band_width_allows_buy_when_met():
    """BUY fires when band width % meets or exceeds the minimum."""
    # min_band_width_pct=0.0 — no minimum — same condition as existing buy test
    strategy = BollingerStrategy(make_cfg(period=3, std_dev=0.1, min_band_width_pct=0.0))
    for h in range(5):
        strategy.evaluate(make_tick(50.0, h))
    strategy.evaluate(make_tick(50.0, 5))
    strategy.evaluate(make_tick(500.0, 5, minute=30))
    result = strategy.evaluate(make_tick(50.0, 6))
    assert result == Signal.BUY


def test_trend_filter_allows_buy_in_uptrend():
    """With the filter on and a rising 4h trend EMA, a breakout still BUYs."""
    strategy = BollingerStrategy(
        make_cfg(period=3, std_dev=0.1, trend_filter_enabled=True, trend_ema_period=3)
    )
    strategy._trend_candles.load(trend_candles([10.0, 20.0, 30.0, 40.0]))
    assert drive_breakout(strategy) == Signal.BUY


def test_trend_filter_blocks_buy_in_downtrend():
    """With the filter on and a falling 4h trend EMA, the same breakout is suppressed."""
    strategy = BollingerStrategy(
        make_cfg(period=3, std_dev=0.1, trend_filter_enabled=True, trend_ema_period=3)
    )
    strategy._trend_candles.load(trend_candles([400.0, 300.0, 200.0, 100.0]))
    assert drive_breakout(strategy) is None


def test_trend_filter_blocks_buy_during_warmup():
    """With the filter on but too few 4h candles for the trend EMA, no BUY fires."""
    strategy = BollingerStrategy(
        make_cfg(period=3, std_dev=0.1, trend_filter_enabled=True, trend_ema_period=3)
    )
    assert drive_breakout(strategy) is None


def test_trend_filter_off_by_default():
    """Default config does not build a trend candle builder; behavior is unchanged."""
    strategy = BollingerStrategy(make_cfg(period=3, std_dev=0.1))
    assert strategy._trend_candles is None
    assert drive_breakout(strategy) == Signal.BUY


def test_stop_loss_exits_underwater_position_despite_profit_gate():
    """Stop-loss cuts a losing position even when the small-profit gate would block the sell."""
    strategy = BollingerStrategy(
        make_cfg(period=3, std_dev=2.0, fee_pct=0.60, stop_loss_pct=10.0)
    )
    strategy._in_position = True
    strategy._entry_price = 100.0  # 10% stop -> exit at close <= 90
    for h in range(5):
        strategy.evaluate(make_tick(100.0, h))
    strategy.evaluate(make_tick(100.0, 5))
    strategy.evaluate(make_tick(80.0, 5, minute=30))  # h5 closes at 80 (-20%)
    assert strategy.evaluate(make_tick(100.0, 6)) == Signal.SELL


def test_disabled_stop_loss_holds_underwater_position():
    """With stop-loss off (0.0) and a fee, the profit-gate blocks the loss -> position is held."""
    strategy = BollingerStrategy(
        make_cfg(period=3, std_dev=2.0, fee_pct=0.60, stop_loss_pct=0.0)
    )
    strategy._in_position = True
    strategy._entry_price = 100.0
    for h in range(5):
        strategy.evaluate(make_tick(100.0, h))
    strategy.evaluate(make_tick(100.0, 5))
    strategy.evaluate(make_tick(80.0, 5, minute=30))
    assert strategy.evaluate(make_tick(100.0, 6)) is None


def test_stop_loss_holds_above_threshold():
    """A drawdown shallower than the stop % does not trigger an exit."""
    strategy = BollingerStrategy(
        make_cfg(period=3, std_dev=2.0, fee_pct=0.60, stop_loss_pct=10.0)
    )
    strategy._in_position = True
    strategy._entry_price = 100.0  # stop at 90
    for h in range(5):
        strategy.evaluate(make_tick(100.0, h))
    strategy.evaluate(make_tick(100.0, 5))
    strategy.evaluate(make_tick(95.0, 5, minute=30))  # -5%, above the 90 stop
    assert strategy.evaluate(make_tick(100.0, 6)) is None


def test_strategy_name():
    assert BollingerStrategy(make_cfg()).name == "bollinger"


# --- exit fee gate (#25) -------------------------------------------------

import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402


def exit_at(close: float, fee_pct: float = 0.80, quantity: float = 0.001) -> Signal | None:
    """Hold from entry 100, then complete a candle closing at `close`, below the mid band."""
    cfg = make_cfg(period=3, std_dev=2.0, fee_pct=fee_pct).model_copy(
        update={"quantity": quantity})
    strategy = BollingerStrategy(cfg)
    strategy._in_position = True
    strategy._entry_price = 100.0
    for h in range(5):
        strategy.evaluate(make_tick(110.0, h))
    strategy.evaluate(make_tick(110.0, 5))
    strategy.evaluate(make_tick(close, 5, minute=30))
    return strategy.evaluate(make_tick(110.0, 6))


def test_gate_releases_an_exit_that_clears_both_percentage_legs():
    """Entry 100, close 101.70: a 1.70 move against 1.61 of fees (0.80% of 201.70)."""
    assert exit_at(101.70) == Signal.SELL


def test_gate_holds_an_exit_that_does_not_clear_both_legs():
    """Close 101.50: a 1.50 move against 1.61 of fees — selling would lose money."""
    assert exit_at(101.50) is None


@pytest.mark.parametrize("quantity", [0.0001, 0.001, 0.5, 10.0])
def test_gate_decision_does_not_depend_on_position_size(quantity):
    """The old gate used the config lot, overstating BTC holdings by 61% (#25).

    A percentage fee scales with the position, so size cancels out and must not
    move the decision either way.
    """
    assert exit_at(101.70, quantity=quantity) == Signal.SELL
    assert exit_at(101.50, quantity=quantity) is None


def test_zero_fee_disables_the_gate():
    assert exit_at(100.10, fee_pct=0.0) == Signal.SELL


def test_the_retired_flat_fee_key_is_refused_not_ignored():
    """Ignoring it would load fee_pct at 0 — the gate silently off."""
    with pytest.raises(ValidationError, match="fee_pct"):
        BollingerParams(fee_per_trade_usd=0.60)


def test_shipped_production_config_keeps_the_gate_on():
    """The key migration must not switch the gate off for any live pair."""
    path = Path(__file__).resolve().parent.parent / "config" / "settings.toml"
    raw = tomllib.loads(path.read_text())
    bollinger_pairs = {
        pair: CurrencyConfig(**cfg) for pair, cfg in raw["currencies"].items()
        if cfg.get("strategy") == "bollinger"
    }
    assert bollinger_pairs, "precondition: production trades bollinger"
    for pair, cfg in bollinger_pairs.items():
        assert cfg.bollinger.fee_pct == pytest.approx(0.80), pair
