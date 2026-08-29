"""One-time backfill of realized P&L onto historical sell trades (issue #15).

Trades recorded before pnl-on-sell existed have a NULL `pnl`. This replays the
trade history FIFO per pair and writes realized P&L onto each sell, using the
same convention as statistics.compute() (gross of fees,
pnl = (sell - entry) * sell_qty).

Dry-run by default (prints the computed values, writes nothing). Pass --apply to
persist. Only rows with pnl IS NULL are touched, so it's safe to re-run and it
never clobbers values the executor already recorded.

    uv run python -m scripts.backfill_pnl            # dry run, production
    uv run python -m scripts.backfill_pnl --apply    # write it
"""

from __future__ import annotations

import argparse
import sqlite3

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Side, Trade


def compute_backfill(db_path: str, mode: str) -> list[tuple[int, float, str, float, float, float]]:
    """FIFO-replay trades and return (sell_id, pnl, pair, entry, exit, qty) per closed sell."""
    trades = database.query_trades(db_path, mode=mode, read_only=True)  # timestamp ASC
    open_buys: dict[str, list[Trade]] = {}
    rows: list[tuple[int, float, str, float, float, float]] = []
    for t in trades:
        if t.side == Side.BUY:
            open_buys.setdefault(t.pair, []).append(t)
        elif open_buys.get(t.pair):
            buy = open_buys[t.pair].pop(0)
            pnl = (t.price - buy.price) * t.quantity
            if t.id is not None:
                rows.append((t.id, pnl, t.pair, buy.price, t.price, t.quantity))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill realized pnl on historical sells (#15).")
    ap.add_argument("--db", default=None, help="DB path (default: settings.database.path)")
    ap.add_argument("--mode", default="production", help="trade mode to backfill")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = ap.parse_args()

    db_path = args.db or get_settings().database.path
    rows = compute_backfill(db_path, args.mode)

    print(f"Backfill target: {db_path}  (mode={args.mode})")
    print(f"{'ID':>5}  {'PAIR':<8} {'ENTRY':>11} {'EXIT':>11} {'QTY':>12} {'PNL':>10}")
    total = 0.0
    for tid, pnl, pair, entry, exit_, qty in rows:
        total += pnl
        print(f"{tid:>5}  {pair:<8} {entry:>11.2f} {exit_:>11.2f} {qty:>12.8f} {pnl:>10.4f}")
    print(f"{'':>5}  {'TOTAL':<8} {'':>11} {'':>11} {'':>12} {total:>10.4f}   ({len(rows)} sells)")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to persist.")
        return

    with sqlite3.connect(db_path, timeout=30) as conn:
        written = 0
        for tid, pnl, *_ in rows:
            cur = conn.execute(
                "UPDATE trades SET pnl = ? WHERE id = ? AND pnl IS NULL", (pnl, tid)
            )
            written += cur.rowcount
        conn.commit()
    print(f"\nAPPLIED — {written} rows updated (rows already having pnl were left untouched).")


if __name__ == "__main__":
    main()
