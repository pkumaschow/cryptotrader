"""Tests for the health check server caching behaviour."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

import cryptotrader.health as health_module


@pytest.fixture(autouse=True)
def reset_health_cache():
    """Reset module-level health cache between tests."""
    health_module._cached_result = None
    health_module._cached_at = 0.0
    yield
    health_module._cached_result = None
    health_module._cached_at = 0.0


@pytest.fixture
def mock_checks():
    db_ok = {"status": "ok"}
    kraken_ok = {"status": "ok", "kraken_status": "online"}
    return db_ok, kraken_ok


async def _make_app():
    from aiohttp import web

    app = web.Application()
    app.router.add_get("/health", health_module._handle_health)
    return app


async def test_cache_miss_makes_live_calls(test_config_path, mock_checks, monkeypatch):
    """First request triggers live DB and Kraken checks."""
    monkeypatch.setenv("CRYPTOTRADER_CONFIG", test_config_path)
    db_ok, kraken_ok = mock_checks

    kraken_patch = patch(
        "cryptotrader.health._check_kraken", new_callable=AsyncMock, return_value=kraken_ok
    )
    with (
        patch("cryptotrader.health._check_database", return_value=db_ok) as mock_db,
        kraken_patch as mock_kraken,
    ):
        app = await _make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            data = await resp.json()

    assert mock_db.call_count == 1
    assert mock_kraken.call_count == 1
    assert data["checks"]["database"] == db_ok
    assert data["checks"]["kraken_api"] == kraken_ok
    assert "uptime_seconds" in data


async def test_cache_hit_skips_live_calls(test_config_path, mock_checks, monkeypatch):
    """Second request within TTL uses cached result — no live calls."""
    monkeypatch.setenv("CRYPTOTRADER_CONFIG", test_config_path)
    db_ok, kraken_ok = mock_checks

    kraken_patch = patch(
        "cryptotrader.health._check_kraken", new_callable=AsyncMock, return_value=kraken_ok
    )
    with (
        patch("cryptotrader.health._check_database", return_value=db_ok) as mock_db,
        kraken_patch as mock_kraken,
    ):
        app = await _make_app()
        async with TestClient(TestServer(app)) as client:
            await client.get("/health")
            resp2 = await client.get("/health")
            assert resp2.status == 200
            data = await resp2.json()

    assert mock_db.call_count == 1, "DB should only be called once within TTL"
    assert mock_kraken.call_count == 1, "Kraken should only be called once within TTL"
    assert data["checks"]["database"] == db_ok
    assert data["checks"]["kraken_api"] == kraken_ok


async def test_cache_expired_makes_new_calls(test_config_path, mock_checks, monkeypatch):
    """After TTL expires, next request triggers fresh live calls."""
    monkeypatch.setenv("CRYPTOTRADER_CONFIG", test_config_path)
    db_ok, kraken_ok = mock_checks

    # Pre-seed an expired cache entry
    health_module._cached_result = {"database": db_ok, "kraken_api": kraken_ok}
    health_module._cached_at = 0.0  # epoch — always expired

    kraken_patch = patch(
        "cryptotrader.health._check_kraken", new_callable=AsyncMock, return_value=kraken_ok
    )
    with (
        patch("cryptotrader.health._check_database", return_value=db_ok) as mock_db,
        kraken_patch as mock_kraken,
    ):
        app = await _make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200

    assert mock_db.call_count == 1, "Expired cache must trigger a fresh DB call"
    assert mock_kraken.call_count == 1, "Expired cache must trigger a fresh Kraken call"


async def test_uptime_seconds_is_live(test_config_path, mock_checks, monkeypatch):
    """uptime_seconds reflects current time, not cached value."""
    monkeypatch.setenv("CRYPTOTRADER_CONFIG", test_config_path)
    db_ok, kraken_ok = mock_checks

    with (
        patch("cryptotrader.health._check_database", return_value=db_ok),
        patch("cryptotrader.health._check_kraken", new_callable=AsyncMock, return_value=kraken_ok),
    ):
        app = await _make_app()
        async with TestClient(TestServer(app)) as client:
            resp1 = await client.get("/health")
            d1 = await resp1.json()
            resp2 = await client.get("/health")
            d2 = await resp2.json()

    # Both responses should report uptime (non-negative); second >= first
    assert d1["uptime_seconds"] >= 0
    assert d2["uptime_seconds"] >= d1["uptime_seconds"]


async def test_degraded_status_on_check_failure(test_config_path, monkeypatch):
    """503 returned when any check reports error."""
    monkeypatch.setenv("CRYPTOTRADER_CONFIG", test_config_path)

    db_err = {"status": "error", "detail": "connection refused"}
    kraken_ok = {"status": "ok", "kraken_status": "online"}

    with (
        patch("cryptotrader.health._check_database", return_value=db_err),
        patch("cryptotrader.health._check_kraken", new_callable=AsyncMock, return_value=kraken_ok),
    ):
        app = await _make_app()
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 503
            data = await resp.json()

    assert data["status"] == "degraded"
    assert data["checks"]["database"]["status"] == "error"
