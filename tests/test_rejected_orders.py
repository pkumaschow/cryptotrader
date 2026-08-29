"""Refused orders must be recorded, not just logged.

The 2026-08-20 declined buy existed only as a journald line, so the unbacked
sell it caused two days later went unnoticed for weeks. These tests pin the
behaviour that makes that visible.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.executor import TradeExecutor
from cryptotrader.models import RejectedOrder, RejectReason, Side, Signal, Trade


class _FakeRest:
    def __init__(self, balance: float) -> None:
        self._balance = balance
        self.orders: list[tuple] = []

    async def get_balance(self) -> dict[str, float]:
        return {"ZUSD": self._balance}

    async def place_order(self, pair: str, side: str, qty: float) -> str:
        self.orders.append((pair, side, qty))
        return "TXFAKE-00001"


@pytest.fixture
def prod_db(tmp_path, monkeypatch):
    """A production-mode settings object pointed at a scratch DB."""
    db = tmp_path / "t.db"
    database.init_db(str(db))
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings.mode, "active", "production")
    monkeypatch.setattr(settings.database, "path", str(db))
    yield str(db)
    get_settings.cache_clear()


def test_rejected_order_roundtrips_through_the_db(prod_db):
    order = RejectedOrder(
        pair="BTC/USD", side=Side.BUY, price=68_539.70, quantity=0.00072952,
        reason=RejectReason.INSUFFICIENT_BALANCE,
        detail="need $50.00, have $12.00", mode="production", strategy="bollinger",
        timestamp=datetime(2026, 8, 19, 16, 0, tzinfo=UTC),
    )
    database.insert_rejected_order(prod_db, order)

    got = database.query_rejected_orders(prod_db)
    assert len(got) == 1
    assert got[0].pair == "BTC/USD"
    assert got[0].side is Side.BUY
    assert got[0].reason is RejectReason.INSUFFICIENT_BALANCE
    assert got[0].detail == "need $50.00, have $12.00"
    assert got[0].quantity == pytest.approx(0.00072952)


def test_query_filters_by_mode_and_time(prod_db):
    base = datetime(2026, 8, 19, 16, 0, tzinfo=UTC)
    for i, mode in enumerate(("production", "test", "production")):
        database.insert_rejected_order(prod_db, RejectedOrder(
            pair="BTC/USD", side=Side.BUY, price=1.0, quantity=1.0,
            reason=RejectReason.DAILY_LOSS_LIMIT, mode=mode,
            timestamp=base + timedelta(hours=i),
        ))
    assert len(database.query_rejected_orders(prod_db, mode="production")) == 2
    assert len(database.query_rejected_orders(prod_db, mode="test")) == 1
    assert len(database.query_rejected_orders(
        prod_db, since=base + timedelta(hours=1))) == 2


def test_insufficient_balance_records_a_rejection(prod_db):
    """The exact 2026-08-20 scenario: buy declined for want of cash."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    ex = TradeExecutor(tui_queue=queue)
    ex.set_rest_client(_FakeRest(balance=12.00))

    result = asyncio.run(
        ex.execute(Signal.BUY, "BTC/USD", 68_539.70, strategy="bollinger"))

    assert result is None, "declined buy must not produce a Trade"

    rows = database.query_rejected_orders(prod_db)
    assert len(rows) == 1
    assert rows[0].reason is RejectReason.INSUFFICIENT_BALANCE
    assert rows[0].side is Side.BUY
    assert "12.00" in rows[0].detail

    queued = queue.get_nowait()
    assert isinstance(queued, RejectedOrder)
    assert queued.reason is RejectReason.INSUFFICIENT_BALANCE


def test_sell_with_no_open_position_records_a_rejection(prod_db):
    """The unbacked-sell guard must leave a trace, not fail silently."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    ex = TradeExecutor(tui_queue=queue)
    ex.set_rest_client(_FakeRest(balance=10_000.0))

    result = asyncio.run(
        ex.execute(Signal.SELL, "BTC/USD", 77_372.10, strategy="bollinger"))

    assert result is None
    rows = database.query_rejected_orders(prod_db)
    assert len(rows) == 1
    assert rows[0].reason is RejectReason.NO_OPEN_POSITION
    assert rows[0].side is Side.SELL
    assert isinstance(queue.get_nowait(), RejectedOrder)


def test_successful_buy_records_no_rejection(prod_db):
    queue: asyncio.Queue = asyncio.Queue(maxsize=10)
    ex = TradeExecutor(tui_queue=queue)
    ex.set_rest_client(_FakeRest(balance=10_000.0))

    result = asyncio.run(
        ex.execute(Signal.BUY, "BTC/USD", 80_638.80, strategy="bollinger"))

    assert isinstance(result, Trade)
    assert database.query_rejected_orders(prod_db) == []


def test_rejection_is_rendered_distinctly_from_a_trade():
    from cryptotrader.tui.trade_log_panel import _render_item

    order = RejectedOrder(
        pair="BTC/USD", side=Side.BUY, price=68_539.70, quantity=0.00072952,
        reason=RejectReason.INSUFFICIENT_BALANCE,
        detail="need $50.00, have $12.00", mode="production", strategy="bollinger",
        timestamp=datetime(2026, 8, 19, 16, 0, tzinfo=UTC),
    )
    rendered = _render_item(order, use_utc=True)

    assert "NO FUNDS" in rendered
    assert "strike" in rendered, "refused orders must be struck through"
    assert "BTC/USD" in rendered
    assert "have $12.00" in rendered

    filled = Trade(pair="BTC/USD", side=Side.BUY, price=80_638.80,
                   quantity=0.00062, mode="production", strategy="bollinger",
                   timestamp=datetime(2026, 8, 25, 3, 0, tzinfo=UTC))
    assert "NO FUNDS" not in _render_item(filled, use_utc=True)


def test_every_reject_reason_has_a_tag():
    """A new RejectReason must not fall through to an unlabelled row."""
    from cryptotrader.tui.trade_log_panel import _REJECT_TAGS

    missing = [r for r in RejectReason if r not in _REJECT_TAGS]
    assert not missing, f"RejectReason without a TUI tag: {missing}"
