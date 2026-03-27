"""
Trade executor — the single place where mode is checked.
test mode  → record to SQLite only, never calls Kraken trade API
production → calls Kraken REST to place a real order, then records to SQLite
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from cryptotrader.config import get_secrets, get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, Signal, Trade

logger = logging.getLogger(__name__)


class TradeExecutor:
    def __init__(self, tui_queue: Optional[asyncio.Queue] = None) -> None:
        self._tui_queue = tui_queue
        # Import here to avoid circular at module load; injected for tests
        self._rest_client: Optional[object] = None

    def set_rest_client(self, client: object) -> None:
        self._rest_client = client

    async def execute(self, signal: Signal, pair: str, price: float) -> Optional[Trade]:
        settings = get_settings()
        mode = settings.mode.active
        currency_cfg = settings.currencies[pair]

        side = Side.BUY if signal == Signal.BUY else Side.SELL
        trade = Trade(
            pair=pair,
            side=side,
            price=price,
            quantity=currency_cfg.quantity,
            mode=mode,
            timestamp=datetime.now(timezone.utc),
        )

        if mode == "test":
            trade_id = database.insert_trade(settings.database.path, trade)
            trade.id = trade_id
            logger.info("[TEST] %s %s %.8f @ %.2f", side.value.upper(), pair, trade.quantity, price)

        elif mode == "production":
            if self._rest_client is None:
                from cryptotrader.exchange.kraken_rest import KrakenRest
                self._rest_client = KrakenRest(get_secrets().kraken_api_key, get_secrets().kraken_api_secret)
            txid = await self._rest_client.place_order(pair, side.value, trade.quantity)  # type: ignore[union-attr]
            trade.txid = txid
            trade_id = database.insert_trade(settings.database.path, trade)
            trade.id = trade_id
            logger.info("[PROD] %s %s %.8f @ %.2f txid=%s", side.value.upper(), pair, trade.quantity, price, txid)

        else:
            raise RuntimeError(f"Unknown mode: {mode!r}")  # config validator should catch this first

        if self._tui_queue is not None:
            await self._tui_queue.put(trade)

        return trade
