"""Post-only maker entries: fills, no-fills, and the guarantees around them.

The point of this feature is a fee cut (Kraken taker 0.80% vs maker 0.40%), but
the risk is a signal that never fills. These tests pin the three things that
must hold regardless: exits are never made maker, a no-fill leaves the strategy
flat, and production is unaffected while the config flag is off.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.executor import TradeExecutor
from cryptotrader.maker import MakerBook, RestingEntry
from cryptotrader.models import PriceTick, RejectReason, Side, Signal


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "m.db"
    database.init_db(str(path))
    return str(path)


@pytest.fixture
def settings(db, monkeypatch):
    get_settings.cache_clear()
    s = get_settings()
    # Pin the mode explicitly. The default config is production, and leaving it
    # would send these tests at the live Kraken API.
    monkeypatch.setattr(s.mode, "active", "test")
    monkeypatch.setattr(s.database, "path", db)
    monkeypatch.setattr(s.execution, "maker_entries", True)
    monkeypatch.setattr(s.execution, "maker_wait_seconds", 300)
    monkeypatch.setattr(s.execution, "maker_max_drift_pct", 0.5)
    yield s
    get_settings.cache_clear()


def _entry(db, **kw):
    base = dict(
        pair="BTC/USD", limit_price=80_000.0, quantity=0.000625,
        strategy="bollinger", mode="test",
        deadline=datetime.now(UTC) + timedelta(seconds=300),
        max_drift_pct=0.5,
    )
    base.update(kw)
    return RestingEntry(**base)


def _tick(price, pair="BTC/USD"):
    return PriceTick(pair=pair, bid=price, ask=price, last=price,
                     timestamp=datetime.now(UTC))


# --- resolution ---------------------------------------------------------


def test_price_reaching_the_limit_fills(db, settings):
    book = MakerBook(db)
    book.add(_entry(db))

    filled = book.on_tick(_tick(79_999.0))

    assert len(filled) == 1
    assert filled[0].price == 80_000.0, "fills at the limit, not the tick price"
    assert filled[0].side is Side.BUY
    assert not book.is_resting("BTC/USD", "bollinger")
    assert len(database.query_trades(db)) == 1
    assert database.query_rejected_orders(db) == []


def test_price_running_away_cancels_and_skips(db, settings):
    rolled_back = []
    book = MakerBook(db)
    book.add(_entry(db, on_reject=lambda: rolled_back.append(True)))

    book.on_tick(_tick(80_000 * 1.006))  # 0.6% above, cap is 0.5%

    assert not book.is_resting("BTC/USD", "bollinger")
    assert database.query_trades(db) == [], "no trade on a skipped signal"
    rejects = database.query_rejected_orders(db)
    assert len(rejects) == 1
    assert rejects[0].reason is RejectReason.MAKER_NO_FILL
    assert "ran 0.60%" in rejects[0].detail
    assert rolled_back == [True], "strategy must be rolled back on a no-fill"


def test_deadline_expiry_cancels_and_skips(db, settings):
    rolled_back = []
    book = MakerBook(db)
    book.add(_entry(db, deadline=datetime.now(UTC) - timedelta(seconds=1),
                    on_reject=lambda: rolled_back.append(True)))

    book.expire_due()

    assert not book.is_resting("BTC/USD", "bollinger")
    rejects = database.query_rejected_orders(db)
    assert len(rejects) == 1 and rejects[0].reason is RejectReason.MAKER_NO_FILL
    assert rolled_back == [True]


def test_expiry_fires_even_when_the_pair_stops_ticking(db, settings):
    """A silent feed is when a fill is least likely, so it must still resolve."""
    book = MakerBook(db)
    book.add(_entry(db, deadline=datetime.now(UTC) - timedelta(seconds=1)))

    book.on_tick(_tick(100.0, pair="SOL/USD"))   # unrelated pair only
    assert book.is_resting("BTC/USD", "bollinger"), "on_tick must not resolve other pairs"

    book.expire_due()
    assert not book.is_resting("BTC/USD", "bollinger")


def test_fill_beats_drift_on_the_same_tick(db, settings):
    """If price traded at the limit the order executed, whatever else it did."""
    book = MakerBook(db)
    book.add(_entry(db))
    filled = book.on_tick(_tick(79_000.0))
    assert len(filled) == 1


def test_each_strategy_rests_independently(db, settings):
    """Test mode runs four strategies per pair; one must not evict another."""
    book = MakerBook(db)
    book.add(_entry(db, strategy="bollinger"))
    book.add(_entry(db, strategy="ema", limit_price=79_500.0))

    assert book.is_resting("BTC/USD", "bollinger")
    assert book.is_resting("BTC/USD", "ema")

    filled = book.on_tick(_tick(79_400.0))
    assert len(filled) == 2, "one tick can resolve every strategy on the pair"


def test_duplicate_entry_is_refused_and_rolled_back(db, settings):
    """Refusing without rolling back would strand the caller believing it is long."""
    rolled_back = []
    book = MakerBook(db)
    book.add(_entry(db))
    book.add(_entry(db, on_reject=lambda: rolled_back.append(True)))

    assert len(book.resting) == 1
    assert rolled_back == [True]


# --- executor integration ----------------------------------------------


def test_entry_rests_instead_of_trading(db, settings):
    book = MakerBook(db)
    ex = TradeExecutor(maker_book=book)

    result = asyncio.run(ex.execute(Signal.BUY, "BTC/USD", 80_000.0,
                                    strategy="bollinger"))

    assert result is None, "no trade exists yet while the entry rests"
    assert book.is_resting("BTC/USD", "bollinger")
    assert database.query_trades(db) == []


def test_exits_are_never_made_maker(db, settings):
    """The core safety property: an unfilled sell would mean bag-holding."""
    book = MakerBook(db)
    ex = TradeExecutor(maker_book=book)

    # A sell needs something to sell, so seed a filled entry first.
    book.add(_entry(db))
    book.on_tick(_tick(79_999.0))
    assert len(database.query_trades(db)) == 1

    result = asyncio.run(ex.execute(Signal.SELL, "BTC/USD", 85_000.0,
                                    strategy="bollinger"))

    assert result is not None, "sell must execute immediately, not rest"
    assert result.side is Side.SELL
    assert not book.is_resting("BTC/USD", "bollinger")


def test_disabled_config_leaves_the_market_path_untouched(db, monkeypatch):
    """Production has no [execution] block, so it must behave exactly as before."""
    get_settings.cache_clear()
    s = get_settings()
    monkeypatch.setattr(s.mode, "active", "test")
    monkeypatch.setattr(s.database, "path", db)
    assert s.execution.maker_entries is False, "must default off"

    book = MakerBook(db)
    ex = TradeExecutor(maker_book=book)
    result = asyncio.run(ex.execute(Signal.BUY, "BTC/USD", 80_000.0,
                                    strategy="bollinger"))

    assert result is not None, "flag off must place a trade immediately"
    assert not book.is_resting("BTC/USD", "bollinger")
    get_settings.cache_clear()


def test_production_config_does_not_enable_maker_entries():
    """Guards the deployment split: staging opts in, production does not."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    prod = tomllib.loads((root / "config" / "settings.toml").read_text())
    staging = tomllib.loads((root / "config" / "settings-staging.toml").read_text())

    assert prod.get("execution", {}).get("maker_entries", False) is False
    assert staging.get("execution", {}).get("maker_entries") is True


