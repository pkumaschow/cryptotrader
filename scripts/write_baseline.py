#!/usr/bin/env python3
"""Record the current exchange-vs-ledger divergence as the reconciliation baseline.

`ledger_matches_exchange` alerts on *drift* from a baseline rather than on raw
inequality, because the two sides are not supposed to match: this account
predates the bot and carries manual trades. Without a baseline the check can
never go green, and a check that can never pass stops being read.

Writing this is a judgement call, not a routine action. The figures it freezes
should be understood first — run `--dry-run` and read the attribution before
committing to them. Anything still unexplained at the moment of writing becomes
invisible to the check from then on, so it is recorded in prose alongside the
numbers rather than silently absorbed.

Usage:
    ./scripts/write_baseline.py --dry-run     # show what would be recorded
    ./scripts/write_baseline.py               # write config/reconciliation-baseline.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptotrader.reconcile import ledger_low_water_by_pair, reconcile, save_baseline
from scripts.daily_check import BASELINE_PATH, fetch_balances, fetch_snapshot

ATTRIBUTION_PATH = str(Path(__file__).resolve().parent.parent
                       / "config" / "reconciliation-attribution.json")


def load_attribution(path: str) -> dict[str, str]:
    """Per-asset explanation of why each divergence figure is what it is.

    Kept in a local, gitignored file rather than in this script: it describes a
    specific account's holdings and manual trades, which is deployment state,
    not code. See reconciliation-attribution.example.json for the shape.
    """
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return {k: str(v) for k, v in json.loads(p.read_text()).items()}
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be recorded and exit")
    ap.add_argument("--out", default=BASELINE_PATH)
    ap.add_argument("--attribution", default=ATTRIBUTION_PATH,
                    help="per-asset explanation of each divergence figure")
    args = ap.parse_args()
    attribution = load_attribution(args.attribution)

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "snap.db"
        fetch_snapshot(db)
        balances = fetch_balances()
        results = reconcile(str(db), balances)
        # The floor is the lowest the running net has ever gone, not the
        # closing net: the check replays history, and only a fall below the
        # historical low is new information.
        floor = ledger_low_water_by_pair(str(db))

    print(f"{'asset':6} {'exchange':>16} {'ledger':>16} {'divergence':>16}")
    print("-" * 58)
    for r in results:
        print(f"{r.asset:6} {r.exchange:16.8f} {r.ledger:+16.8f} {r.divergence:+16.8f}")
    print()
    for r in results:
        print(f"{r.asset}: {attribution.get(r.asset, 'NO ATTRIBUTION RECORDED')}")
        print()

    missing = [r.asset for r in results if r.asset not in attribution]
    if missing:
        print(f"REFUSING: no attribution recorded for {missing} in {args.attribution}. "
              f"Explain these before freezing them into the baseline — an unexplained "
              f"figure, once recorded, is permanent and invisible.", file=sys.stderr)
        return 1

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    save_baseline(
        args.out, results,
        note=("Divergence between Kraken balances and the bot's trade log at the "
              "moment of recording. The check alerts on movement away from these "
              "figures, not on their size."),
        attribution=attribution,
        recorded=datetime.now(UTC).isoformat(timespec="seconds"),
        ledger_floor=floor,
    )
    print(f"Wrote {args.out}")
    print(json.dumps(json.loads(Path(args.out).read_text())["divergence"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
