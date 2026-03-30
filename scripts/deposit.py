#!/usr/bin/env python3
"""
Record an AUD → USD deposit into the trade log.

Usage:
    cryptotrader-deposit --aud 800.00 --usd 512.50
    cryptotrader-deposit --aud 800.00 --usd 512.50 --fee 1.54
    cryptotrader-deposit --aud 800.00 --usd 512.50 --fee 1.54 --notes "March top-up"
    cryptotrader-deposit --aud 800.00 --usd 512.50 --timestamp 2026-03-30T14:00:00
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.models import Deposit


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an AUD→USD deposit")
    parser.add_argument("--aud",       type=float, required=True,  help="AUD amount deposited")
    parser.add_argument("--usd",       type=float, required=True,  help="USD amount received after conversion")
    parser.add_argument("--fee",       type=float, default=0.0,    help="Conversion fee in USD (default: 0.0)")
    parser.add_argument("--notes",     type=str,   default=None,   help="Optional notes")
    parser.add_argument("--timestamp", type=str,   default=None,   help="ISO 8601 timestamp (default: now UTC)")
    args = parser.parse_args()

    if args.timestamp:
        try:
            ts = datetime.fromisoformat(args.timestamp)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            print(f"Error: --timestamp must be ISO 8601 format, e.g. 2026-03-30T14:00:00", file=sys.stderr)
            sys.exit(1)
    else:
        ts = datetime.now(timezone.utc)

    rate = args.usd / args.aud if args.aud else 0.0

    deposit = Deposit(
        aud_amount=args.aud,
        usd_amount=args.usd,
        fee_usd=args.fee,
        timestamp=ts,
        notes=args.notes,
    )

    settings = get_settings()
    database.init_db(settings.database.path)
    deposit_id = database.insert_deposit(settings.database.path, deposit)

    print(f"\n  Deposit recorded (id={deposit_id})")
    print(f"  AUD deposited : A${args.aud:,.2f}")
    print(f"  USD received  : ${args.usd:,.2f}")
    print(f"  Rate          : {rate:.4f} (USD/AUD)")
    print(f"  Fee           : ${args.fee:.2f}")
    print(f"  Timestamp     : {ts.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if args.notes:
        print(f"  Notes         : {args.notes}")
    print()


if __name__ == "__main__":
    main()
