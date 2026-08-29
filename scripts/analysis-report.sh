#!/usr/bin/env bash
# analysis-report.sh — Generate a CryptoTrader strategy snapshot report.
#
# Pulls trade data from the Pi via SSH, computes FIFO P&L per strategy,
# and writes a markdown snapshot to docs/strategy-analysis-YYYY-MM-DD.md.
#
# Usage:
#   ./scripts/analysis-report.sh              # save + print
#   ./scripts/analysis-report.sh --print      # print only, don't save
#   ./scripts/analysis-report.sh --no-print   # save only
#
# Requires: ssh access to your deployment host (see REMOTE_* below)

set -euo pipefail

REMOTE_USER="${CRYPTOTRADER_SSH_USER:-youruser}"
REMOTE_HOST="${CRYPTOTRADER_SSH_HOST:-your-pi-host}"
REMOTE_DB="/opt/cryptotrader/cryptotrader.db"
DOCS_DIR="$(cd "$(dirname "$0")/../docs" && pwd)"
DATE=$(date +%Y-%m-%d)
OUT_FILE="$DOCS_DIR/strategy-analysis-$DATE.md"

SAVE=true
PRINT=true

for arg in "$@"; do
  case "$arg" in
    --print)    SAVE=false ;;
    --no-print) PRINT=false ;;
  esac
done

