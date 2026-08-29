# Screen Rotator (tty1)

The `your-pi-host` Pi has an attached display. A systemd service owns `tty1` and
rotates between **the CryptoTrader monitor TUI** and **PADD** (the Pi-hole terminal
dashboard) on a timer. Survives reboot, restarts each TUI on crash, and pauses on demand.

Lives on the Pi at:

- `/usr/local/bin/screen-rotator.sh` — the rotator script
- `/etc/systemd/system/screen-rotator.service` — the systemd unit
- `/run/screen-rotator.pause` — touch-to-freeze sentinel (tmpfs, auto-wipes on reboot)

These files are not (yet) wired into `deploy.sh`; copies are inlined in §**Files** below
so this doc is sufficient to reconstruct the setup on a fresh Pi.

---

## Why this exists

For 26+ days the tty1 monitor was started manually with `tmux new-session -s cryptotrader …`
after each boot — fragile, and the Pi-hole dashboard (PADD) wasn't on the display at all.
This service replaces the manual step and adds PADD as a rotating second window.

### Safety note — why running the TUI here is fine

The rotator launches `cryptotrader.main` with **`--monitor-only --tui`**, a strict opt-in
read-only mode added specifically for this use case (see `cryptotrader/main.py`). It:

- **Refuses to acquire the instance lock**, ever.
- Skips the production-secrets check (no API keys needed).
- Goes straight to `_run_monitor()`: read-only Kraken WebSocket subscription + DB poll for
  new trades the live trader has written + Textual TUI rendering.
- **Does not** instantiate a `Trader`, does not place orders, cannot race with
  `cryptotrader.service` for the lock under any circumstances.

So stopping/starting the rotator has zero impact on trading, and the rotator can never
accidentally become the live trader — even if `cryptotrader.service` is briefly down or
slow to acquire its lock at boot.

> **Historical note.** Before `--monitor-only` existed, the rotator used just `--tui`,
> which falls into monitor mode *only when the lock is already held*. That left a startup
> race: if the rotator's Python acquired the lock before `cryptotrader.service` did (which
> actually happened — see the 2026-05-29 incident), the rotator became the real trader,
> often with a stale config. `--monitor-only` makes that impossible by skipping lock
> acquisition entirely.

---

## How it works

`screen-rotator.service` is a `Type=simple` unit that binds to `/dev/tty1` via `TTYPath=`
and runs `screen-rotator.sh` as root. The script:

1. Kills any leftover `display` tmux session from a previous run.
2. Creates a new `display` session, detached, with two windows:
   - window `0: trader` running `cryptotrader.main --monitor-only --tui --hide-stats --hide-weekly --hide-balance`
   - window `1: padd` running `/home/peterk/padd.sh`
3. Each window's command is wrapped in `while true; do …; sleep 10; done` so a transient
   crash sleeps 10 s and relaunches inside the same window — no dead windows.
4. Spawns a background subshell that loops forever: select window 0, sleep
   `INTERVAL_TRADER`, select window 1, sleep `INTERVAL_PADD`. Each select is gated on
   the pause sentinel.
5. `exec tmux attach -t display` foregrounds the session and keeps `Type=simple` happy.

Ordering: the unit declares `After=cryptotrader.service` for politeness, but `--monitor-only`
means the rotator can never grab the lock regardless of ordering — so the race is closed
even if `cryptotrader.service` is slow to acquire its lock. `getty@tty1.service` is already
masked on this Pi, so no `Conflicts=` is needed.

### PADD authentication

PADD v4.1.0 normally prompts for the Pi-hole API password. When running as root and
`SERVER` is local, it reads `/etc/pihole/cli_pw` (mode `640 pihole:pihole`) automatically
and skips the prompt (`padd.sh:213-220`). The rotator runs as root, so no password
handling is needed.

---

## Operating

```bash
# status
sudo systemctl status screen-rotator.service
sudo tmux ls                     # shows: display: 2 windows
sudo tmux list-windows -t display

# start / stop / restart
sudo systemctl start screen-rotator.service
sudo systemctl stop screen-rotator.service     # ExecStopPost kills the tmux session
sudo systemctl restart screen-rotator.service

# pause rotation (freezes on whichever window is currently shown)
sudo touch /run/screen-rotator.pause
sudo rm    /run/screen-rotator.pause           # resume

# peek at what each window is rendering (without going to the Pi)
sudo tmux capture-pane -t display:trader -p
sudo tmux capture-pane -t display:padd   -p

# logs
sudo journalctl -u screen-rotator.service -n 50 --no-pager
```

### Tweaking rotation intervals

Edit the top of `/usr/local/bin/screen-rotator.sh`:

```bash
INTERVAL_TRADER=30   # seconds on the trader window
INTERVAL_PADD=15     # seconds on PADD
```

