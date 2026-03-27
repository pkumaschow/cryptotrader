from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from cryptotrader.models import Side, Trade


def init_db(path: str, read_only: bool = False) -> None:
    if read_only:
        return  # WAL mode allows readers without any setup
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
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
        conn.commit()


@contextmanager
def _connect(path: str, read_only: bool = False) -> Generator[sqlite3.Connection, None, None]:
    uri = f"file:{path}{'?mode=ro' if read_only else ''}{'&' if read_only else '?'}cache=shared"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if not read_only:
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
    read_only: bool = False,
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
    with _connect(path, read_only=read_only) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        Trade(
            id=row["id"], pair=row["pair"], side=Side(row["side"]),
            price=row["price"], quantity=row["quantity"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            mode=row["mode"],
            strategy=row["strategy"] if "strategy" in row.keys() else "unknown",
            pnl=row["pnl"], txid=row["txid"],
        )
        for row in rows
    ]
