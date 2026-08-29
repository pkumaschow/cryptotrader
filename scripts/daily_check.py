#!/usr/bin/env python3
"""Daily production invariant check for the cryptotrader bot.

Assertions, not prose. Every check here corresponds to something that actually
went wrong and was noticed only weeks later:

  ledger_non_negative  the bot sold 0.00077 BTC / 0.0044 ETH it never bought
  no_unbacked_sells    a real Kraken sell with no matching buy (2026-08-22)
  no_declined_orders   a declined buy leaves the strategy falsely "long"
  no_stale_position    six weeks of bag-holding before the stop-loss shipped
  stop_loss_honoured   a position past its stop that has not been cut
  feed_fresh           candles still arriving
  service_healthy      unit active and /health responding

Plus one that compares the log against the exchange rather than against itself:

  ledger_matches_exchange
      Exchange balances are not supposed to *equal* trade-log holdings — the
      account predates the bot and carries manual trades. What must hold is that
      the gap between them stays constant, since everything the bot does moves
      both sides equally. So this checks drift from a recorded baseline, and
      catches the ledger diverging from reality: a trade recorded but never
      filled, one filled but never recorded, or someone trading the account by
      hand. An over-sell the exchange actually executes moves both sides and is
      invisible here — `ledger_non_negative` covers that case.

Read-only against production. Takes a WAL-safe snapshot on the Pi, copies it
back, and analyses locally. Nothing under /opt/cryptotrader is modified.

Usage:
    ./scripts/daily_check.py                      # SSH to the Pi and check
    ./scripts/daily_check.py --db snapshot.db     # check a local snapshot
    ./scripts/daily_check.py --json out.json      # also write machine-readable
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cryptotrader.reconcile import (
    attribute_movements,
    kraken_asset,
    load_baseline_recorded,
    load_ledger_floor,
    manual_adjustment,
    open_positions,
)

SSH = "/usr/bin/ssh"
# Deployment-specific; override for your own host.
HOST = os.environ.get("CRYPTOTRADER_SSH_HOST", "user@your-host")
REMOTE_PATH = os.environ.get("CRYPTOTRADER_REMOTE_PATH", "/opt/cryptotrader")
REMOTE_DB = f"{REMOTE_PATH}/cryptotrader.db"
REMOTE_CONFIG = f"{REMOTE_PATH}/config/settings.toml"
UNIT = os.environ.get("CRYPTOTRADER_UNIT", "cryptotrader")

#: Recorded `exchange - ledger` per asset. Absent until #35 decides what the
#: current unexplained holdings actually are.
BASELINE_PATH = str(Path(__file__).resolve().parent.parent
                    / "config" / "reconciliation-baseline.json")

STALE_POSITION_DAYS = 21
FEED_STALE_HOURS = 3
QTY_EPSILON = 1e-9


@dataclass
class Check:
    """One assertion about production, and whether it held.

    `severity` separates a failure needing action from a warning worth
    seeing and an informational line that never fails the run.
    """
    name: str
    ok: bool
    detail: str
    severity: str = "error"  # error | warn | info


@dataclass
class Report:
    """The full set of checks for one run."""
    generated: str
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[Check]:
        """Checks that failed at error severity — the ones needing action."""
        return [c for c in self.checks if not c.ok and c.severity == "error"]

    @property
    def warnings(self) -> list[Check]:
        """Checks that failed at warning severity."""
        return [c for c in self.checks if not c.ok and c.severity == "warn"]


def ssh(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        [SSH, "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", HOST, cmd],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def fetch_snapshot(dest: Path) -> None:
    """WAL-safe copy of the live DB. `.backup` is consistent; `cat` is not."""
    snap = "/tmp/ct-daily-snap.db"  # noqa: S108 — remote path, removed below
    made = ssh(f"sudo -n sqlite3 {shlex.quote(REMOTE_DB)} \".backup {snap}\" "
               f"&& sudo -n chmod 0644 {snap}")
    if made.returncode != 0:
        raise RuntimeError(f"snapshot failed: {made.stderr.strip() or made.stdout.strip()}")
    with dest.open("wb") as fh:
        got = subprocess.run(  # noqa: S603
            [SSH, "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", HOST,
             f"sudo -n cat {snap}"],
            stdout=fh, stderr=subprocess.PIPE, timeout=180, check=False,
        )
    ssh(f"sudo -n rm -f {snap}")
    if got.returncode != 0 or dest.stat().st_size == 0:
        raise RuntimeError(f"snapshot copy failed: {got.stderr.decode().strip()}")


def load_live_config() -> dict:
    res = ssh(f"sudo -n cat {shlex.quote(REMOTE_CONFIG)}")
    if res.returncode != 0:
        return {}
    return tomllib.loads(res.stdout)


def prod_trades(db: Path) -> list[tuple]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return conn.execute(
            "SELECT id, pair, side, price, quantity, timestamp, pnl, strategy "
            "FROM trades WHERE mode='production' ORDER BY timestamp ASC"
        ).fetchall()
    finally:
        conn.close()


def check_ledger(trades: list[tuple], floor: dict[str, float] | None = None) -> Check:
    """Has the bot disposed of more than it holds?

    Plain "never negative" fails forever once a historical over-sell has already
    happened, and a check that cannot pass is a check nobody reads. So the
    assertion is "no lower than the recorded floor" — which still catches a *new*
    over-sell, while letting the known history settle.

    With no floor recorded this falls back to the strict form, so a fresh
    deployment is still protected.
    """
    floor = floor or {}
    running: dict[str, float] = {}
    breaches: list[str] = []
    for _tid, pair, side, _price, qty, ts, _pnl, _strat in trades:
        running[pair] = running.get(pair, 0.0) + (qty if side == "buy" else -qty)
        limit = floor.get(pair, 0.0) - QTY_EPSILON
        if running[pair] < limit and pair not in [b.split()[0] for b in breaches]:
            breaches.append(f"{pair} fell to {running[pair]:.8f} at {ts} "
                            f"(floor {floor.get(pair, 0.0):+.8f})")
    net = ", ".join(f"{p} {q:+.8f}" for p, q in sorted(running.items()))
    if breaches:
        return Check("ledger_non_negative", False,
                     f"sold more than held — {'; '.join(breaches)}. Net now: {net}")
    if floor:
        return Check("ledger_non_negative", True,
                     f"no new over-sell below the recorded floor. Net: {net}")
    return Check("ledger_non_negative", True, f"net position per pair: {net}")


def check_unbacked(trades: list[tuple], since: datetime) -> Check:
    """A sell with NULL pnl had no open buy to close against."""
    recent = [t for t in trades
              if t[2] == "sell" and t[6] is None
              and datetime.fromisoformat(t[5]) >= since]
    lifetime = [t for t in trades if t[2] == "sell" and t[6] is None]
    if recent:
        rows = "; ".join(f"id={t[0]} {t[1]} @ {t[3]:,.2f} {t[5]}" for t in recent)
        return Check("no_unbacked_sells", False, f"unbacked sell in window — {rows}")
    return Check("no_unbacked_sells", True,
                 f"none in window ({len(lifetime)} lifetime)")


def check_declined(since_spec: str) -> Check:
    """A declined buy leaves the strategy believing it is long. This is the
    precursor to an unbacked sell, so it is an error the day it happens."""
    res = ssh(f"sudo -n journalctl -u {UNIT} --since {shlex.quote(since_spec)} "
              f"--no-pager -o short-iso 2>/dev/null | "
              f"grep -iE 'insufficient balance|refusing sell|exceeds max_order|"
              f"daily loss limit|balance check failed' || true")
    lines = [ln for ln in res.stdout.strip().splitlines() if ln.strip()]
    if lines:
        return Check("no_declined_orders", False,
                     f"{len(lines)} declined/refused order(s):\n      "
                     + "\n      ".join(lines[:5]))
    return Check("no_declined_orders", True, "no declined or refused orders")


def check_stale_position(db: Path, now: datetime) -> Check:
    """An open position older than STALE_POSITION_DAYS is bag-holding.

    Position detection uses the executor's flooring semantics. A plain running
    sum reports BTC as flat, because its net is negative from the 2026-08
    over-sell — which would hide a real position from this check entirely.
    """
    stale = []
    held = open_positions(str(db))
    for pair, pos in sorted(held.items()):
        age = now - datetime.fromisoformat(pos.opened_at)
        if age > timedelta(days=STALE_POSITION_DAYS):
            stale.append(f"{pair} open {age.days}d (since {pos.opened_at[:10]})")
    if stale:
        return Check("no_stale_position", False, "; ".join(stale), severity="warn")
    summary = ", ".join(f"{p} {v.quantity:.8f} since {v.opened_at[:10]}"
                        for p, v in sorted(held.items())) or "none"
    return Check("no_stale_position", True, f"open positions: {summary}")


def check_stop_loss(db: Path, cfg: dict) -> Check:
    """Any open position already past its stop that has not been cut.

    Same flooring semantics as the executor — a naive running sum would report
    BTC as flat and leave this check blind on the one pair already known to have
    been mis-accounted.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        latest = {
            pair: close for pair, close in conn.execute(
                "SELECT pair, close FROM candles c WHERE timeframe=60 AND timestamp="
                "(SELECT MAX(timestamp) FROM candles WHERE pair=c.pair AND timeframe=60)"
            ).fetchall()
        }
    finally:
        conn.close()

    breaches = []
    watched = 0
    for pair, pos in sorted(open_positions(str(db)).items()):
        stop = (cfg.get("currencies", {}).get(pair, {})
                .get("bollinger", {}).get("stop_loss_pct", 0.0))
        px = latest.get(pair)
        if not stop or px is None:
            continue
        watched += 1
        if px <= pos.entry_price * (1 - stop / 100):
            drop = (px / pos.entry_price - 1) * 100
            breaches.append(f"{pair} entry {pos.entry_price:,.2f} now {px:,.2f} "
                            f"({drop:+.1f}%, stop {stop}%)")
    if breaches:
        return Check("stop_loss_honoured", False,
                     "position past its stop and still open — " + "; ".join(breaches))
    return Check("stop_loss_honoured", True,
                 f"no open position past its stop ({watched} checked)")


