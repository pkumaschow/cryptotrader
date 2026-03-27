from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Label
from textual.reactive import reactive

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
        table.add_columns("Pair", "Bid", "Ask", "Last", "Updated")

    def update_tick(self, tick: PriceTick) -> None:
        table = self.query_one("#price-table", DataTable)
        row_key = tick.pair
        ts = tick.timestamp.strftime("%H:%M:%S")
        row = (tick.pair, f"{tick.bid:.2f}", f"{tick.ask:.2f}", f"{tick.last:.2f}", ts)
        try:
            table.update_cell(row_key, "Pair", tick.pair)
            table.update_cell(row_key, "Bid", f"{tick.bid:.2f}")
            table.update_cell(row_key, "Ask", f"{tick.ask:.2f}")
            table.update_cell(row_key, "Last", f"{tick.last:.2f}")
            table.update_cell(row_key, "Updated", ts)
        except Exception:
            table.add_row(*row, key=row_key)
