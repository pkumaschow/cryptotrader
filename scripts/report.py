#!/usr/bin/env python3
"""
Generate weekly or monthly trading reports per strategy and comparatively.

Usage:
    cryptotrader-report --period weekly
    cryptotrader-report --period monthly
    cryptotrader-report --period weekly --back 4     # last 4 weeks
    cryptotrader-report --period monthly --back 3    # last 3 months
    cryptotrader-report --period weekly --mode production
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptotrader import statistics
from cryptotrader.config import get_settings
from cryptotrader.db import database
from cryptotrader.strategy.registry import _REGISTRY

W = 64  # report width


def _period_bounds(period: str, back: int) -> list[tuple[datetime, datetime, str]]:
    """Return list of (since, until, label) for each requested period."""
    now = datetime.now(timezone.utc)
    bounds = []
    if period == "weekly":
        # Align to Monday
        start_of_week = now - timedelta(days=now.weekday(), hours=now.hour,
                                        minutes=now.minute, seconds=now.second,
                                        microseconds=now.microsecond)
        for i in range(back):
            until = start_of_week - timedelta(weeks=i)
            since = until - timedelta(weeks=1)
            label = f"Week of {since.strftime('%Y-%m-%d')} → {until.strftime('%Y-%m-%d')}"
            bounds.append((since, until, label))
    else:  # monthly
        year, month = now.year, now.month
        for i in range(back):
            m = month - i
            y = year
            while m <= 0:
                m += 12
                y -= 1
            since = datetime(y, m, 1, tzinfo=timezone.utc)
            if m == 12:
                until = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
            else:
                until = datetime(y, m + 1, 1, tzinfo=timezone.utc)
            label = since.strftime("%B %Y")
            bounds.append((since, until, label))
    return bounds


def _pnl_str(pnl: float) -> str:
    sign = "+" if pnl >= 0 else ""
    return f"{sign}${pnl:.4f}"


def _render_period(label: str, since: datetime, until: datetime, mode: str) -> None:
    strategies = list(_REGISTRY.keys())
    pairs = list(get_settings().currencies.keys())

    print(f"\n{'═' * W}")
    print(f"  {label}")
    print(f"{'═' * W}")

    # ── Individual ──────────────────────────────────────────────────────────
    print(f"\n  {'INDIVIDUAL STRATEGY PERFORMANCE'}")
    print(f"  {'─' * (W - 2)}")

    all_results: dict[str, object] = {}

    for sname in strategies:
        print(f"\n  {sname}")
        total = statistics.compute(mode=mode, strategy=sname, since=since, until=until)
        for pair in pairs:
            r = statistics.compute(pair=pair, mode=mode, strategy=sname, since=since, until=until)
            if r.total_trades == 0:
                print(f"    {pair:<10}  no completed trades")
            else:
                print(f"    {pair:<10}  {r.total_trades:3} trades  "
                      f"{r.win_rate:5.1f}% win  P&L {_pnl_str(r.total_pnl)}")
        if total.total_trades == 0:
            print(f"    {'TOTAL':<10}  no completed trades")
        else:
            print(f"    {'TOTAL':<10}  {total.total_trades:3} trades  "
                  f"{total.win_rate:5.1f}% win  P&L {_pnl_str(total.total_pnl)}")
        all_results[sname] = total

    # ── Comparative ─────────────────────────────────────────────────────────
    print(f"\n  {'COMPARATIVE SUMMARY'}")
    print(f"  {'─' * (W - 2)}")
    print(f"  {'Strategy':<16}  {'Trades':>6}  {'Win %':>6}  {'P&L':>12}  {'Avg Gain':>10}  {'Avg Loss':>10}")
    print(f"  {'─' * 16}  {'─' * 6}  {'─' * 6}  {'─' * 12}  {'─' * 10}  {'─' * 10}")

    active = {s: r for s, r in all_results.items() if r.total_trades > 0}

    for sname in strategies:
        r = all_results[sname]
        if r.total_trades == 0:
            print(f"  {sname:<16}  {'—':>6}  {'—':>6}  {'—':>12}  {'—':>10}  {'—':>10}")
        else:
            print(f"  {sname:<16}  {r.total_trades:>6}  {r.win_rate:>5.1f}%  "
                  f"{_pnl_str(r.total_pnl):>12}  "
                  f"{_pnl_str(r.avg_gain):>10}  "
                  f"{_pnl_str(-abs(r.avg_loss)):>10}")

    if active:
        best_wr = max(active, key=lambda s: active[s].win_rate)
        best_pnl = max(active, key=lambda s: active[s].total_pnl)
        print(f"\n  Best win rate : {best_wr} ({active[best_wr].win_rate:.1f}%)")
        print(f"  Best P&L      : {best_pnl} ({_pnl_str(active[best_pnl].total_pnl)})")
    else:
        print("\n  No completed round-trips in this period.")

    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="CryptoTrader period reports")
    parser.add_argument("--period", choices=["weekly", "monthly"], default="weekly")
    parser.add_argument("--back", type=int, default=1,
                        help="Number of periods to report (default: 1)")
    parser.add_argument("--mode", default="test", choices=["test", "production"])
    args = parser.parse_args()

    settings = get_settings()
    database.init_db(settings.database.path)

    print(f"\n  CryptoTrader — {args.period.capitalize()} Report  |  mode: {args.mode}")

    for since, until, label in _period_bounds(args.period, args.back):
        _render_period(label, since, until, args.mode)


if __name__ == "__main__":
    main()