def check_feed(db: Path, now: datetime) -> Check:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT pair, MAX(timestamp) FROM candles WHERE timeframe=60"
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[1]:
        return Check("feed_fresh", False, "no candles at all")
    age = now - datetime.fromisoformat(row[1])
    hours = age.total_seconds() / 3600
    if hours > FEED_STALE_HOURS:
        return Check("feed_fresh", False,
                     f"newest candle is {hours:.1f}h old ({row[1]})")
    return Check("feed_fresh", True, f"newest candle {hours:.1f}h old")


_BALANCE_SCRIPT = """
import asyncio, json, sys, urllib.request
sys.path.insert(0, "__REMOTE_PATH__")
from cryptotrader.config import get_secrets
from cryptotrader.exchange.kraken_rest import KrakenRest

async def main():
    c = KrakenRest(get_secrets().kraken_api_key,
                   get_secrets().kraken_api_secret.get_secret_value())
    try:
        b = await c.get_balance()
        fills, ofs = {}, 0
        while True:
            page = await c._post("TradesHistory", {"trades": "false", "ofs": str(ofs)})
            batch = page.get("trades") or {}
            fills.update(batch); ofs += len(batch)
            if not batch or ofs >= int(page.get("count", 0)):
                break
    finally:
        await c.close()
    with urllib.request.urlopen(
            "https://api.kraken.com/0/public/AssetPairs", timeout=30) as r:
        ap = json.load(r).get("result", {})
    pairs = {}
    for name, info in ap.items():
        pairs[name] = [info["base"], info["quote"]]
        if info.get("altname"):
            pairs[info["altname"]] = [info["base"], info["quote"]]
    print(json.dumps({"balances": {k: v for k, v in b.items() if v},
                      "fills": fills, "pairs": pairs}))

asyncio.run(main())
"""


