# CryptoTrader Strategy Analysis — 2026-05-04

## Summary

| Strategy | Closed | Wins | Losses | Win Rate | Realised P&L |
|---|---|---|---|---|---|
| bollinger | 19 | 11 | 8 | 58% | **+$17.7544** |
| ema | 1 | 1 | 0 | 100% | **+$6.3455** |
| trend_pullback | 30 | 8 | 22 | 27% | **+$4.5428** |
| **TOTAL** | 50 | 20 | 30 | **40%** | **+$28.6427** |
| threshold | 45 buys | — | — | accumulation | — |

### vs 2026-04-16

| Strategy | Closed Δ | P&L Δ |
|---|---|---|
| bollinger | +2 | +$2.7791 |
| ema | — | — |
| trend_pullback | — | — |
| **TOTAL** | **+2** | **+$2.7791** |

> Only 2 new closes since Apr 16. Both bollinger: ETH sell at loss (-$0.3243) and BTC WIN (+$3.1034). No
> trend_pullback or EMA closes. No trades at all since 2026-04-27T03:00.

---

## Why No Trades Since April 27

**Root cause: market conditions, not a bug.**

All three pairs (BTC, ETH, SOL) are in open bollinger positions. For a new BUY signal, price must break
above the upper Bollinger band while the band is expanding. For a SELL signal, price must close below the
midband. Current prices are sandwiched between mid and upper — neither condition is met.

The April 27 deployment (commit c84c7b3: circuit breaker for stale prices) did NOT cause the silence. Log
inspection confirms zero "Feed unhealthy" messages — the circuit breaker has never fired in production.

**Bollinger band state as of 2026-05-04T07:00 UTC:**

| Pair | Price | Mid | Upper | Position | vs Mid | vs Upper |
|---|---|---|---|---|---|---|
| BTC/USD | $79,689 | $79,183 | $80,482 | IN @ $77,616 (Apr 22) | +$506 above | $793 below |
| ETH/USD | $2,362 | $2,343 | $2,390 | IN @ $2,363 (Apr 22) | +$19 above | $28 below |
| SOL/USD | $84.86 | $84.53 | $85.62 | IN @ $87.83 (Apr 27) | +$0.33 above | $0.76 below |

SOL is only $0.33 above its sell trigger. One weak hourly close could trigger a sell.

**EMA state (20/50 period, hourly):**

| Pair | Fast EMA | Slow EMA | Fast > Slow | Crossover |
|---|---|---|---|---|
| BTC/USD | 79,324 | 78,835 | ✓ Bullish | None |
| ETH/USD | 2,347 | 2,326 | ✓ Bullish | None |
| SOL/USD | 84.63 | 84.27 | ✓ Bullish | None |

All three pairs remain in bullish EMA territory — no sell crossovers imminent.

---

## Open Positions

### Bollinger

| Pair | Entry | Entry Date | Current | Unrealised P&L | Proximity to Sell |
|---|---|---|---|---|---|
| BTC/USD | $77,616.70 | Apr 22 03:00 | $79,689 | **+$2.07** (0.001 qty) | Mid @ $79,183 — $506 buffer |
| ETH/USD | $2,363.77 | Apr 22 05:00 | $2,362 | **-$0.05** (0.03 qty) | Mid @ $2,343 — $19 buffer |
| SOL/USD | $87.83 | Apr 27 03:00 | $84.86 | **-$1.49** (0.5 qty) | Mid @ $84.53 — $0.33 buffer ⚠️ |

### EMA

| Pair | Entry | Entry Date | Current | Unrealised P&L |
|---|---|---|---|---|
| ETH/USD | $2,263.00 | Apr 13 20:00 | $2,362 | **+$4.95** (0.05 qty) |
| BTC/USD | $73,366.20 | Apr 13 20:00 | $79,689 | **+$6.32** (0.001 qty) |

EMA positions are both profitable. Sell requires bearish EMA crossover (fast < slow). Not close.

### Threshold (accumulation mode)

