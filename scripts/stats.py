#!/usr/bin/env python3
"""Display trading statistics. Usage: cryptotrader-stats [--pair BTC/USD] [--strategy ema]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptotrader import statistics
from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.strategy.registry import _REGISTRY


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader statistics")
    parser.add_argument("--pair", help="Filter by pair (e.g. BTC/USD)")
    parser.add_argument("--strategy", help="Filter by strategy (e.g. ema, bollinger)")
    parser.add_argument("--mode", default="test", choices=["test", "production"])
    args = parser.parse_args()

    settings = get_settings()
    database.init_db(settings.database.path, read_only=True)

    strategy_names = [args.strategy] if args.strategy else list(_REGISTRY.keys())
    pairs = [args.pair] if args.pair else list(settings.currencies.keys()) + [None]

    print(f"\n{'─' * 60}")
    print(f"  CryptoTrader Statistics — mode: {args.mode}")
    print(f"{'─' * 60}")

    for sname in strategy_names:
        print(f"\n  Strategy: {sname}")
        for pair in pairs:
            result = statistics.compute(pair=pair, mode=args.mode, strategy=sname)
            label = pair if pair else "ALL PAIRS"
            print(f"    {label}")
            print(f"      Completed trades : {result.total_trades}")
            if result.total_trades == 0:
                print(f"      No completed trades yet.")
                continue
            pnl_sign = "+" if result.total_pnl >= 0 else ""
            print(f"      Win rate         : {result.win_rate:.1f}%")
            print(f"      Total P&L        : {pnl_sign}${result.total_pnl:.4f}")
            print(f"      Avg gain         : +${result.avg_gain:.4f}")
            print(f"      Avg loss         : -${abs(result.avg_loss):.4f}")

    print(f"\n{'─' * 60}\n")


if __name__ == "__main__":
    main()
