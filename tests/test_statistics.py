from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from cryptotrader import statistics
from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, Trade


def insert(db_path: str, pair: str, side: Side, price: float, qty: float = 0.001) -> None:
    database.insert_trade(db_path, Trade(
        pair=pair, side=side, price=price, quantity=qty,
        mode="test", timestamp=datetime.now(UTC)
    ))


def test_empty_db_returns_zeros(test_config_path, tmp_path):
    db_path = str(tmp_path / "stats_empty.db")
    database.init_db(db_path)
    with patch("cryptotrader.statistics.get_settings") as ms:
        s = get_settings(test_config_path)
        s.database.path = db_path
        ms.return_value = s
        result = statistics.compute(mode="test")
    assert result.total_trades == 0
    assert result.win_rate == 0.0
    assert result.total_pnl == 0.0


def test_winning_trade(test_config_path, tmp_path):
    db_path = str(tmp_path / "stats_win.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 50000)
    insert(db_path, "BTC/USD", Side.SELL, 60000)

    with patch("cryptotrader.statistics.get_settings") as ms:
        s = get_settings(test_config_path)
        s.database.path = db_path
        ms.return_value = s
        result = statistics.compute(mode="test")

    assert result.total_trades == 1
    assert result.win_rate == 100.0
    assert result.total_pnl == pytest.approx(10.0)  # (60000-50000)*0.001


def test_losing_trade(test_config_path, tmp_path):
    db_path = str(tmp_path / "stats_loss.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 60000)
    insert(db_path, "BTC/USD", Side.SELL, 50000)

    with patch("cryptotrader.statistics.get_settings") as ms:
        s = get_settings(test_config_path)
        s.database.path = db_path
        ms.return_value = s
        result = statistics.compute(mode="test")

    assert result.total_trades == 1
    assert result.win_rate == 0.0
    assert result.total_pnl == pytest.approx(-10.0)


def test_mixed_trades_win_rate(test_config_path, tmp_path):
    db_path = str(tmp_path / "stats_mixed.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 50000)
    insert(db_path, "BTC/USD", Side.SELL, 60000)  # win
    insert(db_path, "BTC/USD", Side.BUY, 60000)
    insert(db_path, "BTC/USD", Side.SELL, 55000)  # loss

    with patch("cryptotrader.statistics.get_settings") as ms:
        s = get_settings(test_config_path)
        s.database.path = db_path
        ms.return_value = s
        result = statistics.compute(mode="test")

    assert result.total_trades == 2
    assert result.win_rate == pytest.approx(50.0)


def test_all_strategies_returns_sorted_unique(test_config_path, tmp_path):
    db_path = str(tmp_path / "stats_strats.db")
    database.init_db(db_path)
    database.insert_trade(db_path, Trade(
        pair="BTC/USD", side=Side.BUY, price=50000, quantity=0.001,
        mode="test", strategy="ema", timestamp=datetime.now(UTC)
    ))
    database.insert_trade(db_path, Trade(
        pair="BTC/USD", side=Side.BUY, price=50000, quantity=0.001,
        mode="test", strategy="bollinger", timestamp=datetime.now(UTC)
    ))
    database.insert_trade(db_path, Trade(
        pair="BTC/USD", side=Side.BUY, price=50000, quantity=0.001,
        mode="test", strategy="ema", timestamp=datetime.now(UTC)
    ))

    with patch("cryptotrader.statistics.get_settings") as ms:
        s = get_settings(test_config_path)
        s.database.path = db_path
        ms.return_value = s
        result = statistics.all_strategies(mode="test")

    assert result == ["bollinger", "ema"]  # sorted, deduplicated


def test_realized_pnl_for_sell_gain(tmp_db):
    insert(tmp_db, "BTC/USD", Side.BUY, 50000)
    pnl = statistics.realized_pnl_for_sell(
        pair="BTC/USD", mode="test", sell_price=60000, sell_quantity=0.001, db_path=tmp_db)
    assert pnl == pytest.approx(10.0)  # (60000-50000)*0.001


def test_realized_pnl_for_sell_loss(tmp_db):
    insert(tmp_db, "BTC/USD", Side.BUY, 60000)
    pnl = statistics.realized_pnl_for_sell(
        pair="BTC/USD", mode="test", sell_price=50000, sell_quantity=0.001, db_path=tmp_db)
    assert pnl == pytest.approx(-10.0)


def test_realized_pnl_for_sell_is_fifo(tmp_db):
    # Two open buys; the sell must close the OLDEST (50000), not the newer (55000).
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    database.insert_trade(tmp_db, Trade(
        pair="BTC/USD", side=Side.BUY, price=50000, quantity=0.001,
        mode="test", timestamp=t0))
    database.insert_trade(tmp_db, Trade(
        pair="BTC/USD", side=Side.BUY, price=55000, quantity=0.001,
        mode="test", timestamp=t0 + timedelta(hours=1)))
    pnl = statistics.realized_pnl_for_sell(
        pair="BTC/USD", mode="test", sell_price=60000, sell_quantity=0.001, db_path=tmp_db)
    assert pnl == pytest.approx(10.0)  # matched against 50000, not 55000


def test_realized_pnl_for_sell_none_when_no_open_buy(tmp_db):
    pnl = statistics.realized_pnl_for_sell(
        pair="BTC/USD", mode="test", sell_price=60000, sell_quantity=0.001, db_path=tmp_db)
    assert pnl is None


# --- open_position_quantity ---------------------------------------------------
# Sizing-bug regression cover: sells must be sized from what is actually held.


def open_qty(db_path: str, pair: str = "BTC/USD") -> float:
    return statistics.open_position_quantity(pair, "test", db_path=db_path)


def test_open_position_quantity_empty_db(tmp_path):
    db_path = str(tmp_path / "openqty_empty.db")
    database.init_db(db_path)
    assert open_qty(db_path) == 0.0


def test_open_position_quantity_tracks_buys_and_sells(tmp_path):
    db_path = str(tmp_path / "openqty_basic.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 50000, qty=0.001)
    assert open_qty(db_path) == pytest.approx(0.001)

    insert(db_path, "BTC/USD", Side.SELL, 60000, qty=0.001)
    assert open_qty(db_path) == 0.0


def test_open_position_quantity_is_pair_scoped(tmp_path):
    db_path = str(tmp_path / "openqty_pairs.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 50000, qty=0.001)
    insert(db_path, "ETH/USD", Side.BUY, 2000, qty=0.03)

    assert open_qty(db_path, "BTC/USD") == pytest.approx(0.001)
    assert open_qty(db_path, "ETH/USD") == pytest.approx(0.03)


def test_open_position_quantity_floors_historical_oversell(tmp_path):
    """An over-sell must not leave a negative that swallows the next buy.

    Reproduces the real BTC tape: a budget-sized buy of 0.000608 closed by a
    config-sized sell of 0.001. The position is flat afterwards, not -0.000392,
    so a later 0.00062 buy reports 0.00062 rather than 0.000228.
    """
    db_path = str(tmp_path / "openqty_oversell.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 82171.9, qty=0.000608)
    insert(db_path, "BTC/USD", Side.SELL, 64451.2, qty=0.001)
    assert open_qty(db_path) == 0.0

    insert(db_path, "BTC/USD", Side.BUY, 80638.8, qty=0.00062)
    assert open_qty(db_path) == pytest.approx(0.00062)


def test_open_position_quantity_rounds_down(tmp_path):
    """Float drift must never ask the exchange to sell more than is held."""
    db_path = str(tmp_path / "openqty_round.db")
    database.init_db(db_path)
    insert(db_path, "BTC/USD", Side.BUY, 50000, qty=0.1)
    insert(db_path, "BTC/USD", Side.BUY, 50000, qty=0.2)
    qty = open_qty(db_path)
    assert qty <= 0.3
    assert qty == pytest.approx(0.3, abs=1e-8)