# ---------------------------------------------------------------------------
# Pull data and compute analysis on the remote host
# ---------------------------------------------------------------------------
ANALYSIS=$(ssh "$REMOTE_USER@$REMOTE_HOST" "python3 << 'PYEOF'
import sqlite3
from collections import defaultdict
from datetime import datetime

conn = sqlite3.connect('$REMOTE_DB')
rows = conn.execute(
    'SELECT id, pair, side, price, quantity, timestamp, strategy FROM trades ORDER BY timestamp'
).fetchall()

strategies = defaultdict(list)
for r in rows:
    strategies[r[6]].append(r)

def analyze(trades):
    by_pair = defaultdict(list)
    for t in trades:
        by_pair[t[1]].append(t)
    results = []
    opens = []
    for pair, ptrades in by_pair.items():
        buy_q = []
        for t in ptrades:
            sid, pair_, side, price, qty, ts, strat = t
            if side == 'buy':
                buy_q.append((price, qty, ts))
            elif side == 'sell' and buy_q:
                bp, bqty, bts = buy_q.pop(0)
                pnl = round((price - bp) * qty, 4)
                hold_h = round(
                    (datetime.fromisoformat(ts) - datetime.fromisoformat(bts)).total_seconds() / 3600, 1
                )
                results.append((pair_, bp, price, qty, pnl, hold_h))
        for b in buy_q:
            opens.append((pair_, b[0], b[1], b[2][:16]))
    return results, opens

output = {}
for strat in ['bollinger', 'ema', 'trend_pullback']:
    trades = strategies.get(strat, [])
    results, opens = analyze(trades)
    total = round(sum(r[4] for r in results), 4)
    wins = sum(1 for r in results if r[4] > 0)
    losses = sum(1 for r in results if r[4] <= 0)
    output[strat] = {
        'results': results,
        'opens': opens,
        'total': total,
        'wins': wins,
        'losses': losses,
    }

# Print machine-readable block for shell to consume
import json
print('__JSON_START__')
print(json.dumps(output))
print('__JSON_END__')

# Threshold accumulation data
th = strategies.get('threshold', [])
pairs_th = defaultdict(list)
for t in th:
    pairs_th[t[1]].append(t[3])
th_out = {}
for pair_, prices in pairs_th.items():
    avg = round(sum(prices) / len(prices), 2)
    total_qty = round(sum(0.001 if 'BTC' in pair_ else 0.05 for _ in prices), 3)
    th_out[pair_] = {'count': len(prices), 'avg_entry': avg, 'total_qty': total_qty}
print('__TH_START__')
print(json.dumps({'count': len(th), 'pairs': th_out}))
print('__TH_END__')
PYEOF")

# ---------------------------------------------------------------------------
# Parse JSON output from the remote script
# ---------------------------------------------------------------------------
STRAT_JSON=$(echo "$ANALYSIS" | sed -n '/__JSON_START__/,/__JSON_END__/p' | grep -v '__JSON')
TH_JSON=$(echo "$ANALYSIS" | sed -n '/__TH_START__/,/__TH_END__/p' | grep -v '__TH')

# ---------------------------------------------------------------------------
# Build the markdown report using Python locally
# ---------------------------------------------------------------------------
REPORT=$(python3 << LOCALPY
import json
from datetime import date

strats = json.loads('''$STRAT_JSON''')
th = json.loads('''$TH_JSON''')
today = '$DATE'

def sign(v):
    return f'+\${v:.2f}' if v >= 0 else f'-\${abs(v):.2f}'

def sign4(v):
    return f'+\${v:.4f}' if v >= 0 else f'-\${abs(v):.4f}'

lines = []
lines.append(f'# CryptoTrader Strategy Analysis — {today}')
lines.append('')

# ── Summary table ────────────────────────────────────────────────────────────
total_closed = 0
total_wins = 0
total_losses = 0
total_pnl = 0.0

rows = []
for name in ['bollinger', 'ema', 'trend_pullback']:
    d = strats[name]
    closed = len(d['results'])
    wins = d['wins']
    losses = d['losses']
    pnl = d['total']
    total_closed += closed
    total_wins += wins
    total_losses += losses
    total_pnl += pnl
    wr = f"{wins/closed*100:.0f}%" if closed > 0 else '—'
    pnl_str = f"**{sign(pnl)}**" if pnl != 0 else '\$0.00'
    rows.append(f'| {name} | {closed} | {wins} | {losses} | {wr} | {pnl_str} |')

overall_wr = f"{total_wins/(total_wins+total_losses)*100:.0f}%" if (total_wins+total_losses) > 0 else '—'
rows.append(f'| **TOTAL** | {total_closed} | {total_wins} | {total_losses} | **{overall_wr}** | **{sign(total_pnl)}** |')

lines.append('## Summary')
lines.append('')
lines.append('| Strategy | Closed | Wins | Losses | Win Rate | Realised P&L |')
lines.append('|---|---|---|---|---|---|')
lines.extend(rows)
lines.append(f'| threshold | {th["count"]} buys | — | — | accumulation | — |')
lines.append('')
lines.append('---')
lines.append('')

# ── Per-strategy sections ─────────────────────────────────────────────────────
for name in ['bollinger', 'ema', 'trend_pullback']:
    d = strats[name]
    results = d['results']
    opens = d['opens']
    closed = len(results)
    wins = d['wins']
    losses = d['losses']
    pnl = d['total']
    wr = f"{wins/closed*100:.0f}%" if closed > 0 else '—'

    lines.append(f'## STRATEGY: {name}')
    lines.append('')
    lines.append(f'**Closed:** {closed} | **Wins:** {wins} | **Losses:** {losses} | **Win Rate:** {wr}')
    lines.append(f'**Total realised P&L: USD {sign4(pnl)}**')
    lines.append('')

    if results:
        lines.append('| | Pair | Buy | Sell | Qty | P&L | Hold |')
        lines.append('|---|---|---|---|---|---|---|')
        for pair_, bp, sp, qty, rpnl, hold_h in results:
            mark = 'WIN' if rpnl > 0 else 'LOS'
            lines.append(f'| {mark} | {pair_} | \${bp:,.2f} | \${sp:,.2f} | {qty} | {sign4(rpnl)} | {hold_h}h |')
        lines.append('')

    if opens:
        lines.append(f'**Open ({len(opens)}):**')
        for o in opens:
            lines.append(f'- {o[0]} — entry @ \${o[1]:,.2f}  qty={o[2]}  since {o[3]}')
        lines.append('')

    lines.append('---')
    lines.append('')

# ── Threshold ────────────────────────────────────────────────────────────────
lines.append('## STRATEGY: threshold')
lines.append('')
lines.append(f'**{th["count"]} buys — accumulation mode, no closed P&L**')
lines.append('')
lines.append('| Pair | Buys | Avg Entry | Total Qty |')
lines.append('|---|---|---|---|')
for pair_, info in th['pairs'].items():
    lines.append(f'| {pair_} | {info["count"]} | \${info["avg_entry"]:,.2f} | {info["total_qty"]} |')
lines.append('')

print('\n'.join(lines))
LOCALPY
)

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
if $PRINT; then
  echo "$REPORT"
fi

if $SAVE; then
  echo "$REPORT" > "$OUT_FILE"
  echo "" >&2
  echo "Saved: $OUT_FILE" >&2
fi
