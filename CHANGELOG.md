# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-08-28

Two of the fixes below correct bugs that could lose real money in production.
If you run this bot with `budget_usd` set, **upgrade before trading again**.

### Fixed

- **Production sells disposed of more than was bought.** `budget_usd` sized buys
  (`quantity = budget_usd / price`) while sells used the static `quantity` from
  config. With `budget_usd = 50` against a `quantity` of `0.001` BTC, each buy
  acquired ~0.00062 BTC and each sell disposed of 0.001 — 61% more than was ever
  held, drawn from the account's own balance. Sells are now sized from the open
  position in the trade log, and a sell with no open position is refused rather
  than placed.
- **A refused order left the strategy believing it held a position.** A strategy
  flips its own state when it emits a signal, but the executor can decline the
  order afterwards — insufficient balance, a hard cap, the daily loss limit — and
  that return value was discarded. The strategy was left long against an entry
  price that was never paid, and the next exit signal sold coin nobody had
  bought. Emitting a signal now arms a rollback which the trader resolves against
  what actually happened. The same applies when the price feed is unhealthy and
  the order is skipped, and when a hard-cap breach raises.
- **The exit gate measured profit against the wrong quantity** and, on any
  position not sized ~$75, against the wrong fee. Fees are a percentage of
  notional, not a flat amount.
- **Realized P&L is recorded on the closing leg** of each round trip, FIFO
  matched. Previously `pnl` was always NULL. A sell with no matching buy still
  stores NULL, which is the honest answer rather than a fabricated zero.

### Added

- **Stop-loss.** Per-currency `stop_loss_pct` exits a losing position regardless
  of the small-profit sell gate, which otherwise blocks every loss-making exit
  and holds a bag indefinitely. Disabled by default; set it deliberately.
- **Refused orders are recorded and displayed.** Insufficient balance, cap
  breaches, daily-loss halts and refused sells are written to a `rejected_orders`
  table and shown in the TUI trade log, instead of existing only as a log line.
  A declined order is not a non-event: it is what precedes a phantom position.
- **Daily invariant check** (`scripts/daily_check.py`) with a systemd timer.
  Assertions rather than a report — over-selling, unbacked sells, declined
  orders, stale positions, a position past its stop, feed freshness, service
  health. Deliberately not a daily summary: a report you must read every morning
  is how six weeks of bag-holding went unnoticed.
- **Backtest harness** (`scripts/backtest.py`) for comparing strategy variants,
  gated behind `--validate`, which asserts the baseline reproduces real recorded
  trades before any variant is trusted.
- **Reconciliation against exchange balances.** Compares trade-log holdings to
  what the exchange actually holds. Alerts on drift from a recorded baseline
  rather than on raw inequality, since an account that predates the bot or
  carries manual trades is expected to differ.
- **Post-only maker entries**, opt-in and off by default. Kraken charges 0.80%
  taker and 0.40% maker at low volume, so a resting limit halves the fee on any
  leg that fills. Entries only — an unfilled buy costs an opportunity, while an
  unfilled sell means holding a position the strategy decided to close. Refuses
  to run in production until fill confirmation reconciles against the exchange.

### Changed

- Fees are modelled as a percentage of notional throughout. A flat per-trade
  figure is only correct at one position size, and made larger positions look
  cheaper per trade than they are — position size does not move a percentage
  hurdle.
- `open_position_quantity` floors at zero on each sell, so a historical
  over-sell cannot carry a negative balance forward and swallow the next buy.

### Security

- The test suite can no longer reach the live exchange. The shipped
  `settings.toml` runs in production mode, so any test reaching `get_settings()`
  without pinning the mode took the production path and attempted a real balance
  check. Outbound calls are now refused by default.
- Trivy filesystem and image scans gate the pipeline; `pip` is stripped from the
  runtime image.

## [1.1.0] - 2026-05-26

### Added
- Bollinger higher-timeframe trend filter: when `trend_filter_enabled` is set, a breakout BUY
  only fires while the trend EMA (`trend_timeframe_minutes`, default 4h; `trend_ema_period`,
  default 50) is rising. Enabled for large-caps, which also raise `min_band_width_pct` to 4.0.
- Circuit breaker that halts trading when the price feed goes stale.
- Configurable daily loss limit, plus mandatory per-trade and per-day hard caps on order size.
- Per-buy USD budget configuration for production trading.
- SOL/USD added to production; XDG/USD, XLM/USD, and BABY/USD added to staging.
- Separate staging and production configs with dual deployment on distinct ports.
- Rate limiting and response caching on the health endpoint.
- Per-panel TUI toggle flags and keyboard shortcuts.
- Strategy-effectiveness analysis script and snapshot reports.
- Trivy dependency and container-image scanning in CI.
- Dedicated `cryptotrader` service account for the systemd service.

### Changed
- Bollinger strategy tuned to reduce false breakouts, and only takes trades whose expected move
  exceeds the Kraken per-trade fee.
- Threshold strategy now persists position state across restarts.
- Kraken API nonce uses a monotonic counter instead of the wall clock.
- Price queue drops the oldest tick when full (previously dropped the newest).
- Base container image upgraded to `python:3.14-slim`.
- CI lint and test dependencies pinned via `uv`.

### Fixed
- Graceful handling of Kraken server resets and network connection failures.
- Production monitoring filters out non-production log noise.

### Security
- Pinned Kraken SSL certificate and Python dependencies.
- systemd service hardening; the service runs under a dedicated low-privilege account.
- Restricted `.env` file permissions.
- Bumped aiohttp to patch CVEs; added Trivy scanning to the pipeline.

## [1.0.0] - 2026-04-06

### Added
- Initial release: asyncio trading bot consuming the Kraken WebSocket price feed.
- Multi-strategy engine with per-trade strategy tagging: `threshold`, `ema`, `bollinger`,
  and `trend_pullback`.
- OHLC candle aggregation with persistence to SQLite (WAL mode).
- Live Textual TUI: live prices, weekly summary, account balance, service health, trade log,
  and per-strategy test statistics.
- Monitor mode: a read-only TUI that runs alongside an active service.
- Production order execution via the Kraken REST API, account-balance display, and manual
  deposit logging.
- Instance lock that prevents duplicate trades from concurrent instances.
- Ansible + systemd deployment, a manual deploy script, and multi-arch (amd64/arm64)
  Docker/Podman images.
- Pre-commit hooks running ruff and pytest.

### Security
- SLSA build provenance attestations signed with cosign.
