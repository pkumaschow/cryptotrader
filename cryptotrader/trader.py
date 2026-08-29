"""The core loop: consume ticks, evaluate strategies, resolve the outcome.

The subtle responsibility here is keeping a strategy's belief about its own
position in step with reality. A strategy flips its state the moment it emits a
signal, but the executor can refuse the order afterwards — insufficient
balance, a cap, an unhealthy feed. The loop resolves every signal against what
actually happened, rolling the strategy back when nothing was placed.

Without that, a declined buy leaves the strategy long against an entry price
never paid, and the next exit sells coin nobody bought.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from cryptotrader.config import get_secrets, get_settings
from cryptotrader.executor import TradeExecutor
from cryptotrader.maker import MakerBook
from cryptotrader.models import PriceTick
from cryptotrader.strategy import registry
from cryptotrader.strategy.base import Strategy

logger = logging.getLogger(__name__)


class Trader:
    """The core loop: consume ticks, evaluate strategies, resolve the outcome."""
    def __init__(self, price_queue: asyncio.Queue[PriceTick],
                 tui_price_queue: asyncio.Queue | None = None,
                 tui_trade_queue: asyncio.Queue | None = None,
                 feed_healthy_fn: Callable[[], bool] | None = None) -> None:
        """Wire the strategies for each configured pair and restore their state.

        In test mode every strategy runs on every pair for comparison; in
        production only the one named per pair. Maker entries are refused in
        production regardless of config — fill resolution is tick-based and
        cannot confirm a real resting order filled.
        """
        self._price_queue = price_queue
        self._tui_price_queue = tui_price_queue
        self._feed_healthy_fn = feed_healthy_fn
        settings = get_settings()
        self._production = settings.mode.active == "production"
        # In production, fills are confirmed by asking the exchange; the tick
        # stream cannot prove a specific order executed, because queue position
        # decides that. The book is given a REST client so `reconcile` can ask.
        rest = None
        if self._production and settings.execution.maker_entries:
            from cryptotrader.exchange.kraken_rest import KrakenRest
            rest = KrakenRest(get_secrets().kraken_api_key,
                              get_secrets().kraken_api_secret.get_secret_value())
        self._maker_book = (
            MakerBook(settings.database.path, tui_queue=tui_trade_queue,
                      rest_client=rest)
            if settings.execution.maker_entries else None
        )
        self._executor = TradeExecutor(tui_queue=tui_trade_queue,
                                       maker_book=self._maker_book)
        if rest is not None:
            self._executor.set_rest_client(rest)
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
        """Consume ticks forever, dispatching signals to the executor.

        Every signal is resolved against what actually happened: on a refusal,
        an unhealthy feed, or a raised cap breach, the strategy is rolled back
        so it cannot be left describing a position it never opened.
        """
        while True:
            tick: PriceTick = await self._price_queue.get()
            if self._tui_price_queue is not None:
                try:
                    self._tui_price_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    pass  # TUI is slow or not running — drop silently
            if self._maker_book is not None and not self._production:
                # Test mode only: infer fills from the tick stream. Resolve
                # before evaluating, so a fill on this tick is part of the
                # position the strategies are about to reason from.
                self._maker_book.on_tick(tick)
                self._maker_book.expire_due()
            for strategy in self._strategies.get(tick.pair, []):
                signal = strategy.evaluate(tick)
                if signal is not None:
                    if self._feed_healthy_fn is not None and not self._feed_healthy_fn():
                        logger.warning(
                            "Feed unhealthy — skipping order execution for %s @ %.2f",
                            tick.pair, tick.last,
                        )
                        # Skipping the order without this leaves the strategy
                        # describing a position it never opened.
                        strategy.on_order_rejected()
                        continue
                    band_width = getattr(strategy, "last_band_width", None)
                    # Resolve the position the signal assumed against what the
                    # executor actually did. Discarding this return value is what
                    # let a declined buy leave the strategy believing it was long,
                    # and produced a sell of coin that was never bought.
                    try:
                        trade = await self._executor.execute(
                            signal, tick.pair, tick.last, strategy.name,
                            band_width=band_width,
                            on_reject=strategy.on_order_rejected)
                    except Exception:
                        # A hard-cap breach still aborts the loop as before — but
                        # no longer leaves a phantom position behind for whoever
                        # restarts the service.
                        strategy.on_order_rejected()
                        raise
                    if (self._maker_book is not None
                            and self._maker_book.is_resting(tick.pair, strategy.name)):
                        # Returned None because the entry is resting, not refused.
                        # The strategy stays optimistically long so it cannot fire
                        # a second BUY; the book rolls it back if it never fills.
                        continue
                    if trade is None:
                        logger.warning(
                            "Order refused for %s [%s] %s @ %.2f — rolling back "
                            "strategy position state",
                            tick.pair, strategy.name, signal.value, tick.last,
                        )
                        strategy.on_order_rejected()
                    else:
                        strategy.on_order_filled()

    async def reconcile_maker_entries(self, interval: float = 10.0) -> None:
        """Ask the exchange about resting orders, forever.

        Runs as its own task rather than inside the tick loop: a REST round trip
        per resting order would stall tick consumption, back up the price queue
        and leave gaps in the candles the strategies are built from.

        Only meaningful in production — test mode has no real orders to ask
        about and resolves from ticks instead.
        """
        if self._maker_book is None or not self._production:
            return
        while True:
            await asyncio.sleep(interval)
            try:
                await self._maker_book.reconcile()
            except Exception:
                # A reconciliation failure must never kill the loop; the entry
                # stays resting and the next pass retries.
                logger.error("Maker reconciliation pass failed", exc_info=True)
