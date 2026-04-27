import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import PriceTick, Signal
from cryptotrader.trader import Trader


def make_tick(pair: str = "BTC/USD", price: float = 50000.0) -> PriceTick:
    return PriceTick(pair=pair, bid=price, ask=price, last=price,
                     timestamp=datetime.now(UTC))


async def _run_one_tick(trader: Trader, tick: PriceTick) -> None:
    await trader._price_queue.put(tick)
    task = asyncio.create_task(trader.run())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_trader_test_mode_loads_all_strategies(test_config_path, tmp_path):
    db = str(tmp_path / "trader.db")
    database.init_db(db)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = Trader(price_queue=asyncio.Queue())

    assert "BTC/USD" in trader._strategies
    assert len(trader._strategies["BTC/USD"]) == 4  # all 4 strategies in test mode


@pytest.mark.asyncio
async def test_trader_production_mode_loads_single_strategy(test_config_path, tmp_path):
    db = str(tmp_path / "trader_prod.db")
    database.init_db(db)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.mode.active = "production"
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = Trader(price_queue=asyncio.Queue())

    assert "BTC/USD" in trader._strategies
    assert len(trader._strategies["BTC/USD"]) == 1


@pytest.mark.asyncio
async def test_trader_forwards_tick_to_tui_price_queue(test_config_path, tmp_path):
    db = str(tmp_path / "trader_tui.db")
    database.init_db(db)
    tui_price: asyncio.Queue = asyncio.Queue(maxsize=10)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = Trader(price_queue=asyncio.Queue(), tui_price_queue=tui_price)
        tick = make_tick()
        await _run_one_tick(trader, tick)

    assert not tui_price.empty()
    assert tui_price.get_nowait() is tick


@pytest.mark.asyncio
async def test_trader_drops_tick_silently_when_tui_queue_full(test_config_path, tmp_path):
    db = str(tmp_path / "trader_full.db")
    database.init_db(db)
    tui_price: asyncio.Queue = asyncio.Queue(maxsize=1)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = Trader(price_queue=asyncio.Queue(), tui_price_queue=tui_price)
        # Fill the TUI queue to capacity
        await tui_price.put(make_tick(price=1.0))
        # This tick should be dropped silently (QueueFull)
        await _run_one_tick(trader, make_tick(price=2.0))

    assert tui_price.qsize() == 1  # still just the original


@pytest.mark.asyncio
async def test_trader_ignores_unknown_pair(test_config_path, tmp_path):
    db = str(tmp_path / "trader_unk.db")
    database.init_db(db)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = Trader(price_queue=asyncio.Queue())

    # Should not raise
    await _run_one_tick(trader, make_tick(pair="XRP/USD"))


# ── circuit breaker tests ─────────────────────────────────────────────────────

def _make_trader_with_signal(feed_healthy_fn: Callable[[], bool] | None = None) -> Trader:
    """Return a Trader wired with a mock strategy that always emits BUY."""
    trader = Trader(price_queue=asyncio.Queue(), feed_healthy_fn=feed_healthy_fn)
    mock_strategy = MagicMock()
    mock_strategy.evaluate.return_value = Signal.BUY
    mock_strategy.name = "mock"
    trader._strategies = {"BTC/USD": [mock_strategy]}
    return trader


@pytest.mark.asyncio
async def test_trader_skips_execute_when_feed_unhealthy(test_config_path, tmp_path):
    """Circuit breaker: execute is NOT called when feed_healthy_fn returns False."""
    db = str(tmp_path / "cb_unhealthy.db")
    database.init_db(db)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = _make_trader_with_signal(feed_healthy_fn=lambda: False)
        trader._executor.execute = AsyncMock()
        await _run_one_tick(trader, make_tick())

    trader._executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_trader_calls_execute_when_feed_healthy(test_config_path, tmp_path):
    """Circuit breaker: execute IS called when feed_healthy_fn returns True."""
    db = str(tmp_path / "cb_healthy.db")
    database.init_db(db)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = _make_trader_with_signal(feed_healthy_fn=lambda: True)
        trader._executor.execute = AsyncMock(return_value=None)
        await _run_one_tick(trader, make_tick())

    trader._executor.execute.assert_called_once()


@pytest.mark.asyncio
async def test_trader_calls_execute_when_no_feed_fn(test_config_path, tmp_path):
    """Backward compat: no feed_healthy_fn means execute is always called."""
    db = str(tmp_path / "cb_none.db")
    database.init_db(db)
    with patch("cryptotrader.trader.get_settings") as ms, \
         patch("cryptotrader.executor.get_settings") as me:
        s = get_settings(test_config_path)
        s.database.path = db
        ms.return_value = s
        me.return_value = s
        trader = _make_trader_with_signal(feed_healthy_fn=None)
        trader._executor.execute = AsyncMock(return_value=None)
        await _run_one_tick(trader, make_tick())

    trader._executor.execute.assert_called_once()
