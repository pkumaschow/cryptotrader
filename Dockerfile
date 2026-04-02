FROM python:3.13-slim

# Upgrade OS packages to apply all Debian security patches
RUN apt-get update -qq && \
    apt-get upgrade -y -qq && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN groupadd -r cryptotrader && useradd -r -g cryptotrader cryptotrader

WORKDIR /app

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
