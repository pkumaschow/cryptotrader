"""TUI panel: the trade log, including orders that were refused.

Refused orders appear struck through with a reason tag. They are loaded from the
database rather than only from the live queue, because the TUI usually runs in
monitor mode against an already-running service — a queue-only entry would never
be seen in the mode most used to watch the bot.
"""

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label, RichLog

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Deposit, LogItem, RejectedOrder, RejectReason, Trade

_HISTORY_LIMIT = 100

# Short, aligned tags so a scan down the log separates filled from refused.
_REJECT_TAGS: dict[RejectReason, str] = {
    RejectReason.INSUFFICIENT_BALANCE: "NO FUNDS",
    RejectReason.MAX_ORDER_EXCEEDED:   "OVER CAP",
    RejectReason.DAILY_LOSS_LIMIT:     "LOSS CAP",
    RejectReason.NO_OPEN_POSITION:     "NO POSN ",
    RejectReason.BALANCE_CHECK_FAILED: "BAL FAIL",
    RejectReason.MAKER_NO_FILL:        "NO FILL ",
}


def _fmt_ts(ts: datetime, use_utc: bool) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    fmt = "%Y-%m-%d %H:%M:%S"
    return ts.strftime(fmt) if use_utc else ts.astimezone().strftime(fmt)


def _render_trade(trade: Trade, use_utc: bool) -> str:
    color      = "green" if trade.side.value == "buy" else "red"
    side_text  = trade.side.value.upper().ljust(4)
    pair_text  = trade.pair.ljust(7)
    qty_text   = f"{trade.quantity:.5f}"
    price_text = f"{trade.price:>10.2f}"
    strat_text = (trade.strategy or "unknown").ljust(14)
    mode_text  = trade.mode.ljust(4)
    ts         = _fmt_ts(trade.timestamp, use_utc)
    pnl_str = f"  P&L: [yellow]{trade.pnl:+.4f}[/yellow]" if trade.pnl is not None else ""
    bw_str  = f"  bw: [dim]{trade.band_width:.2f}[/dim]" if trade.band_width is not None else ""
    return (
        f"[{color}]{side_text}[/{color}]  {pair_text}  {qty_text} @{price_text}  "
        f"[[cyan]{strat_text}[/cyan]]  {mode_text}  {ts}{bw_str}{pnl_str}"
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


def _render_rejected(order: RejectedOrder, use_utc: bool) -> str:
    """A refused order — struck through in the side column, reason on the right.

    Deliberately loud. The 2026-08-20 declined buy is what produced the unbacked
    sell two days later, and it was invisible here at the time.
    """
    side_text  = order.side.value.upper().ljust(4)
    pair_text  = order.pair.ljust(7)
    qty_text   = f"{order.quantity:.5f}"
    price_text = f"{order.price:>10.2f}"
    strat_text = (order.strategy or "unknown").ljust(14)
    mode_text  = order.mode.ljust(4)
    ts         = _fmt_ts(order.timestamp, use_utc)
    tag        = _REJECT_TAGS.get(order.reason, order.reason.value[:8].upper().ljust(8))
    detail_str = f"  [dim]{order.detail}[/dim]" if order.detail else ""
    return (
        f"[bold yellow on red]{tag}[/bold yellow on red] "
        f"[strike dim]{side_text}  {pair_text}  {qty_text} @{price_text}[/strike dim]  "
        f"[[cyan]{strat_text}[/cyan]]  {mode_text}  {ts}{detail_str}"
    )


def _render_item(item: LogItem, use_utc: bool) -> str:
    if isinstance(item, Deposit):
        return _render_deposit(item, use_utc)
    if isinstance(item, RejectedOrder):
        return _render_rejected(item, use_utc)
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
        self._log_items: list[LogItem] = []
        self.query_one("#trade-log", RichLog).can_focus = True
        self._load_history()

    def _load_history(self) -> None:
        try:
            settings = get_settings()
            mode = settings.mode.active if settings.mode.active == "production" else None
            trades   = database.query_trades(settings.database.path, mode=mode, read_only=True)
            deposits = database.query_deposits(settings.database.path, read_only=True)
            rejected = database.query_rejected_orders(
                settings.database.path, mode=mode, read_only=True)
        except Exception:
            return
        merged: list[LogItem] = sorted(
            list(trades) + list(deposits) + list(rejected),
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

    def append_trade(self, item: LogItem) -> None:
        """Append a live trade, deposit, or refused order."""
        settings = get_settings()
        mode = getattr(item, "mode", None)
        if settings.mode.active == "production" and mode is not None and mode != "production":
            return
        self._log_items.append(item)
        log = self.query_one("#trade-log", RichLog)
        log.write(_render_item(item, getattr(self.app, "use_utc", False)))

    def re_render(self) -> None:
        use_utc = getattr(self.app, "use_utc", False)
        log = self.query_one("#trade-log", RichLog)
        log.clear()
        for item in self._log_items:
            log.write(_render_item(item, use_utc))
