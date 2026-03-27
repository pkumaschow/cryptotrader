"""
Trader — the central orchestrator.
Consumes PriceTick objects from the WebSocket queue, routes each tick to the
correct Strategy instance, and dispatches Signals to the TradeExecutor.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from cryptotrader.config import get_settings
from cryptotrader.executor import TradeExecutor
from cryptotrader.models import PriceTick
from cryptotrader.strategy import registry

logger = logging.getLogger(__name__)


class Trader:
    def __init__(
        self,
        price_queue: asyncio.Queue[PriceTick],
        tui_price_queue: Optional[asyncio.Queue] = None,
        tui_trade_queue: Optional[asyncio.Queue] = None,
    ) -> None:
        self._price_queue = price_queue
        self._tui_price_queue = tui_price_queue
        self._executor = TradeExecutor(tui_queue=tui_trade_queue)

        settings = get_settings()
        self._strategies = {
            pair: registry.get(cfg.strategy)(cfg)
            for pair, cfg in settings.currencies.items()
        }
        logger.info("Trader initialized with pairs: %s", list(self._strategies))

    async def run(self) -> None:
        while True:
            tick: PriceTick = await self._price_queue.get()

            if self._tui_price_queue is not None:
                try:
                    self._tui_price_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    pass  # TUI is slow or not running — drop silently

            strategy = self._strategies.get(tick.pair)
            if strategy is None:
                logger.debug("No strategy for pair %s, skipping", tick.pair)
                continue

            signal = strategy.evaluate(tick)
            if signal is not None:
                await self._executor.execute(signal, tick.pair, tick.last)
