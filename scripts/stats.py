#!/usr/bin/env python3
"""
Display test mode trading statistics from the SQLite database.
Usage: venv/bin/python scripts/stats.py [--pair BTC/USD]
"""
import argparse
import sys
from pathlib import Path

# Allow running from the project root without installing
sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptotrader import statistics
from cryptotrader.config import get_settings
from cryptotrader.db import database


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader statistics")
    parser.add_argument("--pair", help="Filter by pair (e.g. BTC/USD)")
    parser.add_argument("--mode", default="test", choices=["test", "production"],
                        help="Trade mode to report on (default: test)")
    args = parser.parse_args()

    settings = get_settings()
    database.init_db(settings.database.path)

    pairs = [args.pair] if args.pair else list(settings.currencies.keys()) + [None]

    print(f"\n{'─' * 48}")
    print(f"  CryptoTrader Statistics — mode: {args.mode}")
    print(f"{'─' * 48}")

    for pair in pairs:
        result = statistics.compute(pair=pair, mode=args.mode)
        label = pair if pair else "ALL PAIRS"
        print(f"\n  {label}")
        print(f"    Completed trades : {result.total_trades}")
        if result.total_trades == 0:
            print(f"    No completed trades yet.")
            continue
        pnl_sign = "+" if result.total_pnl >= 0 else ""
        print(f"    Win rate         : {result.win_rate:.1f}%")
        print(f"    Total P&L        : {pnl_sign}${result.total_pnl:.4f}")
        print(f"    Avg gain         : +${result.avg_gain:.4f}")
        print(f"    Avg loss         : -${abs(result.avg_loss):.4f}")

    print(f"\n{'─' * 48}\n")


if __name__ == "__main__":
    main()
