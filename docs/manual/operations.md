# Operations

Running the bot is the easy part. Knowing when it has gone wrong is the job.

## The daily check

`scripts/daily_check.py` is a set of assertions, not a report. That distinction
is deliberate: a summary you have to read every morning is how six weeks of
bag-holding went unnoticed here. Checks stay silent until something fails.

```bash
CRYPTOTRADER_SSH_HOST=user@your-host ./scripts/daily_check.py
```

Exit code `0` means all clear, `1` means a check failed, `2` means it could not
run — and that last one alerts too, because a checker that dies quietly is
worse than none.

| Check | Fails when |
|---|---|
| `ledger_non_negative` | The bot has disposed of more than it holds. |
| `no_unbacked_sells` | A sell was recorded with no matching buy. |
| `no_declined_orders` | An order was refused in the window (see below). |
| `no_stale_position` | A position has been open longer than 21 days. |
| `stop_loss_honoured` | An open position is past its stop and still open. |
| `feed_fresh` | No candle has arrived for over 3 hours. |
| `service_healthy` | The unit is down, or `/health` is not answering. |
| `ledger_matches_exchange` | Holdings have drifted from the exchange beyond what the baseline explains. |

`deploy/monitoring/` has a systemd `--user` timer that runs it daily and alerts
only on failure.

## Why a declined order matters

An order can be refused for insufficient balance, a cap breach, or the daily
loss limit. That is not a non-event, and it is worth understanding why.

A strategy flips its own position state at the moment it emits a signal. If the
executor then declines the order, the strategy is left believing it holds a
position it never opened — and the next exit signal tries to sell coin nobody
bought. That defect is fixed (the trader now rolls the strategy back), but the
underlying condition remains a warning sign: **a bot that cannot fund its buys
is a bot whose accounting is under strain.** Fund it, or lower `budget_usd`.

Refusals are recorded in the `rejected_orders` table and shown in the TUI trade
log struck through, tagged with the reason.

## Reconciling against the exchange

Trade-log holdings and exchange balances are **not** supposed to be equal. Your
account probably predates the bot and may carry manual trades. What matters is
that the gap between them stays constant: everything the bot does moves both
sides equally, so the difference only shifts when the accounting is wrong.

So record a baseline once, then alert on drift from it:

```bash
./scripts/write_baseline.py --dry-run     # inspect first
./scripts/write_baseline.py               # then record
```

The script **refuses to run for any asset you have not explained** in
`config/reconciliation-attribution.json`. That is not bureaucracy: an
unexplained figure, once frozen into a baseline, becomes permanent and
invisible. Work out what each number is before recording it.

One limit worth knowing. An over-sell that the exchange *executes* moves both
sides equally and is invisible to this check — `ledger_non_negative` is what
catches that. The two are complementary.

## Reading the trade log

WAL mode, so you can attach while the bot runs:

```sql
SELECT timestamp, side, pair, price, quantity, pnl, strategy
FROM trades WHERE mode='production' ORDER BY timestamp DESC LIMIT 20;

SELECT timestamp, pair, side, reason, detail
FROM rejected_orders ORDER BY timestamp DESC LIMIT 20;
```

`pnl` is recorded on the closing leg, FIFO-matched, and is **gross of fees** —
subtract roughly 1.6% of notional per round trip. A `NULL` pnl on a sell means
there was no matching buy, which is the honest answer rather than a fabricated
zero.

## Health endpoint

```bash
curl http://your-host:8080/health
```

Reports database and Kraken connectivity. It does **not** report whether the
bot is still trading sensibly — a bot that is connected and doing nothing wrong
looks identical to one that is connected and stuck. That is what the daily
check is for.

## Comparing strategies

`scripts/backtest.py` replays stored candles through strategy variants.

```bash
./scripts/backtest.py --validate     # do this first
./scripts/backtest.py
```

`--validate` asserts the baseline reproduces trades the bot actually made. If
it fails, the harness has drifted from the live strategy and every number it
prints is void. Run it before trusting any result.

Be sceptical of your own backtests. Every structural change measured here lost
to the unchanged baseline, and the only variant that beat it was a change to
the *fee*, not the logic.
