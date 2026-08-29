#!/usr/bin/env python3
"""Backtest bollinger strategy variants against stored candle history.

Mirrors `cryptotrader/strategy/bollinger.py` decision-for-decision, then lets
individual rules be swapped so a proposed change can be measured instead of
argued. The `baseline` variant must reproduce the real production trades --
`--validate` asserts that, and every other number here is worthless if it fails.

Decisions are taken when an hourly candle completes; the fill price is that
candle's close, which is what the live bot records (the first tick of the next
candle sits within a cent of the prior close).

Usage:
    ./scripts/backtest.py --validate                    # prove the harness is faithful
    ./scripts/backtest.py --pair SOL/USD                # all variants, one pair
    ./scripts/backtest.py --since 2026-05-01            # restrict the window
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptotrader.strategy._indicators import bollinger_bands, ema

DEFAULT_DB = "cryptotrader.db"
# Verified against Kraken TradesHistory 2026-08-27: every bot fill is charged
# 0.800% of notional. Orders are ordertype="market", so always taker. Maker at
# this volume tier is 0.400%. Fees are PERCENTAGE-based, so position size does
# not move the percentage hurdle -- only the order type or the volume tier does.
TAKER_PCT = 0.80
MAKER_PCT = 0.40
FEE_GATE_USD = 0.60   # what the live strategy's exit gate believes a leg costs


@dataclass
class Params:
    """A strategy variant. Defaults reproduce the live production config."""

    period: int = 20
    std_dev: float = 2.0
    min_bw_pct: float = 4.0
    stop_loss_pct: float = 10.0
    trend_filter: bool = True
    trend_period: int = 50
    trend_tf: int = 240
    # Real cost charged by the exchange, percent of notional per leg.
    fee_pct: float = TAKER_PCT
    # The live exit gate's flat threshold. Modelled separately because the code
    # uses a fixed dollar figure that only matches reality at one position size.
    fee_per_trade: float = FEE_GATE_USD

    # --- swappable rules -------------------------------------------------
    # exit_mode: "mid_band"  = sell when close < middle band (live behaviour)
    #            "trailing"  = sell when close falls trailing_pct below the peak
    #                          reached since entry
    exit_mode: str = "mid_band"
    trailing_pct: float = 5.0
    # entry_mode: "bw_floor" = require bw_pct >= min_bw_pct (live behaviour)
    #             "squeeze"  = require bandwidth to be in the lower
    #                          squeeze_pctile of its recent range AND expanding
    entry_mode: str = "bw_floor"
    squeeze_lookback: int = 120
    squeeze_pctile: float = 40.0
    # Apply the "don't exit unless it clears 2x fees" gate. Live = True, which
    # blocks every losing exit and leaves the stop-loss as the only way out.
    fee_gate: bool = True
    # Refuse a re-entry within this many hours of an exit. 0 = live behaviour.
    cooldown_hours: int = 0


@dataclass
class BtTrade:
    """One simulated fill. Mirrors a real trade minus the exchange round trip."""
    ts: datetime
    side: str
    price: float
    quantity: float
    reason: str


@dataclass
class Result:
    """Outcome of replaying one variant over one pair.

    `gross` is before fees and `net` after, because the gap between them is
    the point: fees are a percentage of notional and dominate at small
    position sizes.
    """
    variant: str
    pair: str
    trades: list[BtTrade] = field(default_factory=list)
    round_trips: int = 0
    wins: int = 0
    gross: float = 0.0
    fees: float = 0.0
    net: float = 0.0
    max_dd: float = 0.0
    hours_in_market: int = 0
    hours_total: int = 0
    buy_hold: float = 0.0

    @property
    def win_rate(self) -> float:
        """Percentage of round trips that cleared both legs of fees."""
        return 100.0 * self.wins / self.round_trips if self.round_trips else 0.0

    @property
    def exposure(self) -> float:
        """Percentage of measured hours spent holding a position.

        Low exposure explains most of any gap to buy-and-hold: a strategy that
        is flat half the time cannot match holding in a rising market.
        """
        return 100.0 * self.hours_in_market / self.hours_total if self.hours_total else 0.0


def load_candles(db: str, pair: str, tf: int) -> list[tuple[datetime, float]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT timestamp, close FROM candles WHERE pair=? AND timeframe=? "
            "ORDER BY timestamp ASC",
            (pair, tf),
        ).fetchall()
    finally:
        conn.close()
    return [(datetime.fromisoformat(ts), close) for ts, close in rows]


def trend_series(c240: list[tuple[datetime, float]], period: int) -> list[tuple[datetime, bool]]:
    """(timestamp, is_rising) for each 4h candle, using only prior closes."""
    out: list[tuple[datetime, bool]] = []
    closes = [c for _, c in c240]
    for i in range(len(c240)):
        e = ema(closes[: i + 1], period)
        out.append((c240[i][0], len(e) >= 2 and e[-1] > e[-2]))
    return out


def trend_up_at(trend: list[tuple[datetime, bool]], ts: datetime) -> bool:
    """Latest 4h verdict from a candle that completed strictly before ts."""
    verdict = False
    for t, rising in trend:
        if t >= ts:
            break
        verdict = rising
    return verdict


def _entry_ok(p: Params, close: float, upper: float, width: float, prev_width: float,
              bw_pct: float, hist: list[float]) -> bool:
    if close <= upper:
        return False
    if p.entry_mode == "bw_floor":
        return width > prev_width and bw_pct >= p.min_bw_pct
    if p.entry_mode == "squeeze":
        # Buy the release of a squeeze: bandwidth was compressed relative to its
        # own recent history and is now expanding. Catches the start of the move
        # rather than waiting for an absolute width the move itself creates.
        if width <= prev_width:
            return False
        window = hist[-p.squeeze_lookback :]
        if len(window) < 20:
            return False
        ranked = sorted(window)
        cutoff = ranked[int(len(ranked) * p.squeeze_pctile / 100.0)]
        return prev_width <= cutoff
    raise ValueError(f"unknown entry_mode {p.entry_mode!r}")


def run(pair: str, c60: list[tuple[datetime, float]], c240: list[tuple[datetime, float]],
        p: Params, budget_usd: float, fixed_qty: float, variant: str,
        trade_from: datetime | None = None) -> Result:
    """Replay `c60` through the variant's rules.

    Candles before `trade_from` warm the indicators but produce no trades, so a
    warm-up lead cannot carry a phantom position into the measured window.
    """
    trend = trend_series(c240, p.trend_period) if p.trend_filter else []
    closes = [c for _, c in c60]
    res = Result(variant=variant, pair=pair)

    in_pos = False
    entry: float | None = None
    qty = 0.0
    peak: float = 0.0
    last_exit_ts: datetime | None = None
    bw_hist: list[float] = []
    equity = 0.0
    equity_peak = 0.0

    for i in range(len(c60)):
        ts, close = c60[i]
        curr = bollinger_bands(closes[: i + 1], p.period, p.std_dev)
        prev = bollinger_bands(closes[:i], p.period, p.std_dev)
        if curr is None or prev is None:
            continue
        upper, mid, lower = curr
        pupper, _, plower = prev
        width, prev_width = upper - lower, pupper - plower
        bw_pct = width / mid * 100 if mid else 0.0
        bw_hist.append(width)

        if trade_from is not None and ts < trade_from:
            continue
        res.hours_total += 1

        if in_pos:
            res.hours_in_market += 1
            peak = max(peak, close)
            reason = ""
            if p.stop_loss_pct > 0 and entry is not None and \
                    close <= entry * (1 - p.stop_loss_pct / 100):
                reason = "stop_loss"
            elif p.exit_mode == "trailing":
                if close <= peak * (1 - p.trailing_pct / 100):
                    reason = "trailing"
            elif p.exit_mode == "mid_band":
                if close < mid:
                    gate_blocks = (
                        p.fee_gate and entry is not None
                        and (close - entry) * qty < p.fee_per_trade * 2
                    )
                    if not gate_blocks:
                        reason = "mid_band"
            else:
                raise ValueError(f"unknown exit_mode {p.exit_mode!r}")

            if reason:
                pnl = (close - (entry or 0.0)) * qty
                res.gross += pnl
                res.fees += close * qty * p.fee_pct / 100
                res.round_trips += 1
                if pnl - (close + (entry or 0.0)) * qty * p.fee_pct / 100 > 0:
                    res.wins += 1
                res.trades.append(BtTrade(ts, "sell", close, qty, reason))
                # Round-trip cost is both legs at the real percentage rate, so the
                # drawdown curve matches the net figure rather than the old flat fee.
                equity += pnl - (close + (entry or 0.0)) * qty * p.fee_pct / 100
                equity_peak = max(equity_peak, equity)
                res.max_dd = max(res.max_dd, equity_peak - equity)
                in_pos, entry, qty, peak = False, None, 0.0, 0.0
                last_exit_ts = ts
            continue

        if p.cooldown_hours and last_exit_ts is not None:
            if (ts - last_exit_ts).total_seconds() < p.cooldown_hours * 3600:
                continue
        if p.trend_filter and not trend_up_at(trend, ts):
            continue
        if _entry_ok(p, close, upper, width, prev_width, bw_pct, bw_hist[:-1]):
            qty = budget_usd / close if budget_usd else fixed_qty
            in_pos, entry, peak = True, close, close
            res.fees += close * qty * p.fee_pct / 100
            res.trades.append(BtTrade(ts, "buy", close, qty, "breakout"))

    res.net = res.gross - res.fees
    # Benchmark over the same window the variant was allowed to trade in.
    window = [c for t, c in c60 if trade_from is None or t >= trade_from]
    if window:
        units = (budget_usd / window[0]) if budget_usd else fixed_qty
        res.buy_hold = (window[-1] - window[0]) * units
    return res


PAIR_SIZING = {
    "BTC/USD": (50.0, 0.001),
    "ETH/USD": (50.0, 0.03),
    "SOL/USD": (0.0, 0.5),  # SOL has no budget_usd in the live config
}

VARIANTS: dict[str, Params] = {
    "baseline": Params(),
    "trailing-5%": Params(exit_mode="trailing", trailing_pct=5.0),
    "trailing-8%": Params(exit_mode="trailing", trailing_pct=8.0),
    "trailing-12%": Params(exit_mode="trailing", trailing_pct=12.0),
    "no-fee-gate": Params(fee_gate=False),
    "squeeze-entry": Params(entry_mode="squeeze"),
    "squeeze+trail-8%": Params(entry_mode="squeeze", exit_mode="trailing", trailing_pct=8.0),
    "cooldown-72h": Params(cooldown_hours=72),
    "no-bw-floor": Params(min_bw_pct=0.0),
    # The one lever the fee data actually offers: limit orders pay maker rate.
    "maker-fees-0.4%": Params(fee_pct=MAKER_PCT),
    "maker+no-fee-gate": Params(fee_pct=MAKER_PCT, fee_gate=False),
}


# The live config only matches `Params()` defaults from 2026-07-26, when
# `stop_loss_pct = 10.0` shipped (a1451e3). Replaying today's rules over trades
# taken under older rules proves nothing, so validation starts after that.
VALIDATE_FROM = datetime.fromisoformat("2026-07-26T13:00:00+00:00")

# Indicators need history before they can signal. Feed the sim this much extra
# candle history ahead of the comparison window so it is warm at VALIDATE_FROM.
WARMUP = timedelta(days=30)

# Simulated trades with no live counterpart that are EXPECTED, because the live
# bot failed to take them. Confirmations of known defects, not harness failures.
EXPECTED_EXTRA = {
    ("BTC/USD", "buy", "2026-08-19 15:00:00"):
        "the executor declined this buy for insufficient balance. The strategy "
        "still marked itself long, which is what made the later sell unbacked — "
        "the defect fixed by the order-rejection rollback.",
}


def validate(db: str, _since: datetime | None) -> int:
    """Assert the baseline replay reproduces the real production trades.

    A trade is matched when the simulation acted on the candle that completed
    within ~a minute before the live order was stamped (decision at candle
    close T+1h; the order row lands a few seconds later).
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        real = conn.execute(
            "SELECT pair, side, price, timestamp FROM trades "
            "WHERE mode='production' AND strategy='bollinger' ORDER BY timestamp"
        ).fetchall()
    finally:
        conn.close()

    print("Validating baseline replay against real production trades")
    print(f"Window: from {VALIDATE_FROM:%Y-%m-%d} (when the live config last changed)\n")
    failures = 0
    for pair in sorted(PAIR_SIZING):
        c60 = [c for c in load_candles(db, pair, 60) if c[0] >= VALIDATE_FROM - WARMUP]
        c240 = [c for c in load_candles(db, pair, 240) if c[0] >= VALIDATE_FROM - WARMUP]
        if not c60:
            print(f"  {pair}: no candle history — skipped")
            continue
        budget, qty = PAIR_SIZING[pair]
        res = run(pair, c60, c240, Params(), budget, qty, "baseline",
                  trade_from=VALIDATE_FROM)
        # Compare only inside the window; the warm-up lead exists to make the
        # indicators valid, not to be checked against a different live config.
        sim = [
            (t.ts.replace(tzinfo=None), t.side, t.price)
            for t in res.trades
            if t.ts >= VALIDATE_FROM
        ]
        matched: set[int] = set()
        actual = [
            r for r in real
            if r[0] == pair and datetime.fromisoformat(r[3]) >= VALIDATE_FROM
        ]
        print(f"  {pair}: {len(actual)} real trades, {len(sim)} simulated")
        for _rpair, side, price, ts in actual:
            real_dt = datetime.fromisoformat(ts).replace(tzinfo=None)
            hit = None
            for idx, (sts, sside, sprice) in enumerate(sim):
                if idx in matched or sside != side:
                    continue
                if 3595 <= (real_dt - sts).total_seconds() <= 3660:
                    hit = (idx, sprice)
                    break
            if hit is not None:
                matched.add(hit[0])
                print(f"    ok   {side:4} @ {price:>10,.2f}  sim @ {hit[1]:>10,.2f}  {ts}")
            else:
                failures += 1
                print(f"    MISS {side:4} @ {price:>10,.2f}  {ts}")
        for idx, (sts, sside, sprice) in enumerate(sim):
            if idx in matched:
                continue
            expected = EXPECTED_EXTRA.get((pair, sside, str(sts)))
            if expected:
                print(f"    n/a  {sside:4} @ {sprice:>10,.2f}  {sts} (sim only)")
                print(f"         └─ {expected}")
            else:
                failures += 1
                print(f"    EXTRA {sside:4} @ {sprice:>10,.2f}  {sts} "
                      f"— sim traded, live did not")
    print()
    if failures:
        print(f"FAILED — {failures} real trade(s) not reproduced. Harness is not faithful.")
    else:
        print("PASS — every reproducible production trade is matched by the baseline replay.")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help="path to a DB snapshot")
    ap.add_argument("--pair", action="append", help="pair to test (repeatable)")
    ap.add_argument("--since", help="ISO date — start MEASURING here; all earlier "
                                    "candles are still loaded to warm the indicators")
    ap.add_argument("--validate", action="store_true",
                    help="check the baseline reproduces real trades, then exit")
    args = ap.parse_args()

    since = datetime.fromisoformat(args.since) if args.since else None
    if args.validate:
        return validate(args.db, since)

    pairs = args.pair or sorted(PAIR_SIZING)
    totals: dict[str, Result] = {}

    for pair in pairs:
        c60 = load_candles(args.db, pair, 60)
        c240 = load_candles(args.db, pair, 240)
        if not c60:
            print(f"{pair}: no candle history\n")
            continue
        # The 4h trend filter gates every entry, so nothing can trade until the
        # trend EMA has warmed. Start measuring after that unless told otherwise.
        trend_ready = (
            c240[Params().trend_period][0]
            if len(c240) > Params().trend_period else c60[-1][0]
        )
        trade_from = since or max(c60[0][0] + WARMUP, trend_ready)
        budget, qty = PAIR_SIZING[pair]
        measured = [t for t, _ in c60 if t >= trade_from]
        if not measured:
            print(f"{pair}: no candles after {trade_from:%Y-%m-%d}\n")
            continue
        span = (f"{measured[0]:%Y-%m-%d} .. {measured[-1]:%Y-%m-%d}  "
                f"({len(measured)} hourly candles measured, "
                f"{len(c60) - len(measured)} used for warm-up)")
        print(f"\n=== {pair} ===  {span}")
        head = (f"{'variant':<18}{'trips':>6}{'win%':>7}{'gross':>9}{'fees':>8}"
                f"{'NET':>9}{'maxDD':>8}{'expo%':>7}")
        print(head)
        print("-" * len(head))
        for name, p in VARIANTS.items():
            res = run(pair, c60, c240, replace(p), budget, qty, name,
                      trade_from=trade_from)
            key = name
            if key not in totals:
                totals[key] = Result(variant=name, pair="ALL")
            agg = totals[key]
            agg.round_trips += res.round_trips
            agg.wins += res.wins
            agg.gross += res.gross
            agg.fees += res.fees
            agg.net += res.net
            agg.max_dd += res.max_dd
            agg.buy_hold += res.buy_hold
            print(f"{name:<18}{res.round_trips:>6}{res.win_rate:>7.0f}{res.gross:>9.2f}"
                  f"{res.fees:>8.2f}{res.net:>9.2f}{res.max_dd:>8.2f}{res.exposure:>7.0f}")
        bh = run(pair, c60, c240, Params(), budget, qty, "bh",
                 trade_from=trade_from).buy_hold
        print(f"{'buy & hold':<18}{'-':>6}{'-':>7}{'-':>9}{'-':>8}{bh:>9.2f}")

    if len(pairs) > 1:
        print("\n=== ALL PAIRS COMBINED ===")
        head = f"{'variant':<18}{'trips':>6}{'win%':>7}{'NET':>9}{'vs buy&hold':>13}"
        print(head)
        print("-" * len(head))
        for name, agg in sorted(totals.items(), key=lambda kv: -kv[1].net):
            print(f"{name:<18}{agg.round_trips:>6}{agg.win_rate:>7.0f}{agg.net:>9.2f}"
                  f"{agg.net - agg.buy_hold:>13.2f}")
        any_agg = next(iter(totals.values()), None)
        if any_agg:
            print(f"{'buy & hold':<18}{'-':>6}{'-':>7}{any_agg.buy_hold:>9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