Then `sudo systemctl restart screen-rotator.service`. No `daemon-reload` needed (the
unit file didn't change).

---

## Verifying it's healthy

```bash
sudo systemctl is-active screen-rotator.service       # active
sudo systemctl is-enabled screen-rotator.service      # enabled
sudo tmux list-windows -t display | wc -l             # 2
pgrep -f 'screen-rotator.sh'                          # one PID
pgrep -f 'cryptotrader.main --monitor-only' | wc -l   # 1 (the monitor)
pgrep -f '/home/peterk/padd.sh' | wc -l               # 1 (PADD)
```

Cold-boot recovery time is ~10 s for the rotator to come up after kernel reaches
multi-user.target, plus ~30 s for `cryptotrader.service` to transition from `activating`
to `active` (its existing behaviour, unrelated to the rotator).

---

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| Service active but screen blank | PADD or trader exited and is in its 10 s sleep before relaunch | `sudo journalctl -u screen-rotator.service`; `pgrep -af padd.sh \| cryptotrader.main` |
| PADD prompts for password | Something changed `/etc/pihole/cli_pw` perms so root can't read it (unlikely), or PADD is running as non-root | `ls -la /etc/pihole/cli_pw`; `ps -ef \| grep padd.sh` (should be uid 0) |
| Trader window shows "ERROR: Another CryptoTrader instance is already running" | The rotator is invoking without `--monitor-only` (old behavior). Check the `TRADER_CMD` line in `/usr/local/bin/screen-rotator.sh` includes `--monitor-only`. | `grep monitor-only /usr/local/bin/screen-rotator.sh` |
| Rotation stuck on one window | `/run/screen-rotator.pause` exists | `ls /run/screen-rotator.pause` then `rm` it |
| Service won't start, restart loops | Bad script edit or missing tmux/padd path | `sudo systemctl status screen-rotator.service`; `bash -n /usr/local/bin/screen-rotator.sh` |
| PADD renders smaller than the screen | PADD's largest layout is `mega = 80×26`; it auto-centers in the larger terminal. Not a bug — by design. | To fill more of the screen, install a bigger console font (e.g. `Lat15-Terminus24x12`). Tradeoff: the trader TUI also gets fewer columns. |

---

## Files

### `/usr/local/bin/screen-rotator.sh` (0755 root:root)

```bash
#!/usr/bin/env bash
# Rotates tty1 display between the cryptotrader monitor TUI and PADD.
# Started by /etc/systemd/system/screen-rotator.service on boot.
#
# Tweakables:
#   - INTERVAL_TRADER / INTERVAL_PADD : seconds per window before rotation
#   - PAUSE_FILE : touch this file to freeze rotation on whatever's currently shown
#
# Notes:
#   - Runs as root (set in the service unit). PADD reads /etc/pihole/cli_pw
#     automatically and skips its password prompt.
#   - The cryptotrader --monitor-only --tui invocation refuses to acquire the lock,
#     so the rotator can never accidentally become the live trader.

set -u

SESSION="display"
INTERVAL_TRADER=30
INTERVAL_PADD=15
PAUSE_FILE="/run/screen-rotator.pause"

TRADER_CMD='cd /opt/cryptotrader && exec venv/bin/python -m cryptotrader.main --monitor-only --tui --hide-stats --hide-weekly --hide-balance'
PADD_CMD='exec /home/peterk/padd.sh'

# Restart wrapper: if a TUI exits (crash, normal exit), sleep then restart so the
# window stays alive across transient failures instead of going blank.
TRADER_WRAPPED="while true; do $TRADER_CMD; sleep 10; done"
PADD_WRAPPED="while true; do $PADD_CMD; sleep 10; done"

# Clean any leftover 'display' session from a previous start
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Create the session detached, with both windows
tmux new-session -d -s "$SESSION" -n trader "$TRADER_WRAPPED"
tmux new-window -t "$SESSION":1 -n padd "$PADD_WRAPPED"

# Background rotator subshell
(
  while true; do
    if [ ! -e "$PAUSE_FILE" ]; then
      tmux select-window -t "$SESSION":0
    fi
    sleep "$INTERVAL_TRADER"
    if [ ! -e "$PAUSE_FILE" ]; then
      tmux select-window -t "$SESSION":1
    fi
    sleep "$INTERVAL_PADD"
  done
) &

# Foreground attach binds tmux to /dev/tty1 (via the service unit's TTYPath) and
# keeps systemd's Type=simple happy.
exec tmux attach -t "$SESSION"
```

### `/etc/systemd/system/screen-rotator.service`

```ini
[Unit]
Description=Cryptotrader monitor + PADD rotating display on tty1
Documentation=file:///usr/local/bin/screen-rotator.sh
After=network-online.target cryptotrader.service
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=TERM=xterm-256color
ExecStart=/usr/local/bin/screen-rotator.sh
ExecStopPost=/usr/bin/tmux kill-session -t display
StandardInput=tty
StandardOutput=tty
StandardError=journal
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Install on a fresh Pi

```bash
sudo install -m 0755 -o root -g root screen-rotator.sh   /usr/local/bin/screen-rotator.sh
sudo install -m 0644 -o root -g root screen-rotator.service /etc/systemd/system/screen-rotator.service
sudo systemctl daemon-reload
sudo systemctl enable --now screen-rotator.service
```
