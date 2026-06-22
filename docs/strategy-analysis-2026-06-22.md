# CryptoTrader Strategy Analysis — 2026-06-22

**Scope:** production only (`mode='production'`, `config/settings.toml` → `active="production"`).
**Data source:** Pi DB `pihole.homelab.com:/opt/cryptotrader/cryptotrader.db`, candles current to
2026-06-22T04:00. All P&L computed via FIFO (DB `pnl` column is unreliable / mostly NULL).

---

## TL;DR

- **No trades since 2026-05-11 (~6 weeks) is correct behaviour, not a fault.** Bollinger here is
  a long-only **breakout** strategy; it only buys upside breakouts in a rising trend with band
  width ≥ 4%. Right now band width is **1.7–2.8%** on all three pairs (low-volatility regime), so
  no buy can fire. The strategy is *designed* to sit out exactly these conditions.
- **The real problem is not entries — it's exits.** The bot holds **3 underwater longs**
  (BTC −22%, ETH −27%, SOL −22%, **−$40 unrealized**) and *cannot sell them*, because the sell
  logic's profit-gate blocks any loss-making exit. **There is no stop-loss.** That is the single
  most important thing to fix for a falling market.
- **"Falling market" nuance:** the recent 10-day move is actually flat-to-up (BTC +1.4%, ETH +4.1%,
  SOL +10.9%). The *fall* is relative to the bot's entry prices. It is bag-holding, not reacting
  to a live crash.
- **Better currencies:** for a breakout strategy that needs ≥4% band width, BTC/ETH are
  structurally poor right now (2026 realized vol is in a *low* regime). Higher-volatility alts
  (SOL > BTC/ETH; XRP, DOGE, AVAX higher still) are a better *fit* — **but only after a stop-loss
  exists**, because higher vol without loss-cutting amplifies the bag-holding problem.

---

## 1. Current state (verified)

| Pair | Realized P&L | Open lot | Entry | Mark (22 Jun) | Drawdown | Unrealized |
|------|-------------:|---------:|------:|-------------:|---------:|-----------:|
| BTC/USD | +$1.09 | 0.000608 | 82,171.9 (11 May) | 64,022 | −22.1% | −$11.04 |
| ETH/USD | −$0.32 | 0.030000 | 2,363.77 (22 Apr) | 1,733.24 | −26.7% | −$18.92 |
| SOL/USD | +$2.52 | 0.500000 | 94.85 (10 May) | 73.78 | −22.2% | −$10.53 |
| **Total** | **+$3.29** | | | | | **−$40.49** |

- **Lifetime realized: +$3.29** across 11 production trades (≈ breakeven; fees ~$0.60/leg eat most edge).
- **Combined mark-to-market: −$37.21.**
- Last trade: **2026-05-11**. Circuit breaker has **never** fired (0 `Feed unhealthy`, 0 `skipping order`).
- Minor reliability note: Kraken WS drops with `1011 keepalive ping timeout` roughly every ~2h and
  auto-reconnects in 1–2s. Not causing the no-trades, but worth a ping-interval tweak later.

## 2. Why there have been no trades (root cause)

Bollinger buy requires **all four** of: `close > upper band`, band **expanding**, `bw% ≥ 4.0`,
and **4h EMA50 trend rising** (`bollinger.py:85-95`). Live state:

| Pair | close>upper? | expanding? | bw% (need ≥4) | 4h trend rising? | Buy possible? |
|------|:---:|:---:|:---:|:---:|:---:|
| BTC/USD | no | no | **1.66** | no | no (4/4 fail) |
| ETH/USD | no | yes | **1.92** | yes | no (bw% + breakout) |
| SOL/USD | no | no | **2.83** | yes | no (bw% + breakout) |

The binding constraint on every pair is **band width far below the 4% gate** — i.e. volatility is
compressed. This matches the external picture: in 2026 BTC realized vol collapsed to ~25% (25th
percentile, "trough" territory). Low vol → tight bands → breakout strategy stays flat. **Working
as designed.** Do **not** lower the 4% gate to force trades — it was raised to 4% on 2026-05-26
specifically because trading BTC/ETH in chop *lost* money; lowering it re-introduces those losses.

