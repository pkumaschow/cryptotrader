#!/usr/bin/env bash
# Called by GitLab CI deploy stage.
# Expects: PI_USER, PI_HOST env vars set by CI.
set -euo pipefail

DEPLOY_PATH="${DEPLOY_PATH:-/opt/cryptotrader}"
SERVICE_NAME="${SERVICE_NAME:-cryptotrader}"

echo "==> Syncing source to ${PI_USER}@${PI_HOST}:${DEPLOY_PATH}"
# The CI checkout is world-writable and -a copies modes verbatim, which left the
# code and config of a bot holding live API keys writable by every local account.
# Strip only the world bit: the root dir must stay group-writable for the DB and lock.
# cryptotrader.db* also covers -wal/-shm, which --delete would otherwise remove
# from under the running service.
rsync -avz --delete \
  --chmod=Do-w,Fo-w \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='cryptotrader.db*' \
  --exclude='cryptotrader.lock' \
  --exclude='.venv' \
  --exclude='tests' \
  --exclude='docs' \
  --exclude='Plans' \
  --exclude='.github' \
  --exclude='public' \
  --exclude='.pytest_cache' \
  --exclude='.ruff_cache' \
  --exclude='.coverage' \
  ./ "${PI_USER}@${PI_HOST}:${DEPLOY_PATH}/"

echo "==> Removing non-runtime directories left by earlier deploys"
# rsync --delete protects excluded paths, so previously-synced copies persist.
# --delete-excluded would also delete .env and cryptotrader.db, which are
# excluded for the opposite reason — so remove only these known paths.
ssh "${PI_USER}@${PI_HOST}" "
  set -e
  for d in tests docs Plans .github public .pytest_cache .ruff_cache; do
    sudo rm -rf ${DEPLOY_PATH:?}/\$d
  done
"

echo "==> Installing dependencies on Pi"
ssh "${PI_USER}@${PI_HOST}" "
  cd ${DEPLOY_PATH} && \
  python3 -m venv --clear venv && \
  venv/bin/pip install --quiet --upgrade pip && \
  venv/bin/pip install --quiet -e .
"

echo "==> Refusing to continue if anything in the deploy is world-writable"
ssh "${PI_USER}@${PI_HOST}" "
  bad=\$(find ${DEPLOY_PATH} \\( -type f -o -type d \\) -perm -o+w)
  if [ -n \"\$bad\" ]; then
    echo 'World-writable paths in ${DEPLOY_PATH}:'; echo \"\$bad\" | head -20
    exit 1
  fi
"

echo "==> Ensuring cryptotrader service account exists"
ssh "${PI_USER}@${PI_HOST}" "
  sudo groupadd -f cryptotrader && \
  id cryptotrader &>/dev/null || sudo useradd -r -s /sbin/nologin -M -g cryptotrader cryptotrader
"

echo "==> Stopping service before ownership changes"
ssh "${PI_USER}@${PI_HOST}" "
  sudo systemctl stop ${SERVICE_NAME} 2>/dev/null || true
"

echo "==> Setting deploy directory ownership"
ssh "${PI_USER}@${PI_HOST}" "
  sudo chown ${PI_USER}:cryptotrader ${DEPLOY_PATH} && \
  sudo chmod 775 ${DEPLOY_PATH} && \
  if [ -f ${DEPLOY_PATH}/.env ]; then
    sudo chown cryptotrader:cryptotrader ${DEPLOY_PATH}/.env && \
    sudo chmod 600 ${DEPLOY_PATH}/.env
  fi && \
  for f in ${DEPLOY_PATH}/cryptotrader.db ${DEPLOY_PATH}/cryptotrader.db-shm ${DEPLOY_PATH}/cryptotrader.db-wal; do
    [ -f \"\$f\" ] && sudo chown cryptotrader:cryptotrader \"\$f\" || true
  done
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
