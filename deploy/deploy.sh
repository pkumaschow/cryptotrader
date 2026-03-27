#!/usr/bin/env bash
# Called by GitLab CI deploy stage.
# Expects: PI_USER, PI_HOST env vars set by CI.
set -euo pipefail

DEPLOY_PATH="/opt/cryptotrader"

echo "==> Syncing source to ${PI_USER}@${PI_HOST}:${DEPLOY_PATH}"
rsync -avz --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='cryptotrader.db' \
  ./ "${PI_USER}@${PI_HOST}:${DEPLOY_PATH}/"

echo "==> Installing dependencies on Pi"
ssh "${PI_USER}@${PI_HOST}" "
  cd ${DEPLOY_PATH} && \
  python3 -m venv venv && \
  venv/bin/pip install --quiet --upgrade pip && \
  venv/bin/pip install --quiet -e .
"

echo "==> Copying systemd service"
ssh "${PI_USER}@${PI_HOST}" "
  sudo cp ${DEPLOY_PATH}/deploy/cryptotrader.service /etc/systemd/system/ && \
  sudo systemctl daemon-reload && \
  sudo systemctl enable cryptotrader && \
  sudo systemctl restart cryptotrader
"

echo "==> Deployment complete"
ssh "${PI_USER}@${PI_HOST}" "sudo systemctl status cryptotrader --no-pager"
