"""Tests for KrakenWebSocket reconnect backoff behaviour and feed health."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.frames import Close

from cryptotrader.exchange.kraken_ws import KrakenWebSocket
from cryptotrader.models import PriceTick


def _close_exc(code: int | None) -> ConnectionClosed:
    rcvd = Close(code=code, reason="") if code is not None else None
    return ConnectionClosed(rcvd=rcvd, sent=None)


async def _run_one_iteration(ws: KrakenWebSocket, exc: ConnectionClosed) -> None:
    """Run _connect_loop for exactly one connection attempt then stop.

    Uses connect timeout (15s) vs close timeout (3s) to route mocks:
    - timeout=15 → the websockets.connect call → returns fake ws that raises exc in receive
    - timeout=3  → the ws.close() in finally → raise TimeoutError (swallowed by except)
    Second connect attempt → set _running=False → loop exits.
    """
    ws._running = True
    connect_call_count = 0

    async def fake_wait_for(coro, timeout):
        nonlocal connect_call_count
        try:
            coro.close()  # prevent coroutine-never-awaited warnings
        except Exception:
            pass

        if timeout == 3:
            # ws.close() call in finally block — just raise to keep things clean
            raise TimeoutError

        # timeout == 15 → websockets.connect call
        connect_call_count += 1
        if connect_call_count > 1:
            ws._running = False
            raise TimeoutError  # stop after second connect attempt

        # First connect: return a fake ws whose receive loop raises exc
        fake_ws = MagicMock()
        fake_ws.send = AsyncMock()
        fake_ws.close = AsyncMock()

        async def fake_receive_gen():
            raise exc
            # unreachable, but satisfies the async generator contract

        # Make `async for raw in ws:` raise exc immediately
        async def fake_aiter(self_ws):
            raise exc

        # _receive does: async for raw in ws: self._dispatch(raw)
        # We need ws to be async-iterable and raise on first __anext__
        fake_ws.__aiter__ = MagicMock(return_value=fake_ws)
        fake_ws.__anext__ = AsyncMock(side_effect=exc)
        return fake_ws

    async def fake_sleep(_):
        pass  # don't actually sleep

    with patch("cryptotrader.exchange.kraken_ws.asyncio.wait_for", fake_wait_for), \
         patch("cryptotrader.exchange.kraken_ws.asyncio.sleep", fake_sleep):
        await ws._connect_loop()


@pytest.mark.asyncio
async def test_backoff_resets_on_code_1000():
    """Code 1000 (server-side refresh) should reset _backoff_attempt to 0 before increment.

    Starting at backoff=3: without fix would end at 4. With fix: resets to 0, increments to 1.
    """
    queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=10)
    ws = KrakenWebSocket(["BTC/USD"], queue)
    ws._backoff_attempt = 3

    await _run_one_iteration(ws, _close_exc(1000))

    # Reset to 0 in exception handler, then +1 at end of loop = 1
    assert ws._backoff_attempt == 1, (
        f"Expected 1 (reset to 0 + increment), got {ws._backoff_attempt}. "
        "Without the fix this would be 4."
    )


@pytest.mark.asyncio
async def test_backoff_not_reset_on_code_1006():
    """Unexpected close (code 1006) should NOT reset backoff — penalty compounds."""
    queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=10)
    ws = KrakenWebSocket(["BTC/USD"], queue)
    ws._backoff_attempt = 3

    await _run_one_iteration(ws, _close_exc(1006))

    # No reset: 3 + 1 = 4
    assert ws._backoff_attempt == 4, (
        f"Expected 4 (kept 3 + increment), got {ws._backoff_attempt}"
    )


@pytest.mark.asyncio
async def test_backoff_not_reset_on_abnormal_close():
    """Abnormal close (rcvd=None, no close frame received) should NOT reset backoff."""
    queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=10)
    ws = KrakenWebSocket(["BTC/USD"], queue)
    ws._backoff_attempt = 2

    await _run_one_iteration(ws, _close_exc(None))

    # No reset: 2 + 1 = 3
    assert ws._backoff_attempt == 3, (
        f"Expected 3 (kept 2 + increment), got {ws._backoff_attempt}"
    )


# ── feed_healthy() tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feed_healthy_false_when_never_connected():
    """feed_healthy() returns False before any tick is received."""
    queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=10)
    ws = KrakenWebSocket(["BTC/USD"], queue)
    # _last_tick_time starts at 0.0 — early-return path, no get_settings call needed
    assert ws.feed_healthy() is False


@pytest.mark.asyncio
async def test_feed_healthy_true_within_threshold():
    """feed_healthy() returns True when last tick was recent."""
    queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=10)
    ws = KrakenWebSocket(["BTC/USD"], queue)
    now = asyncio.get_event_loop().time()
    ws._last_tick_time = now - 5.0  # 5s ago, well within 30s threshold

    with patch("cryptotrader.exchange.kraken_ws.get_settings") as ms:
        fake = MagicMock()
        fake.websocket.stale_threshold = 30
        ms.return_value = fake
        assert ws.feed_healthy() is True


@pytest.mark.asyncio
async def test_feed_healthy_false_beyond_threshold():
    """feed_healthy() returns False when last tick exceeded stale_threshold."""
    queue: asyncio.Queue[PriceTick] = asyncio.Queue(maxsize=10)
    ws = KrakenWebSocket(["BTC/USD"], queue)
    now = asyncio.get_event_loop().time()
    ws._last_tick_time = now - 60.0  # 60s ago, beyond 30s threshold

    with patch("cryptotrader.exchange.kraken_ws.get_settings") as ms:
        fake = MagicMock()
        fake.websocket.stale_threshold = 30
        ms.return_value = fake
        assert ws.feed_healthy() is False


def _blocking_feed(ws: KrakenWebSocket):
    """Patch connect so every attempt yields a socket whose receive loop never returns."""
    state = {"connects": 0}

    async def fake_wait_for(coro, timeout):
        try:
            coro.close()
        except Exception:
            pass
        if timeout == 3:
            raise TimeoutError
        state["connects"] += 1
        fake_ws = MagicMock()
        fake_ws.send = AsyncMock()
        fake_ws.close = AsyncMock()
        return fake_ws

    async def never_returns(_ws):
        await asyncio.Event().wait()

    patches = (
        patch("cryptotrader.exchange.kraken_ws.asyncio.wait_for", fake_wait_for),
        patch.object(ws, "_receive", never_returns),
    )
    return state, patches


async def _stop(ws: KrakenWebSocket, task: asyncio.Task) -> None:
    """Shut the loop down even if a regression swallows the cancel, so a failure fails fast."""
    ws._running = False
    if ws._receive_task is not None:
        ws._receive_task.cancel()
    task.cancel()
    await asyncio.wait({task}, timeout=2)


async def _until(pred, limit: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + limit
    while not pred():
        assert loop.time() < end, "condition not reached"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_cancelling_the_feed_task_ends_it():
    """A cancel aimed at the feed itself must end it, not trigger a reconnect.

    Swallowing it hung shutdown forever: another task raised,
    asyncio.run cancelled the feed, the feed reconnected, and the process sat
    'active' with no trader and no traceback.
    """
    ws = KrakenWebSocket(["BTC/USD"], asyncio.Queue())
    ws._running = True
    state, (p1, p2) = _blocking_feed(ws)
    with p1, p2:
        task = asyncio.create_task(ws._connect_loop())
        try:
            await _until(lambda: ws._receive_task is not None)
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=2)
        finally:
            await _stop(ws, task)
    assert task in done and task.cancelled()
    assert state["connects"] == 1


@pytest.mark.asyncio
async def test_watchdog_cancel_of_receive_still_reconnects():
    """The watchdog cancels only the receive task; that path must still reconnect."""
    ws = KrakenWebSocket(["BTC/USD"], asyncio.Queue())
    ws._running = True
    state, (p1, p2) = _blocking_feed(ws)
    with p1, p2:
        task = asyncio.create_task(ws._connect_loop())
        await _until(lambda: ws._receive_task is not None)
        ws._receive_task.cancel()
        await _until(lambda: state["connects"] == 2)
        try:
            assert not task.done()
        finally:
            await _stop(ws, task)
    assert task.done()
