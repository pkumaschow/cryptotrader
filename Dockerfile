FROM python:3.14-slim

# Cache-bust the apt-upgrade layer so each CI build pulls the latest
# Debian security patches (CI passes APT_REFRESH=${{ github.run_id }}).
ARG APT_REFRESH=daily

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

# pip vendors its own dependency tree (pip/_vendor/vendor.txt) — currently
# msgpack 1.1.2 and setuptools 70.3.0, both carrying HIGH CVEs that fail
# `trivy image` even when the app's own dependencies are clean. Nothing needs
# pip once the app is installed and the entrypoint is `python -m`, so it comes
# out of the final image along with ensurepip's bundled wheel. Same reasoning
# as dropping npm from the node images.
RUN pip install --no-cache-dir . && \
    SITE="$(python -c 'import site; print(site.getsitepackages()[0])')" && \
    STDLIB="$(python -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')" && \
    rm -rf "${SITE}"/pip "${SITE}"/pip-*.dist-info \
           "${STDLIB}/ensurepip" \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.* && \
    chown -R cryptotrader:cryptotrader /app

USER cryptotrader

# Database is written to the working directory — mount a volume to persist it
VOLUME ["/app"]

ENTRYPOINT ["python", "-m", "cryptotrader.main"]
