# CryptoTrader TUI

## Starting the TUI

```bash
python -m cryptotrader.main --tui
```

`--tui` automatically selects the right mode based on whether the service is already running:

| Situation | Mode | What starts |
|-----------|------|-------------|
| No service running | **Full** | Trader + WS + TUI |
| Service already running | **Monitor** | Read-only WS + DB poller + TUI |

**Full mode** — owns the instance lock, starts its own trader and WebSocket. Trades execute from this process. Use this when running the bot interactively without the systemd service.

**Monitor mode** — detects that the service holds the lock and starts read-only. A separate WebSocket subscription provides live prices; a DB poller queries for new trades every 3 seconds and feeds them into the trade log. No strategies run, no orders are placed. Use this to observe a running service.

```
# Service running via systemd:
python -m cryptotrader.main --tui
# 2026-04-06 09:00:00 INFO __main__ — Service already running — starting in monitor mode (read-only)
```

If running over SSH, use `tmux` or `screen` to keep the session alive:
```bash
tmux new -s trader
python -m cryptotrader.main --tui
# detach: Ctrl-B D  |  reattach: tmux attach -t trader
```

### Panel visibility flags

Individual panels can be hidden at startup. Hidden panels remain in the DOM and can be toggled back on with their keyboard shortcut at any time.

```bash
python -m cryptotrader.main --tui --hide-weekly --hide-stats
```

| Flag | Panel hidden |
|------|-------------|
| `--hide-prices` | Live Prices |
| `--hide-weekly` | Past 7 Days |
| `--hide-balance` | Account Balance |
| `--hide-health` | Service Health |
| `--hide-trades` | Trade Log |
| `--hide-stats` | Test Statistics |

Flags can be combined freely. Hiding a panel that doesn't exist in the current mode (e.g. `--hide-balance` in test mode) is silently ignored.

---

## Layout

### Test mode

```
┌─ Live Prices ──────────────────┐ ┌─ Past 7 Days ──────────────────┐
│ Pair     Bid      Ask    Last  │ │ Pair     Buys  Sells            │
│ BTC/USD  84230    84231  84230 │ │ BTC/USD    12      9            │
│ ETH/USD   2145     2146   2145 │ │ ETH/USD     4      3            │
└────────────────────────────────┘ │ TOTAL       16     12           │
                                   └────────────────────────────────┘
┌─ Trade Log ───────────────────────┐ ┌─ Test Statistics ──────────────────┐
│ BUY   BTC/USD  0.00100 @ 84230   │ │ threshold     B:12 S:12  58.3% +$0.01│
│   [ema           ]  test  12:34  │ │ ema           B:4  S:4   75.0% +$0.00│
│ DEPOSIT  A$800.00 → $512.50      │ │ bollinger     B:3  S:0              │
│   rate 0.6406  fee $1.54  12:30  │ │ trend_pullback  no trades yet       │
└───────────────────────────────────┘ └────────────────────────────────────┘
TZ: Local  ·  Built: 2026-03-30 15:42
 t  Toggle UTC/Local    tab  Switch Panel
```

### Production mode

```
┌─ Live Prices ──────────────────┐ ┌─ Past 7 Days ──────────┐ ┌─ Account Balance ──┐
│ Pair     Bid      Ask    Last  │ │ Pair     Buys  Sells    │ │ USD   $1,234.56     │
│ BTC/USD  84230    84231  84230 │ │ BTC/USD    12      9    │ │ BTC  0.00500000     │
│ ETH/USD   2145     2146   2145 │ │ TOTAL      12      9    │ │ ETH  0.05000000     │
└────────────────────────────────┘ └────────────────────────┘ └────────────────────┘
┌─ Trade Log ────────────────────────────────────────────────────────────────────────┐
│ BUY   BTC/USD  0.00059 @ 84230.00  [bollinger      ]  production  12:34:56        │
│ DEPOSIT  A$800.00 → $512.50  rate 0.6406  fee $1.54  12:30:00                     │
└────────────────────────────────────────────────────────────────────────────────────┘
TZ: Local  ·  Built: 2026-03-30 15:42
 t  Toggle UTC/Local    tab  Switch Panel
```

---

## Panels

### Live Prices

One row per configured currency pair, updated in-place on every price tick from Kraken.

Columns: `Pair` · `Bid` · `Ask` · `Last` · `Updated`

### Past 7 Days

Trade count summary for the last 7 days, refreshed every 30 seconds. Shows buys and sells per pair plus a TOTAL row.

### Account Balance *(production mode only)*

Live Kraken account balance, refreshed every 30 seconds. Dust amounts below display thresholds are hidden.

