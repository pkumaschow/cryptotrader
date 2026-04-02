# Contributing

## Development Setup

```bash
python3 -m venv venv
venv/bin/pip install -e ".[dev]"
cp .env.example .env
pre-commit install
```

Pre-commit hooks run ruff (lint) and pytest automatically before every commit.

## Code Style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting.

```bash
ruff check cryptotrader/ tests/   # lint
ruff format cryptotrader/ tests/  # format
```

Line length is 100 characters. Target version is Python 3.11.

## Running Tests

```bash
pytest tests/ -v --tb=short
```

To run with coverage:

```bash
pytest tests/ --cov=cryptotrader --cov-report=term-missing
```

## Making Changes

1. Fork the repository and create a branch from `main`
2. Make your changes with tests where applicable
3. Ensure `pre-commit run --all-files` passes cleanly
4. Open a pull request against `main`

Keep pull requests focused — one concern per PR. Include a clear description of what changed and why.

## Commit Messages

Use the imperative mood and keep the subject line under 72 characters:

```
fix: handle WebSocket reconnect on Kraken 1008 close code
feat: add EMA crossover strategy
docs: update deployment notes for Ansible
```

Common prefixes: `fix`, `feat`, `docs`, `test`, `ci`, `chore`, `refactor`.

## Running Locally with Docker

See [README.md](README.md#docker) for Docker and Podman instructions.
