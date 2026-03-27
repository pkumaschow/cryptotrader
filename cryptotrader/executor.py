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
        self._rest_client: Optional[object] = None

    def set_rest_client(self, client: object) -> None:
        self._rest_client = client

    async def execute(self, signal: Signal, pair: str, price: float,
                      strategy: str = "unknown") -> Optional[Trade]:
        settings = get_settings()
        mode = settings.mode.active
        currency_cfg = settings.currencies[pair]
        side = Side.BUY if signal == Signal.BUY else Side.SELL
        trade = Trade(pair=pair, side=side, price=price,
                      quantity=currency_cfg.quantity, mode=mode, strategy=strategy,
                      timestamp=datetime.now(timezone.utc))
        if mode == "test":
            trade.id = database.insert_trade(settings.database.path, trade)
            logger.info("[TEST] %s %s %.8f @ %.2f  [%s]",
                        side.value.upper(), pair, trade.quantity, price, strategy)
        elif mode == "production":
            if self._rest_client is None:
                from cryptotrader.exchange.kraken_rest import KrakenRest
                self._rest_client = KrakenRest(
                    get_secrets().kraken_api_key, get_secrets().kraken_api_secret)
            txid = await self._rest_client.place_order(pair, side.value, trade.quantity)  # type: ignore
            trade.txid = txid
            trade.id = database.insert_trade(settings.database.path, trade)
            logger.info("[PROD] %s %s %.8f @ %.2f  [%s]  txid=%s",
                        side.value.upper(), pair, trade.quantity, price, strategy, txid)
        else:
            raise RuntimeError(f"Unknown mode: {mode!r}")
        if self._tui_queue is not None:
            try:
                self._tui_queue.put_nowait(trade)
            except asyncio.QueueFull:
                pass
        return trade
