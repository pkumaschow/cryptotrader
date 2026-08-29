# Configuration

Two files. `config/settings.toml` holds everything non-secret and is committed;
`.env` holds the Kraken credentials and never is.

Point the bot at a different config with `CRYPTOTRADER_CONFIG`. That is how one
machine runs a production instance and a staging instance side by side.

```bash
CRYPTOTRADER_CONFIG=/opt/cryptotrader/config/settings-staging.toml \
  python -m cryptotrader.main
```

## `[mode]`

| Key | Default | Meaning |
|---|---|---|
| `active` | `test` | `test` = paper, all strategies. `production` = **real orders**, one strategy per pair. |
| `max_daily_loss_usd` | — | Circuit breaker. Once realized losses since UTC midnight exceed this, every further order is refused for the rest of the day. |

`max_daily_loss_usd` is mandatory and there is no safe default, so pick one you
would actually accept losing in a day. It is evaluated on **realized** P&L, so
an open position falling in value does not trip it — `stop_loss_pct` is what
covers that.

## `[currencies."PAIR"]`

One block per traded pair.

| Key | Meaning |
|---|---|
| `strategy` | Which strategy runs in production: `threshold`, `ema`, `bollinger`, `trend_pullback`. Ignored in test mode, where all four run. |
| `quantity` | Base-asset amount per trade. Used in test mode, and in production when `budget_usd` is unset. |
| `budget_usd` | Production only. Spend this much USD per buy: `quantity = budget_usd / price`. |
| `max_order_usd` | Hard cap. An order valued above this is refused and the trading loop aborts. Mandatory. |

> **`budget_usd` and `quantity` interact, and getting it wrong used to cost
> money.** `budget_usd` sizes *buys*; sells are sized from the open position in
> the trade log. Before 1.2.0 sells used `quantity` instead, so with
> `budget_usd = 50` against `quantity = 0.001` BTC each buy acquired ~0.00062
> and each sell disposed of 0.001 — 61% more than was ever bought, taken from
> the account's own balance. If you are on an older image, upgrade.

## `[currencies."PAIR".bollinger]`

| Key | Default | Meaning |
|---|---|---|
| `period` | `20` | Candles in the moving average. |
| `std_dev` | `2.0` | Band width in standard deviations. |
| `min_band_width_pct` | `0.0` | Refuse entries when the bands are narrower than this % of the middle band. Suppresses false breakouts in quiet markets. |
| `fee_per_trade_usd` | `0.0` | What the exit gate believes one leg costs. A sell below the middle band is blocked unless it clears twice this. |
| `stop_loss_pct` | `0.0` (off) | Exit when price falls this % below entry, ignoring the gate above. |
| `trend_filter_enabled` | `false` | Only buy breakouts while the higher-timeframe trend EMA is rising. |
| `trend_timeframe_minutes` | `240` | Timeframe for that trend filter. |
| `trend_ema_period` | `50` | EMA period for it. |

**Set `stop_loss_pct`.** With it at `0.0` the fee gate blocks every exit that
would realize a loss, so a losing position is held indefinitely — the strategy
has no way out but a recovery that may not come. Enabling it is what ends
bag-holding.

**`fee_per_trade_usd` is a flat figure and real fees are not.** Kraken charges a
percentage of notional, so a flat value is only correct at one position size.
Set it to roughly `0.008 × your typical position` for a taker fill, and revisit
it if you change position size.

## `[execution]`

Opt-in, off by default.

| Key | Default | Meaning |
|---|---|---|
| `maker_entries` | `false` | Rest a post-only limit for entries instead of crossing the spread. Halves the fee on any leg that fills — 0.40% maker against 0.80% taker. |
| `maker_wait_seconds` | `300` | How long the order rests before being cancelled and the signal skipped. |
| `maker_max_drift_pct` | `0.5` | Cancel early if price runs this far from the decision price. |

Entries only. Exits stay market orders on purpose: an unfilled buy costs an
opportunity, but an unfilled *sell* means holding a position the strategy
decided to close — which is how a stop-loss turns back into bag-holding.

This currently refuses to run in production, because fill resolution is
tick-based and cannot confirm that a real resting order filled. Use it in test
mode to measure how often your entries would fill before trusting it.

## `[database]` and `[websocket]`

| Key | Default | Meaning |
|---|---|---|
| `database.path` | `cryptotrader.db` | SQLite file. WAL mode, so readers can attach while the bot runs. |
| `websocket.stale_threshold` | `30` | Seconds without a tick before the feed is considered stale and orders are suspended. |
| `websocket.stats_refresh_interval` | `5` | TUI refresh cadence, seconds. |

## `.env`

```
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
```

Required in production, ignored in test mode. Give the key **trade and query
permissions only** — never withdrawal. If you intend to reconcile holdings
against the exchange, also grant *Query Ledger Entries*, or deposits and
transfers cannot be distinguished from accounting errors.