def fetch_exchange_state() -> dict:
    """Balances, every fill, and pair composition — read-only.

    Reusing KrakenRest matters: it owns the microsecond nonce sequence the
    running service shares on this API key, so a hand-rolled client is rejected
    with EAPI:Invalid nonce. Balance and TradesHistory are read endpoints;
    AssetPairs is public.
    """
    res = subprocess.run(  # noqa: S603
        [SSH, "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", HOST,
         f"cd {REMOTE_PATH} && sudo -n -u cryptotrader "
         f"{REMOTE_PATH}/venv/bin/python -"],
        input=_BALANCE_SCRIPT.replace("__REMOTE_PATH__", REMOTE_PATH),
        capture_output=True, text=True, timeout=180, check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"exchange read failed: {res.stderr.strip()[:300]}")
    return json.loads(res.stdout)


def fetch_balances() -> dict[str, float]:
    return {k: float(v) for k, v in fetch_exchange_state()["balances"].items()}


def check_ledger_vs_exchange(db: Path, baseline_path: str) -> Check:
    """Does the exchange still hold what the trade log implies it should?

    Compares drift from a recorded baseline, not raw equality — the two sides
    are not supposed to match, since the account predates the bot.

    Manual trades are absorbed rather than alarmed on. The account is shared
    with discretionary trading by decision (#35), so a fill the bot did not
    place is *expected* divergence: it is identified from Kraken's own history
    by `ordertxid` and added to the expected figure. Without that, every manual
    trade would turn this check permanently red, which is the exact failure it
    exists to avoid. Until #38 lands, manual trades stay outside the trade log
    and this is what keeps the check honest.
    """
    from cryptotrader.reconcile import load_baseline, reconcile

    try:
        state = fetch_exchange_state()
    except Exception as exc:
        return Check("ledger_matches_exchange", False,
                     f"could not read the exchange — {type(exc).__name__}: {exc}",
                     severity="warn")

    balances = {k: float(v) for k, v in state["balances"].items()}
    baseline = load_baseline(baseline_path)
    watch = tuple(sorted({kraken_asset(p) for p in
                          load_ledger_floor(baseline_path)} or balances))

    adjustment: dict[str, float] = {}
    manual_note = ""
    if baseline:
        pairs = {k: (v[0], v[1]) for k, v in state.get("pairs", {}).items()}
        bot_txids = _bot_order_txids(db)
        movements = attribute_movements(state.get("fills", {}), pairs, bot_txids, watch)
        since = load_baseline_recorded(baseline_path)
        adjustment = manual_adjustment(movements, since, watch)
        applied = {a: v for a, v in adjustment.items() if abs(v) > 1e-12}
        if applied:
            manual_note = ("  Manual trades since the baseline, absorbed: "
                           + ", ".join(f"{a} {v:+.8f}" for a, v in sorted(applied.items()))
                           + " (see #38)")

    results = reconcile(str(db), balances, baseline, adjustment=adjustment)
    if not results:
        return Check("ledger_matches_exchange", True, "no traded assets", severity="info")

    lines = []
    for r in results:
        drift = "no baseline" if r.drift is None else f"drift {r.drift:+.8f}"
        lines.append(f"{r.asset}: exchange {r.exchange:.8f} vs ledger "
                     f"{r.ledger:+.8f} → unexplained {r.divergence:+.8f} ({drift})")
    detail = "; ".join(lines)

    if not baseline:
        return Check("ledger_matches_exchange", False,
                     "no baseline recorded, so nothing is being checked — "
                     f"see #35. Current state: {detail}", severity="warn")

    if [r for r in results if not r.is_ok()]:
        return Check("ledger_matches_exchange", False,
                     f"divergence MOVED beyond what the baseline and known "
                     f"manual trading explain: {detail}{manual_note}")
    return Check("ledger_matches_exchange", True,
                 f"divergence as expected: {detail}{manual_note}")


