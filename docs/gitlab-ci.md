# GitLab CI/CD Pipeline

## Overview

Three stages run on every push to any branch:

| Stage | Job | Image | Trigger |
|---|---|---|---|
| `lint` | `ruff check` | python:3.11-slim | push |
| `test` | `pytest` + coverage | python:3.11-slim | push |
| `deploy` | rsync + SSH to Pi | alpine:latest | manual, `main` branch only |

Runner: Kubernetes runner tagged `cryptotrader`, namespace `cryptotrader-runner`.

## Required CI/CD Variables

Set at: **GitLab → Project → Settings → CI/CD → Variables**

| Variable | Protected | Description |
|---|---|---|
| `PI_SSH_PRIVATE_KEY` | Yes | Base64-encoded SSH private key for Pi access |
| `PI_HOST` | Yes | Pi hostname or IP address (e.g. `192.168.1.66`) |
| `PI_USER` | Yes | SSH username on the Pi (e.g. `peterk`) |

### Encoding the SSH key

```bash
# Encode — paste output into GitLab variable
base64 -w 0 ~/.ssh/id_rsa

# Verify the round-trip is clean
echo "<paste value>" | base64 -d | ssh-keygen -y -f /dev/stdin
```

The CI script decodes it with `base64 -d` before passing to `ssh-add`. Do **not** store the raw key — GitLab variable storage strips newlines, which breaks PEM format.

## Pi Prerequisites

- Public key matching `PI_SSH_PRIVATE_KEY` present in `~/.ssh/authorized_keys` on Pi
- `rsync`, `python3`, `pip` installed
- `/opt/cryptotrader/` exists and is writable by `PI_USER`
- Passwordless `sudo` for `systemctl` commands (required by `deploy/deploy.sh`):

```
# /etc/sudoers.d/cryptotrader
peterk ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload, \
                            /usr/bin/systemctl enable cryptotrader, \
                            /usr/bin/systemctl restart cryptotrader, \
                            /usr/bin/cp /opt/cryptotrader/deploy/cryptotrader.service /etc/systemd/system/
```

## Deploy Process

The `deploy` job runs `deploy/deploy.sh` which:

1. `rsync` source to `/opt/cryptotrader/` (excludes `.git`, `__pycache__`, `.env`, `cryptotrader.db`)
2. `pip install -e .` inside Pi venv
3. Copies `deploy/cryptotrader.service` to `/etc/systemd/system/`
4. `systemctl daemon-reload && systemctl enable && systemctl restart cryptotrader`

Trigger manually via **GitLab → CI/CD → Pipelines → Run pipeline** or the deploy job's play button.

## Coverage Reporting

- Coverage % extracted from pytest stdout — visible next to the test job in pipeline view
- Cobertura XML artifact (`coverage.xml`) enables per-line diff annotations in Merge Requests
- Coverage history graph: **GitLab → Project → Analytics → CI/CD**
