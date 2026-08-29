"""Reconciling trade-log holdings against exchange balances.

The design point these tests protect: the two sides are *not* supposed to be
equal. The account predates the bot and carries manual trades, so raw equality
would fail forever. What must hold is that the gap between them stays constant.
"""

from __future__ import annotations

import json

import pytest

from cryptotrader.db import database
from cryptotrader.models import Side, Trade
from cryptotrader.reconcile import (
    AssetReconciliation,
    kraken_asset,
    ledger_holdings,
    load_baseline,
    reconcile,
    save_baseline,
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "r.db"
    database.init_db(str(path))
    return str(path)


def _trade(db_path, pair, side, qty, mode="production"):
    database.insert_trade(db_path, Trade(
        pair=pair, side=side, price=100.0, quantity=qty, mode=mode,
        strategy="bollinger"))


def test_kraken_asset_codes_are_explicit():
    """Kraken prefixes legacy assets and not newer ones; guessing breaks it."""
    assert kraken_asset("BTC/USD") == "XXBT"
    assert kraken_asset("ETH/USD") == "XETH"
    assert kraken_asset("SOL/USD") == "SOL"
    assert kraken_asset("WIF/USD") == "WIF", "unknown bases pass through"


def test_ledger_holdings_sum_buys_and_sells(db):
    _trade(db, "SOL/USD", Side.BUY, 2.0)
    _trade(db, "SOL/USD", Side.SELL, 1.5)
    assert ledger_holdings(db)["SOL"] == pytest.approx(0.5)


def test_ledger_holdings_are_not_floored_at_zero(db):
    """A negative total is the signal, not something to hide.

    `statistics.open_position_quantity` floors at zero so a historical over-sell
    cannot swallow the next buy. Doing that here would erase the very evidence
    this exists to surface.
    """
    _trade(db, "BTC/USD", Side.BUY, 0.003)
    _trade(db, "BTC/USD", Side.SELL, 0.004)
    assert ledger_holdings(db)["XXBT"] == pytest.approx(-0.001)


def test_ledger_holdings_ignore_test_mode_trades(db):
    _trade(db, "SOL/USD", Side.BUY, 5.0, mode="test")
    _trade(db, "SOL/USD", Side.BUY, 1.0, mode="production")
    assert ledger_holdings(db)["SOL"] == pytest.approx(1.0)


def test_divergence_is_what_the_ledger_cannot_explain(db):
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    results = reconcile(db, {"SOL": 2.0})

    assert len(results) == 1
    assert results[0].divergence == pytest.approx(1.5)


def test_unchanged_divergence_passes_against_a_baseline(db):
    """The whole point: a constant gap is healthy and must be able to go green."""
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    results = reconcile(db, {"SOL": 2.0},
                        baseline={"SOL": 1.5})

    assert results[0].drift == pytest.approx(0.0)
    assert results[0].is_ok()


def test_recorded_trade_that_never_executed_moves_the_gap(db):
    """The ledger moved and the balance did not — that is the alarm."""
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    _trade(db, "SOL/USD", Side.SELL, 0.75)      # recorded, but never filled
    results = reconcile(db, {"SOL": 2.0},  # balance unchanged
                        baseline={"SOL": 1.5})

    assert results[0].drift == pytest.approx(0.75)
    assert not results[0].is_ok()


def test_manual_trading_on_the_account_moves_the_gap(db):
    """Balance moved and the ledger did not — the two SOL buys of 2026-07."""
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    results = reconcile(db, {"SOL": 2.0 + 1.54},
                        baseline={"SOL": 1.5})

    assert results[0].drift == pytest.approx(1.54)
    assert not results[0].is_ok()


def test_an_executed_over_sell_does_NOT_move_the_gap(db):
    """Boundary of this check, worth stating plainly.

    When the bot sells coin it never bought and the exchange *executes* it from
    the standing balance, both sides fall by the same amount and the divergence
    is unchanged. So this check cannot see the 2026-08-22 defect.

    That case is caught by `ledger_non_negative`, which fails the moment the
    trade log goes negative. The two checks are complementary, not redundant:
    this one catches the ledger drifting from reality, that one catches the bot
    disposing of more than it holds.
    """
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    _trade(db, "SOL/USD", Side.SELL, 0.75)
    results = reconcile(db, {"SOL": 2.0 - 0.75},   # exchange filled it
                        baseline={"SOL": 1.5})

    assert results[0].drift == pytest.approx(0.0)
    assert results[0].is_ok(), "invisible here by construction — see ledger_non_negative"


def test_missing_baseline_is_not_a_pass(db):
    """No baseline means nothing is being checked — that must not read green."""
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    results = reconcile(db, {"SOL": 2.0})

    assert results[0].drift is None
    assert not results[0].is_ok()


def test_asset_held_only_in_the_ledger_is_still_reported(db):
    """An asset the exchange no longer holds is a discrepancy, not an omission."""
    _trade(db, "BTC/USD", Side.BUY, 0.001)
    results = reconcile(db, {"SOL": 2.0})            # no XXBT balance at all

    btc = next(r for r in results if r.asset == "XXBT")
    assert btc.exchange == 0.0
    assert btc.divergence == pytest.approx(-0.001)


def test_unrelated_exchange_assets_are_ignored(db):
    """The account holds DOGE and XLM the bot never trades — not its business."""
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    results = reconcile(db, {"SOL": 2.0, "XXDG": 80.0, "ZAUD": 100.0})

    assert [r.asset for r in results] == ["SOL"]


def test_tolerance_absorbs_dust(db):
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    results = reconcile(db, {"SOL": 2.0}, baseline={"SOL": 1.5 + 1e-9})
    assert results[0].is_ok(), "float noise must not raise an alarm"


def test_baseline_roundtrips(tmp_path):
    path = tmp_path / "baseline.json"
    results = [
        AssetReconciliation("SOL", 2.0, 0.5, None),
        AssetReconciliation("XXBT", 0.002, -0.001, None),
    ]
    save_baseline(path, results, note="pre-bot holdings + manual SOL buys")

    loaded = load_baseline(path)
    assert loaded["SOL"] == pytest.approx(1.5)
    assert loaded["XXBT"] == pytest.approx(0.003)
    assert json.loads(path.read_text())["note"].startswith("pre-bot")


def test_missing_or_corrupt_baseline_reads_as_absent(tmp_path):
    assert load_baseline(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_baseline(bad) == {}


# --- attribution --------------------------------------------------------

from cryptotrader.reconcile import Movement, attribute_movements, residuals  # noqa: E402

PAIRS = {
    "XXBTZUSD": ("XXBT", "ZUSD"),
    "XETHZUSD": ("XETH", "ZUSD"),
    "SOLUSD": ("SOL", "ZUSD"),
    "XXLMXXBT": ("XXLM", "XXBT"),
    "ETHAUD": ("XETH", "ZAUD"),
}
WATCH = ("XXBT", "XETH", "SOL")


def _fill(pair, side, vol, cost, fee=0.0, ordertxid="OMANUAL", t=1.0):
    return {"pair": pair, "type": side, "vol": vol, "cost": cost,
            "fee": fee, "ordertxid": ordertxid, "time": t}


def test_quote_side_movements_are_counted():
    """A cross-pair sell moves the quote asset too.

    Counting only base assets leaves such a trade looking unexplained when it
    is fully accounted for.
    """
    fills = {"T1": _fill("XXLMXXBT", "sell", 100.0, 0.002)}
    moves = attribute_movements(fills, PAIRS, set(), WATCH)

    btc = [m for m in moves if m.asset == "XXBT"]
    assert len(btc) == 1
    assert btc[0].amount == pytest.approx(0.002)
    assert not btc[0].by_bot


def test_bot_fills_match_on_ordertxid_not_the_record_key():
    """Kraken keys by trade id; the bot stores the order id from AddOrder."""
    fills = {"TRADEID": _fill("SOLUSD", "buy", 0.5, 40.0, ordertxid="ORDERID")}
    moves = attribute_movements(fills, PAIRS, {"ORDERID"}, WATCH)

    assert moves[0].by_bot, "matching on the key would tag this as manual"

    moves = attribute_movements(fills, PAIRS, {"TRADEID"}, WATCH)
    assert not moves[0].by_bot


def test_unwatched_pairs_are_skipped():
    fills = {"T1": _fill("XXDGZUSD", "buy", 80.0, 29.0)}
    assert attribute_movements(fills, PAIRS, set(), WATCH) == []


def test_residual_is_zero_when_fills_explain_the_balance():
    """Bot fills plus one cross-pair quote-leg trade account for the balance."""
    fills = {
        "T1": _fill("XXLMXXBT", "sell", 100.0, 0.002),
        "T2": _fill("XXBTZUSD", "sell", 0.001, 60.0, ordertxid="OBOT"),
    }
    moves = attribute_movements(fills, PAIRS, {"OBOT"}, WATCH)
    res = residuals({"XXBT": 0.001}, moves, WATCH)

    assert res["XXBT"] == pytest.approx(0.0, abs=1e-8)


def test_residual_surfaces_a_non_trade_movement():
    """ETH left the account without a trade — a withdrawal or transfer."""
    fills = {"T1": _fill("ETHAUD", "buy", 0.05, 30.02)}
    moves = attribute_movements(fills, PAIRS, set(), WATCH)
    res = residuals({"XETH": 0.01}, moves, WATCH)

    assert res["XETH"] == pytest.approx(-0.04, abs=1e-8)


def test_fee_is_taken_from_the_quote_side_only():
    """Fee affects a watched balance only when the quote is itself watched."""
    fills = {"T1": _fill("SOLUSD", "buy", 1.0, 100.0, fee=0.80)}
    moves = attribute_movements(fills, PAIRS, set(), WATCH)

    sol = [m for m in moves if m.asset == "SOL"]
    assert sol[0].amount == pytest.approx(1.0), "base leg must not absorb the fee"


def test_movement_dataclass_records_provenance():
    fills = {"T1": _fill("SOLUSD", "buy", 0.5, 40.0, ordertxid="OEXAMPLE")}
    m = attribute_movements(fills, PAIRS, set(), WATCH)[0]

    assert isinstance(m, Movement)
    assert m.ordertxid == "OEXAMPLE" and m.pair == "SOLUSD" and m.side == "buy"


# --- ledger floor -------------------------------------------------------

from cryptotrader.reconcile import (  # noqa: E402
    ledger_low_water_by_pair,
    ledger_net_by_pair,
    load_ledger_floor,
)


def test_low_water_is_the_historical_minimum_not_the_closing_net(db):
    """The distinction that matters, and that I got wrong first time.

    SOL touched zero mid-history before being re-entered. Recording the closing
    net (+0.5) as the floor would flag that historical dip as a fresh breach
    every day, which is the permanently-red trap all over again.
    """
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    _trade(db, "SOL/USD", Side.SELL, 0.5)      # touches zero
    _trade(db, "SOL/USD", Side.BUY, 0.5)       # closes at +0.5

    assert ledger_net_by_pair(db)["SOL/USD"] == pytest.approx(0.5)
    assert ledger_low_water_by_pair(db)["SOL/USD"] == pytest.approx(0.0)


def test_low_water_captures_a_negative_excursion(db):
    _trade(db, "BTC/USD", Side.BUY, 0.001)
    _trade(db, "BTC/USD", Side.SELL, 0.002)    # over-sold to -0.001
    _trade(db, "BTC/USD", Side.BUY, 0.0005)    # recovers to -0.0005

    assert ledger_low_water_by_pair(db)["BTC/USD"] == pytest.approx(-0.001)
    assert ledger_net_by_pair(db)["BTC/USD"] == pytest.approx(-0.0005)


def test_ledger_floor_roundtrips(tmp_path):
    from cryptotrader.reconcile import save_baseline as save

    path = tmp_path / "b.json"
    save(path, [], ledger_floor={"BTC/USD": -0.0014})
    assert load_ledger_floor(path)["BTC/USD"] == pytest.approx(-0.0014)
    assert load_ledger_floor(tmp_path / "absent.json") == {}


def test_check_ledger_passes_below_zero_but_above_the_floor():
    """A known historical over-sell must stop failing; a new one must not."""
    from scripts.daily_check import check_ledger

    def row(pair, side, qty, ts):
        return (1, pair, side, 100.0, qty, ts, None, "bollinger")

    trades = [row("BTC/USD", "buy", 0.001, "2026-01-01T00:00:00+00:00"),
              row("BTC/USD", "sell", 0.002, "2026-01-02T00:00:00+00:00")]

    strict = check_ledger(trades)
    assert not strict.ok, "with no floor the strict rule still protects"

    with_floor = check_ledger(trades, floor={"BTC/USD": -0.001})
    assert with_floor.ok, "known history must be able to go green"

    deeper = [*trades, row("BTC/USD", "sell", 0.0005, "2026-01-03T00:00:00+00:00")]
    assert not check_ledger(deeper, floor={"BTC/USD": -0.001}).ok, "new over-sell must fail"


# --- open positions & manual-trade absorption ---------------------------

from cryptotrader.reconcile import (  # noqa: E402
    load_baseline_recorded,
    manual_adjustment,
    open_positions,
)


def test_open_positions_agree_with_the_executor(db):
    """These must never diverge — the executor sizes real sells from its version.

    A plain running sum reports BTC as flat here, because the net is negative
    from the historical over-sell. That is what hid a live position from the
    stale-position and stop-loss checks.
    """
    from cryptotrader.statistics import open_position_quantity

    _trade(db, "BTC/USD", Side.BUY, 0.001)
    _trade(db, "BTC/USD", Side.SELL, 0.002)     # over-sell; net now -0.001
    _trade(db, "BTC/USD", Side.BUY, 0.00062)    # a genuinely open position

    naive = sum(q for q in [0.001, -0.002, 0.00062])
    assert naive < 0, "precondition: a plain sum reports this pair as flat"

    ours = open_positions(db)["BTC/USD"].quantity
    theirs = open_position_quantity(pair="BTC/USD", mode="production", db_path=db)
    assert ours == pytest.approx(theirs)
    assert ours == pytest.approx(0.00062)


def test_open_positions_records_entry_and_opened_at(db):
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    pos = open_positions(db)["SOL/USD"]
    assert pos.entry_price == pytest.approx(100.0)
    assert pos.opened_at


def test_closed_positions_are_not_reported(db):
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    _trade(db, "SOL/USD", Side.SELL, 0.5)
    assert "SOL/USD" not in open_positions(db)


def test_manual_trades_after_the_baseline_are_absorbed(db):
    """The account is shared with manual trading by decision (#35).

    A discretionary fill is expected divergence, not drift. Alarming on it
    would make this check permanently red again.
    """
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    moves = [Movement(timestamp=200.0, asset="SOL", pair="SOLUSD", side="buy",
                      amount=1.5, by_bot=False)]
    adj = manual_adjustment(moves, since=100.0, watch=("SOL",))
    assert adj["SOL"] == pytest.approx(1.5)

    results = reconcile(db, {"SOL": 2.0}, baseline={"SOL": 0.0}, adjustment=adj)
    assert results[0].expected == pytest.approx(1.5)
    assert results[0].drift == pytest.approx(0.0)
    assert results[0].is_ok(), "a manual trade must not trip the check"


def test_manual_trades_before_the_baseline_are_not_double_counted(db):
    """They are already inside the recorded figure."""
    moves = [Movement(timestamp=50.0, asset="SOL", pair="SOLUSD", side="buy",
                      amount=1.5, by_bot=False)]
    assert manual_adjustment(moves, since=100.0, watch=("SOL",))["SOL"] == 0.0


def test_bot_fills_are_never_treated_as_manual(db):
    """A bot fill moves both sides equally and needs no adjustment."""
    moves = [Movement(timestamp=200.0, asset="SOL", pair="SOLUSD", side="buy",
                      amount=0.5, by_bot=True)]
    assert manual_adjustment(moves, since=100.0, watch=("SOL",))["SOL"] == 0.0


def test_real_drift_still_fails_despite_manual_absorption(db):
    """Absorbing manual trades must not blunt the check."""
    _trade(db, "SOL/USD", Side.BUY, 0.5)
    moves = [Movement(timestamp=200.0, asset="SOL", pair="SOLUSD", side="buy",
                      amount=1.5, by_bot=False)]
    adj = manual_adjustment(moves, since=100.0, watch=("SOL",))

    # Exchange holds 0.25 more than baseline + manual explains.
    results = reconcile(db, {"SOL": 2.25}, baseline={"SOL": 0.0}, adjustment=adj)
    assert results[0].drift == pytest.approx(0.25)
    assert not results[0].is_ok()


def test_baseline_recorded_timestamp_parses(tmp_path):
    from cryptotrader.reconcile import save_baseline as save

    path = tmp_path / "b.json"
    save(path, [], recorded="2026-08-27T12:31:40+00:00")
    assert load_baseline_recorded(path) > 0
    assert load_baseline_recorded(tmp_path / "absent.json") == 0.0
