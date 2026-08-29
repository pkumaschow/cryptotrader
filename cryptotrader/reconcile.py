"""Compare trade-log holdings against what the exchange actually holds.

The naive check — "warn when they differ" — is useless here, because they are
*supposed* to differ. The account predates the bot, holds assets it never traded,
and has manual activity on it (two SOL buys at the maker rate appear in Kraken's
history but not in the trade log, because the bot only sends market orders).

What carries signal is that the difference should be **constant**. Everything the
bot does moves both sides equally: a buy adds to the ledger and to the balance. So
`exchange - ledger` stays fixed at whatever the account held outside the bot, and
only moves when the bot's accounting is wrong — a sell of coin it never bought, a
partial fill, an unrecorded order.

So: record a baseline once, then alert on *drift from that baseline*. That gives a
check which can actually return to green, instead of one that fails forever on a
historical fact and trains everyone to ignore it.
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Kraken's asset codes are not the ticker. Legacy assets carry an X/Z prefix
# (XXBT, XETH, ZUSD) while newer listings do not (SOL). Guessing this mapping
# silently reconciles against the wrong asset, so it is explicit.
KRAKEN_ASSET_CODES: dict[str, str] = {
    "BTC": "XXBT",
    "XBT": "XXBT",
    "ETH": "XETH",
    "SOL": "SOL",
    "DOGE": "XXDG",
    "XLM": "XXLM",
}

#: Below this, treat as equal — float noise and exchange dust rounding.
DEFAULT_TOLERANCE = 1e-6


def kraken_asset(pair: str) -> str:
    """'BTC/USD' -> 'XXBT'. Unknown bases pass through unchanged."""
    base = pair.split("/")[0]
    return KRAKEN_ASSET_CODES.get(base, base)


def ledger_holdings(db_path: str, mode: str = "production") -> dict[str, float]:
    """Net quantity per Kraken asset code, as the trade log believes it.

    Deliberately *not* floored at zero, unlike `statistics.open_position_quantity`.
    That flooring exists so a historical over-sell cannot swallow the next buy;
    here a negative total is exactly the signal being looked for.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT pair, side, quantity FROM trades WHERE mode = ?", (mode,)
        ).fetchall()
    finally:
        conn.close()

    holdings: dict[str, float] = {}
    for pair, side, qty in rows:
        asset = kraken_asset(pair)
        holdings[asset] = holdings.get(asset, 0.0) + (qty if side == "buy" else -qty)
    return holdings


@dataclass
class AssetReconciliation:
    """One asset's position according to the exchange, the log, and the baseline.

    `divergence` is what the trade log cannot explain; `drift` is how far that
    has moved from the recorded baseline, which is the figure worth alerting
    on. The two are not the same, and confusing them produces a check that
    fails forever on history it can never change.
    """
    asset: str
    exchange: float
    ledger: float
    baseline: float | None
    #: Non-bot fills since the baseline was recorded. The account is shared with
    #: manual trading by decision (#35), so a discretionary trade is expected
    #: divergence, not drift — alarming on it would make this check
    #: permanently red again, which is the failure it exists to avoid.
    adjustment: float = 0.0

    @property
    def divergence(self) -> float:
        """Holdings the exchange has that the trade log does not explain."""
        return self.exchange - self.ledger

    @property
    def expected(self) -> float | None:
        """Divergence the baseline plus known manual trading accounts for."""
        if self.baseline is None:
            return None
        return self.baseline + self.adjustment

    @property
    def drift(self) -> float | None:
        """Movement the baseline and manual trading together cannot explain."""
        if self.expected is None:
            return None
        return self.divergence - self.expected

    def is_ok(self, tolerance: float = DEFAULT_TOLERANCE) -> bool:
        """Unknown baseline is not a pass — it means nothing is being checked."""
        if self.drift is None:
            return False
        return abs(self.drift) <= tolerance


