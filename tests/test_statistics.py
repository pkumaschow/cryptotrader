from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from cryptotrader import statistics
from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, Trade


def insert(db_path: str, pair: str, side: Side, price: float, qty: float = 0.001) -> None:
    database.insert_trade(db_path, Trade(
        pair=pair, side=side, price=price, quantity=qty,
        mode="test", timestamp=datetime.now(timezone.utc)
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
    insert(db_path, "XBTUSD", Side.BUY, 50000)
    insert(db_path, "XBTUSD", Side.SELL, 60000)

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
    insert(db_path, "XBTUSD", Side.BUY, 60000)
    insert(db_path, "XBTUSD", Side.SELL, 50000)

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
    insert(db_path, "XBTUSD", Side.BUY, 50000)
    insert(db_path, "XBTUSD", Side.SELL, 60000)  # win
    insert(db_path, "XBTUSD", Side.BUY, 60000)
    insert(db_path, "XBTUSD", Side.SELL, 55000)  # loss

    with patch("cryptotrader.statistics.get_settings") as ms:
        s = get_settings(test_config_path)
        s.database.path = db_path
        ms.return_value = s
        result = statistics.compute(mode="test")

    assert result.total_trades == 2
    assert result.win_rate == pytest.approx(50.0)
