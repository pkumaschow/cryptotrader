"""A refused order must not leave the strategy describing a position it lacks.

The 2026-08-20 sequence in one sentence: a BTC buy was declined for insufficient
balance, the strategy kept `_in_position = True`, and two days later it sold
0.001 BTC that had never been bought. These tests pin both directions of the
rollback, and the end-to-end path through the trader loop.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from cryptotrader.models import PriceTick, Signal
from cryptotrader.strategy.base import Strategy
from cryptotrader.strategy.registry import ALL_STRATEGIES
from cryptotrader.trader import Trader


class _StubStrategy(Strategy):
    """Emits a scripted signal, mutating state exactly as a real strategy does."""

    POSITION_ATTRS = ("_in_position", "_entry_price")

    def __init__(self, signal: Signal, in_position: bool,
                 entry_price: float | None) -> None:
        self._signal: Signal | None = signal
        self._in_position = in_position
        self._entry_price = entry_price

    @property
    def name(self) -> str:
        return "stub"

    def evaluate(self, tick: PriceTick) -> Signal | None:
        sig, self._signal = self._signal, None
        if sig is None:
            return None
        self._arm_rollback()
        if sig is Signal.BUY:
            self._in_position = True
            self._entry_price = tick.last
        else:
            self._in_position = False
            self._entry_price = None
        return sig


def _tick(pair: str = "BTC/USD", last: float = 68_539.70) -> PriceTick:
    return PriceTick(pair=pair, bid=last, ask=last, last=last,
                     timestamp=datetime(2026, 8, 19, 16, 0, tzinfo=UTC))


class _Executor:
    """Stands in for TradeExecutor. `result` None = refused."""

    def __init__(self, result: object, raises: bool = False) -> None:
        self._result, self._raises = result, raises
        self.calls = 0

    async def execute(self, signal, pair, price, strategy, band_width=None,
                      on_reject=None):
        self.calls += 1
        if self._raises:
            raise RuntimeError("exceeds max_order_usd")
        return self._result


def _drive(strategy: Strategy, executor: _Executor, feed_healthy: bool = True) -> None:
    """Run exactly one tick through the real Trader loop."""
    queue: asyncio.Queue = asyncio.Queue()

    async def go() -> None:
        trader = Trader.__new__(Trader)
        trader._price_queue = queue
        trader._tui_price_queue = None
        trader._feed_healthy_fn = (lambda: feed_healthy)
        trader._executor = executor
        trader._maker_book = None      # market-order path: no resting entries
        trader._strategies = {"BTC/USD": [strategy]}
        await queue.put(_tick())
        task = asyncio.create_task(trader.run())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError):
            pass

    asyncio.run(go())


def test_declined_buy_restores_flat_state():
    """The exact 2026-08-20 failure."""
    s = _StubStrategy(Signal.BUY, in_position=False, entry_price=None)
    _drive(s, _Executor(result=None))

    assert s._in_position is False, "declined buy must not leave the strategy long"
    assert s._entry_price is None


def test_declined_sell_restores_the_position_and_entry_price():
    """A refused SELL must put back the entry price too.

    Restoring only the flag would leave `_entry_price = None`, and the
    stop-loss would have no reference — the position could never be cut.
    """
    s = _StubStrategy(Signal.SELL, in_position=True, entry_price=82_171.90)
    _drive(s, _Executor(result=None))

    assert s._in_position is True
    assert s._entry_price == 82_171.90, "stop-loss reference must survive a refusal"


def test_filled_order_keeps_the_new_state():
    s = _StubStrategy(Signal.BUY, in_position=False, entry_price=None)
    _drive(s, _Executor(result=object()))

    assert s._in_position is True
    assert s._entry_price == pytest.approx(68_539.70)


def test_unhealthy_feed_rolls_back_without_ordering():
    """The order is skipped, so the position it assumed must be undone."""
    s = _StubStrategy(Signal.BUY, in_position=False, entry_price=None)
    ex = _Executor(result=object())
    _drive(s, ex, feed_healthy=False)

    assert ex.calls == 0, "no order should be attempted on an unhealthy feed"
    assert s._in_position is False
    assert s._entry_price is None


def test_executor_exception_rolls_back_before_propagating():
    s = _StubStrategy(Signal.BUY, in_position=False, entry_price=None)
    _drive(s, _Executor(result=None, raises=True))

    assert s._in_position is False, "a raised cap breach must not leave a phantom long"
    assert s._entry_price is None


def test_rollback_is_single_use():
    """A second rejection with nothing armed must not resurrect stale state."""
    s = _StubStrategy(Signal.BUY, in_position=False, entry_price=None)
    _drive(s, _Executor(result=object()))
    assert s._in_position is True

    s.on_order_rejected()  # nothing armed — the fill consumed the snapshot
    assert s._in_position is True, "a consumed snapshot must not be replayed"


@pytest.mark.parametrize("cls", ALL_STRATEGIES)
def test_every_strategy_arms_a_rollback(cls):
    """Guards against a new strategy silently missing the mechanism."""
    import inspect

    src = inspect.getsource(cls)
    emits = src.count("return Signal.")
    arms = src.count("_arm_rollback()")
    assert arms == emits, (
        f"{cls.__name__}: {emits} signal emission(s) but {arms} armed rollback(s)"
    )
    assert "_in_position" in cls.POSITION_ATTRS


# --- end-to-end: the real strategy, the real executor, the real incident ------

def _breakout_ticks(pair: str = "BTC/USD") -> list[PriceTick]:
    """A flat run then a spike — enough to make BollingerStrategy emit a BUY.

    One tick per hourly boundary, so each tick completes the previous candle,
    which is how the live bot reaches a decision.
    """
    from datetime import timedelta
    base = datetime(2026, 8, 18, 0, 0, tzinfo=UTC)
    prices = [68_000.0 + (i % 2) * 20 for i in range(24)] + [72_000.0, 72_100.0]
    return [
        PriceTick(pair=pair, bid=p, ask=p, last=p, timestamp=base + timedelta(hours=i))
        for i, p in enumerate(prices)
    ]


def _bollinger_config():
    from cryptotrader.config import BollingerParams, CurrencyConfig
    return CurrencyConfig(
        strategy="bollinger", quantity=0.001, budget_usd=50.0, max_order_usd=500.0,
        bollinger=BollingerParams(min_band_width_pct=0.0, trend_filter_enabled=False,
                                  stop_loss_pct=0.0, fee_per_trade_usd=0.0),
    )


def test_real_bollinger_goes_flat_when_the_real_executor_declines(tmp_path, monkeypatch):
    """Replays 2026-08-20 with production classes, no stubs.

    A breakout fires a BUY; the executor declines it for insufficient balance.
    The strategy must end up flat — because if it does not, the next mid-band
    cross sells coin that was never bought.
    """
    from cryptotrader.config import get_settings
    from cryptotrader.db import database
    from cryptotrader.executor import TradeExecutor
    from cryptotrader.strategy.bollinger import BollingerStrategy

    db = tmp_path / "e2e.db"
    database.init_db(str(db))
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings.mode, "active", "production")
    monkeypatch.setattr(settings.database, "path", str(db))
    monkeypatch.setitem(settings.currencies, "BTC/USD", _bollinger_config())

    class _BrokeKraken:
        async def get_balance(self):
            return {"ZUSD": 12.00}          # too little to fund the order

        async def place_order(self, *a):    # pragma: no cover — must never run
            raise AssertionError("no order should reach the exchange")

    strategy = BollingerStrategy(_bollinger_config())
    executor = TradeExecutor()
    executor.set_rest_client(_BrokeKraken())

    async def go():
        signal = None
        for tick in _breakout_ticks():
            signal = strategy.evaluate(tick)
            if signal is not None:
                trade = await executor.execute(signal, tick.pair, tick.last, strategy.name)
                if trade is None:
                    strategy.on_order_rejected()
                else:
                    strategy.on_order_filled()
                return signal, trade
        return signal, None

    signal, trade = asyncio.run(go())

    assert signal is Signal.BUY, "the fixture must actually produce a breakout"
    assert trade is None, "the executor must decline against an underfunded balance"
    assert strategy._in_position is False, "declined buy left a phantom long position"
    assert strategy._entry_price is None

    rejected = database.query_rejected_orders(str(db))
    assert len(rejected) == 1 and rejected[0].side.value == "buy"
    get_settings.cache_clear()
