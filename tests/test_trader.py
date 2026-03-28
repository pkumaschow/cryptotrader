import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import PriceTick
from cryptotrader.trader import Trader


def make_tick(pair: str = "BTC/USD", price: float = 50000.0) -> PriceTick:
    return PriceTick(pair=pair, bid=price, ask=price, last=price,
                     timestamp=datetime.now(timezone.utc))


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
