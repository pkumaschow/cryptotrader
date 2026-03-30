# CryptoTrader

Python-based algorithmic trading bot for Kraken, with a live Textual TUI and SQLite trade log.

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
cp .env.example .env                            # add Kraken API keys for production
```

### Pre-commit hooks

Lint and tests run automatically before every commit:

```bash
pre-commit install
```

To run manually without committing:

```bash
pre-commit run --all-files
```

Hooks configured in `.pre-commit-config.yaml`:
- **ruff** — lints changed Python files
- **pytest** — runs the full test suite (`-x` stops on first failure)

## Configuration

Edit `config/settings.toml`:

- `[mode] active` — `"test"` (paper trading, all 4 strategies) or `"production"` (live, single strategy per pair)
- `[currencies."BTC/USD".threshold]` — price levels for the threshold strategy
- See `config/settings.toml` for all available strategy parameters

## Running

**Headless (systemd / background):**
```bash
python -m cryptotrader.main
```

**With TUI:**
```bash
python -m cryptotrader.main --tui
```

## TUI

The optional terminal UI provides a live view of the running bot:

- **Live Prices** — real-time bid/ask/last per pair via Kraken WebSocket
- **Past 7 Days** — buy/sell counts per pair refreshed every 30s
- **Account Balance** — live Kraken balance (production mode only)
- **Service Health** — database and Kraken API connectivity, uptime, deploy timestamp
- **Trade Log** — scrolling history of trades and deposits, interleaved chronologically
- **Test Statistics** — per-strategy P&L and win rate (test mode only)

See [docs/tui.md](docs/tui.md) for full layout, key bindings, and data flow.

## Deployment

```bash
bash deploy/deploy-local.sh           # deploy current working tree to Pi
bash deploy/deploy-local.sh --skip-pull  # skip git pull step
```

## Inspecting the Database

The trade log is stored in `cryptotrader.db` (SQLite, WAL mode).

**Recommended client: `litecli`**

```bash
pip install litecli
```

```bash
litecli /opt/cryptotrader/cryptotrader.db --warn
```

`--warn` prompts before executing destructive statements (`UPDATE`, `DELETE`, `DROP`). WAL mode allows concurrent readers alongside the running bot with no locking issues.

Useful queries:

```sql
-- Recent trades
SELECT timestamp, side, pair, price, strategy FROM trades ORDER BY timestamp DESC LIMIT 20;

-- Trade count per strategy
SELECT strategy, COUNT(*) AS trades FROM trades GROUP BY strategy;

-- All sells
SELECT * FROM trades WHERE side = 'sell' ORDER BY timestamp DESC;
```
