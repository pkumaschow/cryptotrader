from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional

import duckdb

from cryptotrader.models import Side, Trade


def _to_utc_naive(dt: datetime) -> datetime:
    """Strip timezone from a UTC-aware datetime for DuckDB TIMESTAMP storage."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _from_naive(dt: datetime) -> datetime:
    """Re-attach UTC timezone when reading a naive datetime back from DuckDB."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

_lock = threading.Lock()
_conn: Optional[duckdb.DuckDBPyConnection] = None
_read_only: bool = False


def init_db(path: str, read_only: bool = False) -> None:
    global _conn, _read_only
    _read_only = read_only
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = duckdb.connect(path, read_only=read_only)
        if not read_only:
            _conn.execute("CREATE SEQUENCE IF NOT EXISTS trades_id_seq START 1")
            _conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id        BIGINT      PRIMARY KEY DEFAULT nextval('trades_id_seq'),
                    pair      VARCHAR     NOT NULL,
                    side      VARCHAR     NOT NULL,
                    price     DOUBLE      NOT NULL,
                    quantity  DOUBLE      NOT NULL,
                    timestamp TIMESTAMP   NOT NULL,
                    mode      VARCHAR     NOT NULL,
                    strategy  VARCHAR     NOT NULL DEFAULT 'unknown',
                    pnl       DOUBLE,
                    txid      VARCHAR
                )
            """)


def insert_trade(path: str, trade: Trade) -> int:
    assert _conn is not None, "Database not initialised — call init_db first"
    if _read_only:
        return -1
    with _lock:
        row = _conn.execute(
            """
            INSERT INTO trades (pair, side, price, quantity, timestamp, mode, strategy, pnl, txid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            [trade.pair, trade.side.value, trade.price, trade.quantity,
             _to_utc_naive(trade.timestamp), trade.mode, trade.strategy, trade.pnl, trade.txid],
        ).fetchone()
    return row[0]  # type: ignore[index]


def query_trades(
    path: str,
    pair: Optional[str] = None,
    mode: Optional[str] = None,
    strategy: Optional[str] = None,
    since: Optional[datetime] = None,
) -> list[Trade]:
    assert _conn is not None, "Database not initialised — call init_db first"
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
        params.append(since)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = (
        "SELECT id, pair, side, price, quantity, timestamp, mode, strategy, pnl, txid "
        f"FROM trades {where} ORDER BY timestamp ASC"
    )
    with _lock:
        rows = _conn.execute(sql, params).fetchall()
    return [
        Trade(
            id=row[0], pair=row[1], side=Side(row[2]),
            price=row[3], quantity=row[4],
            timestamp=_from_naive(row[5] if isinstance(row[5], datetime) else datetime.fromisoformat(str(row[5]))),
            mode=row[6], strategy=row[7] or "unknown",
            pnl=row[8], txid=row[9],
        )
        for row in rows
    ]
