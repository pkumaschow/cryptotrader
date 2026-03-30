from datetime import datetime, timezone

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Deposit, Trade

_HISTORY_LIMIT = 100


def _fmt_ts(ts: datetime, use_utc: bool) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.strftime("%Y-%m-%d %H:%M:%S") if use_utc else ts.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _render_trade(trade: Trade, use_utc: bool) -> str:
    color      = "green" if trade.side.value == "buy" else "red"
    side_text  = trade.side.value.upper().ljust(4)
    pair_text  = trade.pair.ljust(7)
    qty_text   = f"{trade.quantity:.5f}"
    price_text = f"{trade.price:>10.2f}"
    strat_text = (trade.strategy or "unknown").ljust(14)
    mode_text  = trade.mode.ljust(4)
    ts         = _fmt_ts(trade.timestamp, use_utc)
    pnl_str    = f"  P&L: [yellow]{trade.pnl:+.4f}[/yellow]" if trade.pnl is not None else ""
    return (
        f"[{color}]{side_text}[/{color}]  {pair_text}  {qty_text} @{price_text}  "
        f"[[cyan]{strat_text}[/cyan]]  {mode_text}  {ts}{pnl_str}"
    )


def _render_deposit(deposit: Deposit, use_utc: bool) -> str:
    rate = deposit.usd_amount / deposit.aud_amount if deposit.aud_amount else 0.0
    ts   = _fmt_ts(deposit.timestamp, use_utc)
    fee_str = f"  fee: [yellow]-${deposit.fee_usd:.2f}[/yellow]" if deposit.fee_usd else ""
    notes_str = f"  {deposit.notes}" if deposit.notes else ""
    return (
        f"[cyan]DEPOSIT[/cyan]  "
        f"[white]A${deposit.aud_amount:,.2f}[/white] → "
        f"[green]${ deposit.usd_amount:,.2f} USD[/green]  "
        f"@ {rate:.4f}{fee_str}  {ts}{notes_str}"
    )


def _render_item(item: Trade | Deposit, use_utc: bool) -> str:
    if isinstance(item, Deposit):
        return _render_deposit(item, use_utc)
    return _render_trade(item, use_utc)


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

    def on_mount(self) -> None:
        self._log_items: list[Trade | Deposit] = []
        self.query_one("#trade-log", RichLog).can_focus = True
        self._load_history()

    def _load_history(self) -> None:
        try:
            settings = get_settings()
            trades   = database.query_trades(settings.database.path, read_only=True)
            deposits = database.query_deposits(settings.database.path, read_only=True)
        except Exception:
            return
        merged: list[Trade | Deposit] = sorted(
            list(trades) + list(deposits),
            key=lambda x: x.timestamp,
        )
        recent = merged[-_HISTORY_LIMIT:]
        if not recent:
            return
        log = self.query_one("#trade-log", RichLog)
        use_utc = getattr(self.app, "use_utc", False)
        for item in recent:
            self._log_items.append(item)
            log.write(_render_item(item, use_utc))
        log.write(f"[dim]── {len(recent)} historical · live below ──[/dim]")

    def append_trade(self, trade: Trade) -> None:
        self._log_items.append(trade)
        log = self.query_one("#trade-log", RichLog)
        log.write(_render_item(trade, getattr(self.app, "use_utc", False)))

    def re_render(self) -> None:
        use_utc = getattr(self.app, "use_utc", False)
        log = self.query_one("#trade-log", RichLog)
        log.clear()
        for item in self._log_items:
            log.write(_render_item(item, use_utc))
