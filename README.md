# CryptoTrader

Python-based algorithmic trading bot for Kraken, with a live Textual TUI and SQLite trade log.

[![CI](https://github.com/pkumaschow/cryptotrader/actions/workflows/ci.yml/badge.svg)](https://github.com/pkumaschow/cryptotrader/actions/workflows/ci.yml)

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

### Ansible (recommended)

**Prerequisites:**
```bash
pip install ansible
ansible-galaxy collection install ansible.posix
```

**Configure inventory** — edit `deploy/inventory.ini` to set your Pi's hostname/IP and SSH user:
```ini
[pi]
pihole ansible_host=192.168.1.66 ansible_user=peterk
```

**Run the playbook:**
```bash
ansible-playbook deploy/playbook.yml -i deploy/inventory.ini
```

The playbook:
- Creates `/opt/cryptotrader/` on the Pi
- Syncs the project source (excludes `.git`, `.venv`, `.env`, `cryptotrader.db`)
- Creates a placeholder `.env` if one doesn't exist — never overwrites an existing one
- Creates a Python virtualenv and installs all dependencies
- Installs and restarts the `cryptotrader` systemd service
- Prints service status and trading statistics on completion

**After first deploy** — set your Kraken API keys directly on the Pi:
```bash
ssh peterk@192.168.1.66 'nano /opt/cryptotrader/.env'
sudo systemctl restart cryptotrader
```

**Useful post-deploy commands:**
```bash
journalctl -fu cryptotrader
ssh peterk@192.168.1.66 '/opt/cryptotrader/venv/bin/cryptotrader-stats'
ssh peterk@192.168.1.66 'cd /opt/cryptotrader && venv/bin/python -m cryptotrader.main --tui'
ssh peterk@192.168.1.66 '/opt/cryptotrader/venv/bin/litecli /opt/cryptotrader/cryptotrader.db --warn'
```

### Local script

```bash
bash deploy/deploy-local.sh           # deploy current working tree to Pi
bash deploy/deploy-local.sh --skip-pull  # skip git pull step
```

## Supply Chain Security

Every push to `main` generates a [SLSA Level 3](https://slsa.dev/spec/v1.0/levels) provenance attestation signed by GitHub's OIDC provider via Sigstore.

**Prerequisites:**
```bash
gh extension install github/gh-attestation   # if not already installed
```

**Verify a release artifact:**
```bash
# Download the artifact from the Actions run
gh run download --repo pkumaschow/cryptotrader --name dist --dir /tmp/ct-dist

# Verify provenance
gh attestation verify /tmp/ct-dist/cryptotrader-0.1.0.tar.gz --repo pkumaschow/cryptotrader
```

A successful verification confirms:
- The artifact was built by the `provenance.yml` workflow in this repository
- It was built from the `main` branch on GitHub-hosted runners
- The provenance is recorded in the public [Sigstore Rekor](https://rekor.sigstore.dev) transparency log

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
