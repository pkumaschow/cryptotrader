import asyncio
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
        trade = await executor.execute(Signal.BUY, "BTC/USD", 49999.0)

    assert trade is not None
    assert trade.side == Side.BUY
    assert trade.mode == "test"
    assert trade.pair == "BTC/USD"
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

        await executor.execute(Signal.SELL, "BTC/USD", 61000.0)

    mock_rest.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_max_order_usd_blocks_oversized_buy(test_config_path, tmp_path):
    """Order exceeding max_order_usd must raise before hitting the REST API."""
    with patch("cryptotrader.executor.get_settings") as mock_settings:
        settings = get_settings(test_config_path)
        settings.mode.active = "production"
        settings.database.path = str(tmp_path / "exec_max_order.db")
        settings.currencies["BTC/USD"].max_order_usd = 100.0
        database.init_db(settings.database.path)
        mock_settings.return_value = settings

        mock_rest = AsyncMock()
        mock_rest.get_balance.return_value = {"ZUSD": 10000.0}
        executor = TradeExecutor()
        executor.set_rest_client(mock_rest)

        # quantity=0.001 @ $200,000 = $200 — exceeds max_order_usd=100
        with pytest.raises(RuntimeError, match="max_order_usd"):
            await executor.execute(Signal.BUY, "BTC/USD", 200000.0)

    mock_rest.place_order.assert_not_called()


@pytest.mark.asyncio
async def test_max_order_usd_allows_order_within_limit(test_config_path, tmp_path):
    """Order within max_order_usd must proceed normally."""
    with patch("cryptotrader.executor.get_settings") as mock_settings:
        settings = get_settings(test_config_path)
        settings.mode.active = "production"
        settings.database.path = str(tmp_path / "exec_max_order_ok.db")
        settings.currencies["BTC/USD"].max_order_usd = 500.0
        database.init_db(settings.database.path)
        mock_settings.return_value = settings

        mock_rest = AsyncMock()
        mock_rest.get_balance.return_value = {"ZUSD": 10000.0}
        mock_rest.place_order.return_value = "TXID-123"
        executor = TradeExecutor()
        executor.set_rest_client(mock_rest)

        # quantity=0.001 @ $50,000 = $50 — within max_order_usd=500
        trade = await executor.execute(Signal.BUY, "BTC/USD", 50000.0)

    assert trade is not None
    mock_rest.place_order.assert_called_once()


@pytest.mark.asyncio
async def test_tui_queue_receives_trade(test_config_path, tmp_path):
    tui_queue: asyncio.Queue = asyncio.Queue()
    with patch("cryptotrader.executor.get_settings") as mock_settings:
        settings = get_settings(test_config_path)
        settings.database.path = str(tmp_path / "exec_tui.db")
        database.init_db(settings.database.path)
        mock_settings.return_value = settings

        executor = TradeExecutor(tui_queue=tui_queue)
        await executor.execute(Signal.BUY, "ETH/USD", 1999.0)

    assert not tui_queue.empty()
    trade = tui_queue.get_nowait()
    assert isinstance(trade, Trade)
    assert trade.pair == "ETH/USD"
