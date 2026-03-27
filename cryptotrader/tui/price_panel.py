from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

from cryptotrader.models import PriceTick


def _fmt_ts(ts: datetime, use_utc: bool) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%H:%M:%S") if use_utc else ts.astimezone().strftime("%H:%M:%S")


def _direction(prev: float, current: float) -> str:
    if current > prev:
        return "[green]▲[/green]"
    if current < prev:
        return "[red]▼[/red]"
    return " "


class PricePanel(Widget):
    DEFAULT_CSS = """
    PricePanel {
        height: auto;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Live Prices[/bold]")
        yield DataTable(id="price-table")

    def on_mount(self) -> None:
        table = self.query_one("#price-table", DataTable)
        col_keys = table.add_columns("Pair", "Bid", "Ask", "Last", "", "Updated")
        self._col_keys = col_keys
        self._known_rows: set[str] = set()
        self._last_prices: dict[str, float] = {}

    def update_tick(self, tick: PriceTick) -> None:
        table = self.query_one("#price-table", DataTable)
        ts = _fmt_ts(tick.timestamp, getattr(self.app, "use_utc", False))
        prev = self._last_prices.get(tick.pair)
        arrow = _direction(prev, tick.last) if prev is not None else " "
        self._last_prices[tick.pair] = tick.last
        values = (tick.pair, f"{tick.bid:.2f}", f"{tick.ask:.2f}", f"{tick.last:.2f}", arrow, ts)
        if tick.pair in self._known_rows:
            for col_key, val in zip(self._col_keys, values):
                table.update_cell(tick.pair, col_key, val, update_width=False)
        else:
            table.add_row(*values, key=tick.pair)
            self._known_rows.add(tick.pair)
