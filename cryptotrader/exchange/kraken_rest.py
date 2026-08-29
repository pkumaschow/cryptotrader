"""
Kraken REST API client for private operations (order placement, balance).
Implements HMAC-SHA512 authentication per Kraken's spec.
Includes a simple token-bucket rate limiter.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.kraken.com"


class _TokenBucket:
    """Allows `capacity` calls per `refill_rate` seconds."""

    def __init__(self, capacity: float = 15.0, refill_rate: float = 0.33) -> None:
        """Args:
            capacity: Burst size before throttling begins.
            refill_rate: Tokens restored per second.
        """
        self._capacity = capacity
        self._tokens = capacity
        self._refill_rate = refill_rate  # tokens per second
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
        """Wait until a call is permitted, then consume a token.

        Sleeps rather than raising: exceeding Kraken's rate limit earns a
        temporary ban, so slowing down beats failing the order.
        """
        while True:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            wait = (1.0 - self._tokens) / self._refill_rate
            await asyncio.sleep(wait)


class KrakenRest:
    """Authenticated Kraken REST client for orders and balances.

    Signing is HMAC-SHA512 over the nonce and body, per Kraken's spec. Every
    call funnels through `_post`, which is also the single place tests block
    to keep the suite off the live exchange.
    """
    def __init__(self, api_key: str, api_secret: str) -> None:
        """Args:
        api_key: Kraken API key.
        api_secret: Base64 API secret, as issued.
        """
        self._api_key = api_key
        self._api_secret = api_secret
        self._bucket = _TokenBucket()
        self._session: aiohttp.ClientSession | None = None
        self._last_nonce: int = 0

    def _nonce(self) -> int:
        """Return a strictly increasing nonce robust to NTP clock adjustments.

        Uses microsecond precision so the counter stays ahead of the millisecond
        nonces produced before this change.  If the wall clock ever steps backward
        (NTP resync), the in-process high-water mark ensures the value still
        increases, preventing Kraken EAPI:Invalid nonce rejections.
        """
        candidate = int(time.time() * 1_000_000)
        nonce = max(candidate, self._last_nonce + 1)
        self._last_nonce = nonce
        return nonce

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the HTTP session. Safe to call when never opened."""
        if self._session and not self._session.closed:
            await self._session.close()

    def _sign(self, uri_path: str, data: dict[str, Any]) -> str:
        post_data = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + post_data).encode()
        message = uri_path.encode() + hashlib.sha256(encoded).digest()
        mac = hmac.new(base64.b64decode(self._api_secret), message, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    async def _post(self, endpoint: str, data: dict[str, Any]) -> dict[str, Any]:
        await self._bucket.acquire()
        uri_path = f"/0/private/{endpoint}"
        data["nonce"] = str(self._nonce())
        signature = self._sign(uri_path, data)
        headers = {
            "API-Key": self._api_key,
            "API-Sign": signature,
        }
        session = await self._session_get()
        async with session.post(
            f"{_BASE_URL}{uri_path}",
            data=data,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            result: dict[str, Any] = await resp.json()
        if result.get("error"):
            raise RuntimeError(f"Kraken API error: {result['error']}")
        return result.get("result", {})

    async def place_order(self, pair: str, side: str, volume: float) -> str:
        """Place a market order. Returns the transaction ID."""
        result = await self._post("AddOrder", {
            "pair": pair,
            "type": side,
            "ordertype": "market",
            "volume": str(volume),
        })
        txids = result.get("txid", [])
        if not txids:
            raise RuntimeError("Kraken returned no txid for order")
        logger.info("Order placed: %s %s %s txid=%s", side, volume, pair, txids[0])
        return txids[0]

    async def place_post_only_limit(self, pair: str, side: str, volume: float,
                                    price: float, expire_seconds: int) -> str:
        """Rest a maker-only limit order. Returns the transaction ID.

        `oflags=post` is the whole point: without it, a limit that crosses the
        book executes immediately as taker and pays the very fee this exists to
        avoid. Kraken cancels such an order instead of crossing.

        `expiretm` is a relative expiry, so the exchange cancels the order even
        if this process dies while holding it.
        """
        result = await self._post("AddOrder", {
            "pair": pair,
            "type": side,
            "ordertype": "limit",
            "price": f"{price}",
            "volume": str(volume),
            "oflags": "post",
            "expiretm": f"+{int(expire_seconds)}",
        })
        txids = result.get("txid", [])
        if not txids:
            raise RuntimeError("Kraken returned no txid for limit order")
        logger.info("Post-only limit placed: %s %s %s @ %s expire=+%ss txid=%s",
                    side, volume, pair, price, expire_seconds, txids[0])
        return txids[0]

    async def order_status(self, txid: str) -> dict[str, Any]:
        """Raw QueryOrders record: status, vol_exec, price, fee."""
        result = await self._post("QueryOrders", {"txid": txid})
        return result.get(txid, {})

    async def cancel_order(self, txid: str) -> None:
        """Cancel a resting order. An already-closed order is not an error."""
        try:
            await self._post("CancelOrder", {"txid": txid})
            logger.info("Cancelled order txid=%s", txid)
        except Exception:
            logger.warning("Cancel failed for txid=%s (may already be closed)",
                           txid, exc_info=True)

    async def get_balance(self) -> dict[str, float]:
        """Current balances per asset code.

        Note the codes are Kraken's, not tickers: BTC is `XXBT`, ETH is `XETH`,
        USD is `ZUSD`, while newer listings like `SOL` carry no prefix.

        Returns:
        Asset code to amount held.
        """
        result = await self._post("Balance", {})
        return {k: float(v) for k, v in result.items()}
