from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Generator, Optional

from cryptotrader.models import Candle, Deposit, Side, Trade


def init_db(path: str, read_only: bool = False) -> None:
    if read_only:
        return  # WAL mode allows readers without any setup
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                pair       TEXT    NOT NULL,
                timeframe  INTEGER NOT NULL,
                open       REAL    NOT NULL,
                high       REAL    NOT NULL,
                low        REAL    NOT NULL,
                close      REAL    NOT NULL,
                tick_count INTEGER NOT NULL,
                timestamp  TEXT    NOT NULL,
                UNIQUE(pair, timeframe, timestamp)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                aud_amount REAL    NOT NULL,
                usd_amount REAL    NOT NULL,
                fee_usd    REAL    NOT NULL DEFAULT 0.0,
                timestamp  TEXT    NOT NULL,
                notes      TEXT,
                rate_mid   REAL
            )
        """)
        try:
            conn.execute("ALTER TABLE deposits ADD COLUMN rate_mid REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                pair       TEXT    NOT NULL,
                side       TEXT    NOT NULL,
                price      REAL    NOT NULL,
                quantity   REAL    NOT NULL,
                timestamp  TEXT    NOT NULL,
                mode       TEXT    NOT NULL,
                strategy   TEXT    NOT NULL DEFAULT 'unknown',
                pnl        REAL,
                txid       TEXT,
                band_width REAL
            )
        """)
        # Migration: add band_width to existing databases
        try:
            conn.execute("ALTER TABLE trades ADD COLUMN band_width REAL")
        except sqlite3.OperationalError:
            pass  # column already exists
        # Migration: unique guard against concurrent-instance duplicate trades
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_trades_unique "
                "ON trades (pair, strategy, timestamp, side)"
            )
        except sqlite3.IntegrityError:
            pass  # existing duplicate rows — index skipped, file lock is primary guard
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
    try:
        with _connect(path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO trades (pair, side, price, quantity, timestamp, mode, strategy, pnl, txid, band_width)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (trade.pair, trade.side.value, trade.price, trade.quantity,
                 trade.timestamp.isoformat(), trade.mode, trade.strategy, trade.pnl, trade.txid,
                 trade.band_width),
            )
            return cursor.lastrowid  # type: ignore[return-value]
    except sqlite3.IntegrityError as exc:
        raise RuntimeError(
            f"Duplicate trade rejected ({trade.side.value.upper()} {trade.pair} "
            f"@ {trade.price} [{trade.strategy}]): {exc}"
        ) from exc


def insert_candle(path: str, candle: Candle) -> None:
    with _connect(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO candles "
            "(pair, timeframe, open, high, low, close, tick_count, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (candle.pair, candle.timeframe, candle.open, candle.high, candle.low,
             candle.close, candle.tick_count, candle.timestamp.isoformat()),
        )


def query_candles(path: str, pair: str, timeframe: int, limit: int) -> list[Candle]:
    with _connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM candles WHERE pair = ? AND timeframe = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (pair, timeframe, limit),
        ).fetchall()
    return [
        Candle(
            pair=row["pair"], timeframe=row["timeframe"],
            open=row["open"], high=row["high"], low=row["low"], close=row["close"],
            tick_count=row["tick_count"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
        for row in reversed(rows)
    ]


def insert_deposit(path: str, deposit: Deposit) -> int:
    with _connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO deposits (aud_amount, usd_amount, fee_usd, timestamp, notes, rate_mid) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (deposit.aud_amount, deposit.usd_amount, deposit.fee_usd,
             deposit.timestamp.isoformat(), deposit.notes, deposit.rate_mid),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def query_deposits(
    path: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    read_only: bool = False,
) -> list[Deposit]:
    conditions: list[str] = []
    params: list[object] = []
    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())
    if until:
        conditions.append("timestamp <= ?")
        params.append(until.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM deposits {where} ORDER BY timestamp ASC"
    with _connect(path, read_only=read_only) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        Deposit(
            id=row["id"],
            aud_amount=row["aud_amount"],
            usd_amount=row["usd_amount"],
            fee_usd=row["fee_usd"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            notes=row["notes"],
            rate_mid=row["rate_mid"] if "rate_mid" in row.keys() else None,
        )
        for row in rows
    ]


def query_trades(
    path: str,
    pair: Optional[str] = None,
    mode: Optional[str] = None,
    strategy: Optional[str] = None,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
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
    if until:
        conditions.append("timestamp <= ?")
        params.append(until.isoformat())
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
            band_width=row["band_width"] if "band_width" in row.keys() else None,
        )
        for row in rows
    ]