### Trade Log

Scrolling log of trades and deposits, capped at 500 entries. Shows history from the database on startup, then appends live trades as they fire. Deposits (recorded via `cryptotrader-deposit`) are interleaved chronologically.

Trade line format:
```
SIDE  PAIR     QUANTITY  @      PRICE  [strategy      ]  mode  HH:MM:SS
BUY   BTC/USD  0.00100  @  84230.00   [ema            ]  test  12:34:56
```

Deposit line format:
```
DEPOSIT  A$800.00 → $512.50  rate 0.6406  fee $1.54  HH:MM:SS
```

### Test Statistics *(test mode only)*

Per-strategy summary refreshed every 5 seconds:

```
threshold        B:12 S:12   58.3%  P&L +$0.0142
ema              B:4  S:4    75.0%  P&L +$0.0089
bollinger        B:3  S:0
trend_pullback   no trades yet
```

Columns: strategy name · buy count · sell count · win rate · cumulative P&L

Win rate and P&L only appear once at least one BUY+SELL round-trip has completed. Open BUYs with no matching SELL are visible immediately via the `B:N` count.

---

## Key Bindings

### General

| Key | Action |
|-----|--------|
| `t` | Toggle timestamps between local timezone and UTC |
| `tab` | Cycle focus between panels |
| `q` / `ctrl-c` | Quit |

Current timezone is shown in the status bar. Switching timezone re-renders the entire trade log.

### Panel toggles

Each panel can be toggled on/off at runtime. Hidden panels retain their state and resume live updates when shown again.

| Key | Panel |
|-----|-------|
| `p` | Live Prices |
| `w` | Past 7 Days |
| `b` | Account Balance |
| `h` | Service Health |
| `l` | Trade Log |
| `s` | Test Statistics |

Toggling a panel that doesn't exist in the current mode (e.g. `b` in test mode) has no effect. Panel toggles are not shown in the footer — use `--hide-*` flags to set the initial state at startup.

---

## Status Bar

```
TZ: Local  ·  Built: 2026-03-30 15:42
```

Shows the active timezone and the build timestamp of the installed package.

---

## Data Flow

### Full mode

```
Kraken WS ──► price_queue ──► Trader ──► tui_price_queue ──► PricePanel
                                    └──► trade_queue ─────► TradeLogPanel (live)
SQLite (WAL) ◄──────────────────────────────────────────── TradeLogPanel (history)
             ◄──────────────────────────────────────────── WeeklySummaryPanel (30s)
             ◄──────────────────────────────────────────── StatsPanel (5s, test only)
Kraken REST ◄───────────────────────────────────────────── BalancePanel (30s, prod)
```

### Monitor mode

```
Kraken WS ──► price_queue ──────────────────────────────── PricePanel
DB poller (every 3s) ──► trade_queue ───────────────────── TradeLogPanel (live)
SQLite (WAL) ◄──────────────────────────────────────────── TradeLogPanel (history)
             ◄──────────────────────────────────────────── WeeklySummaryPanel (30s)
             ◄──────────────────────────────────────────── StatsPanel (5s, test only)
Kraken REST ◄───────────────────────────────────────────── BalancePanel (30s, prod)
```

- In full mode, price ticks go through the Trader before reaching the TUI so the Trader always gets first access. If the TUI falls behind, ticks are dropped silently from the TUI queue (`maxsize=100`) without blocking the engine.
- In monitor mode, the price queue feeds the TUI directly (no Trader). New trades appear with up to 3 seconds of latency from when the service executes them.
- Stats and history panels read directly from SQLite in both modes.

---

## Modes

### Trading mode

Set in `config/settings.toml` under `[mode] active`:

| Mode | Behaviour |
|------|-----------|
| `test` | All strategies run simultaneously per pair. No real orders. Stats panel visible. Balance panel hidden. |
| `production` | Single configured strategy per pair. Real orders sent to Kraken. Balance panel visible. Stats panel hidden. |

### Launch mode

Detected automatically from the instance lock — no flag needed:

| Launch mode | When | Trader | Orders |
|-------------|------|--------|--------|
| Full | No service running | Started | Yes (per trading mode) |
| Monitor | Service already running | Not started | Never |

---

## Recording Deposits

AUD→USD deposits are recorded manually and appear in the trade log:

```bash
cryptotrader-deposit --aud 800.00 --usd 512.50
cryptotrader-deposit --aud 800.00 --usd 512.50 --fee 1.54 --notes "March top-up"
cryptotrader-deposit --aud 800.00 --usd 512.50 --timestamp 2026-03-30T14:00:00
```

See `scripts/deposit.py` for full usage.
