# Deployment

Two ways to deploy CryptoTrader to the Pi. **Prefer the CI production job.**
`deploy-local.sh` is the manual desktop fallback.

## Preferred: CI production deploy

Push to `main`, then in the pipeline trigger the **manual** `deploy:` (production) job.

- Pipeline runs lint → test → docker → security → provenance.
- `deploy-staging` auto-deploys to `/opt/cryptotrader-staging` on success.
- `deploy:` (production, `when: manual`) runs `deploy/deploy.sh` and deploys to `/opt/cryptotrader`.

Why preferred: it runs from a **clean git checkout**, so no stray local files leak
(a local `.venv` or a stale `cryptotrader.lock` are the two that have bitten us),
it deploys to staging first, and it sets ownership correctly every time.

## Ownership model (the thing that bites)

The bot runs as the **`cryptotrader`** system user (systemd `User=cryptotrader`,
`WorkingDirectory=/opt/cryptotrader`). The correct on-disk state:

| Path | Owner | Mode | Why |
|------|-------|------|-----|
| `/opt/cryptotrader` (dir) | `peterk:cryptotrader` | `0775` | group-writable so the service can create `cryptotrader.lock` at startup |
| code files | `peterk` | `0644` | the service only needs to read them |
| `.env`, `cryptotrader.db*` | `cryptotrader:cryptotrader` | `0600` | secrets/data owned by the service user |

**Failure mode.** If files get left owned only by `cryptotrader` (e.g. after a
manual `chown -R cryptotrader`), or the dir loses group-write, then:

- rsync-as-`peterk` can't overwrite them → partial deploy (`Permission denied` on
  `mkstemp`), **and/or**
- the service can't open `cryptotrader.lock` for writing → **crash loop** with
  `PermissionError: [Errno 13] Permission denied: 'cryptotrader.lock'`.

Both outages on 2026-07-26 were this. The lock is a transient runtime file — the
fix is almost always "make the dir group-writable and delete the stale lock so the
service recreates its own."

## Fallback: `deploy/deploy-local.sh` (from the desktop)

Deploys the local working tree over SSH + rsync. Hardened to be ownership-safe:

- **pre-rsync:** `chown -R peterk:cryptotrader` so rsync can always overwrite.
- **post-rsync:** dir → `775`, `.env`/DB → `cryptotrader`, and removes any stale
  `cryptotrader.lock`.
- excludes `.git`, `venv`, `.venv`, `.env`, `cryptotrader.db*`, `cryptotrader.lock`.

```bash
bash deploy/deploy-local.sh              # pull main, then deploy
bash deploy/deploy-local.sh --skip-pull  # deploy the working tree as-is
```

Never edit code directly on the Pi — all changes go through git → deploy, or they
get overwritten on the next sync.

## Recovery: bot crash-looping on `PermissionError: cryptotrader.lock`

```bash
sudo chown -R peterk:cryptotrader /opt/cryptotrader
sudo chmod 775 /opt/cryptotrader
sudo chown cryptotrader:cryptotrader /opt/cryptotrader/.env /opt/cryptotrader/cryptotrader.db*
sudo rm -f /opt/cryptotrader/cryptotrader.lock
sudo systemctl restart cryptotrader
```

## Verify a deploy

```bash
ssh youruser@your-pi-host 'systemctl is-active cryptotrader; curl -s localhost:8080/health'
```

Expect `active` and `"status": "ok"` (with `"mode": "production"` and Kraken online).
