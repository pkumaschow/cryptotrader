import asyncio

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, Static


# Kraken balance keys → display labels
_DISPLAY = {
    "ZUSD": "USD",
    "XXBT": "BTC",
    "XETH": "ETH",
    "ZGBP": "GBP",
    "ZEUR": "EUR",
    "ZAUD": "AUD",
}

# Zero-balance threshold — don't show dust
_MIN_DISPLAY = {
    "ZUSD": 0.01,
    "ZEUR": 0.01,
    "ZGBP": 0.01,
    "ZAUD": 0.01,
    "XXBT": 0.000001,
    "XETH": 0.0001,
}


class BalancePanel(Widget):
    DEFAULT_CSS = """
    BalancePanel {
        height: auto;
        border: solid $accent;
        padding: 0 1;
        min-width: 28;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Account Balance[/bold]")
        yield Static("Loading…", id="balance-body")

    def on_mount(self) -> None:
        self.set_interval(30, self.refresh_balance)
        self.run_worker(self.refresh_balance(), exclusive=True)

    async def refresh_balance(self) -> None:
        async def _fetch() -> dict[str, float]:
            from cryptotrader.config import get_secrets
            from cryptotrader.exchange.kraken_rest import KrakenRest
            secrets = get_secrets()
            client = KrakenRest(secrets.kraken_api_key, secrets.kraken_api_secret)
            try:
                return await client.get_balance()
            finally:
                await client.close()

        try:
            balance = await asyncio.shield(asyncio.ensure_future(_fetch()))
        except Exception as exc:
            self.query_one("#balance-body", Static).update(f"[red]Error: {exc}[/red]")
            return

        lines: list[str] = []
        for key, label in _DISPLAY.items():
            val = balance.get(key, 0.0)
            threshold = _MIN_DISPLAY.get(key, 0.0)
            if val < threshold:
                continue
            if key in ("ZUSD", "ZEUR", "ZGBP", "ZAUD"):
                lines.append(f"[cyan]{label:>4}[/cyan]  [green]${val:,.2f}[/green]")
            else:
                lines.append(f"[cyan]{label:>4}[/cyan]  [white]{val:.8f}[/white]")

        # Any non-zero balances not in _DISPLAY
        for key, val in sorted(balance.items()):
            if key not in _DISPLAY and val > 0.0:
                lines.append(f"[cyan]{key:>4}[/cyan]  [white]{val:.8f}[/white]")

        self.query_one("#balance-body", Static).update(
            "\n".join(lines) if lines else "[dim]No balances[/dim]"
        )