def _read_baseline(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def load_baseline(path: str | Path) -> dict[str, float]:
    """Recorded `exchange - ledger` per asset. Missing file means no baseline."""
    return {k: float(v) for k, v in _read_baseline(path).get("divergence", {}).items()}


def load_baseline_recorded(path: str | Path) -> float:
    """Unix time the baseline was taken. 0.0 when absent or unparseable.

    Only fills *after* this count as adjustments; anything earlier is already
    inside the recorded figure and would otherwise be double-counted.
    """
    raw = _read_baseline(path).get("recorded", "")
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (TypeError, ValueError):
        return 0.0


def manual_adjustment(movements: list[Movement], since: float,
                      watch: tuple[str, ...]) -> dict[str, float]:
    """Net effect of non-bot fills after `since`, per asset."""
    out: dict[str, float] = dict.fromkeys(watch, 0.0)
    for m in movements:
        if not m.by_bot and m.timestamp > since and m.asset in out:
            out[m.asset] += m.amount
    return out


def load_ledger_floor(path: str | Path) -> dict[str, float]:
    """Lowest net quantity per pair the trade log is known to have reached.

    The historical over-sell left BTC and ETH permanently negative. Asserting
    "never negative" would fail forever on a fact that cannot change, so the
    check asserts "no lower than the recorded floor" instead — which still
    catches a *new* over-sell while letting the check go green.
    """
    return {k: float(v) for k, v in _read_baseline(path).get("ledger_floor", {}).items()}


def ledger_net_by_pair(db_path: str, mode: str = "production") -> dict[str, float]:
    """Net quantity per trading pair, as the trade log has it."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT pair, side, quantity FROM trades WHERE mode = ?", (mode,)
        ).fetchall()
    finally:
        conn.close()
    net: dict[str, float] = {}
    for pair, side, qty in rows:
        net[pair] = net.get(pair, 0.0) + (qty if side == "buy" else -qty)
    return net


def ledger_low_water_by_pair(db_path: str,
                             mode: str = "production") -> dict[str, float]:
    """Lowest running net each pair has ever reached.

    Not the *current* net. The check walks history forward, and a pair
    legitimately dips below its closing figure along the way — SOL touched zero
    mid-2026 before being re-entered. Recording the closing net as the floor
    would therefore flag that historical dip as a fresh breach every single day.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT pair, side, quantity FROM trades WHERE mode = ? "
            "ORDER BY timestamp ASC", (mode,)
        ).fetchall()
    finally:
        conn.close()
    running: dict[str, float] = {}
    low: dict[str, float] = {}
    for pair, side, qty in rows:
        running[pair] = running.get(pair, 0.0) + (qty if side == "buy" else -qty)
        low[pair] = min(low.get(pair, 0.0), running[pair])
    return low


def save_baseline(path: str | Path, results: list[AssetReconciliation],
                  note: str = "", attribution: dict[str, str] | None = None,
                  recorded: str = "",
                  ledger_floor: dict[str, float] | None = None) -> None:
    """Freeze the current divergence as the reference point.

    `attribution` explains each figure in prose and is the reason this is safe
    to record. A bare number would make whatever is *not* understood permanent
    and invisible; writing down which part is accounted for and which is merely
    accepted keeps the open questions legible to whoever reads it next.
    """
    Path(path).write_text(json.dumps({
        "note": note,
        "recorded": recorded,
        "divergence": {r.asset: round(r.divergence, 12) for r in results},
        "ledger_floor": {k: round(v, 12) for k, v in (ledger_floor or {}).items()},
        "attribution": attribution or {},
    }, indent=2, sort_keys=True) + "\n")


@dataclass
class OpenPosition:
    """A position the trade log says is currently held."""

    pair: str
    quantity: float
    entry_price: float
    opened_at: str


