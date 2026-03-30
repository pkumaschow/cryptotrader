import asyncio
import time

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static

from cryptotrader.health import _check_database, _check_kraken, _deployed_at, _start_time


def _fmt_uptime(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


class HealthPanel(Widget):
    DEFAULT_CSS = """
    HealthPanel {
        height: auto;
        border: solid $accent;
        padding: 0 1;
        min-width: 28;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Service Health[/bold]")
        yield Static("Checking…", id="health-body")

    def on_mount(self) -> None:
        self.set_interval(30, self.refresh_health)
        self.run_worker(self.refresh_health(), exclusive=True)

    async def refresh_health(self) -> None:
        from cryptotrader.config import get_settings
        settings = get_settings()

        db_result, kraken_result = await asyncio.gather(
            asyncio.to_thread(_check_database, settings.database.path),
            _check_kraken(),
        )

        all_ok = db_result["status"] == "ok" and kraken_result["status"] == "ok"
        status_markup = "[green]OK[/green]" if all_ok else "[red]DEGRADED[/red]"

        db_ok = db_result["status"] == "ok"
        db_markup = "[green]ok[/green]" if db_ok else f"[red]error[/red]"

        kraken_ok = kraken_result["status"] == "ok"
        if kraken_ok:
            ks = kraken_result.get("kraken_status", "ok")
            kraken_markup = f"[green]{ks}[/green]"
        else:
            kraken_markup = "[red]error[/red]"

        uptime = _fmt_uptime(int(time.monotonic() - _start_time))
        deployed = _deployed_at()

        lines = [
            f"[cyan]{'Status':>8}[/cyan]  {status_markup}",
            f"[cyan]{'Uptime':>8}[/cyan]  {uptime}",
            f"[cyan]{'Deployed':>8}[/cyan]  {deployed}",
            f"[cyan]{'Database':>8}[/cyan]  {db_markup}",
            f"[cyan]{'Kraken':>8}[/cyan]  {kraken_markup}",
        ]
        self.query_one("#health-body", Static).update("\n".join(lines))
