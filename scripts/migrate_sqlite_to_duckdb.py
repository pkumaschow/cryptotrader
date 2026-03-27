"""
One-time migration: copy trades from the old SQLite DB to the new DuckDB file.

Usage:
    python scripts/migrate_sqlite_to_duckdb.py \
        --sqlite cryptotrader.db \
        --duckdb cryptotrader.duckdb
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime

import duckdb


def migrate(sqlite_path: str, duckdb_path: str) -> None:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row

    dst = duckdb.connect(duckdb_path)
    dst.execute("CREATE SEQUENCE IF NOT EXISTS trades_id_seq START 1")
    dst.execute("""
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

    rows = src.execute("SELECT * FROM trades ORDER BY id ASC").fetchall()
    print(f"Migrating {len(rows)} trades from {sqlite_path} → {duckdb_path}")

    for row in rows:
        strategy = row["strategy"] if "strategy" in row.keys() else "unknown"
        ts = datetime.fromisoformat(row["timestamp"]).replace(tzinfo=None)
        dst.execute(
            """
            INSERT INTO trades (pair, side, price, quantity, timestamp, mode, strategy, pnl, txid)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [row["pair"], row["side"], row["price"], row["quantity"],
             ts, row["mode"], strategy, row["pnl"], row["txid"]],
        )

    src.close()
    dst.close()
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite trades to DuckDB")
    parser.add_argument("--sqlite", default="cryptotrader.db")
    parser.add_argument("--duckdb", default="cryptotrader.duckdb")
    args = parser.parse_args()
    migrate(args.sqlite, args.duckdb)


if __name__ == "__main__":
    main()