def test_production_resolves_fills_against_the_exchange(db, monkeypatch):
    """Production must never infer a fill from the tick stream.

    A tick touching the limit does not mean *this* order executed — queue
    position decides that. So the book gets a REST client and asks, and the
    tick-driven path is disabled (issue #30).
    """
    import asyncio as _asyncio

    from cryptotrader.trader import Trader

    get_settings.cache_clear()
    st = get_settings()
    monkeypatch.setattr(st.mode, "active", "production")
    monkeypatch.setattr(st.database, "path", db)
    monkeypatch.setattr(st.execution, "maker_entries", True)

    trader = Trader(_asyncio.Queue())

    assert trader._maker_book is not None, "production should run maker entries now"
    assert trader._maker_book._rest is not None, "must be able to ask the exchange"
    assert trader._production is True, "tick-driven resolution must be off"
    get_settings.cache_clear()


def test_test_mode_has_no_rest_client(db, settings):
    """Paper trading must not be wired to the exchange at all."""
    import asyncio as _asyncio

    from cryptotrader.trader import Trader

    trader = Trader(_asyncio.Queue())
    assert trader._maker_book is not None
    assert trader._maker_book._rest is None, "test mode must not hold an exchange client"
    assert trader._production is False


# --- exchange reconciliation (#30) --------------------------------------

