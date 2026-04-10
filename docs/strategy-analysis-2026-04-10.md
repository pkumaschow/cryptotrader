# Strategy Effectiveness Analysis — 2026-04-10

**Mode:** test  
**Data source:** `pihole.homelab.com:/opt/cryptotrader/cryptotrader.db`  
**Period:** 2026-03-27 → 2026-04-10  
**Total trades:** 97

---

## Summary Table

| Strategy       | Closed | Win Rate | Realised P&L | Open |
|----------------|--------|----------|--------------|------|
| bollinger      | 11     | **64%**  | **+$11.56**  | 1 (BTC) |
| trend_pullback | 14     | 21%      | **-$1.07**   | 2 (BTC+ETH) |
| ema            | 0      | —        | $0.00        | 1 (ETH) |
| threshold      | 0 sells| —        | —            | 43 buys accumulated |

**Combined realised P&L: +$10.49**

---

## Bollinger — Best Performer

64% win rate, +$11.56 across 11 closed trades.

| Result | Pair    | Entry     | Exit      | Qty   | P&L       | Hold |
|--------|---------|-----------|-----------|-------|-----------|------|
| WIN    | ETH/USD | 2028.24   | 2039.83   | 0.05  | +$0.58    | 15h  |
| WIN    | ETH/USD | 2089.80   | 2099.69   | 0.05  | +$0.49    | 33h  |
| LOSS   | ETH/USD | 2064.43   | 2055.99   | 0.05  | -$0.42    | 8h   |
| WIN    | ETH/USD | 2085.17   | 2139.35   | 0.05  | +$2.71    | 23h  |
| WIN    | ETH/USD | 2145.22   | 2195.00   | 0.05  | +$2.49    | 17h  |
| LOSS   | ETH/USD | 2218.13   | 2190.60   | 0.05  | -$1.38    | 8h   |
| LOSS   | BTC/USD | 67059.00  | 66767.70  | 0.001 | -$0.29    | 15h  |
| LOSS   | BTC/USD | 67151.30  | 67080.10  | 0.001 | -$0.07    | 15h  |
| WIN    | BTC/USD | 67151.30  | 68826.50  | 0.001 | +$1.68    | 60h  |
| WIN    | BTC/USD | 67629.30  | 70885.00  | 0.001 | +$3.26    | 66h  |
| WIN    | BTC/USD | 69303.80  | 71826.00  | 0.001 | +$2.52    | 58h  |

**Open:** BTC/USD entry@72141.70 since 2026-04-09T16:00

**Key insight:** Wins hold 17–66h averaging +$1.96. Losses exit at 8–15h averaging -$0.54. This positive asymmetry (win/loss ratio ~3.6x) is healthy.

**Issue flagged:** Duplicate BTC buy at 67151.30 on 2026-04-04T11:00 (two identical timestamps, IDs 2335+2336) — likely a double-fire bug in entry logic.

---

## trend_pullback — Underperforming

21% win rate, -$1.07 across 14 closed trades.

| Result | Pair    | Entry     | Exit      | Qty   | P&L       | Hold |
|--------|---------|-----------|-----------|-------|-----------|------|
| LOSS   | ETH/USD | 2128.26   | 2089.10   | 0.05  | -$1.96    | 1h   |
| WIN    | ETH/USD | 2114.00   | 2195.00   | 0.05  | +$4.05    | 19h  |
| LOSS   | ETH/USD | 2215.50   | 2201.54   | 0.05  | -$0.70    | 3h   |
| LOSS   | ETH/USD | 2214.88   | 2190.16   | 0.05  | -$1.24    | 1h   |
| LOSS   | ETH/USD | 2194.38   | 2190.76   | 0.05  | -$0.18    | 1h   |
| LOSS   | ETH/USD | 2218.13   | 2197.95   | 0.05  | -$1.01    | 7h   |
| LOSS   | ETH/USD | 2197.04   | 2186.39   | 0.05  | -$0.53    | 1h   |
| LOSS   | BTC/USD | 69156.50  | 68230.10  | 0.001 | -$0.93    | 1h   |
| LOSS   | BTC/USD | 68703.00  | 68433.60  | 0.001 | -$0.27    | 1h   |
| WIN    | BTC/USD | 69008.00  | 70885.00  | 0.001 | +$1.88    | 19h  |
| LOSS   | BTC/USD | 71294.50  | 71104.40  | 0.001 | -$0.19    | 3h   |
| LOSS   | BTC/USD | 71322.40  | 71088.70  | 0.001 | -$0.23    | 3h   |
| LOSS   | BTC/USD | 71263.70  | 70806.70  | 0.001 | -$0.46    | 5h   |
| WIN    | BTC/USD | 71131.90  | 71826.00  | 0.001 | +$0.69    | 16h  |

**Open:** ETH/USD entry@2196.11, BTC/USD entry@71797.10 — both since 2026-04-10T10:00

**Key insight:** Nearly all losses held only 1–3h — the strategy is entering on noise and stopping out immediately. The two largest wins (+$4.05, +$1.88) held 19h, showing the signal works when genuine trend conditions exist. Entry filter is too loose.

---

## EMA — Insufficient Data

One open position: ETH/USD entry@2068.45 since 2026-04-05T21:00. No sells recorded yet.

---

## Threshold — Accumulation

43 DCA buys, no sells (expected behaviour). No closed P&L.

| Pair    | Buys | Avg Entry | Total Qty |
|---------|------|-----------|-----------|
| ETH/USD | 21   | $2,023.10 | 1.05 ETH  |
| BTC/USD | 22   | $67,136   | 0.022 BTC |

Positions sitting at roughly +$175 (ETH) and +$103 (BTC) unrealised as of analysis date.

---

## Recommendations

1. **Bollinger** — performing well. Investigate duplicate-fire bug (IDs 2335/2336).
2. **trend_pullback** — add minimum trend confirmation window before entry; 21% win rate at high frequency nearly erases the large wins.
3. **EMA** — too early to judge; needs sell-side signal observed.
4. **threshold** — consider adding a take-profit leg to realise accumulated gains.
