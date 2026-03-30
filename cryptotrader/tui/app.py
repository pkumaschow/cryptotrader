"""
Textual TUI application for monitoring the trading bot.
Runs alongside the trading engine by sharing asyncio.Queue instances.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Label

from cryptotrader.config import get_settings
from cryptotrader.models import PriceTick, Trade
from cryptotrader.tui.balance_panel import BalancePanel
from cryptotrader.tui.health_panel import HealthPanel
from cryptotrader.tui.price_panel import PricePanel
from cryptotrader.tui.stats_panel import StatsPanel
from cryptotrader.tui.trade_log_panel import TradeLogPanel
from cryptotrader.tui.weekly_summary_panel import WeeklySummaryPanel


class CryptoTraderApp(App):
    TITLE = "CryptoTrader"
    BINDINGS = [
        Binding("t", "toggle_tz", "Toggle UTC/Local", priority=True),
        Binding("tab", "focus_next", "Switch Panel", show=True),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    #top-row {
        height: auto;
        min-height: 8;
    }
    #price-panel {
        width: 1fr;
    }
    #weekly-summary-panel {
        width: 1fr;
    }
    #health-panel {
        width: 1fr;
    }
    #bottom-row {
        height: 1fr;
    }
    #trade-log-panel {
        width: 2fr;
    }
    #stats-panel {
        width: 1fr;
    }
    #weekly-summary-panel > DataTable {
        height: auto;
    }
    #tz-indicator {
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
        self.sub_title = settings.mode.active
        yield Header()
        with Horizontal(id="top-row"):
            yield PricePanel(id="price-panel")
            yield WeeklySummaryPanel(id="weekly-summary-panel")
            if settings.mode.active == "production":
                yield BalancePanel(id="balance-panel")
            yield HealthPanel(id="health-panel")
        with Horizontal(id="bottom-row"):
            yield TradeLogPanel(id="trade-log-panel")
            if settings.mode.active == "test":
                yield StatsPanel(id="stats-panel")
        yield Label(self._tz_label(), id="tz-indicator")
        yield Footer()

    @staticmethod
    def _build_label() -> str:
        import cryptotrader
        ts = os.path.getmtime(cryptotrader.__file__)
        dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        return f"Built: {dt}"

    def _tz_label(self) -> str:
        tz = "TZ: UTC" if self.use_utc else "TZ: Local"
        return f"{tz}  ·  {self._build_label()}"

    def action_toggle_tz(self) -> None:
        self.use_utc = not self.use_utc

    def watch_use_utc(self) -> None:
        self.query_one("#tz-indicator", Label).update(self._tz_label())
        self.query_one("#trade-log-panel", TradeLogPanel).re_render()

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
