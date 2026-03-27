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
        side_text  = trade.side.value.upper().ljust(4)
        pair_text  = trade.pair.ljust(7)
        qty_text   = f"{trade.quantity:.5f}"
        price_text = f"{trade.price:>10.2f}"
        strat_text = (trade.strategy or "unknown").ljust(14)
        mode_text  = trade.mode.ljust(4)
        ts         = trade.timestamp.strftime("%H:%M:%S")
        pnl_str    = f"  P&L: [yellow]{trade.pnl:+.4f}[/yellow]" if trade.pnl is not None else ""
        log.write(
            f"[{color}]{side_text}[/{color}]  {pair_text}  {qty_text} @{price_text}  "
            f"[[cyan]{strat_text}[/cyan]]  {mode_text}  {ts}{pnl_str}"
        )
