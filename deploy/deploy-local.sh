#!/usr/bin/env bash
# Manual deployment script — run from Fedora desktop.
# Deploys the current main branch to the Pi.
#
# Usage:
#   ./deploy/deploy-local.sh
#   ./deploy/deploy-local.sh --skip-pull   # skip git pull, deploy local working tree
set -euo pipefail

PI_USER="${PI_USER:-peterk}"
PI_HOST="${PI_HOST:?set PI_HOST to your deployment target}"
DEPLOY_PATH="/opt/cryptotrader"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SKIP_PULL=false
if [[ "${1:-}" == "--skip-pull" ]]; then
  SKIP_PULL=true
fi

echo "╔══════════════════════════════════════╗"
echo "║  CryptoTrader — Manual Deploy        ║"
echo "║  Target: ${PI_USER}@${PI_HOST}       ║"
echo "╚══════════════════════════════════════╝"
echo ""

# Step 1: pull latest from GitLab
if [[ "$SKIP_PULL" == false ]]; then
  echo "==> Pulling latest from GitLab..."
  cd "$REPO_ROOT"
  git fetch origin
  git checkout main
  git pull origin main
  echo "    Deployed commit: $(git rev-parse --short HEAD) — $(git log -1 --format='%s')"
fi

echo ""
echo "==> Normalising ownership so ${PI_USER} can sync (idempotent)..."
# rsync runs as ${PI_USER}; if a prior op left files owned by the 'cryptotrader'
# service user, rsync can't overwrite them (Permission denied). Reclaim to
# ${PI_USER} first; post-sync we hand secrets/DB back to the service user.
ssh "${PI_USER}@${PI_HOST}" "sudo chown -R ${PI_USER}:cryptotrader ${DEPLOY_PATH} 2>/dev/null || true"

echo ""
echo "==> Syncing to ${PI_USER}@${PI_HOST}:${DEPLOY_PATH}"
rsync -avz --delete \
  --exclude='.git' \
  --exclude='venv' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='cryptotrader.db*' \
  --exclude='cryptotrader.lock' \
  "${REPO_ROOT}/" "${PI_USER}@${PI_HOST}:${DEPLOY_PATH}/"

echo ""
echo "==> Installing dependencies on Pi..."
ssh "${PI_USER}@${PI_HOST}" "
  set -e
  cd ${DEPLOY_PATH}
  python3 -m venv venv
  venv/bin/pip install --quiet --upgrade pip
  venv/bin/pip install --quiet -e .
  echo '    Dependencies installed.'
"

echo ""
echo "==> Restoring deploy directory ownership (rsync ran as ${PI_USER})..."
# rsync over SSH lands files owned by ${PI_USER}; the service runs as the
# 'cryptotrader' user and must be able to write its lock file (and DB) in
# ${DEPLOY_PATH}. Mirror deploy/deploy.sh: PI_USER:cryptotrader + group-writable
# dir, service-user-owned secrets/DB. Without this the bot crash-loops on
# PermissionError: 'cryptotrader.lock'.
ssh "${PI_USER}@${PI_HOST}" "
  set -e
  sudo chown ${PI_USER}:cryptotrader ${DEPLOY_PATH}
  sudo chmod 775 ${DEPLOY_PATH}
  # Drop any stale lock so the freshly-started service (user 'cryptotrader')
  # creates its own writable one instead of crash-looping on a file it can't open.
  sudo rm -f ${DEPLOY_PATH}/cryptotrader.lock
  if [ -f ${DEPLOY_PATH}/.env ]; then
    sudo chown cryptotrader:cryptotrader ${DEPLOY_PATH}/.env
    sudo chmod 600 ${DEPLOY_PATH}/.env
  fi
  for f in ${DEPLOY_PATH}/cryptotrader.db ${DEPLOY_PATH}/cryptotrader.db-shm ${DEPLOY_PATH}/cryptotrader.db-wal; do
    [ -f \"\$f\" ] && sudo chown cryptotrader:cryptotrader \"\$f\" || true
  done
"

echo ""
echo "==> Installing and restarting systemd service..."
ssh "${PI_USER}@${PI_HOST}" "
  set -e
  sudo cp ${DEPLOY_PATH}/deploy/cryptotrader.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable cryptotrader
  sudo systemctl restart cryptotrader
  sleep 2
  sudo systemctl status cryptotrader --no-pager
"

echo ""
echo "✓ Deploy complete."
echo ""
echo "  View logs:  ssh ${PI_USER}@${PI_HOST} 'sudo journalctl -fu cryptotrader'"
echo "  Launch TUI: ssh ${PI_USER}@${PI_HOST} 'cd ${DEPLOY_PATH} && venv/bin/python -m cryptotrader.main --tui'"
