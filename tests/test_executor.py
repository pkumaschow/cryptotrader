import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.executor import TradeExecutor
from cryptotrader.models import Side, Signal, Trade


@pytest.mark.asyncio
async def test_test_mode_records_trade(test_config_path, tmp_path):
    # Override db path to tmp
    with patch("cryptotrader.executor.get_settings") as mock_settings:
        settings = get_settings(test_config_path)
        # Point database to tmp
        settings.database.path = str(tmp_path / "exec_test.db")
        database.init_db(settings.database.path)
        mock_settings.return_value = settings

        executor = TradeExecutor()
        trade = await executor.execute(Signal.BUY, "XBTUSD", 49999.0)

    assert trade is not None
    assert trade.side == Side.BUY
    assert trade.mode == "test"
    assert trade.pair == "XBTUSD"
    assert trade.id is not None

    trades = database.query_trades(settings.database.path, mode="test")
    assert len(trades) == 1
    assert trades[0].side == Side.BUY


@pytest.mark.asyncio
async def test_production_mode_never_fires_in_test(test_config_path, tmp_path):
    """Verifies production REST is NOT called when mode is test."""
    with patch("cryptotrader.executor.get_settings") as mock_settings:
        settings = get_settings(test_config_path)
        settings.database.path = str(tmp_path / "exec_prod_guard.db")
        database.init_db(settings.database.path)
        mock_settings.return_value = settings

        mock_rest = AsyncMock()
        executor = TradeExecutor()
        executor.set_rest_client(mock_rest)

        await executor.execute(Signal.SELL, "XBTUSD", 61000.0)

    mock_rest.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_tui_queue_receives_trade(test_config_path, tmp_path):
    tui_queue: asyncio.Queue = asyncio.Queue()
    with patch("cryptotrader.executor.get_settings") as mock_settings:
        settings = get_settings(test_config_path)
        settings.database.path = str(tmp_path / "exec_tui.db")
        database.init_db(settings.database.path)
        mock_settings.return_value = settings

        executor = TradeExecutor(tui_queue=tui_queue)
        await executor.execute(Signal.BUY, "ETHUSD", 1999.0)

    assert not tui_queue.empty()
    trade = tui_queue.get_nowait()
    assert isinstance(trade, Trade)
    assert trade.pair == "ETHUSD"
