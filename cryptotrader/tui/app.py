"""
Textual TUI application for monitoring the trading bot.
Runs alongside the trading engine by sharing asyncio.Queue instances.
"""
from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Label

from cryptotrader.config import get_settings
from cryptotrader.models import PriceTick, Trade
from cryptotrader.tui.price_panel import PricePanel
from cryptotrader.tui.stats_panel import StatsPanel
from cryptotrader.tui.trade_log_panel import TradeLogPanel


class CryptoTraderApp(App):
    BINDINGS = [Binding("t", "toggle_tz", "Toggle UTC/Local", priority=True)]

    CSS = """
    Screen {
        layout: vertical;
    }
    Horizontal {
        height: 1fr;
    }
    #tz-indicator {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text-muted;
        padding: 0 1;
    }
    """

    use_utc: reactive[bool] = reactive(False, init=False)

    def __init__(
        self,
        price_queue: asyncio.Queue[PriceTick],
        trade_queue: asyncio.Queue[Trade],
    ) -> None:
        super().__init__()
        self._price_queue = price_queue
        self._trade_queue = trade_queue

    def compose(self) -> ComposeResult:
        settings = get_settings()
        yield PricePanel(id="price-panel")
        with Horizontal():
            yield TradeLogPanel(id="trade-log-panel")
            if settings.mode.active == "test":
                yield StatsPanel(id="stats-panel")
        yield Label(self._tz_label(), id="tz-indicator")
        yield Footer()

    def _tz_label(self) -> str:
        return "TZ: UTC" if self.use_utc else "TZ: Local"

    def action_toggle_tz(self) -> None:
        self.use_utc = not self.use_utc

    def watch_use_utc(self) -> None:
        self.query_one("#tz-indicator", Label).update(self._tz_label())

    def on_mount(self) -> None:
        self.run_worker(self._consume_prices(), exclusive=False)
        self.run_worker(self._consume_trades(), exclusive=False)

    async def _consume_prices(self) -> None:
        panel = self.query_one("#price-panel", PricePanel)
        while True:
            tick = await self._price_queue.get()
            panel.update_tick(tick)

    async def _consume_trades(self) -> None:
        panel = self.query_one("#trade-log-panel", TradeLogPanel)
        while True:
            trade = await self._trade_queue.get()
            panel.append_trade(trade)
