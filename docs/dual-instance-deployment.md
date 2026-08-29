# Dual-Instance Deployment (Staging + Production)

Two instances of cryptotrader run on `your-pi-host` (`your-pi-host`):

- **staging** — paper trading, auto-deploys on every merge to `main`
- **production** — live trading, manual deploy gated behind staging success

---

## Directory Layout

```
your-pi-host
├── /opt/cryptotrader/           ← production (live trading)
│   ├── .env                     ← prod Kraken keys + HEALTH_PORT=8080 (default, optional)
│   ├── venv/
│   └── cryptotrader.db
└── /opt/cryptotrader-staging/   ← staging (paper trading)
    ├── .env                     ← staging Kraken keys + HEALTH_PORT=8081
    ├── venv/
    └── cryptotrader.db
```

---

## Environment Files

**`/opt/cryptotrader/.env`** (production):
```env
KRAKEN_API_KEY=<live key>
KRAKEN_API_SECRET=<live secret>
```

**`/opt/cryptotrader-staging/.env`** (staging):
```env
KRAKEN_API_KEY=<staging key>
KRAKEN_API_SECRET=<staging secret>
HEALTH_PORT=8081
```

`HEALTH_PORT` prevents both instances binding to port 8080 simultaneously.
Paper vs live trading mode is controlled by `mode.active` in `config/settings.toml`, not the `.env`.

---

## Systemd Services

Both service files live in `deploy/` and are synced to the Pi on each deploy.

| Service | File | Path |
|---|---|---|
| Production | `deploy/cryptotrader.service` | `/etc/systemd/system/cryptotrader.service` |
| Staging | `deploy/cryptotrader-staging.service` | `/etc/systemd/system/cryptotrader-staging.service` |

The staging service is identical to production except all paths point to `/opt/cryptotrader-staging` and the description reads `CryptoTrader (Staging)`. All hardening directives (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem`, etc.) are preserved in both.

---

## Pi Prerequisites (one-time manual setup)

```bash
# 1. Create staging directory
sudo mkdir -p /opt/cryptotrader-staging
sudo chown peterk:peterk /opt/cryptotrader-staging

# 2. Create staging .env
cat > /opt/cryptotrader-staging/.env <<'EOF'
KRAKEN_API_KEY=<staging key>
KRAKEN_API_SECRET=<staging secret>
HEALTH_PORT=8081
EOF
chmod 600 /opt/cryptotrader-staging/.env

# 3. Install staging service (after first pipeline run copies the file)
sudo cp /opt/cryptotrader-staging/deploy/cryptotrader-staging.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cryptotrader-staging

# 4. Sudoers — passwordless restart and service install for both instances
sudo tee /etc/sudoers.d/cryptotrader > /dev/null <<'EOF'
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart cryptotrader
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart cryptotrader-staging
peterk ALL=(ALL) NOPASSWD: /bin/cp /opt/cryptotrader/deploy/cryptotrader.service /etc/systemd/system/cryptotrader.service
peterk ALL=(ALL) NOPASSWD: /bin/cp /opt/cryptotrader-staging/deploy/cryptotrader-staging.service /etc/systemd/system/cryptotrader-staging.service
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable cryptotrader
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable cryptotrader-staging
EOF
sudo chmod 440 /etc/sudoers.d/cryptotrader
```

---

## CI/CD Pipeline

```
push to main
     │
     ▼
lint → test → docker
                 │
                 ▼
          deploy-staging   (auto, on_success)
                 │
                 ▼  [manual button only appears after staging succeeds]
          deploy            (manual trigger → production)
```

Both deploy jobs call `deploy/deploy.sh`. The script is parameterised via environment variables:

| Variable | Production | Staging |
|---|---|---|
| `DEPLOY_PATH` | `/opt/cryptotrader` (default) | `/opt/cryptotrader-staging` |
| `SERVICE_NAME` | `cryptotrader` (default) | `cryptotrader-staging` |

The staging CI job sets these inline:
```yaml
script:
  - DEPLOY_PATH=/opt/cryptotrader-staging SERVICE_NAME=cryptotrader-staging bash deploy/deploy.sh
```

No new CI/CD variables are needed — both jobs reuse `PI_SSH_PRIVATE_KEY`, `PI_HOST`, and `PI_USER`.

---

## Health Check Endpoints

| Instance | URL |
|---|---|
| Production | `http://your-pi-host:8080/health` |
| Staging | `http://your-pi-host:8081/health` |

---

## Logs and Status

```bash
# Production
journalctl -u cryptotrader -f
systemctl status cryptotrader

# Staging
journalctl -u cryptotrader-staging -f
systemctl status cryptotrader-staging
```
