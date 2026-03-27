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
        self._capacity = capacity
        self._tokens = capacity
        self._refill_rate = refill_rate  # tokens per second
        self._last_refill = time.monotonic()

    async def acquire(self) -> None:
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
    def __init__(self, api_key: str, api_secret: str) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._bucket = _TokenBucket()
        self._session: aiohttp.ClientSession | None = None

    async def _session_get(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
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
        data["nonce"] = str(int(time.time() * 1000))
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

    async def get_balance(self) -> dict[str, float]:
        result = await self._post("Balance", {})
        return {k: float(v) for k, v in result.items()}
