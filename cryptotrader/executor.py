"""Places orders, and refuses the ones that should not be placed.

Every safety rail lives here rather than in the strategies: the balance check,
`max_order_usd`, the daily loss limit, and the refusal to sell a position the
trade log does not show. A strategy proposes; this decides.

Two behaviours are worth knowing because they are not obvious:

- **Sells are sized from the open position**, not from `config.quantity`.
  `budget_usd` sizes buys only, so a config-sized sell would dispose of more
  than was ever bought.
- **A refusal is recorded, not just logged.** Refused orders go to the
  `rejected_orders` table and the TUI. A declined buy is what precedes a
  strategy believing it holds a position it never opened.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from cryptotrader.config import get_secrets, get_settings
from cryptotrader.db import database
from cryptotrader.models import RejectedOrder, RejectReason, Side, Signal, Trade

logger = logging.getLogger(__name__)

# Maps the quote currency from a pair string to Kraken's balance key.
_KRAKEN_QUOTE_KEYS: dict[str, str] = {
    "USD": "ZUSD",
    "EUR": "ZEUR",
    "GBP": "ZGBP",
    "CAD": "ZCAD",
    "JPY": "ZJPY",
    "CHF": "ZCHF",
    "AUD": "ZAUD",
}


def _quote_balance_key(pair: str) -> str:
    """Extract quote currency from 'BASE/QUOTE' and return Kraken balance key."""
    quote = pair.split("/")[-1] if "/" in pair else pair[-3:]
    return _KRAKEN_QUOTE_KEYS.get(quote, quote)


class TradeExecutor:
    """Places orders, and refuses the ones that should not be placed.

    Every safety rail lives here rather than in the strategies: the balance
    check, `max_order_usd`, the daily loss limit, and the refusal to sell a
    position the trade log does not show. A strategy proposes; this decides.
    """
    def __init__(self, tui_queue: asyncio.Queue | None = None,
                 maker_book: object | None = None) -> None:
        """Args:
        tui_queue: Optional queue for live display of trades and refusals.
        maker_book: Optional resting-order book; when absent, or when the
        config has not opted in, entries cross the spread as market
        orders.
        """
        self._tui_queue = tui_queue
        self._rest_client: object | None = None
        self._maker_book = maker_book

    def set_rest_client(self, client: object) -> None:
        """Inject an exchange client, chiefly so tests can supply a fake."""
        self._rest_client = client

    def _reject(self, pair: str, side: Side, price: float, quantity: float,
                reason: RejectReason, detail: str, mode: str,
                strategy: str) -> None:
        """Record a refused order so it survives beyond a journald line.

        Persisted as well as queued: the TUI runs in monitor mode most of the
        time, where its trade log is fed from the DB rather than this queue, so
        a queue-only rejection would never be seen.
        """
        order = RejectedOrder(
            pair=pair, side=side, price=price, quantity=quantity,
            reason=reason, detail=detail, mode=mode, strategy=strategy,
            timestamp=datetime.now(UTC),
        )
        try:
            settings = get_settings()
            order.id = database.insert_rejected_order(settings.database.path, order)
        except Exception:
            # Never let bookkeeping turn a declined order into a crash.
            logger.error("Failed to record rejected order for %s", pair, exc_info=True)
        if self._tui_queue is not None:
            try:
                self._tui_queue.put_nowait(order)
            except asyncio.QueueFull:
                pass

    def _ensure_rest_client(self) -> None:
        if self._rest_client is None:
            from cryptotrader.exchange.kraken_rest import KrakenRest
            self._rest_client = KrakenRest(
                get_secrets().kraken_api_key,
                get_secrets().kraken_api_secret.get_secret_value())

    async def _check_balance(self, pair: str,
                             cost: float) -> tuple[RejectReason, str] | None:
        """None when the balance covers `cost`, otherwise (reason, detail)."""
        try:
            balance = await self._rest_client.get_balance()  # type: ignore[union-attr]
            available = balance.get(_quote_balance_key(pair), 0.0)
            if available < cost:
                logger.warning(
                    "Insufficient balance for %s buy: need $%.2f, have $%.2f — skipping",
                    pair, cost, available,
                )
                return (RejectReason.INSUFFICIENT_BALANCE,
                        f"need ${cost:.2f}, have ${available:.2f}")
            return None
        except Exception as exc:
            logger.error("Balance check failed for %s — skipping trade", pair, exc_info=True)
            return (RejectReason.BALANCE_CHECK_FAILED, f"{type(exc).__name__}: {exc}")

    def _maker_eligible(self, side: Side, pair: str, strategy: str) -> bool:
        """Entries only, and only when a config has opted in.

        Exits stay market orders by design: an unfilled buy costs an opportunity,
        an unfilled sell means holding a position the strategy decided to close.
        """
        if side is not Side.BUY or self._maker_book is None:
            return False
        if not get_settings().execution.maker_entries:
            return False
        return not self._maker_book.is_resting(pair, strategy)  # type: ignore[union-attr]

    async def _rest_maker_entry(self, pair: str, price: float, quantity: float,
                                strategy: str, mode: str, band_width: float | None,
                                on_reject: object | None) -> None:
        """Post the entry and hand it to the book; it resolves from later ticks."""
        from datetime import timedelta

        from cryptotrader.maker import RestingEntry

        cfg = get_settings().execution
        entry = RestingEntry(
            pair=pair, limit_price=price, quantity=quantity, strategy=strategy,
            mode=mode, band_width=band_width,
            deadline=datetime.now(UTC) + timedelta(seconds=cfg.maker_wait_seconds),
            max_drift_pct=cfg.maker_max_drift_pct,
            on_reject=on_reject,  # type: ignore[arg-type]
        )
        if mode == "production":
            self._ensure_rest_client()
            entry.txid = await self._rest_client.place_post_only_limit(  # type: ignore[union-attr]
                pair, Side.BUY.value, quantity, price, cfg.maker_wait_seconds)
        self._maker_book.add(entry)  # type: ignore[union-attr]

    async def execute(self, signal: Signal, pair: str, price: float,
                      strategy: str = "unknown",
                      band_width: float | None = None,
                      on_reject: object | None = None) -> Trade | None:
        """Place the proposed order, or refuse it and record why.

        Buys are sized by `budget_usd` when set; sells are sized from the open
        position in the trade log, never from `config.quantity` — that mismatch
        is what once disposed of more than had been bought.

        Returns:
        The recorded trade, or None if the order was refused **or** rested
        as a maker entry. Those two are different states: the caller must
        check the maker book before treating None as a refusal, or it will
        roll back a strategy whose order is still working.

        Raises:
        RuntimeError: If the order value exceeds `max_order_usd`. Deliberately
        fatal — a breach of the hard cap should stop the loop.
        """
        settings = get_settings()
        mode = settings.mode.active
        currency_cfg = settings.currencies[pair]
        side = Side.BUY if signal == Signal.BUY else Side.SELL

        quantity = currency_cfg.quantity

        if mode == "production" and side == Side.BUY:
            self._ensure_rest_client()

            # Budget-based quantity: spend a fixed USD amount per buy
            if currency_cfg.budget_usd is not None and price > 0:
                quantity = currency_cfg.budget_usd / price

            cost = quantity * price

            if cost > currency_cfg.max_order_usd:
                self._reject(pair, side, price, quantity,
                             RejectReason.MAX_ORDER_EXCEEDED,
                             f"${cost:.2f} exceeds cap ${currency_cfg.max_order_usd:.2f}",
                             mode, strategy)
                raise RuntimeError(
                    f"Order value ${cost:.2f} exceeds max_order_usd=${currency_cfg.max_order_usd}"
                    f" for {pair} — refusing to place order"
                )

            rejection = await self._check_balance(pair, cost)
            if rejection is not None:
                self._reject(pair, side, price, quantity, rejection[0], rejection[1],
                             mode, strategy)
                return None

        elif mode == "production" and side == Side.SELL:
            # Sell what is actually held, not the static config lot. `budget_usd`
            # sizes buys only, so a config-sized sell disposes of more than was ever
            # bought (BTC: buys ~0.00062 against a 0.001 lot — 61% too much).
            #
            # Sizing from the trade log also makes an unbacked sell impossible: a
            # strategy that believes it is long after the executor declined its buy
            # now resolves to zero, and the order is refused rather than placed.
            from cryptotrader.statistics import open_position_quantity

            quantity = open_position_quantity(
                pair=pair, mode=mode, strategy=strategy,
                db_path=settings.database.path,
            )
            if quantity <= 0:
                logger.error(
                    "Refusing SELL %s [%s] @ %.2f — no open position in the trade log. "
                    "Nothing was bought to sell; the strategy's position state is stale.",
                    pair, strategy, price,
                )
                self._reject(pair, side, price, 0.0, RejectReason.NO_OPEN_POSITION,
                             "strategy believes it is long; trade log says flat",
                             mode, strategy)
                return None

        from cryptotrader.statistics import daily_pnl
        pnl_today = daily_pnl(mode=mode, db_path=settings.database.path)
        if pnl_today <= -settings.mode.max_daily_loss_usd:
            logger.warning(
                "Daily loss limit breached ($%.2f lost today, limit=$%.2f) "
                "— halting all trades for the rest of the day",
                -pnl_today, settings.mode.max_daily_loss_usd,
            )
            limit = settings.mode.max_daily_loss_usd
            self._reject(pair, side, price, quantity, RejectReason.DAILY_LOSS_LIMIT,
                         f"${-pnl_today:.2f} lost today, limit ${limit:.2f}",
                         mode, strategy)
            return None

        # Maker entry: rest a post-only limit rather than crossing the spread.
        # Returns None because no trade exists yet — the book resolves it from
        # later ticks and calls `on_reject` if it never fills.
        if self._maker_eligible(side, pair, strategy):
            await self._rest_maker_entry(pair, price, quantity, strategy, mode,
                                         band_width, on_reject)
            return None

        trade = Trade(pair=pair, side=side, price=price,
                      quantity=quantity, mode=mode, strategy=strategy,
                      timestamp=datetime.now(UTC), band_width=band_width)

        # Record realized P&L on the closing (sell) leg, FIFO-matched against the
        # open entry buy. Computed before insert so query_trades sees only prior
        # trades. Same convention as statistics.compute() (gross of fees).
        if side == Side.SELL:
            from cryptotrader.statistics import realized_pnl_for_sell
            trade.pnl = realized_pnl_for_sell(
                pair=pair, mode=mode, sell_price=price,
                sell_quantity=quantity, strategy=strategy,
                db_path=settings.database.path,
            )

        if mode == "test":
            trade.id = database.insert_trade(settings.database.path, trade)
            logger.info("[TEST] %s %s %.8f @ %.2f  [%s]",
                        side.value.upper(), pair, trade.quantity, price, strategy)
        elif mode == "production":
            self._ensure_rest_client()
            txid = await self._rest_client.place_order(pair, side.value, trade.quantity)  # type: ignore[union-attr]
            trade.txid = txid
            trade.id = database.insert_trade(settings.database.path, trade)
            logger.info("[PROD] %s %s %.8f @ %.2f  [%s]  txid=%s",
                        side.value.upper(), pair, trade.quantity, price, strategy, txid)
        else:
            raise RuntimeError(f"Unknown mode: {mode!r}")

        if self._tui_queue is not None:
            try:
                self._tui_queue.put_nowait(trade)
            except asyncio.QueueFull:
                pass
        return trade