| Pair | Buys | Avg Entry | Total Qty |
|---|---|---|---|
| ETH/USD | 22 | $2,033.23 | 1.100 ETH |
| BTC/USD | 23 | $67,390.86 | 0.023 BTC |

---

## STRATEGY: bollinger

**Closed:** 19 | **Wins:** 11 | **Losses:** 8 | **Win Rate:** 58%
**Total realised P&L: USD +$17.7544**

New closes since Apr 16:

| | Pair | Buy | Sell | Qty | P&L | Hold |
|---|---|---|---|---|---|---|
| LOS | ETH/USD | $2,319.91 | $2,309.10 | 0.03 | -$0.3243 | 14.0h |
| WIN | BTC/USD | $72,435.10 | $75,538.50 | 0.001 | +$3.1034 | 132.0h |

(All prior trades unchanged from 2026-04-16 snapshot.)

**Open (3):** ← Note: previous snapshot showed BTC open @ $75,769.90 — this was closed on Apr 19 at $75,538.50 (loss -$0.2314, not yet in prior analysis as it closed after the Apr 16 snapshot)

---

## STRATEGY: ema

**Closed:** 1 | **Wins:** 1 | **Losses:** 0 | **Win Rate:** 100%
**Total realised P&L: USD +$6.3455**

No new closes since Apr 16.

**Open (2):**
- ETH/USD — entry @ $2,263.00  qty=0.05  since 2026-04-13T20:00  unrealised: +$4.95
- BTC/USD — entry @ $73,366.20  qty=0.001  since 2026-04-13T20:00  unrealised: +$6.32

---

## STRATEGY: trend_pullback

**Closed:** 30 | **Wins:** 8 | **Losses:** 22 | **Win Rate:** 27%
**Total realised P&L: USD +$4.5428**

No new closes since Apr 16. Note: 27% win rate is low but the strategy remains profitable due to
asymmetric win/loss sizes (avg win ~$2.20, avg loss ~$0.60). No open positions.

---

## Issues Found

### 1. Duplicate buy — BTC/USD bollinger (Apr 4)

Trade IDs 2335 and 2336 are identical: both `buy @ $67,151.30 qty=0.001` at `2026-04-04T11:00:00`.
The strategy's `_in_position` flag should prevent this. Likely caused by two processes running
simultaneously before the "already running → monitor mode" detection was in place. Not currently
active. The circuit breaker (Apr 27) guards against stale-feed trading but does not address
duplicate-process execution.

### 2. No stop-loss on any strategy

All three strategies (bollinger, ema, trend_pullback) exit positions via signal conditions only — no
stop-loss. SOL bollinger is currently at -$1.49 (-3.4% from $87.83 entry). If the Bollinger midband
drifts down with price, the sell trigger follows it down, potentially locking in a larger loss before
exit. The strategy will sell when price closes below the midband; it does NOT cut losses at a fixed %.

---

## Tweak Recommendations

These are recommendations only. No changes have been made.

### A. Add stop-loss to bollinger strategy [optional, discuss]

A fixed stop below entry (e.g., -5%) would have exited SOL already. Current design is intentional
(Bollinger bands adapt to volatility), but a hard floor would cap downside. Tradeoff: early stop-outs
on volatile assets could cut profitable positions that recover.

### B. Investigate duplicate buy root cause [low risk, investigate]

Review whether the "already running → monitor mode" detection was present before Apr 4. If not, confirm
it now prevents two live trading instances. The CandleBuilder is correct (can only emit once per candle
boundary); the duplicate must have come from two concurrent strategy.evaluate() calls.

### C. WS reconnect every ~2h [no action needed]

Kraken sends 1011 keepalive ping timeout roughly every 2 hours. The bot reconnects within 1-2s. The
circuit breaker correctly gates trading when `_last_tick_time == 0.0` (i.e., immediately after
reconnect, before the first tick arrives). This is working as designed.

### D. SOL position exit likely imminent [monitor]

SOL at $84.86 is $0.33 above the midband ($84.53). The next weak hourly candle could trigger a sell
at a ~$1.49 loss. No action needed — just awareness.
