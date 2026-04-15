"""
Entry point. Wires all components together and starts the asyncio event loop.

Usage:
    python -m cryptotrader.main          # headless (logs to stdout/journald)
    python -m cryptotrader.main --tui    # with Textual TUI (starts trader)
    python -m cryptotrader.main --tui    # monitor mode if service already running
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import logging
import os
import sys
from datetime import UTC, datetime, timedelta

from cryptotrader.config import get_secrets, get_settings
from cryptotrader.db import database
from cryptotrader.exchange.kraken_ws import KrakenWebSocket
from cryptotrader.health import run as run_health
from cryptotrader.models import PriceTick, Trade
from cryptotrader.trader import Trader

logger = logging.getLogger(__name__)

# Held open for the lifetime of the process — lock releases on exit.
_lock_fh: list[object] = []


def _acquire_instance_lock(db_path: str) -> bool:
    """Try to acquire an exclusive instance lock. Returns True if acquired."""
    lock_path = os.path.splitext(db_path)[0] + ".lock"
    fh = open(lock_path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _lock_fh.append(fh)
    return True


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


def _tui_terminal_setup() -> None:
    # Force a conservative terminal type so Textual skips advanced capability
    # probing (Sixel, focus-reporting, etc.) that leaks escape codes over SSH.
    os.environ["TERM"] = "xterm-256color"
    # Disable all terminal mouse-tracking modes before Textual initialises.
    sys.stdout.write(
        "\x1b[?1000l"  # disable X10 mouse
        "\x1b[?1002l"  # disable button-event mouse
        "\x1b[?1003l"  # disable all-motion mouse
        "\x1b[?1006l"  # disable SGR extended mouse
        "\x1b[?1015l"  # disable URXVT extended mouse
        "\x1b[?1004l"  # disable focus reporting
    )
    sys.stdout.flush()


async def _poll_new_trades(trade_queue: asyncio.Queue[Trade], db_path: str) -> None:
    """Push trades written by the running service into the TUI trade queue."""
    # Seed cursor so we only pick up trades that arrive after monitor starts.
    last_ts: datetime = datetime.now(UTC)
    while True:
        await asyncio.sleep(3)
        try:
            new_trades = database.query_trades(
                db_path, since=last_ts + timedelta(microseconds=1), read_only=True
            )
            for trade in new_trades:
                last_ts = trade.timestamp
                try:
                    trade_queue.put_nowait(trade)
                except asyncio.QueueFull:
                    pass
        except Exception:  # noqa: S110
            pass


async def _run_monitor(hidden_panels: set[str]) -> None:
    """Monitor mode: display prices and DB trades without starting a Trader."""
    settings = get_settings()
    pairs = list(settings.currencies.keys())
    logger.info("Starting CryptoTrader monitor | pairs=%s", pairs)

    price_queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=100)
    trade_queue: asyncio.Queue[Trade] = asyncio.Queue(maxsize=100)

    ws = KrakenWebSocket(pairs, price_queue)
    ws_task = asyncio.create_task(ws.run())
    poller_task = asyncio.create_task(_poll_new_trades(trade_queue, settings.database.path))

    _tui_terminal_setup()
    from cryptotrader.tui.app import CryptoTraderApp
    app = CryptoTraderApp(price_queue, trade_queue, hidden_panels=hidden_panels)
    try:
        await app.run_async(mouse=False)
    finally:
        await ws.stop()
        ws_task.cancel()
        poller_task.cancel()


async def _run(tui: bool, hidden_panels: set[str]) -> None:
    settings = get_settings()
    database.init_db(settings.database.path)

    pairs = list(settings.currencies.keys())
    logger.debug("Starting CryptoTrader | mode=%s | pairs=%s", settings.mode.active, pairs)

    price_queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=100)
    trade_queue: asyncio.Queue[Trade] = asyncio.Queue(maxsize=100)

    # Separate TUI price queue so TUI gets every tick without blocking trader
    tui_price_queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=100)

    ws = KrakenWebSocket(pairs, price_queue)
    trader = Trader(price_queue, tui_price_queue=tui_price_queue, tui_trade_queue=trade_queue)

    ws_task = asyncio.create_task(ws.run())
    trader_task = asyncio.create_task(trader.run())
    health_port = int(os.environ.get("HEALTH_PORT", "8080"))
    health_task = asyncio.create_task(run_health(health_port))

    if tui:
        _tui_terminal_setup()
        from cryptotrader.tui.app import CryptoTraderApp
        app = CryptoTraderApp(tui_price_queue, trade_queue, hidden_panels=hidden_panels)
        try:
            await app.run_async(mouse=False)
        finally:
            await ws.stop()
            ws_task.cancel()
            trader_task.cancel()
            health_task.cancel()
    else:
        try:
            await asyncio.gather(ws_task, trader_task, health_task)
        except asyncio.CancelledError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader")
    parser.add_argument("--tui", action="store_true", help="Launch interactive TUI")
    parser.add_argument("--hide-prices", action="store_true", help="Hide live prices panel")
    parser.add_argument("--hide-weekly", action="store_true", help="Hide weekly summary panel")
    parser.add_argument("--hide-balance", action="store_true", help="Hide balance panel")
    parser.add_argument("--hide-health", action="store_true", help="Hide health panel")
    parser.add_argument("--hide-trades", action="store_true", help="Hide trade log panel")
    parser.add_argument("--hide-stats", action="store_true", help="Hide stats panel")
    args = parser.parse_args()
    _configure_logging(tui=args.tui)

    hidden_panels: set[str] = set()
    if args.hide_prices:
        hidden_panels.add("price-panel")
    if args.hide_weekly:
        hidden_panels.add("weekly-summary-panel")
    if args.hide_balance:
        hidden_panels.add("balance-panel")
    if args.hide_health:
        hidden_panels.add("health-panel")
    if args.hide_trades:
        hidden_panels.add("trade-log-panel")
    if args.hide_stats:
        hidden_panels.add("stats-panel")

    settings = get_settings()

    if settings.mode.active == "production":
        secrets = get_secrets()
        if not secrets.kraken_api_key or not secrets.kraken_api_secret:
            raise RuntimeError(
                "KRAKEN_API_KEY and KRAKEN_API_SECRET must be set before running in production mode"
            )

    lock_acquired = _acquire_instance_lock(settings.database.path)

    if not lock_acquired:
        if args.tui:
            logger.info("Service already running — starting in monitor mode (read-only)")
            try:
                asyncio.run(_run_monitor(hidden_panels))
            except KeyboardInterrupt:
                pass
            return
        sys.exit(
            "ERROR: Another CryptoTrader instance is already running. "
            "Stop it before starting a new one."
        )

    try:
        asyncio.run(_run(tui=args.tui, hidden_panels=hidden_panels))
    except KeyboardInterrupt:
        logger.info("Shutting down.")


if __name__ == "__main__":
    main()
