import asyncio
from datetime import datetime, timedelta, timezone

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side


class WeeklySummaryPanel(Widget):
    DEFAULT_CSS = """
    WeeklySummaryPanel {
        height: auto;
        border: solid $accent;
        padding: 0 1;
        min-width: 36;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Past 7 Days[/bold]")
        yield DataTable(id="weekly-table")

    def on_mount(self) -> None:
        table = self.query_one("#weekly-table", DataTable)
        _, self._col_buys, self._col_sells = table.add_columns("Pair", "Buys", "Sells")
        table.cursor_type = "none"
        self._known_rows: set[str] = set()
        self.set_interval(30, self.refresh_summary)
        self.run_worker(self.refresh_summary(), exclusive=True)

    async def refresh_summary(self) -> None:
        def _query() -> list[tuple[str, int, int]]:
            settings = get_settings()
            since = datetime.now(timezone.utc) - timedelta(days=7)
            trades = database.query_trades(
                settings.database.path, since=since, read_only=True
            )
            counts: dict[str, dict[str, int]] = {}
            for trade in trades:
                entry = counts.setdefault(trade.pair, {"buy": 0, "sell": 0})
                if trade.side == Side.BUY:
                    entry["buy"] += 1
                else:
                    entry["sell"] += 1
            rows = [(pair, v["buy"], v["sell"]) for pair, v in sorted(counts.items())]
            total_buy = sum(v["buy"] for v in counts.values())
            total_sell = sum(v["sell"] for v in counts.values())
            rows.append(("TOTAL", total_buy, total_sell))
            return rows

        rows = await asyncio.to_thread(_query)
        table = self.query_one("#weekly-table", DataTable)

        for pair, buys, sells in rows:
            buy_str = f"[green]{buys}[/green]"
            sell_str = f"[red]{sells}[/red]"
            if pair in self._known_rows:
                table.update_cell(pair, self._col_buys, buy_str, update_width=False)
                table.update_cell(pair, self._col_sells, sell_str, update_width=False)
            else:
                label = f"[bold]{pair}[/bold]" if pair == "TOTAL" else pair
                table.add_row(label, buy_str, sell_str, key=pair)
                self._known_rows.add(pair)
