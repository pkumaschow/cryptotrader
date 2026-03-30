# CryptoTrader TUI

## Starting the TUI

```bash
python -m cryptotrader.main --tui
```

The TUI opens the database read-only when run alongside the service. Live price data comes from its own WebSocket connection to Kraken; stats and trade history are read from the shared SQLite database (WAL mode allows concurrent access).

If running over SSH, use `tmux` or `screen` to keep the session alive:
```bash
tmux new -s trader
python -m cryptotrader.main --tui
# detach: Ctrl-B D  |  reattach: tmux attach -t trader
```

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

| Key | Action |
|-----|--------|
| `t` | Toggle timestamps between local timezone and UTC |
| `tab` | Cycle focus between panels |
| `q` / `ctrl-c` | Quit |

Current timezone is shown in the status bar. Switching timezone re-renders the entire trade log.

---

## Status Bar

```
TZ: Local  ·  Built: 2026-03-30 15:42
```

Shows the active timezone and the build timestamp of the installed package.

---

## Data Flow

```
Kraken WS ──► price_queue ──► PricePanel
         └──► trade_queue ──► TradeLogPanel (live trades)
                         └──► SQLite (WAL) ◄─── TradeLogPanel (history on mount)
                                          ◄─── WeeklySummaryPanel (every 30s)
                                          ◄─── StatsPanel (every 5s, test only)
Kraken REST ◄────────────────────────────────── BalancePanel (every 30s, prod only)
```

- Price ticks are delivered via an in-memory queue (`maxsize=100`). If the TUI falls behind, ticks are dropped silently to avoid blocking the trading engine.
- Trade entries arrive via a separate queue, always in sync with what the engine executed.
- Stats and history are queried directly from SQLite in background threads so the UI never blocks.

---

## Modes

| Mode | Behaviour |
|------|-----------|
| `test` | All strategies run simultaneously per pair. No real orders. Stats panel visible. Balance panel hidden. |
| `production` | Single configured strategy per pair. Real orders sent to Kraken. Balance panel visible. Stats panel hidden. |

Mode is set in `config/settings.toml` under `[mode] active`.

---

## Recording Deposits

AUD→USD deposits are recorded manually and appear in the trade log:

```bash
cryptotrader-deposit --aud 800.00 --usd 512.50
cryptotrader-deposit --aud 800.00 --usd 512.50 --fee 1.54 --notes "March top-up"
cryptotrader-deposit --aud 800.00 --usd 512.50 --timestamp 2026-03-30T14:00:00
```

See `scripts/deposit.py` for full usage.
