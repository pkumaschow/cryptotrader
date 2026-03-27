from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static

from cryptotrader import statistics


class StatsPanel(Widget):
    DEFAULT_CSS = """
    StatsPanel {
        height: auto;
        border: solid $accent;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Test Mode Statistics[/bold]")
        yield Static(id="stats-body")

    def on_mount(self) -> None:
        self.set_interval(5, self.refresh_stats)
        self.refresh_stats()

    def refresh_stats(self) -> None:
        result = statistics.compute(mode="test")
        body = self.query_one("#stats-body", Static)
        body.update(
            f"Completed trades : {result.total_trades}\n"
            f"Win rate         : {result.win_rate:.1f}%\n"
            f"Total P&L        : ${result.total_pnl:+.4f}\n"
            f"Avg gain         : ${result.avg_gain:+.4f}\n"
            f"Avg loss         : ${result.avg_loss:+.4f}"
        )
