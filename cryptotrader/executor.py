from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from cryptotrader.config import get_secrets, get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, Signal, Trade

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
    def __init__(self, tui_queue: Optional[asyncio.Queue] = None) -> None:
        self._tui_queue = tui_queue
        self._rest_client: Optional[object] = None

    def set_rest_client(self, client: object) -> None:
        self._rest_client = client

    def _ensure_rest_client(self) -> None:
        if self._rest_client is None:
            from cryptotrader.exchange.kraken_rest import KrakenRest
            self._rest_client = KrakenRest(
                get_secrets().kraken_api_key, get_secrets().kraken_api_secret)

    async def _check_balance(self, pair: str, cost: float) -> bool:
        """Return True if sufficient balance exists for the trade cost. Skips on error."""
        try:
            balance = await self._rest_client.get_balance()  # type: ignore[union-attr]
            available = balance.get(_quote_balance_key(pair), 0.0)
            if available < cost:
                logger.warning(
                    "Insufficient balance for %s buy: need $%.2f, have $%.2f — skipping",
                    pair, cost, available,
                )
                return False
            return True
        except Exception:
            logger.error("Balance check failed for %s — skipping trade", pair, exc_info=True)
            return False

    async def execute(self, signal: Signal, pair: str, price: float,
                      strategy: str = "unknown",
                      band_width: Optional[float] = None) -> Optional[Trade]:
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
            if not await self._check_balance(pair, cost):
                return None

        trade = Trade(pair=pair, side=side, price=price,
                      quantity=quantity, mode=mode, strategy=strategy,
                      timestamp=datetime.now(timezone.utc), band_width=band_width)

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
