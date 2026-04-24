#!/usr/bin/env bash
# Called by GitLab CI deploy stage.
# Expects: PI_USER, PI_HOST env vars set by CI.
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/cryptotrader}"
SERVICE_NAME="${SERVICE_NAME:-cryptotrader}"

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

echo "==> Ensuring cryptotrader service account exists"
ssh "${PI_USER}@${PI_HOST}" "
  sudo groupadd -f cryptotrader && \
  id cryptotrader &>/dev/null || sudo useradd -r -s /sbin/nologin -M -g cryptotrader cryptotrader
"

echo "==> Setting deploy directory ownership"
ssh "${PI_USER}@${PI_HOST}" "
  sudo chown ${PI_USER}:cryptotrader ${DEPLOY_PATH} && \
  sudo chmod 775 ${DEPLOY_PATH} && \
  if [ -f ${DEPLOY_PATH}/.env ]; then
    sudo chown cryptotrader:cryptotrader ${DEPLOY_PATH}/.env && \
    sudo chmod 600 ${DEPLOY_PATH}/.env
  fi && \
  if [ -f ${DEPLOY_PATH}/cryptotrader.db ]; then
    sudo chown cryptotrader:cryptotrader ${DEPLOY_PATH}/cryptotrader.db
  fi
"

echo "==> Copying systemd service"
ssh "${PI_USER}@${PI_HOST}" "
  sudo cp ${DEPLOY_PATH}/deploy/${SERVICE_NAME}.service /etc/systemd/system/ && \
  sudo systemctl daemon-reload && \
  sudo systemctl enable ${SERVICE_NAME} && \
  sudo systemctl restart ${SERVICE_NAME}
"

echo "==> Deployment complete"
ssh "${PI_USER}@${PI_HOST}" "sudo systemctl status ${SERVICE_NAME} --no-pager"
