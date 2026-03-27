from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog

from cryptotrader.models import Trade


def _fmt_ts(ts: datetime, use_utc: bool) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%H:%M:%S") if use_utc else ts.astimezone().strftime("%H:%M:%S")


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
        yield RichLog(id="trade-log", wrap=True, markup=True, max_lines=500)

    def append_trade(self, trade: Trade) -> None:
        log = self.query_one("#trade-log", RichLog)
        color = "green" if trade.side.value == "buy" else "red"
        side_text  = trade.side.value.upper().ljust(4)
        pair_text  = trade.pair.ljust(7)
        qty_text   = f"{trade.quantity:.5f}"
        price_text = f"{trade.price:>10.2f}"
        strat_text = (trade.strategy or "unknown").ljust(14)
        mode_text  = trade.mode.ljust(4)
        ts         = _fmt_ts(trade.timestamp, getattr(self.app, "use_utc", False))
        pnl_str    = f"  P&L: [yellow]{trade.pnl:+.4f}[/yellow]" if trade.pnl is not None else ""
        log.write(
            f"[{color}]{side_text}[/{color}]  {pair_text}  {qty_text} @{price_text}  "
            f"[[cyan]{strat_text}[/cyan]]  {mode_text}  {ts}{pnl_str}"
        )
