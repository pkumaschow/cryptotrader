"""The test suite must never reach the real exchange.

`config/settings.toml` carries `active = "production"`, so a test that touches
`get_settings()` without pinning the mode takes the production path and
`TradeExecutor` attempts a real balance check. That happened during development
of the maker-entry work and failed only because this machine has no credentials.
The Pi has them, with a production config and `tests/` deployed beside them.

These tests assert the guard in conftest is actually load-bearing, so it cannot
be quietly removed or bypassed.
"""

from __future__ import annotations

import asyncio

import pytest

from cryptotrader.config import get_settings
from cryptotrader.exchange.kraken_rest import KrakenRest


def _client() -> KrakenRest:
    return KrakenRest("k", "dGVzdF9zZWNyZXQ=")


def test_balance_call_is_refused():
    with pytest.raises(AssertionError, match="live Kraken API call"):
        asyncio.run(_client().get_balance())


def test_order_placement_is_refused():
    """The one that would actually cost money."""
    with pytest.raises(AssertionError, match="live Kraken API call"):
        asyncio.run(_client().place_order("BTC/USD", "buy", 0.001))


def test_post_only_limit_is_refused():
    with pytest.raises(AssertionError, match="live Kraken API call"):
        asyncio.run(_client().place_post_only_limit("BTC/USD", "buy", 0.001, 80000.0, 300))


def test_refusal_names_the_endpoint_and_the_way_out():
    """A blocked call must explain itself, or the next person just deletes it."""
    with pytest.raises(AssertionError) as exc:
        asyncio.run(_client().get_balance())

    message = str(exc.value)
    assert "Balance" in message, "must name the endpoint that was attempted"
    assert "set_rest_client" in message, "must point at the supported alternative"
    assert "exchange_http" in message, "must mention the opt-out marker"


def test_the_production_default_that_makes_this_necessary():
    """Documents the root cause: the default config is production mode.

    If this ever becomes 'test', the guard stops being load-bearing and this
    test should be revisited rather than silently passing for a new reason.
    """
    assert get_settings().mode.active == "production"


def test_executor_cannot_place_an_order_through_the_guard(tmp_path, monkeypatch):
    """The exact 2026-08-27 incident, reproduced.

    A production-mode `execute()` with no injected client used to escape to the
    live API. It cannot now: the balance check is refused, so the order is
    declined and nothing is placed.

    Note the guard's AssertionError does not propagate — `_check_balance` wraps
    everything in `except Exception` and degrades, which is deliberate (a
    balance-check failure must not kill the trading loop). The property that
    matters is not that it raises, but that **no order reaches the exchange**.
    """
    from cryptotrader.db import database
    from cryptotrader.executor import TradeExecutor
    from cryptotrader.models import RejectReason, Signal

    db = tmp_path / "guard.db"
    database.init_db(str(db))
    settings = get_settings()
    assert settings.mode.active == "production", "precondition for this test"
    monkeypatch.setattr(settings.database, "path", str(db))

    result = asyncio.run(TradeExecutor().execute(Signal.BUY, "BTC/USD", 80_000.0,
                                                 strategy="bollinger"))

    assert result is None, "no trade may be produced when the exchange is unreachable"
    rejects = database.query_rejected_orders(str(db))
    assert len(rejects) == 1
    assert rejects[0].reason is RejectReason.BALANCE_CHECK_FAILED
    assert "live Kraken API call" in rejects[0].detail, (
        "the recorded reason should carry the guard's message, so a blocked call "
        "is traceable rather than looking like a real exchange outage"
    )