def _bot_order_txids(db: Path) -> set[str]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return {r[0] for r in conn.execute(
            "SELECT txid FROM trades WHERE mode='production' AND txid IS NOT NULL")}
    finally:
        conn.close()


def check_maker_fill_rate(db: Path, since: datetime) -> Check:
    """Report how often post-only entries actually fill.

    Informational, never a failure: this exists to answer the open question in
    #27 — what `maker_wait_seconds` should be — with observed data rather than a
    guess. Silent on any deployment not running maker entries.
    """
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        no_fills = conn.execute(
            "SELECT pair, detail, timestamp FROM rejected_orders "
            "WHERE reason='maker_no_fill' ORDER BY timestamp ASC"
        ).fetchall()
        # A maker fill is a buy carrying no txid in test mode; in production it
        # carries the resting order's txid. Either way it is a recorded buy, so
        # count buys since the first maker attempt to get the denominator.
        first = no_fills[0][2] if no_fills else since.isoformat()
        fills = conn.execute(
            "SELECT COUNT(*) FROM trades WHERE side='buy' AND timestamp >= ?",
            (first,),
        ).fetchone()[0]
    except sqlite3.OperationalError:
        return Check("maker_fill_rate", True, "no rejected_orders table yet",
                     severity="info")
    finally:
        conn.close()

    attempts = fills + len(no_fills)
    if attempts == 0:
        return Check("maker_fill_rate", True, "no maker entries attempted",
                     severity="info")
    pct = 100.0 * fills / attempts
    reasons: dict[str, int] = {}
    for _pair, detail, _ts in no_fills:
        key = "drift" if "ran" in (detail or "") else "timeout"
        reasons[key] = reasons.get(key, 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "none"
    return Check("maker_fill_rate", True,
                 f"{fills}/{attempts} filled ({pct:.0f}%) since {first[:10]}; "
                 f"no-fill causes: {breakdown}",
                 severity="info")


def check_service() -> Check:
    active = ssh(f"systemctl is-active {UNIT}").stdout.strip()
    health = ssh("curl -sf -m 10 http://127.0.0.1:8080/health -o /dev/null "
                 "-w '%{http_code}' || echo FAIL").stdout.strip()
    if active != "active":
        return Check("service_healthy", False, f"unit is {active!r}")
    if not health.endswith("200"):
        return Check("service_healthy", False,
                     f"unit active but /health returned {health!r}")
    return Check("service_healthy", True, "unit active, /health 200")


def build_report(db: Path, cfg: dict, window_hours: int, remote: bool,
                 baseline_path: str = BASELINE_PATH) -> Report:
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)
    trades = prod_trades(db)
    rep = Report(generated=now.isoformat())
    rep.checks.append(check_ledger(trades, load_ledger_floor(baseline_path)))
    rep.checks.append(check_unbacked(trades, since))
    rep.checks.append(check_stale_position(db, now))
    rep.checks.append(check_stop_loss(db, cfg))
    rep.checks.append(check_feed(db, now))
    rep.checks.append(check_maker_fill_rate(db, since))
    if remote:
        rep.checks.append(check_ledger_vs_exchange(db, baseline_path))
    if remote:
        rep.checks.append(check_declined(f"-{window_hours}h"))
        rep.checks.append(check_service())
    return rep


