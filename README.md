# CryptoTrader

Python-based algorithmic trading bot for Kraken, with a live Textual TUI and SQLite trade log.

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -e .
cp config/settings.toml config/settings.toml   # already present
cp .env.example .env                            # add Kraken API keys for production
```

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

See [docs/tui.md](docs/tui.md) for TUI layout, key bindings, and data flow.

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
