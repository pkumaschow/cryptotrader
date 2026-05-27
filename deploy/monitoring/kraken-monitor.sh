#!/usr/bin/env bash
# kraken-monitor.sh — monitor the CryptoTrader bot's health and alert on the desktop.
#
# Runs on the desktop (where the PAI voice server lives) via a systemd --user timer.
# It queries the bot's own /health endpoint, which runs ON the Pi and checks the
# database plus the Kraken API. This is deliberately different from the old monitor,
# which SSH'd to the Pi and curled an unrelated Kraken REST endpoint — an empty SSH
# response was indistinguishable from a Kraken outage and produced false
# "Kraken API connection failed" alerts (688 of them, all empty-response, over 40 days).
#
# Accuracy properties:
#   * The Kraken probe executes on the Pi inside the bot — no SSH hop to misfire.
#   * Failure modes are distinguished so each alert says what actually broke:
#       ok       — bot healthy (HTTP 200)
#       kraken   — bot up, Kraken API check failing (HTTP 503, kraken_api != ok)
#       database — bot up, database check failing (HTTP 503, database != ok)
#       bot      — Pi reachable but the bot/health endpoint isn't answering
#       pi       — the Pi itself is unreachable (network/host) — NOT a Kraken problem
#   * Transient blips are suppressed: a failure is only declared after RETRIES
#     consecutive failed attempts (~20-30s), and alerts fire only on a state change.
#
# Future enhancement: the /health endpoint does not yet report WebSocket feed
# staleness (the bot's actual price path). See docs/monitoring.md.

set -uo pipefail

HOST="${CRYPTOTRADER_HOST:-pihole.homelab.com}"
HEALTH_PORT="${CRYPTOTRADER_HEALTH_PORT:-8080}"
HEALTH_URL="http://${HOST}:${HEALTH_PORT}/health"
SSH_PORT="${CRYPTOTRADER_SSH_PORT:-22}"
RETRIES="${CRYPTOTRADER_RETRIES:-3}"
RETRY_DELAY="${CRYPTOTRADER_RETRY_DELAY:-10}"   # seconds between attempts
HTTP_TIMEOUT="${CRYPTOTRADER_HTTP_TIMEOUT:-6}"
TCP_TIMEOUT=4

STATE_DIR="$HOME/.local/share/ip-watcher"
STATE_FILE="$STATE_DIR/kraken-status.txt"
LOG_FILE="$STATE_DIR/kraken-monitor.log"
PAI_VOICE_URL="http://localhost:8888/notify"
VOICE_ID="fTtv3eikoepIosk8dTZ5"

mkdir -p "$STATE_DIR"

# Is the Pi host itself up? A dependency-free TCP connect to the SSH port — no SSH
# session, so it can't fail for key/agent/BatchMode reasons the way the old probe did.
pi_is_up() {
    timeout "$TCP_TIMEOUT" bash -c "cat < /dev/null > /dev/tcp/${HOST}/${SSH_PORT}" 2>/dev/null
}

# Classify a single probe. Echoes one of: ok|kraken|database|bot|pi
probe_once() {
    local body http_code rc kraken_status db_status
    body=$(curl -s --max-time "$HTTP_TIMEOUT" -w $'\n%{http_code}' "$HEALTH_URL" 2>/dev/null)
    rc=$?
    http_code="${body##*$'\n'}"
    body="${body%$'\n'*}"

    if [[ $rc -ne 0 || -z "$http_code" ]]; then
        if pi_is_up; then
            echo "bot"      # Pi up, but the bot/health endpoint isn't answering
        else
            echo "pi"       # Pi itself unreachable
        fi
        return
    fi

    if [[ "$http_code" == "200" ]]; then
        echo "ok"
        return
    fi

    # Non-200 (typically 503 degraded) — inspect which check failed.
    kraken_status=$(echo "$body" | jq -r '.checks.kraken_api.status // "unknown"' 2>/dev/null)
    db_status=$(echo "$body" | jq -r '.checks.database.status // "unknown"' 2>/dev/null)
    if [[ "$kraken_status" != "ok" ]]; then
        echo "kraken"
    elif [[ "$db_status" != "ok" ]]; then
        echo "database"
    else
        echo "bot"          # 503 but checks parse ok — treat as a bot anomaly
    fi
}

# Determine the current state. Return "ok" as soon as any attempt succeeds; only
# declare a failure after RETRIES consecutive failed attempts (suppresses blips).
determine_state() {
    local state="" i
    for ((i = 1; i <= RETRIES; i++)); do
        state=$(probe_once)
        if [[ "$state" == "ok" ]]; then
            echo "ok"
            return
        fi
        [[ $i -lt $RETRIES ]] && sleep "$RETRY_DELAY"
    done
    echo "$state"           # last failure classification
}

fail_message() {
    case "$1" in
        kraken)   echo "Kraken API connection failed. Check the bot." ;;
        database) echo "CryptoTrader database check is failing on the Pi." ;;
        bot)      echo "CryptoTrader bot is not responding on the Pi." ;;
        pi)       echo "Cannot reach the Pi to check CryptoTrader." ;;
        *)        echo "CryptoTrader health check failed." ;;
    esac
}

recover_message() {
    case "$1" in
        kraken)   echo "Kraken API connection restored." ;;
        database) echo "CryptoTrader database recovered." ;;
        bot)      echo "CryptoTrader bot is responding again." ;;
        pi)       echo "Pi is reachable again; CryptoTrader healthy." ;;
        *)        echo "CryptoTrader is healthy again." ;;
    esac
}

notify() {
    curl -s -X POST "$PAI_VOICE_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$1\", \"voice_id\": \"$VOICE_ID\", \"voice_enabled\": true}" \
        > /dev/null 2>&1
}

STATE=$(determine_state)

LAST_STATE="ok"
[[ -f "$STATE_FILE" ]] && LAST_STATE=$(cat "$STATE_FILE")
[[ "$LAST_STATE" == "fail" ]] && LAST_STATE="kraken"   # migrate legacy state file

TIMESTAMP=$(date -Iseconds)

if [[ "$STATE" == "ok" ]]; then
    if [[ "$LAST_STATE" != "ok" ]]; then
        echo "$TIMESTAMP  recovered (was: $LAST_STATE)" >> "$LOG_FILE"
        notify "$(recover_message "$LAST_STATE")"
    fi
else
    echo "$TIMESTAMP  $STATE failure" >> "$LOG_FILE"
    if [[ "$STATE" != "$LAST_STATE" ]]; then
        notify "$(fail_message "$STATE")"
    fi
fi

echo "$STATE" > "$STATE_FILE"
