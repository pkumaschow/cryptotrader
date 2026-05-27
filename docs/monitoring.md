# Monitoring

The bot exposes an HTTP health endpoint, and a desktop-side watcher turns failures into
audio + desktop notifications. This document describes both.

## Health endpoint (`/health`)

`cryptotrader/health.py` runs a small aiohttp server inside the bot process, started from
`main.py` on `0.0.0.0:${HEALTH_PORT}` (default `8080`). It is reachable on the LAN.

```bash
curl http://pihole.homelab.com:8080/health
```

```json
{
  "status": "ok",
  "deployed_at": "2026-05-26T05:32:10Z",
  "uptime_seconds": 112904,
  "mode": "production",
  "checks": {
    "database": { "status": "ok" },
    "kraken_api": { "status": "ok", "kraken_status": "online" }
  }
}
```

- **HTTP 200** when every check passes; **HTTP 503** when any check is `error` (`status: degraded`).
- `database` — opens the SQLite file read-only and runs `SELECT 1`.
- `kraken_api` — GETs `https://api.kraken.com/0/public/SystemStatus` and reports Kraken's
  self-declared status.
- Results are cached for 10s (`CACHE_TTL`) so frequent polling can't hammer Kraken or the DB.

> **Note / future work:** `/health` does **not** yet reflect WebSocket feed staleness — the
> bot's actual price path (`wss://ws.kraken.com/v2`). The bot tracks this internally
> (`KrakenWebSocket.feed_healthy`), but it is not surfaced in `/health`. Wiring
> `feed_healthy` into the endpoint would let the monitor catch WS drops (the original
> "failing once an hour" symptom), which a REST `SystemStatus` check cannot see.

## Desktop monitor (`kraken-monitor.sh`)

`deploy/monitoring/kraken-monitor.sh` runs on the **desktop** (where the PAI voice server
lives) via a systemd `--user` timer, every 5 minutes. On a failure or recovery it POSTs to
the PAI voice server (`http://localhost:8888/notify`), which speaks the message and raises a
`notify-send` desktop banner.

### Why it queries `/health` (and not Kraken directly)

The previous monitor SSH'd to the Pi and curled a Kraken REST endpoint from there. When the
SSH/Pi/LAN hop blipped, the response was empty — **indistinguishable from a Kraken outage** —
so it fired "Kraken API connection failed" alerts that had nothing to do with Kraken. Over 40
days it logged **688 "unreachable" events, every one with an empty response** (i.e. not a
single real Kraken error payload).

The current monitor fixes this:

| Fix | How |
|-----|-----|
| Probe what the bot uses | Queries the bot's own `/health` (DB + Kraken), not an unrelated endpoint. |
| Run the probe on the Pi | The Kraken check executes inside the bot on the Pi; the desktop only does an HTTP GET — no SSH hop to misfire. |
| Distinguish failure modes | Separate states/messages for Kraken vs database vs bot-down vs Pi-down. |
| Suppress transient blips | Retries 3× (~10s apart) before declaring failure; alerts only on a state change. |

### States and messages

| State | Detected when | Spoken message |
|-------|---------------|----------------|
| `ok` | HTTP 200 | (recovery message, see below) |
| `kraken` | HTTP 503, `kraken_api.status != ok` | "Kraken API connection failed. Check the bot." |
| `database` | HTTP 503, `database.status != ok` | "CryptoTrader database check is failing on the Pi." |
| `bot` | no HTTP response, but Pi:22 reachable | "CryptoTrader bot is not responding on the Pi." |
| `pi` | no HTTP response, Pi:22 unreachable | "Cannot reach the Pi to check CryptoTrader." |

`pi`-vs-`bot` is distinguished with a dependency-free TCP connect to the Pi's SSH port via
bash `/dev/tcp` (no SSH session, so no key/agent failure modes). Recovery messages are chosen
from the prior failure state (e.g. recovering from `kraken` → "Kraken API connection
restored.").

### Configuration

Environment variables (with defaults) read by the script:

| Variable | Default | Meaning |
|----------|---------|---------|
| `CRYPTOTRADER_HOST` | `pihole.homelab.com` | Pi hostname |
| `CRYPTOTRADER_HEALTH_PORT` | `8080` | bot health port |
| `CRYPTOTRADER_SSH_PORT` | `22` | port used for the Pi-up TCP check |
| `CRYPTOTRADER_RETRIES` | `3` | failed attempts before declaring a failure |
| `CRYPTOTRADER_RETRY_DELAY` | `10` | seconds between attempts |
| `CRYPTOTRADER_HTTP_TIMEOUT` | `6` | per-request timeout for `/health` |

State and history live under `~/.local/share/ip-watcher/`:
`kraken-status.txt` (last state) and `kraken-monitor.log` (timestamped transitions).

### Install (desktop)

```bash
install -m 0755 deploy/monitoring/kraken-monitor.sh ~/.local/bin/kraken-monitor.sh
install -m 0644 deploy/monitoring/kraken-monitor.service ~/.config/systemd/user/kraken-monitor.service
install -m 0644 deploy/monitoring/kraken-monitor.timer   ~/.config/systemd/user/kraken-monitor.timer
systemctl --user daemon-reload
systemctl --user enable --now kraken-monitor.timer
```

Check it:

```bash
systemctl --user list-timers kraken-monitor.timer
systemctl --user start kraken-monitor.service   # run once now
tail ~/.local/share/ip-watcher/kraken-monitor.log
```
