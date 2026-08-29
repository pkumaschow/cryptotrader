# CryptoTrader — Operator Manual

A Python trading bot for Kraken. It consumes a WebSocket price feed, aggregates
ticks into candles, evaluates them against a configured strategy, and places
orders through Kraken's REST API. Trades go to a local SQLite log; an optional
Textual TUI shows what it is doing.

> **This trades real money.** Read [DISCLAIMER.md](https://github.com/pkumaschow/cryptotrader/blob/main/DISCLAIMER.md)
> before running it in production. The defaults are conservative, but no
> configuration makes an algorithmic trading bot safe.

## Start here

- **[Configuration](configuration.html)** — every key, what it does, and what a
  wrong value costs you.
- **[Operations](operations.html)** — monitoring, the daily check, reconciling
  against the exchange, and reading the trade log.
- **[API reference](api/cryptotrader.html)** — generated from the source.

## The two modes

Mode is set by `mode.active` in `config/settings.toml`, and it is the single
most consequential setting in the file.

| | `test` | `production` |
|---|---|---|
| Orders | none — paper only | **real, with real money** |
| Strategies | all four run at once, for comparison | only the one configured per pair |
| API credentials | not needed | required |
| Trade log `mode` column | `test` | `production` |

Test mode runs every strategy against the same live feed simultaneously, which
is how you compare them on identical data. Nothing reaches the exchange.

## Quick start

Paper trading, no credentials, nothing at risk:

```bash
git clone https://github.com/pkumaschow/cryptotrader && cd cryptotrader
uv sync --extra dev
cp .env.example .env                      # leave the keys blank for test mode
python -m cryptotrader.main --tui         # mode.active is "test" by default
```

Or with Docker:

```bash
docker run --rm -it \
  -v "$PWD/config:/app/config" \
  -v "$PWD/cryptotrader.db:/app/cryptotrader.db" \
  pkumaschow/cryptotrader:latest
```

## Going to production

Do these in order. Each one exists because of something that went wrong.

1. **Run in test mode for weeks, not days.** A strategy that looks good over
   ten trades is telling you nothing. See
   [`scripts/backtest.py`](https://github.com/pkumaschow/cryptotrader/blob/main/scripts/backtest.py).
2. **Set the safety rails deliberately** — `max_order_usd`,
   `mode.max_daily_loss_usd`, and `stop_loss_pct`. The stop-loss is disabled by
   default and the small-profit exit gate will otherwise block every
   loss-making exit, holding a losing position indefinitely.
3. **Understand the fee hurdle.** Kraken charges a percentage of notional per
   leg — 0.80% taker at low volume, so **1.6% per round trip**. Because it is a
   percentage, trading larger does not improve the hurdle at all. Your strategy
   must beat that before it earns anything.
4. **Fund the account properly.** A declined buy is not harmless; see
   [Operations](operations.html).
5. **Set up the daily check** before you leave it running unattended.

## How a decision is made

Worth understanding, because most surprising behaviour follows from it:

1. `kraken_ws` publishes each price tick onto a queue.
2. `trader` hands ticks to the strategy for the pair.
3. The strategy aggregates ticks into candles and **only evaluates when a
   candle completes** — hourly by default. So the bot acts at most once an
   hour per pair, on the candle's closing price.
4. If a signal fires, `executor` checks the safety rails and places the order.
5. The trade, or the refusal, is written to SQLite.

That third step surprises people: a price spike between candle closes is
invisible to the strategy.
