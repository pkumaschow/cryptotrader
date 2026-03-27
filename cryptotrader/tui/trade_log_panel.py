from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog

from cryptotrader.models import Trade


class TradeLogPanel(Widget):
    DEFAULT_CSS = """
    TradeLogPanel {
        height: 1fr;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Trade Log[/bold]")
        yield RichLog(id="trade-log", wrap=True, markup=True)

    def append_trade(self, trade: Trade) -> None:
        log = self.query_one("#trade-log", RichLog)
        color = "green" if trade.side.value == "buy" else "red"
        ts = trade.timestamp.strftime("%H:%M:%S")
        pnl_str = f"  P&L: [yellow]{trade.pnl:+.4f}[/yellow]" if trade.pnl is not None else ""
        log.write(
            f"[{color}]{trade.side.value.upper()}[/{color}] {trade.pair} "
            f"{trade.quantity} @ {trade.price:.2f}  [{trade.mode}]  {ts}{pnl_str}"
        )
