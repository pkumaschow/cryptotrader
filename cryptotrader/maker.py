"""Post-only entries that rest until they fill, drift too far, or time out.

Why this is tick-driven rather than a blocking await: a resting order lives for
minutes, and the trader loop must keep consuming ticks the whole time. Blocking
would back up the price queue (maxsize=100) and leave gaps in the candles the
strategies are built from — corrupting the very signals this is trying to fill.

While an entry rests the strategy stays optimistically long, which is correct:
it must not emit a second BUY for the same breakout. If the order does not fill,
`on_reject` runs the same rollback the executor uses for a refused order, and the
strategy goes flat again.

In test mode nothing is sent to the exchange — the fill is judged against the
live tick stream instead. That is deliberate: staging runs paper-only, so this is
how fill statistics are gathered without risking money on an unproven path.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from cryptotrader.db import database
from cryptotrader.models import PriceTick, RejectedOrder, RejectReason, Side, Trade

logger = logging.getLogger(__name__)


@dataclass
class RestingEntry:
    """A post-only entry waiting to fill, and the terms it dies on.

    `deadline` and `max_drift_pct` bound two different risks: how long the
    signal may age, and how far price may run before a fill would no longer
    reflect the decision that produced it.
    """
    pair: str
    limit_price: float
    quantity: float
    strategy: str
    mode: str
    deadline: datetime
    max_drift_pct: float
    band_width: float | None = None
    on_reject: Callable[[], None] | None = None
    placed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    txid: str | None = None

    def drift_pct(self, price: float) -> float:
        """How far price has run above the limit, as a percentage."""
        if self.limit_price <= 0:
            return 0.0
        return (price - self.limit_price) / self.limit_price * 100


class MakerBook:
    """Holds resting entries and resolves each one exactly once."""

    def __init__(self, db_path: str, tui_queue: asyncio.Queue | None = None,
                 rest_client: object | None = None) -> None:
        """Args:
        db_path: Database for recording fills and no-fills.
        tui_queue: Optional queue for live display.
        rest_client: Exchange client. When present, fills are resolved by
            asking the exchange (`reconcile`) rather than inferred from ticks.
            Required in production: a tick touching the limit does not mean
            *this* order filled, because queue position decides that.
        """
        self._db_path = db_path
        self._tui_queue = tui_queue
        self._rest = rest_client
        # Keyed by (pair, strategy), not pair: test mode runs all four strategies
        # on every pair, and keying by pair alone would silently drop three of
        # them — leaving those strategies believing they were long forever.
        self._resting: dict[tuple[str, str], RestingEntry] = {}

    @property
    def resting(self) -> dict[tuple[str, str], RestingEntry]:
        """Currently resting entries, keyed by (pair, strategy)."""
        return dict(self._resting)

    def is_resting(self, pair: str, strategy: str) -> bool:
        """Whether this pair and strategy already have an entry working.

        The caller needs this to tell a resting order from a refused one: both
        leave `execute()` returning None, but only the second is a rejection.
        """
        return (pair, strategy) in self._resting

    def add(self, entry: RestingEntry) -> None:
        """Take ownership of a resting entry.

        A duplicate for the same pair and strategy is refused and rolled back
        rather than queued — two fills would double the intended position.
        """
        key = (entry.pair, entry.strategy)
        if key in self._resting:
            # One entry per pair+strategy. A duplicate would double the position
            # if both filled, so refuse it — and roll the caller back, or it is
            # left believing it holds something that was never ordered.
            logger.warning("Maker entry already resting for %s [%s] — refusing duplicate",
                           entry.pair, entry.strategy)
            if entry.on_reject is not None:
                entry.on_reject()
            return
        self._resting[key] = entry
        logger.info("Maker entry resting: %s %.8f @ %.2f until %s (drift cap %.2f%%)",
                    entry.pair, entry.quantity, entry.limit_price,
                    entry.deadline.isoformat(timespec="seconds"), entry.max_drift_pct)

    def _emit(self, item: Trade | RejectedOrder) -> None:
        if self._tui_queue is None:
            return
        try:
            self._tui_queue.put_nowait(item)
        except asyncio.QueueFull:
            pass

    def _fill(self, entry: RestingEntry, price: float, now: datetime,
              quantity: float | None = None) -> Trade:
        trade = Trade(pair=entry.pair, side=Side.BUY, price=price,
                      quantity=quantity if quantity is not None else entry.quantity,
                      mode=entry.mode,
                      strategy=entry.strategy, timestamp=now,
                      band_width=entry.band_width, txid=entry.txid)
        try:
            trade.id = database.insert_trade(self._db_path, trade)
        except Exception:
            logger.error("Failed to record maker fill for %s", entry.pair, exc_info=True)
        waited = (now - entry.placed_at).total_seconds()
        logger.info("Maker entry FILLED: %s %.8f @ %.2f after %.0fs",
                    entry.pair, entry.quantity, price, waited)
        self._emit(trade)
        return trade

    def _no_fill(self, entry: RestingEntry, reason_detail: str,
                 now: datetime) -> RejectedOrder:
        order = RejectedOrder(
            pair=entry.pair, side=Side.BUY, price=entry.limit_price,
            quantity=entry.quantity, reason=RejectReason.MAKER_NO_FILL,
            detail=reason_detail, mode=entry.mode, strategy=entry.strategy,
            timestamp=now,
        )
        try:
            order.id = database.insert_rejected_order(self._db_path, order)
        except Exception:
            logger.error("Failed to record maker no-fill for %s", entry.pair, exc_info=True)
        logger.warning("Maker entry NOT FILLED: %s @ %.2f — %s. Signal skipped.",
                       entry.pair, entry.limit_price, reason_detail)
        self._emit(order)
        if entry.on_reject is not None:
            # Same rollback the executor uses: the strategy must not be left
            # believing it holds a position that was never opened.
            entry.on_reject()
        return order

    def on_tick(self, tick: PriceTick, now: datetime | None = None) -> list[Trade]:
        """Resolve every entry on this pair against the tick.

        Fill wins over drift when both hold on the same tick: the price genuinely
        traded at the limit, so the order would have executed.
        """
        now = now or datetime.now(UTC)
        filled: list[Trade] = []
        for key in [k for k in self._resting if k[0] == tick.pair]:
            entry = self._resting[key]

            if tick.last <= entry.limit_price:
                del self._resting[key]
                filled.append(self._fill(entry, entry.limit_price, now))
                continue

            drift = entry.drift_pct(tick.last)
            if drift > entry.max_drift_pct:
                del self._resting[key]
                self._no_fill(entry,
                              f"price ran {drift:.2f}% above the limit "
                              f"(cap {entry.max_drift_pct:.2f}%)", now)
                continue

            if now >= entry.deadline:
                del self._resting[key]
                waited = (now - entry.placed_at).total_seconds()
                self._no_fill(entry, f"unfilled after {waited:.0f}s", now)
        return filled

    async def reconcile(self, now: datetime | None = None) -> list[Trade]:
        """Ask the exchange what actually happened to each resting order.

        This is the difference between paper and money. `on_tick` infers a fill
        from the price touching the limit, which is sound for simulation and
        wrong for a real order: the book may trade through a level while this
        order sits behind others and never executes. Recording that as a fill
        would put a position in the trade log that the account does not hold —
        the unbacked sell again, from the other direction.

        Kraken order states map as:

        - ``closed``                 fully executed
        - ``canceled``/``expired``   with ``vol_exec > 0``: partially executed
        - ``canceled``/``expired``   with ``vol_exec == 0``: never executed
        - ``open``/``pending``       still working — check drift and deadline

        A partial fill is recorded at the volume actually executed, not the
        volume requested. Sizing a later sell from the requested amount is
        exactly the defect that made the bot dispose of more than it held.
        """
        now = now or datetime.now(UTC)
        if self._rest is None:
            return []
        filled: list[Trade] = []
        for key in list(self._resting):
            entry = self._resting.get(key)
            if entry is None or not entry.txid:
                continue
            try:
                record = await self._rest.order_status(entry.txid)
            except Exception:
                # A failed query is not a no-fill. Leave the entry resting and
                # retry; assuming either outcome from a network error would
                # invent a position or discard a real one.
                logger.warning("Could not query order %s for %s — leaving it resting",
                               entry.txid, entry.pair, exc_info=True)
                continue

            status = str(record.get("status", "")).lower()
            vol_exec = float(record.get("vol_exec", 0) or 0)
            avg_price = float(record.get("price", 0) or 0) or entry.limit_price

            if status == "closed":
                del self._resting[key]
                filled.append(self._fill(entry, avg_price, now, quantity=vol_exec or None))
            elif status in ("canceled", "expired"):
                del self._resting[key]
                if vol_exec > 0:
                    logger.warning("Maker entry partially filled: %s %.8f of %.8f",
                                   entry.pair, vol_exec, entry.quantity)
                    filled.append(self._fill(entry, avg_price, now, quantity=vol_exec))
                else:
                    self._no_fill(entry, f"exchange reported {status} with nothing executed",
                                  now)
            elif now >= entry.deadline:
                # expiretm should have cancelled it; cancel explicitly so a
                # clock skew or a missed expiry cannot leave it working.
                await self._cancel(entry)
                del self._resting[key]
                waited = (now - entry.placed_at).total_seconds()
                self._no_fill(entry, f"unfilled after {waited:.0f}s (cancelled)", now)
        return filled

    async def _cancel(self, entry: RestingEntry) -> None:
        if self._rest is None or not entry.txid:
            return
        try:
            await self._rest.cancel_order(entry.txid)
        except Exception:
            logger.warning("Cancel failed for %s (%s)", entry.pair, entry.txid, exc_info=True)

    def expire_due(self, now: datetime | None = None) -> None:
        """Time out entries on pairs that have gone quiet.

        `on_tick` cannot expire an entry for a pair that stops ticking, and a
        silent feed is exactly when an order is least likely to have filled.
        """
        now = now or datetime.now(UTC)
        for key in [k for k, e in self._resting.items() if now >= e.deadline]:
            entry = self._resting.pop(key)
            waited = (now - entry.placed_at).total_seconds()
            self._no_fill(entry, f"unfilled after {waited:.0f}s (no ticks)", now)
