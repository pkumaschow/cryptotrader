# CryptoTrader — AI Assistant Guide

## Project Overview

Python asyncio trading bot that connects to the Kraken exchange via WebSocket, evaluates price
ticks against configurable strategies, and executes trades. Includes an optional live Textual TUI
and a SQLite trade log. Runs in **test mode** (paper trading, all strategies simultaneously) or
**production mode** (live orders, one strategy per currency pair).

## Tech Stack

- **Python 3.11+** — uses `asyncio`, `tomllib`, `dataclasses`, `StrEnum`
- **aiohttp** — Kraken REST API calls (orders, balance)
- **websockets** — Kraken public WebSocket feed (price ticks)
- **Pydantic / pydantic-settings** — config validation and `.env` secrets
- **Textual** — terminal UI (`cryptotrader/tui/`)
- **SQLite** — trade log (`cryptotrader.db`, WAL mode)
- **Ruff** — linting and formatting
- **pytest + pytest-asyncio** — test suite (`asyncio_mode = "auto"`)

## Architecture

```
main.py            Entry point — wires components, starts event loop
trader.py          Core loop — consumes price ticks, dispatches to strategies, calls executor
executor.py        Places orders via Kraken REST, writes trades to DB
candles.py         Aggregates price ticks into OHLC candles for strategies
strategy/
  base.py          Abstract Strategy — evaluate(tick) → Signal | None
  threshold.py     Buy/sell at fixed price levels
  ema.py           Dual EMA crossover + ATR volatility filter
  bollinger.py     Bollinger Band breakout + min band-width + optional 4h trend filter
  trend_pullback.py  Trend EMA + pullback EMA mean-reversion
  registry.py      Maps strategy name strings to classes
config.py          Pydantic settings loaded from config/settings.toml
models.py          Dataclasses: PriceTick, Candle, Trade, Deposit, Signal
db/database.py     SQLite init, trade queries, candle persistence
health.py          Periodic connectivity checks
exchange/
  kraken_ws.py     WebSocket client — reconnects, publishes PriceTick to queue
  kraken_rest.py   REST client — place/query orders, fetch balance
tui/               Textual panels: prices, weekly summary, balance, health, trade log, stats
scripts/           CLI utilities: stats.py, report.py, deposit.py
```

## Running

```bash
# Headless (logs to stdout / journald)
python -m cryptotrader.main

# With Textual TUI (auto-detects monitor mode if service is already running)
python -m cryptotrader.main --tui

# Hide individual TUI panels
python -m cryptotrader.main --tui --hide-balance --hide-stats
```

**Monitor mode:** `--tui` auto-detects whether the service holds the instance lock. If it does,
the TUI starts read-only (polls DB every 3 s, opens its own read-only WebSocket). No second
trader is started.

## Testing

```bash
# Full test suite
pytest

# Single file
pytest tests/test_bollinger_strategy.py

# With coverage
pytest --cov=cryptotrader

# Lint
ruff check .
ruff format --check .
```

Pre-commit hooks run ruff and pytest automatically on every commit:

```bash
pre-commit install        # first-time setup
pre-commit run --all-files  # manual run
```

## Configuration

**`config/settings.toml`** — main config, committed to repo:

```toml
[mode]
active = "test"          # "test" | "production"

[database]
path = "cryptotrader.db"

[currencies."BTC/USD"]
strategy = "ema"         # "threshold" | "ema" | "bollinger" | "trend_pullback"
quantity = 0.001         # BTC per trade (test mode)
# budget_usd = 50.00    # production: USD to spend per buy
# max_order_usd = 500   # production: hard cap per order

[currencies."BTC/USD".bollinger]
min_band_width_pct = 4.0      # minimum band width % to allow a trade (large-caps: 4.0; high-vol pairs: 2.0)
trend_filter_enabled = true   # only buy breakouts when the higher-TF trend EMA is rising
# trend_timeframe_minutes = 240  # trend candle timeframe (default 4h)
# trend_ema_period = 50          # trend EMA period (default 50)
```

