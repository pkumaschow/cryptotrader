# CryptoTrader TUI

## Starting the TUI

The TUI can be run in two ways:

**As the primary process** (replaces the headless service — do not run both):
```bash
python -m cryptotrader.main --tui
```

**As a monitor alongside the running service** (read-only DB access):
```bash
python -m cryptotrader.main --tui
```
The TUI opens the database read-only when run alongside the service. Live price data comes from its own WebSocket connection to Kraken; stats are read from the shared SQLite database (WAL mode allows concurrent access).

If running over SSH, use `tmux` or `screen` to keep the session alive:
```bash
tmux new -s trader
python -m cryptotrader.main --tui
# detach: Ctrl-B D  |  reattach: tmux attach -t trader
```

---

## Layout

```
┌─ Live Prices ──────────────────────────────────────────────────────┐
│ Pair     Bid       Ask       Last      Updated                     │
│ BTC/USD  84230.00  84231.00  84230.50  12:34:56                    │
│ ETH/USD   2145.00   2145.50   2145.20  12:34:56                    │
└────────────────────────────────────────────────────────────────────┘
┌─ Trade Log ──────────────────────────────┐ ┌─ Test Statistics ────┐
│ BUY   BTC/USD  0.00100 @  84230.00       │ │ threshold       ...  │
│   [ema           ]  test  12:34:56       │ │ ema             ...  │
│ SELL  ETH/USD  0.05000 @   2145.00       │ │ bollinger       ...  │
│   [trend_pullback]  test  12:34:57       │ │ trend_pullback  ...  │
└──────────────────────────────────────────┘ └──────────────────────┘
TZ: Local
 t  Toggle UTC/Local
```

### Live Prices panel

One row per configured currency pair. Updated in-place on every price tick from Kraken — the row count never grows beyond the number of configured pairs.

Columns: `Pair` · `Bid` · `Ask` · `Last` · `Updated`

### Trade Log panel

Scrolling log of every trade fired during the session. Capped at 500 lines — oldest entries drop off as new ones arrive.

Each line format:
```
SIDE  PAIR     QUANTITY  @      PRICE  [strategy      ]  mode  HH:MM:SS
BUY   BTC/USD  0.00100  @  84230.00   [ema            ]  test  12:34:56
```

### Test Statistics panel

Only visible in `test` mode. Shows a per-strategy summary refreshed every 5 seconds:

```
threshold        12 trades   58.3%  P&L +$0.0142
ema               4 trades   75.0%  P&L +$0.0089
bollinger         0 trades   —
trend_pullback    0 trades   —
```

Columns: strategy name · trade count · win rate · cumulative P&L

Stats are read from the SQLite database in a background thread so the UI never blocks.

---

## Key bindings

| Key | Action |
|-----|--------|
| `tab` | Cycle focus between panels (use arrow / Page Up / Page Down to scroll focused panel) |
| `t` | Toggle timestamps between local system timezone and UTC |
| `q` | Quit |
| `ctrl-c` | Quit |

Current timezone is shown in the status bar at the bottom of the screen.

> **Note:** switching timezone only affects new entries — past trade log lines are not retroactively reformatted.

---

## Data flow

```
Kraken WS ──► price_queue ──► Trader ──► tui_price_queue ──► PricePanel
                                    └──► tui_trade_queue ──► TradeLogPanel
                                    └──► SQLite (WAL) ◄────── StatsPanel (every 5s)
```

- Price ticks are delivered to the TUI via an in-memory queue (`maxsize=100`). If the TUI falls behind, ticks are dropped silently — this avoids blocking the trading engine.
- Trade entries arrive via a separate queue so the trade log is always in sync with what the engine actually executed.
- Stats are queried directly from SQLite on a 5-second interval, independent of the queues.

---

## Modes

| Mode | Behaviour |
|------|-----------|
| `test` | All 4 strategies run simultaneously per pair. No real orders placed. Stats panel visible. |
| `production` | Single configured strategy per pair. Real orders sent to Kraken. Stats panel hidden. |

Mode is set in `config/settings.toml` under `[mode] active`.
