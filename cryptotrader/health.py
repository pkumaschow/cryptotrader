"""
Lightweight HTTP health-check server.

GET /health — JSON with deployment timestamp, uptime, DB status, Kraken API status.
Returns 200 if all checks pass, 503 if any check fails.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)

_start_time = time.monotonic()


def _deployed_at() -> str:
    try:
        import cryptotrader
        ts = os.path.getmtime(cryptotrader.__file__)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return "unknown"


def _check_database(db_path: str) -> dict:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3)
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _check_kraken() -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.kraken.com/0/public/SystemStatus",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                kraken_status = data.get("result", {}).get("status", "unknown")
                return {"status": "ok", "kraken_status": kraken_status}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


async def _handle_health(request: web.Request) -> web.Response:
    from cryptotrader.config import get_settings
    settings = get_settings()

    db_result, kraken_result = await asyncio.gather(
        asyncio.to_thread(_check_database, settings.database.path),
        _check_kraken(),
    )

    all_ok = db_result["status"] == "ok" and kraken_result["status"] == "ok"
    body = {
        "status": "ok" if all_ok else "degraded",
        "deployed_at": _deployed_at(),
        "uptime_seconds": int(time.monotonic() - _start_time),
        "mode": settings.mode.active,
        "checks": {
            "database": db_result,
            "kraken_api": kraken_result,
        },
    }
    return web.Response(
        text=json.dumps(body, indent=2),
        content_type="application/json",
        status=200 if all_ok else 503,
    )


async def run(port: int = 8080) -> None:
    app = web.Application()
    app.router.add_get("/health", _handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info("Health check server listening on :%d/health", port)
    try:
        await asyncio.get_event_loop().create_future()
    finally:
        await runner.cleanup()