class _FakeExchange:
    """Stands in for KrakenRest. `record` is what QueryOrders returns."""

    def __init__(self, record: dict | None = None, raises: bool = False) -> None:
        self._record = record or {}
        self._raises = raises
        self.cancelled: list[str] = []
        self.queries = 0

    async def order_status(self, txid: str) -> dict:
        self.queries += 1
        if self._raises:
            raise RuntimeError("network down")
        return self._record

    async def cancel_order(self, txid: str) -> None:
        self.cancelled.append(txid)


def _resting(db, **kw):
    e = _entry(db, mode="production", **kw)
    e.txid = "OTEST-1"
    return e


def test_closed_order_records_a_fill(db, settings):
    ex = _FakeExchange({"status": "closed", "vol_exec": 0.000625, "price": 79_950.0})
    book = MakerBook(db, rest_client=ex)
    book.add(_resting(db))

    filled = asyncio.run(book.reconcile())

    assert len(filled) == 1
    assert filled[0].price == pytest.approx(79_950.0), "records the executed price"
    assert filled[0].quantity == pytest.approx(0.000625)
    assert not book.is_resting("BTC/USD", "bollinger")


def test_partial_fill_records_only_what_executed(db, settings):
    """Recording the requested volume is the defect that over-sold before.

    A later sell is sized from the trade log, so logging 0.000625 when only
    0.0002 executed would dispose of coin the account never received.
    """
    ex = _FakeExchange({"status": "canceled", "vol_exec": 0.0002, "price": 80_000.0})
    book = MakerBook(db, rest_client=ex)
    book.add(_resting(db, quantity=0.000625))

    filled = asyncio.run(book.reconcile())

    assert len(filled) == 1
    assert filled[0].quantity == pytest.approx(0.0002), "must log the executed volume"
    assert database.query_trades(db)[0].quantity == pytest.approx(0.0002)


def test_cancelled_with_nothing_executed_is_a_no_fill(db, settings):
    rolled_back = []
    ex = _FakeExchange({"status": "canceled", "vol_exec": 0})
    book = MakerBook(db, rest_client=ex)
    book.add(_resting(db, on_reject=lambda: rolled_back.append(True)))

    filled = asyncio.run(book.reconcile())

    assert filled == []
    assert database.query_trades(db) == []
    rejects = database.query_rejected_orders(db)
    assert len(rejects) == 1 and rejects[0].reason is RejectReason.MAKER_NO_FILL
    assert rolled_back == [True]


def test_still_open_order_keeps_resting(db, settings):
    ex = _FakeExchange({"status": "open", "vol_exec": 0})
    book = MakerBook(db, rest_client=ex)
    book.add(_resting(db))

    assert asyncio.run(book.reconcile()) == []
    assert book.is_resting("BTC/USD", "bollinger"), "an open order must not be resolved"
    assert database.query_trades(db) == []
    assert database.query_rejected_orders(db) == []


def test_open_past_its_deadline_is_cancelled_explicitly(db, settings):
    """expiretm should have done it, but a clock skew must not leave it working."""
    ex = _FakeExchange({"status": "open", "vol_exec": 0})
    book = MakerBook(db, rest_client=ex)
    book.add(_resting(db, deadline=datetime.now(UTC) - timedelta(seconds=1)))

    asyncio.run(book.reconcile())

    assert ex.cancelled == ["OTEST-1"], "must cancel at the exchange, not just locally"
    assert not book.is_resting("BTC/USD", "bollinger")
    assert database.query_rejected_orders(db)[0].reason is RejectReason.MAKER_NO_FILL


def test_query_failure_leaves_the_entry_resting(db, settings):
    """A network error is not evidence either way.

    Treating it as a fill invents a position; treating it as a no-fill discards
    a real one. The only safe response is to retry.
    """
    ex = _FakeExchange(raises=True)
    book = MakerBook(db, rest_client=ex)
    book.add(_resting(db))

    assert asyncio.run(book.reconcile()) == []
    assert book.is_resting("BTC/USD", "bollinger"), "must retry, not guess"
    assert database.query_trades(db) == []
    assert database.query_rejected_orders(db) == []


def test_reconcile_without_a_client_does_nothing(db, settings):
    """Test mode holds no exchange client and resolves from ticks instead."""
    book = MakerBook(db)
    book.add(_resting(db))
    assert asyncio.run(book.reconcile()) == []
    assert book.is_resting("BTC/USD", "bollinger")
