from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static
from cryptotrader import statistics
from cryptotrader.strategy.registry import _REGISTRY


class StatsPanel(Widget):
    DEFAULT_CSS = """
    StatsPanel {
        height: auto;
        border: solid $accent;
        padding: 0 1;
        min-width: 48;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Test Statistics[/bold]")
        yield Static(id="stats-body")

    def on_mount(self) -> None:
        self.set_interval(5, self.refresh_stats)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        lines: list[str] = []
        for sname in _REGISTRY:
            r = statistics.compute(mode="test", strategy=sname)
            if r.total_trades == 0:
                lines.append(f"[cyan]{sname:14}[/cyan]  no trades yet")
            else:
                sign = "+" if r.total_pnl >= 0 else ""
                lines.append(
                    f"[cyan]{sname:14}[/cyan]  {r.total_trades:3} trades  "
                    f"{r.win_rate:5.1f}%  P&L {sign}${r.total_pnl:.4f}"
                )
        self.query_one("#stats-body", Static).update("\n".join(lines))