def render(rep: Report, window_hours: int) -> str:
    lines = [f"CryptoTrader daily check — {rep.generated[:19]}Z "
             f"(window {window_hours}h)", ""]
    for c in rep.checks:
        if c.severity == "info":
            mark = "INFO"
        else:
            mark = "PASS" if c.ok else ("WARN" if c.severity == "warn" else "FAIL")
        lines.append(f"  [{mark}] {c.name}")
        lines.append(f"         {c.detail}")
    lines.append("")
    if rep.failures:
        lines.append(f"{len(rep.failures)} FAILURE(S) — action needed.")
    elif rep.warnings:
        lines.append(f"{len(rep.warnings)} warning(s).")
    else:
        lines.append("All checks passed.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", help="analyse a local snapshot instead of SSHing to the Pi")
    ap.add_argument("--window-hours", type=int, default=24)
    ap.add_argument("--json", help="also write the report as JSON here")
    ap.add_argument("--baseline", default=BASELINE_PATH,
                    help="recorded exchange-vs-ledger divergence to check drift against")
    args = ap.parse_args()

    tmp: tempfile.TemporaryDirectory | None = None
    try:
        if args.db:
            db, cfg, remote = Path(args.db), {}, False
        else:
            tmp = tempfile.TemporaryDirectory()
            db = Path(tmp.name) / "snap.db"
            fetch_snapshot(db)
            cfg, remote = load_live_config(), True
        rep = build_report(db, cfg, args.window_hours, remote, args.baseline)
    except Exception as exc:
        # A checker that dies silently is worse than no checker.
        print(f"CryptoTrader daily check — COULD NOT RUN\n\n  {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 2
    finally:
        if tmp is not None:
            tmp.cleanup()

    print(render(rep, args.window_hours))
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"generated": rep.generated,
             "failures": len(rep.failures),
             "warnings": len(rep.warnings),
             "checks": [asdict(c) for c in rep.checks]}, indent=2))
    return 1 if rep.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
