# CryptoTrader

Python-based algorithmic trading bot for Kraken, with a live Textual TUI and SQLite trade log.

## ⚠️ Risk Disclaimer

**This software places real orders with real money.** In `production` mode CryptoTrader connects to
your Kraken account with your API keys and executes live buy/sell trades automatically, without
per-trade confirmation.

- **You can lose money — potentially all of it.** Crypto markets are highly volatile and automated
  trading is risky. Backtests and historical results in this repo are **not** indicative of future
  performance.
- **No warranty.** Provided "as is", without warranty of any kind (see [`LICENSE`](LICENSE)). The
  authors are not liable for any financial loss, missed trade, bug, outage, or incorrect order.
- **Not financial advice.** Nothing here is investment, financial, legal, or tax advice.
- **You are responsible** for your API keys, funds, configuration, and strategy parameters, and for
  complying with the laws and exchange terms that apply to you.
- **Test first.** Run in `test` (paper-trading) mode and review the strategy logic before risking
  real capital. Use only funds you can afford to lose.

By running this software in production you accept full responsibility for all resulting trades and
outcomes. Full text: [DISCLAIMER.md](DISCLAIMER.md).

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
- `[currencies."BTC/USD".bollinger]` — `min_band_width_pct` (minimum band width % to trade; large-caps use `4.0`, high-volatility pairs `2.0`) and `trend_filter_enabled` (when `true`, only buy breakouts while the 4h EMA50 trend is rising — recommended for large-caps, off for high-volatility pairs)
- See `config/settings.toml` for all available strategy parameters

## Running

**Headless (systemd / background):**
```bash
python -m cryptotrader.main
```

**With TUI (full mode — starts its own trader):**
```bash
python -m cryptotrader.main --tui
```

**Monitor mode — TUI alongside a running service:**

`--tui` detects whether the service already holds the instance lock and automatically starts in monitor mode if so. No second trader is started; prices come from a read-only WebSocket connection and trades are polled from the database every 3 seconds.

```bash
# Service is running via systemd — just launch the TUI normally:
python -m cryptotrader.main --tui
# Logs: "Service already running — starting in monitor mode (read-only)"
```

Attempting to start a second **headless** instance while the service is running exits immediately with an error.

## Docker

The image is built and pushed to the GitLab container registry on every push to `main`.

```bash
docker pull gitlab.homelab.com:5050/peterk/cryptotrader:latest
```

**Using the Makefile (recommended):**
```bash
make build              # build image locally
make run                # run headless (reads .env, mounts cryptotrader.db)
make tui                # run with interactive TUI
make shell              # open a bash shell inside the container
make push               # push to the registry

# Use Podman instead of Docker
make run CTR=podman
```

**Direct invocation:**
```bash
# Headless
docker run --rm \
  --env-file .env \
  -v $(pwd)/cryptotrader.db:/app/cryptotrader.db \
  gitlab.homelab.com:5050/peterk/cryptotrader:latest

# With TUI
docker run --rm -it \
  --env-file .env \
  -v $(pwd)/cryptotrader.db:/app/cryptotrader.db \
  gitlab.homelab.com:5050/peterk/cryptotrader:latest --tui
```

**Notes:**
- The database is bind-mounted from the host so trade data persists across container restarts. The file is created automatically if it does not exist.
- On Fedora/RHEL with SELinux, use Podman and append `:Z` to the volume flag: `-v $(pwd)/cryptotrader.db:/app/cryptotrader.db:Z`. The Makefile handles this automatically via `make run CTR=podman`.
- Pass Kraken API keys via `.env` (copy `.env.example` as a starting point) or as individual `-e KRAKEN_API_KEY=...` flags.
- The registry requires authentication: `docker login gitlab.homelab.com:5050`

## TUI

The optional terminal UI provides a live view of the running bot:

- **Live Prices** — real-time bid/ask/last per pair via Kraken WebSocket
- **Past 7 Days** — buy/sell counts per pair refreshed every 30s
- **Account Balance** — live Kraken balance (production mode only)
- **Service Health** — database and Kraken API connectivity, uptime, deploy timestamp
- **Trade Log** — scrolling history of trades and deposits, interleaved chronologically
- **Test Statistics** — per-strategy P&L and win rate (test mode only)

Runs in **full mode** (own trader + WS) when no service is active, or **monitor mode** (read-only WS + DB polling) when the service is already running — no configuration needed, detected automatically.

See [docs/tui.md](docs/tui.md) for full layout, key bindings, and data flow.

## Deployment

```bash
bash deploy/deploy-local.sh           # deploy current working tree to Pi
bash deploy/deploy-local.sh --skip-pull  # skip git pull step
```

## Monitoring

The bot serves a health endpoint (`/health` on port `8080`) that reports database and Kraken
API status. A desktop-side watcher (`deploy/monitoring/kraken-monitor.sh`, run by a systemd
`--user` timer every 5 minutes) polls that endpoint and raises an audio + desktop notification
on failure or recovery. It distinguishes Kraken failures from database, bot-down, and
Pi-unreachable conditions, and retries before alerting to suppress transient blips.

```bash
curl http://pihole.homelab.com:8080/health          # inspect health directly
```

See [docs/monitoring.md](docs/monitoring.md) for the health-endpoint schema, the monitor's
failure-state model, configuration, and install steps.

## Supply Chain Security

Every push generates a [SLSA Level 2](https://slsa.dev/spec/v1.0/levels) provenance attestation signed with a cosign key-pair. The provenance document and signature bundle are stored as pipeline artifacts.

**Prerequisites:**
```bash
# Install cosign
curl -sSfL https://github.com/sigstore/cosign/releases/download/v3.0.5/cosign-linux-amd64 \
  -o /usr/local/bin/cosign && chmod +x /usr/local/bin/cosign
```

**Verify a provenance bundle:**
```bash
# Download provenance.json and provenance.bundle from the pipeline artifacts, then:
cosign verify-blob \
  --key cosign.pub \
  --bundle provenance.bundle \
  provenance.json
```

`cosign.pub` is committed to this repository. A successful verification confirms:
- The provenance was generated by this pipeline
- It has not been tampered with since signing
- The signing key corresponds to the public key in `cosign.pub`

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
