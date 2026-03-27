from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label

from cryptotrader.models import PriceTick


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
        col_keys = table.add_columns("Pair", "Bid", "Ask", "Last", "Updated")
        self._col_keys = col_keys
        self._known_rows: set[str] = set()

    def update_tick(self, tick: PriceTick) -> None:
        table = self.query_one("#price-table", DataTable)
        ts = tick.timestamp.strftime("%H:%M:%S")
        values = (tick.pair, f"{tick.bid:.2f}", f"{tick.ask:.2f}", f"{tick.last:.2f}", ts)
        if tick.pair in self._known_rows:
            for col_key, val in zip(self._col_keys, values):
                table.update_cell(tick.pair, col_key, val)
        else:
            table.add_row(*values, key=tick.pair)
            self._known_rows.add(tick.pair)
