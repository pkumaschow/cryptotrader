from __future__ import annotations
import asyncio
import logging
from typing import Optional
from cryptotrader.config import get_settings
from cryptotrader.executor import TradeExecutor
from cryptotrader.models import PriceTick
from cryptotrader.strategy import registry
from cryptotrader.strategy.base import Strategy

logger = logging.getLogger(__name__)


class Trader:
    def __init__(self, price_queue: asyncio.Queue[PriceTick],
                 tui_price_queue: Optional[asyncio.Queue] = None,
                 tui_trade_queue: Optional[asyncio.Queue] = None) -> None:
        self._price_queue = price_queue
        self._tui_price_queue = tui_price_queue
        self._executor = TradeExecutor(tui_queue=tui_trade_queue)
        settings = get_settings()
        self._strategies: dict[str, list[Strategy]] = {}
        for pair, cfg in settings.currencies.items():
            if settings.mode.active == "test":
                self._strategies[pair] = [cls(cfg) for cls in registry.ALL_STRATEGIES]
            else:
                self._strategies[pair] = [registry.get(cfg.strategy)(cfg)]
            for strategy in self._strategies[pair]:
                strategy.restore(settings.database.path, pair)
        strategy_names = {p: [s.name for s in ss] for p, ss in self._strategies.items()}
        logger.info("Trader initialized | pairs=%s | strategies=%s",
                    list(self._strategies), strategy_names)

    async def run(self) -> None:
        while True:
            tick: PriceTick = await self._price_queue.get()
            if self._tui_price_queue is not None:
                try:
                    self._tui_price_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    pass  # TUI is slow or not running — drop silently
            for strategy in self._strategies.get(tick.pair, []):
                signal = strategy.evaluate(tick)
                if signal is not None:
                    band_width = getattr(strategy, "last_band_width", None)
                    await self._executor.execute(signal, tick.pair, tick.last, strategy.name,
                                                 band_width=band_width)
