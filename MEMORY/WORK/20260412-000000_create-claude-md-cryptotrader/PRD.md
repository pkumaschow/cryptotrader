---
task: Create CLAUDE.md file for cryptotrader project
slug: 20260412-000000_create-claude-md-cryptotrader
effort: standard
phase: complete
progress: 8/8
mode: interactive
started: 2026-04-12T00:00:00Z
updated: 2026-04-12T00:01:00Z
---

## Context

Create a CLAUDE.md project guide for the cryptotrader repo. This file tells AI assistants
about the project architecture, conventions, and how to work with it effectively.

Cryptotrader is a Python async trading bot for Kraken exchange with 4 strategies (Threshold,
EMA, Bollinger, TrendPullback), a Textual TUI, SQLite trade log, and two modes: test/production.

## Criteria

- [x] ISC-1: Project overview section accurately describes cryptotrader purpose
- [x] ISC-2: Tech stack section lists Python 3.11+, asyncio, Pydantic, Textual, aiohttp, SQLite
- [x] ISC-3: Architecture section covers main components and their roles
- [x] ISC-4: All 4 strategies named: Threshold, EMA, Bollinger, TrendPullback
- [x] ISC-5: Run/test commands documented: headless, TUI, pytest, ruff
- [x] ISC-6: Configuration section covers settings.toml and .env secrets
- [x] ISC-7: Key conventions documented: ruff line-length 100, py311, pre-commit hooks
- [x] ISC-8: Deployment info: deploy scripts, Docker/Podman, systemd service

## Decisions

Used inline Explore (Glob/Read/Grep tools) during OBSERVE to understand codebase before writing.

## Verification
