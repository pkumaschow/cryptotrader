#!/usr/bin/env bash
# Manual deployment script — run from Fedora desktop.
# Deploys the current main branch to the Pi.
#
# Usage:
#   ./deploy/deploy-local.sh
#   ./deploy/deploy-local.sh --skip-pull   # skip git pull, deploy local working tree
set -euo pipefail

PI_USER="${PI_USER:-peterk}"
PI_HOST="${PI_HOST:-192.168.1.66}"
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
echo "==> Syncing to ${PI_USER}@${PI_HOST}:${DEPLOY_PATH}"
rsync -avz --delete \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='cryptotrader.db' \
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
