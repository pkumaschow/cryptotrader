"""
Entry point. Wires all components together and starts the asyncio event loop.

Usage:
    python -m cryptotrader.main          # headless (logs to stdout/journald)
    python -m cryptotrader.main --tui    # with Textual TUI
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.exchange.kraken_ws import KrakenWebSocket
from cryptotrader.models import PriceTick, Trade
from cryptotrader.trader import Trader

logger = logging.getLogger(__name__)


def _configure_logging(tui: bool) -> None:
    fmt = "%(asctime)s %(levelname)s %(name)s — %(message)s"
    if tui:
        # Textual owns the terminal — write logs to file to avoid ANSI garbage
        logging.basicConfig(
            level=logging.INFO,
            format=fmt,
            filename="cryptotrader.log",
            filemode="a",
        )
    else:
        logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stdout)


async def _run(tui: bool) -> None:
    settings = get_settings()
    database.init_db(settings.database.path)

    pairs = list(settings.currencies.keys())
    logger.info("Starting CryptoTrader | mode=%s | pairs=%s", settings.mode.active, pairs)

    price_queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=100)
    trade_queue: asyncio.Queue[Trade] = asyncio.Queue(maxsize=100)

    # Separate TUI price queue so TUI gets every tick without blocking trader
    tui_price_queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=100)

    ws = KrakenWebSocket(pairs, price_queue)
    trader = Trader(price_queue, tui_price_queue=tui_price_queue, tui_trade_queue=trade_queue)

    ws_task = asyncio.create_task(ws.run())
    trader_task = asyncio.create_task(trader.run())

    if tui:
        from cryptotrader.tui.app import CryptoTraderApp
        app = CryptoTraderApp(tui_price_queue, trade_queue)
        try:
            await app.run_async(mouse=False)
        finally:
            await ws.stop()
            ws_task.cancel()
            trader_task.cancel()
    else:
        try:
            await asyncio.gather(ws_task, trader_task)
        except asyncio.CancelledError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader")
    parser.add_argument("--tui", action="store_true", help="Launch interactive TUI")
    args = parser.parse_args()
    _configure_logging(tui=args.tui)

    try:
        asyncio.run(_run(tui=args.tui))
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
