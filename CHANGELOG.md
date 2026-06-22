# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2026-06-22

### Added
- Bollinger stop-loss: new per-currency `stop_loss_pct` (default `0.0` = disabled) exits a losing
  position when price falls that percentage below entry, regardless of the small-profit sell gate —
  preventing indefinite bag-holding in a downtrend. Left disabled in production pending a chosen
  threshold.

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
