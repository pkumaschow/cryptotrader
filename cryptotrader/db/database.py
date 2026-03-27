from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from cryptotrader.models import Side, Trade


def init_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                pair      TEXT    NOT NULL,
                side      TEXT    NOT NULL,
                price     REAL    NOT NULL,
                quantity  REAL    NOT NULL,
                timestamp TEXT    NOT NULL,
                mode      TEXT    NOT NULL,
                strategy  TEXT    NOT NULL DEFAULT 'unknown',
                pnl       REAL,
                txid      TEXT
            )
        """)
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN strategy TEXT NOT NULL DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass
        conn.commit()


@contextmanager
def _connect(path: str) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_trade(path: str, trade: Trade) -> int:
    with _connect(path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO trades (pair, side, price, quantity, timestamp, mode, strategy, pnl, txid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (trade.pair, trade.side.value, trade.price, trade.quantity,
             trade.timestamp.isoformat(), trade.mode, trade.strategy, trade.pnl, trade.txid),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def query_trades(
    path: str,
    pair: Optional[str] = None,
    mode: Optional[str] = None,
    strategy: Optional[str] = None,
    since: Optional[datetime] = None,
) -> list[Trade]:
    conditions: list[str] = []
    params: list[object] = []
    if pair:
        conditions.append("pair = ?")
        params.append(pair)
    if mode:
        conditions.append("mode = ?")
        params.append(mode)
    if strategy:
        conditions.append("strategy = ?")
        params.append(strategy)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM trades {where} ORDER BY timestamp ASC"
    with _connect(path) as conn:
        rows = conn.execute(sql, params).fetchall()
    trades: list[Trade] = []
    for row in rows:
        trades.append(Trade(
            id=row["id"], pair=row["pair"], side=Side(row["side"]),
            price=row["price"], quantity=row["quantity"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            mode=row["mode"],
            strategy=row["strategy"] if "strategy" in row.keys() else "unknown",
            pnl=row["pnl"], txid=row["txid"],
        ))
    return trades
