FROM python:3.11-slim

RUN groupadd -r cryptotrader && useradd -r -g cryptotrader cryptotrader

WORKDIR /app

# Install dependencies first for layer caching
COPY pyproject.toml ./
COPY cryptotrader/ ./cryptotrader/
COPY scripts/ ./scripts/
COPY config/ ./config/

RUN pip install --no-cache-dir . && \
    chown -R cryptotrader:cryptotrader /app

USER cryptotrader

# Database is written to the working directory — mount a volume to persist it
VOLUME ["/app"]

ENTRYPOINT ["python", "-m", "cryptotrader.main"]
