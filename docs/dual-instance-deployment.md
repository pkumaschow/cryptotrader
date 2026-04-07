# Dual-Instance Deployment (Production + Test)

Running a production instance and a test/paper-trading instance of cryptotrader on the same host (`pihole.homelab.com`).

## Directory Layout

```
/opt/cryptotrader/          ← production (live trading)
  .env                      ← prod API keys + TRADING_MODE=live
  *.py, requirements.txt

/opt/cryptotrader-test/     ← test (paper trading)
  .env                      ← test API keys + TRADING_MODE=paper
  *.py, requirements.txt
```

## Environment Files

**`/opt/cryptotrader/.env`** (production):
```env
KRAKEN_API_KEY=<live key>
KRAKEN_API_SECRET=<live secret>
TRADING_MODE=live
```

**`/opt/cryptotrader-test/.env`** (test):
```env
KRAKEN_API_KEY=<sandbox or sub-account key>
KRAKEN_API_SECRET=<sandbox or sub-account secret>
TRADING_MODE=paper
```

Use a separate Kraken sub-account or the Kraken sandbox environment for the test instance to ensure no real orders are placed.

## Systemd Services

### Production — `/etc/systemd/system/cryptotrader.service`

Existing service, unchanged.

### Test — `/etc/systemd/system/cryptotrader-test.service`

```ini
[Unit]
Description=CryptoTrader (Test)
After=network.target

[Service]
WorkingDirectory=/opt/cryptotrader-test
EnvironmentFile=/opt/cryptotrader-test/.env
ExecStart=/usr/bin/python3 /opt/cryptotrader-test/main.py
User=peterk
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable cryptotrader-test
sudo systemctl start cryptotrader-test
```

## Sudoers

Both services need passwordless restart for CI/CD deploy:

```
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart cryptotrader
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart cryptotrader-test
```

Add via `sudo visudo -f /etc/sudoers.d/cryptotrader`.

## CI/CD Pipeline

Add a second deploy job to `.gitlab-ci.yml` alongside the existing `deploy` job:

```yaml
deploy-test:
  stage: deploy
  when: on_success        # auto-deploy to test on every main merge
  only:
    - main
  image: alpine:latest
  before_script:
    - apk add --no-cache openssh-client rsync
    - eval $(ssh-agent -s)
    - echo "$PI_SSH_PRIVATE_KEY" | base64 -d | ssh-add -
    - mkdir -p ~/.ssh && chmod 700 ~/.ssh
    - ssh-keyscan -H "$PI_HOST" >> ~/.ssh/known_hosts
  script:
    - rsync -az --delete --exclude='.env' --exclude='*.db'
        . $PI_USER@$PI_HOST:/opt/cryptotrader-test/
    - ssh $PI_USER@$PI_HOST "sudo systemctl restart cryptotrader-test"
```

The existing `deploy` job (production) remains manual-trigger only. Test deploys automatically on every merge to `main`.

Note: `--exclude='.env'` and `--exclude='*.db'` prevent rsync from overwriting the instance-specific env file or the live database.

## Viewing Logs

```bash
# Production
journalctl -u cryptotrader -f

# Test
journalctl -u cryptotrader-test -f
```

## Service Status

```bash
systemctl status cryptotrader
systemctl status cryptotrader-test
```