def open_positions(db_path: str, mode: str = "production") -> dict[str, OpenPosition]:
    """Positions currently held, using the executor's own flooring semantics.

    Must match `statistics.open_position_quantity`: the running total is floored
    at zero on each sell, so a historical over-sell does not carry a negative
    balance forward.

    A plain running sum gets this wrong in exactly the case that matters here.
    BTC's net is -0.00077 from the 2026-08 over-sell, so a naive sum reports the
    pair as flat and hides a real open position from the stale-position and
    stop-loss checks — leaving the stop-loss check blind on the one pair that
    had already been mis-accounted.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT pair, side, price, quantity, timestamp FROM trades "
            "WHERE mode = ? ORDER BY timestamp ASC", (mode,)
        ).fetchall()
    finally:
        conn.close()

    qty: dict[str, float] = {}
    entry: dict[str, tuple[float, str]] = {}
    for pair, side, price, quantity, ts in rows:
        before = qty.get(pair, 0.0)
        if side == "buy":
            qty[pair] = before + quantity
            if before <= 0.0:
                entry[pair] = (price, ts)
        else:
            qty[pair] = max(0.0, before - quantity)
            if qty[pair] <= 0.0:
                entry.pop(pair, None)
    return {
        pair: OpenPosition(pair=pair, quantity=math.floor(q * 1e8) / 1e8,
                           entry_price=entry[pair][0], opened_at=entry[pair][1])
        for pair, q in qty.items()
        if math.floor(q * 1e8) / 1e8 > 0 and pair in entry
    }


@dataclass
class Movement:
    """One leg of one exchange fill, in a single asset."""

    timestamp: float
    asset: str
    pair: str
    side: str
    amount: float
    by_bot: bool
    ordertxid: str = ""


def attribute_movements(fills: dict[str, dict], pair_assets: dict[str, tuple[str, str]],
                        bot_txids: set[str],
                        watch: tuple[str, ...]) -> list[Movement]:
    """Break exchange fills into per-asset movements, tagged bot or not.

    Both legs matter. A cross-pair sell such as XLM/BTC moves the BTC balance
    via the *quote* side, and looking only at base assets leaves such a trade
    looking unexplained when it is fully accounted for.

    Matching is on `ordertxid`, not the record key: Kraken keys TradesHistory by
    trade id while the bot stores the order id returned by AddOrder, so matching
    on the key would tag every bot fill as manual.
    """
    out: list[Movement] = []
    for fill in sorted(fills.values(), key=lambda f: f.get("time", 0)):
        pair = fill.get("pair", "")
        if pair not in pair_assets:
            continue
        base, quote = pair_assets[pair]
        vol = float(fill.get("vol", 0))
        cost = float(fill.get("cost", 0))
        fee = float(fill.get("fee", 0))
        ordertxid = fill.get("ordertxid", "")
        by_bot = ordertxid in bot_txids
        # Kraken charges the fee on the quote side, so it only shifts a watched
        # balance when the quote itself is one of the assets being reconciled.
        if fill.get("type") == "buy":
            legs = ((base, vol), (quote, -(cost + fee)))
        else:
            legs = ((base, -vol), (quote, cost - fee))
        for asset, amount in legs:
            if asset in watch and amount:
                out.append(Movement(
                    timestamp=float(fill.get("time", 0)), asset=asset, pair=pair,
                    side=str(fill.get("type", "")), amount=amount, by_bot=by_bot,
                    ordertxid=ordertxid))
    return out


def residuals(balances: dict[str, float], movements: list[Movement],
              watch: tuple[str, ...]) -> dict[str, float]:
    """Balance left over after every known fill is accounted for.

    A non-zero residual is a movement that was not a trade — a deposit,
    withdrawal, transfer or staking reward. Confirming which requires the
    Ledgers endpoint, which this API key is not currently permitted to call.
    """
    moved: dict[str, float] = {}
    for m in movements:
        moved[m.asset] = moved.get(m.asset, 0.0) + m.amount
    return {a: balances.get(a, 0.0) - moved.get(a, 0.0) for a in watch}


def reconcile(db_path: str, balances: dict[str, float],
              baseline: dict[str, float] | None = None,
              mode: str = "production",
              adjustment: dict[str, float] | None = None,
              ) -> list[AssetReconciliation]:
    """Reconcile every asset the bot trades or the exchange holds a balance in."""
    baseline = baseline or {}
    adjustment = adjustment or {}
    ledger = ledger_holdings(db_path, mode=mode)
    # Union of both sides: an asset the ledger knows but the exchange does not
    # is just as much a discrepancy as the reverse.
    assets = sorted(set(ledger) | {a for a in balances if a in set(ledger) | set(baseline)})
    return [
        AssetReconciliation(
            asset=asset,
            exchange=balances.get(asset, 0.0),
            ledger=ledger.get(asset, 0.0),
            baseline=baseline.get(asset),
            adjustment=adjustment.get(asset, 0.0),
        )
        for asset in assets
    ]
