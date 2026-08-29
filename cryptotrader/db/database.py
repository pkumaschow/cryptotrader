"""SQLite storage for trades, refused orders, candles and deposits.

WAL mode, so a reader (the TUI, an analysis script) can attach while the bot is
running. `init_db` is idempotent and performs schema migrations with
`CREATE TABLE IF NOT EXISTS` / `ALTER TABLE`, so an existing database is
upgraded in place on startup.

Strategy code never issues SQL directly — everything goes through this module.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime

from cryptotrader.models import Candle, Deposit, RejectedOrder, RejectReason, Side, Trade


def init_db(path: str, read_only: bool = False) -> None:
    """Create the schema if absent and migrate an existing database in place.

    Idempotent and safe to call on every start: tables use
    `CREATE TABLE IF NOT EXISTS` and added columns are attempted with
    `ALTER TABLE`, ignoring the error when they already exist. Sets WAL mode
    so readers can attach while the bot runs, and tightens file permissions —
    the trade log describes an account's positions.

    Args:
    path: Database file, created if missing.
    read_only: Skip all setup. WAL allows readers without it.
    """
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rejected_orders (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                pair      TEXT    NOT NULL,
                side      TEXT    NOT NULL,
                price     REAL    NOT NULL,
                quantity  REAL    NOT NULL,
                reason    TEXT    NOT NULL,
                detail    TEXT    NOT NULL DEFAULT '',
                mode      TEXT    NOT NULL,
                strategy  TEXT    NOT NULL DEFAULT 'unknown',
                timestamp TEXT    NOT NULL
            )
        """)
        conn.commit()
    os.chmod(path, 0o600)


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
    """Record an executed trade.

    Raises:
    RuntimeError: If the trade duplicates one already recorded. A unique
    index guards against two instances writing the same fill, which
    would otherwise double the apparent position.
    """
    try:
        with _connect(path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO trades
                    (pair, side, price, quantity, timestamp, mode, strategy, pnl, txid, band_width)
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
    """Store a completed candle, ignoring one already recorded.

    Persisting these is what lets a strategy rebuild its indicators after a
    restart instead of waiting hours to warm up again.
    """
    with _connect(path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO candles "
            "(pair, timeframe, open, high, low, close, tick_count, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (candle.pair, candle.timeframe, candle.open, candle.high, candle.low,
             candle.close, candle.tick_count, candle.timestamp.isoformat()),
        )


def query_candles(path: str, pair: str, timeframe: int, limit: int) -> list[Candle]:
    """Most recent `limit` candles for a pair and timeframe, oldest first."""
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


def insert_rejected_order(path: str, order: RejectedOrder) -> int:
    """Record an order that was refused before reaching the exchange.

    A refusal is not a non-event: a declined buy is what precedes a strategy
    believing it holds a position it never opened.
    """
    with _connect(path) as conn:
        cursor = conn.execute(
            "INSERT INTO rejected_orders "
            "(pair, side, price, quantity, reason, detail, mode, strategy, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (order.pair, order.side.value, order.price, order.quantity,
             order.reason.value, order.detail, order.mode, order.strategy,
             order.timestamp.isoformat()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def query_rejected_orders(
    path: str,
    pair: str | None = None,
    mode: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    read_only: bool = False,
) -> list[RejectedOrder]:
    """Refused orders, filtered and ordered oldest first."""
    conditions: list[str] = []
    params: list[object] = []
    if pair:
        conditions.append("pair = ?")
        params.append(pair)
    if mode:
        conditions.append("mode = ?")
        params.append(mode)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())
    if until:
        conditions.append("timestamp <= ?")
        params.append(until.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM rejected_orders {where} ORDER BY timestamp ASC"  # noqa: S608
    with _connect(path, read_only=read_only) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        RejectedOrder(
            id=row["id"], pair=row["pair"], side=Side(row["side"]),
            price=row["price"], quantity=row["quantity"],
            reason=RejectReason(row["reason"]), detail=row["detail"],
            mode=row["mode"], strategy=row["strategy"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
        )
        for row in rows
    ]


def insert_deposit(path: str, deposit: Deposit) -> int:
    """Record funds added to the account."""
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
    since: datetime | None = None,
    until: datetime | None = None,
    read_only: bool = False,
) -> list[Deposit]:
    """Deposits, oldest first."""
    conditions: list[str] = []
    params: list[object] = []
    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())
    if until:
        conditions.append("timestamp <= ?")
        params.append(until.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM deposits {where} ORDER BY timestamp ASC"  # noqa: S608
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
    pair: str | None = None,
    mode: str | None = None,
    strategy: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    read_only: bool = False,
) -> list[Trade]:
    """Trades matching the given filters, oldest first.

    Pass `mode` deliberately. Omitting it returns paper and live trades
    together, which is rarely what a caller wants and has caused a strategy
    to restore its position from a test-mode trade.
    """
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
    sql = f"SELECT * FROM trades {where} ORDER BY timestamp ASC"  # noqa: S608
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