## 3. The real flaw for a falling market: no stop-loss

Sell logic (`bollinger.py:96-107`):

```python
if last_close < curr_mid:
    if (self._fee_per_trade > 0 and self._entry_price is not None
        and (last_close - self._entry_price) * self._quantity < self._fee_per_trade * 2):
        return None          # <-- skips the sell
    # ... otherwise SELL
```

The profit-gate was meant to avoid selling for a profit too small to cover fees. But because
`(last_close - entry)` is **negative** for any underwater position, the condition is **always**
true when you're losing — so **a losing position is never sold.** The bot will hold a bag until
it returns to > entry + 2×fees, however far it falls. That is why all three positions are sitting
at −22% to −27% with no exit. **In a falling market this is the dangerous behaviour, not the lack
of new buys.**

## 4. Is bollinger the right strategy for a falling market?

Honest framing: this is a **long-only spot bot — it cannot short**, so it can never *profit* from
a fall. The only things a long-only bot can do in a downtrend are (a) **preserve capital** by
staying flat, or (b) **accumulate** cheaply if you believe in mean reversion. Today's strategy
does (a) on the entry side (correctly sits out) but **fails on risk control** (won't cut losers).

So "is there a better strategy?" splits into two real options:

- **Keep breakout + add risk control (recommended).** Stay long-only-momentum, but stop bag-holding.
- **Add a separate accumulation/DCA sleeve** for falling markets (mean reversion). The existing
  `threshold` strategy already does fixed-price accumulation. Note its configured triggers are now
  *above* market (BTC buy 65,000 vs 64,022; ETH 1,900 vs 1,733; SOL 120 vs 73.78) — if it were
  active it would already be buying. This is the "buy the dip" path, with explicit falling-knife risk.

## 5. Recommendations (prioritized)

> All code/config changes go through the repo (`~/project/cryptotrader/`) + GitLab CI/CD or
> Ansible. **No direct edits on the Pi** (`/opt/cryptotrader/`).

1. **Add a real stop-loss (highest impact).** Decouple loss-cutting from the profit-gate: in
   `bollinger.py`, before the profit-gate, add an unconditional exit when
   `(entry - close) / entry >= stop_loss_pct` (e.g. 8–10%). The profit-gate should only suppress
   *small-profit* sells, never loss-cutting. This alone would have capped the current −$40 at
   roughly −$12–15. *(code change → repo + CI)*
2. **Keep `min_band_width_pct = 4.0`.** It is doing its job (filtering low-vol chop). The absence
   of trades is the filter working, not a bug. *(no change)*
3. **Fix the profit-gate quantity mismatch (minor correctness).** The gate uses `self._quantity`
   (config 0.001 BTC) while budget-based buys use a different lot size (0.000608). Use the actual
   filled quantity so the fee math is right. *(code change → repo + CI)*
4. **Decide on falling-market posture explicitly:** either (a) accept "flat until vol returns"
   (current, safe), or (b) enable a `threshold`/DCA accumulation sleeve on 1 pair as an experiment,
   with a hard per-pair budget cap and a stop. Recommend (a) until the stop-loss in #1 ships.
   *(config/strategy change → repo + CI)*
5. **Tune the WS keepalive** (lower ping interval / client-side ping) to stop the ~2-hourly
   reconnects. Low priority — not affecting trades. *(code change → repo + CI)*

## 6. Better currencies to trade?

For **this** (breakout) strategy, the asset must produce band widths that clear 4%. Evidence:

- BTC/ETH are in a **low realized-vol regime** in 2026 (BTC ~25% 7-day RV, trough territory) →
  bands stay ~1.7–1.9% → **structurally few/no signals.** They are a poor fit *right now*.
- SOL is meaningfully more volatile (band width 2.83% vs BTC 1.66%) and is the best of the three.
- Higher-volatility majors/alts in 2026 — **XRP, DOGE, AVAX, SOL** — are the assets actually
  printing large moves (early-2026: XRP +27%, DOGE +24%, AVAX +17%, SOL +12%). These would
  generate breakout signals a 4% filter can act on.
- Your own staging backtest (2026-05-26) already showed bollinger only *profited* on a
  high-volatility pair (BABY) and lost on BTC/ETH — same conclusion from a different angle.

**Recommendation:** if the goal is for the breakout strategy to actually trade, shift at least one
slot from BTC/ETH toward a higher-vol pair (SOL stays; consider adding XRP or AVAX) — **but only
after the stop-loss (#1) exists.** Higher volatility + no loss-cutting = bigger bags. Validate any
new pair in the staging (`mode=test`) DB first, applying Kraken taker fees (~0.26%/leg) in post.

---

## Appendix — method & verification

- Production trades filtered `WHERE mode='production'` (11 rows); FIFO with partial-lot handling.
- Indicators recomputed from DB candles: tf=60 for Bollinger(20, 2σ, population), tf=240 EMA50 for
  the trend filter — matching `strategy/bollinger.py` + `strategy/_indicators.py`.
- Marks: latest tf=60 close per pair at 2026-06-22T04:00 (BTC 64,022 / ETH 1,733.24 / SOL 73.78).
- Circuit breaker / feed health checked via log greps (both 0). WS instability from `cryptotrader.log`.
- External vol regime: 2026 BTC/ETH low realized vol; SOL/XRP/DOGE/AVAX highest-vol (sources below).

**Sources (market regime):**
- [Amberdata — Crypto Markets Early 2026](https://blog.amberdata.io/crypto-markets-in-early-2026-rally-builds-as-etf-flows-return)
- [CoinDesk — volatility cools, futures tilt bearish](https://www.coindesk.com/markets/2026/04/03/crypto-consolidates-as-volatility-cools-and-futures-markets-tilt-bearish)
- [Analytics Insight — Best High-Volatility Coins 2026](https://www.analyticsinsight.net/cryptocurrency-analytics-insight/best-high-volatility-crypto-coins-for-trading-in-2026)

---

## Stop-Loss Backtest (added 2026-06-22)

**Method:** replayed the *real* `BollingerStrategy` (production params: period 20, 2σ, bw%≥4, 4h
EMA50 trend filter) over historical hourly candles (BTC/ETH/SOL, 28 Mar – 22 Jun), feeding closes
as ticks and sweeping `stop_loss_pct`. Fees $0.60/leg. This is a clean-code simulation, not a
replay of actual order history (config changed over the period) — but the simulated entries land
within ~1% of the real ones (e.g. BTC sim 81,578 vs real 82,172), so it's representative.

| stop % | closed | wins | losses | realized $ | open (unreal) $ | **combined $** | worst trade drawdown $ |
|-------:|-------:|-----:|-------:|-----------:|----------------:|---------------:|-----------------------:|
| 0 (current) | 6 | 5 | 1 | +3.55 | −50.27 | **−46.73** | −26.25 |
| 5 | 12 | 6 | 6 | −15.13 | 0.00 | **−15.13** | −4.25 |
| 8 | 11 | 6 | 5 | −16.83 | 0.00 | **−16.83** | −7.16 |
| 10 | 11 | 6 | 5 | −21.71 | 0.00 | **−21.71** | −8.53 |
| 15 | 11 | 6 | 5 | −29.70 | 0.00 | **−29.70** | −12.36 |

**Findings:**
- **No stop = bag-holding.** Current behaviour ends holding all 3 positions at −$50 unrealized
  (combined −$46.73). It "wins" 5 of 6 closed trades, but the open exposure dwarfs the realized
  edge — the classic *wins small, holds big losers* failure mode.
- **Any stop closes the bags** (open $0 at every level) and **cuts total loss** from −$47 to as
  little as −$15, while slashing worst single-trade drawdown from −$26 to −$4.
- **Tighter is better — in this regime.** 5% < 8% < 10% < 15% on total loss, because a tighter
  stop bleeds less per stopped trade. Stops also trade more (12 vs 6) at a lower win rate (50% vs
  83%) — they convert held bags into realized small losses and re-enter on the next breakout.
- **Nothing is profitable here.** A long-only breakout strategy can't win this choppy/down regime
  (consistent with the 2026-05-26 staging finding). The stop is **risk control, not alpha.**

**Caveat:** this is one unfavourable (down/choppy) window, which biases the result toward
"tighter is better." A 5% stop would whipsaw out of winners in a sustained uptrend. Don't over-fit.

**Recommendation:** enable a stop for tail protection. **8%** is the balanced pick — only ~$1.70
worse than 5% here but materially less whipsaw-prone; choose **5%** if you want strict capital
preservation. **Avoid ≥15%** (barely better than holding on tail risk, worst on total). Revisit
the level if the regime turns trending-up.

### Staging cross-pair backtest (added 2026-06-22)

Re-ran the same harness over the **staging** universe (BTC/ETH/XDG/XLM/BABY, 24 Apr – 22 Jun) —
the canonical backtest DB (mode=test, all pairs, same window), which adds the higher-volatility
pairs the production set lacks. Percentage taker fee 0.26%/leg (notionals range $8–73).

| stop % | closed | wins | losses | realized $ | open $ | **combined $** | worst drawdown $ |
|-------:|-------:|-----:|-------:|-----------:|-------:|---------------:|-----------------:|
| 0 | 8 | 7 | 1 | +6.46 | −20.42 | **−13.96** | −22.32 |
| 5 | 23 | 10 | 13 | −2.04 | 0.00 | **−2.04** | −4.25 |
| 8 | 21 | 9 | 12 | −7.54 | 0.00 | **−7.54** | −7.16 |
| 10 | 18 | 9 | 9 | −8.34 | −0.43 | **−8.77** | −8.53 |
| 15 | 16 | 9 | 7 | −12.21 | −0.43 | **−12.64** | −12.36 |

**Combined net P&L $ by pair × stop:**

| pair | s0 | s5 | s8 | s10 | s15 |
|------|---:|---:|---:|----:|----:|
| BTC/USD | −17.63 | −4.83 | −7.39 | −8.93 | −12.43 |
| ETH/USD | +1.48 | +1.48 | +1.48 | +1.48 | +1.48 |
| XDG/USD | −0.42 | −1.16 | −0.51 | −0.42 | −0.42 |
| XLM/USD | +0.11 | +1.94 | +0.92 | +0.24 | +0.71 |
| BABY/USD | +2.51 | +0.53 | −2.03 | −1.14 | −1.97 |

**Findings:**
- **Same shape** as the production-candle run: no stop = bag-holding (combined −$13.96, worst
  drawdown −$22); any stop closes the bag and caps tail risk (−$22 → −$4 at 5%); nothing is profitable.
- **Losses concentrate in BTC** (−$17.63 unstopped — the low-vol large-cap trap). The stop helps
  BTC the most (−17.63 → −4.83 at 5%).
- **CRITICAL nuance — a tight stop *hurts* the highest-vol pair.** BABY is **+2.51 unstopped but
  −2.03 at an 8% stop** — a tight stop whipsaws a high-volatility asset out of positions that
  recover. XLM (mid-vol) peaks at 5% (+1.94). So *"tighter is better"* holds **only** for low-vol
  large-caps that get trapped — **not** for high-vol alts.

**Refined recommendation (supersedes the single-number pick above):**
`stop_loss_pct` is **per-currency** (the field added supports this). Set a **tight-to-moderate
stop (5–8%) on BTC/ETH/SOL** (large/mid caps that get trapped — BTC benefits most), and a **wide
stop or none on high-volatility pairs** (BABY-like) to avoid whipsaw. This also sharpens the
*better-currencies* answer: the strategy's losses are largely a **BTC problem**; XLM/BABY were
net-positive **without** a stop — so if you add high-vol pairs, pair them with a wide/no stop, not
the same number you'd use on BTC.