**`.env`** — secrets, never committed (copy from `.env.example`):

```
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
```

Secrets are only required in production mode. Test mode runs without API keys.

Config is loaded once via `@lru_cache` in `config.py` — call `get_settings()` anywhere.
To reload config in tests, use `get_settings.cache_clear()`.

## Strategies

All strategies implement `Strategy` (abstract base in `strategy/base.py`):

| Strategy | Signal logic | Key params |
|---|---|---|
| `threshold` | Buy below trigger price, sell above | `buy_trigger`, `sell_trigger` |
| `ema` | Fast/slow EMA crossover + ATR volatility filter | `fast_period`, `slow_period`, `atr_period`, `atr_min_pct` |
| `bollinger` | Band breakout + min bandwidth guard + optional higher-TF trend filter | `period`, `std_dev`, `min_band_width_pct`, `trend_filter_enabled`, `trend_timeframe_minutes`, `trend_ema_period` |
| `trend_pullback` | Trend EMA + pullback EMA mean-reversion | `trend_ema_period`, `pullback_ema_period` |

In **test mode** all four strategies run simultaneously per pair for comparison.
In **production mode** only the strategy named in `settings.toml` runs.

**Bollinger trend filter** (per-currency, default off): when `trend_filter_enabled = true`, a breakout
BUY only fires if the trend EMA on a higher timeframe (`trend_timeframe_minutes`, default 240 = 4h;
`trend_ema_period`, default 50) is rising. This suppresses breakouts bought into a flat/down market —
the main loss source for low-volatility large-caps. Enable it for large-caps (BTC/ETH/SOL, also raised to
`min_band_width_pct = 4.0`); leave it off for high-volatility pairs where backtests show it removes
genuinely profitable breakouts. See `docs/strategy-analysis-2026-05-26-staging.md` for the analysis.

Strategies that need candle history call `restore(db_path, pair)` on startup to reload from DB.

## Key Conventions

- **Line length:** 100 characters (`ruff`)
- **Imports:** isort-ordered via ruff (`I` rules)
- **No mutable class attributes in Textual widgets** — ruff `RUF012` suppressed in `tui/`
- **Security rules** (`S`) suppressed in `tests/` — asserts are fine
- **`assert` allowed** in production code for invariants
- **asyncio patterns:** `asyncio.create_task()` for concurrent work; queues (`asyncio.Queue`)
  for inter-component communication (price ticks, trades)
- **DB access:** always through `db/database.py` functions; never raw SQL in strategy code
- **`from __future__ import annotations`** used in files with forward references

## Deployment

```bash
# Deploy to Raspberry Pi (local network)
bash deploy/deploy-local.sh

# Skip git pull (deploy working tree as-is)
bash deploy/deploy-local.sh --skip-pull
```

Ansible playbook at `deploy/playbook.yml`. Systemd service at `deploy/cryptotrader.service`.
The service runs headless; use `--tui` from a terminal to monitor it live.

**Docker / Podman:**

```bash
make build    # build image
make run      # headless (reads .env, mounts cryptotrader.db)
make tui      # with TUI
make push     # push to GitLab registry (gitlab.homelab.com:5050/peterk/cryptotrader)

# Podman on Fedora/RHEL (handles SELinux :Z automatically)
make run CTR=podman
```

## Database

SQLite WAL mode — safe for concurrent readers alongside the running bot.

```bash
litecli cryptotrader.db --warn   # recommended client (--warn prompts before destructive ops)
```

Useful queries:

```sql
SELECT timestamp, side, pair, price, strategy FROM trades ORDER BY timestamp DESC LIMIT 20;
SELECT strategy, COUNT(*) AS trades, SUM(pnl) AS total_pnl FROM trades GROUP BY strategy;
```

## Supply Chain Security

Every CI push generates a SLSA Level 2 provenance attestation signed with cosign.
Public key is at `cosign.pub`. Verify with:

```bash
cosign verify-blob --key cosign.pub --bundle provenance.bundle provenance.json
```
