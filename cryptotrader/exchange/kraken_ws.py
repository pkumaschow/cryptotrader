"""
Kraken WebSocket v2 client.
Subscribes to ticker feeds for configured currency pairs, pushes PriceTick
objects into an asyncio.Queue. Includes exponential-backoff reconnect and a
stale-data watchdog that triggers reconnect if no tick arrives within
settings.websocket.stale_threshold seconds.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from cryptotrader.config import get_settings
from cryptotrader.models import PriceTick

logger = logging.getLogger(__name__)

_WS_URL = "wss://ws.kraken.com/v2"


class KrakenWebSocket:
    def __init__(self, pairs: list[str], price_queue: asyncio.Queue[PriceTick]) -> None:
        self._pairs = pairs
        self._price_queue = price_queue
        self._last_tick_time: float = 0.0
        self._running = False
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._receive_task: asyncio.Task | None = None
        self._backoff_attempt: int = 0

    async def run(self) -> None:
        self._running = True
        watchdog_task = asyncio.create_task(self._watchdog())
        try:
            await self._connect_loop()
        finally:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass

    async def stop(self) -> None:
        self._running = False
        if self._receive_task is not None and not self._receive_task.done():
            self._receive_task.cancel()

    async def _connect_loop(self) -> None:
        while self._running:
            ws = None
            try:
                logger.info("Connecting to Kraken WS (attempt %d)", self._backoff_attempt + 1)
                ws = await asyncio.wait_for(
                    websockets.connect(
                        _WS_URL,
                        ping_interval=20,
                        ping_timeout=10,
                        additional_headers={"User-Agent": "cryptotrader/0.1.0"},
                    ),
                    timeout=15,
                )
                logger.info("Connected to Kraken WS")
                self._ws = ws
                await ws.send(json.dumps({
                    "method": "subscribe",
                    "params": {
                        "channel": "ticker",
                        "symbol": self._pairs,
                    },
                }))
                logger.info("Subscription sent for pairs=%s", self._pairs)
                self._last_tick_time = asyncio.get_event_loop().time()

                # Run receive loop as a separate task so the watchdog can cancel it
                # without deadlocking (calling ws.close() while recv is running can hang)
                self._receive_task = asyncio.create_task(self._receive(ws))
                try:
                    await self._receive_task
                except asyncio.CancelledError:
                    logger.info("Receive loop cancelled — reconnecting")
                finally:
                    self._receive_task = None

            except asyncio.TimeoutError:
                logger.warning("WS connect timed out after 15s — will retry")
            except ConnectionClosed as exc:
                logger.warning("WS connection closed: %s", exc)
            except InvalidStatus as exc:
                if exc.response.status_code == 429:
                    logger.warning("Kraken rate limited (HTTP 429) — waiting 60s before retry")
                    await asyncio.sleep(60)
                else:
                    logger.error("WS handshake rejected: %s", exc)
            except Exception:
                logger.exception("WS error")
            finally:
                self._ws = None
                if ws is not None:
                    try:
                        await asyncio.wait_for(ws.close(), timeout=3)
                    except Exception:
                        pass

            if not self._running:
                break
            wait = min(2 ** self._backoff_attempt, 60)
            logger.info("Reconnecting in %ds...", wait)
            await asyncio.sleep(wait)
            self._backoff_attempt += 1

    async def _receive(self, ws: websockets.asyncio.client.ClientConnection) -> None:
        async for raw in ws:
            if not self._running:
                return
            self._dispatch(raw)

    def _dispatch(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        # Log any error or status messages from Kraken
        channel = msg.get("channel")
        if channel not in ("ticker", "heartbeat"):
            if msg.get("success") is False or "error" in msg:
                logger.error("Kraken WS error: %s", msg)
            else:
                logger.info("Kraken WS message: %s", msg)

        # Kraken WS v2 ticker messages have type=="update" and channel=="ticker"
        if channel != "ticker" or msg.get("type") not in ("snapshot", "update"):
            return

        for item in msg.get("data", []):
            try:
                tick = PriceTick(
                    pair=item["symbol"],
                    bid=float(item["bid"]),
                    ask=float(item["ask"]),
                    last=float(item["last"]),
                    timestamp=datetime.now(timezone.utc),
                )
                self._last_tick_time = asyncio.get_event_loop().time()
                self._backoff_attempt = 0  # reset backoff only after a real tick arrives
                try:
                    self._price_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    logger.warning("Price queue full — dropping tick for %s", tick.pair)
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug("Failed to parse tick: %s — %s", item, exc)

    async def _watchdog(self) -> None:
        settings = get_settings()
        threshold = settings.websocket.stale_threshold
        while self._running:
            await asyncio.sleep(threshold)
            if self._last_tick_time == 0:
                continue
            elapsed = asyncio.get_event_loop().time() - self._last_tick_time
            logger.debug("Watchdog: elapsed=%.0fs threshold=%.0fs", elapsed, threshold)
            if elapsed > threshold:
                logger.warning("Stale data: no tick in %.0fs — cancelling receive task", elapsed)
                if self._receive_task is not None and not self._receive_task.done():
                    self._receive_task.cancel()
