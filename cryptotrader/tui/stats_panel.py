import asyncio

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
        self.run_worker(self.refresh_stats(), exclusive=True)

    async def refresh_stats(self) -> None:
        def _query() -> list[str]:
            lines: list[str] = []
            for sname in _REGISTRY:
                r = statistics.compute(mode="test", strategy=sname)
                if r.buys == 0 and r.sells == 0:
                    lines.append(f"[cyan]{sname:14}[/cyan]  no trades yet")
                else:
                    sign = "+" if r.total_pnl >= 0 else ""
                    pnl_str = f"  P&L {sign}${r.total_pnl:.4f}" if r.total_trades > 0 else ""
                    wr_str = f"  {r.win_rate:5.1f}%" if r.total_trades > 0 else ""
                    lines.append(
                        f"[cyan]{sname:14}[/cyan]"
                        f"  B:{r.buys} S:{r.sells}"
                        f"{wr_str}{pnl_str}"
                    )
            return lines

        lines = await asyncio.to_thread(_query)
        self.query_one("#stats-body", Static).update("\n".join(lines))
