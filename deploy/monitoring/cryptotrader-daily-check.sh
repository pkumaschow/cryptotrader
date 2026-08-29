#!/usr/bin/env bash
# cryptotrader-daily-check.sh — run the production invariant check once a day
# and alert only when something is actually wrong.
#
# Deliberately NOT a daily prose report. A report you have to read every morning
# is how six weeks of bag-holding went unnoticed; assertions that stay silent
# until they fail are how you find out the same day.
#
# Exit codes from daily_check.py: 0 = all clear, 1 = failure(s), 2 = could not run.
# "Could not run" alerts too — a checker that dies quietly is worse than none.

set -uo pipefail

REPO="${CRYPTOTRADER_REPO:-$HOME/project/cryptotrader}"
STATE_DIR="$HOME/.local/share/cryptotrader"
STATE_FILE="$STATE_DIR/daily-check-state.txt"
LOG_FILE="$STATE_DIR/daily-check.log"
JSON_FILE="$STATE_DIR/daily-check.json"
REPORT_FILE="$STATE_DIR/daily-check-latest.txt"
PAI_VOICE_URL="${PAI_VOICE_URL:-http://localhost:8888/notify}"
VOICE_ID="${CRYPTOTRADER_VOICE_ID:-}"

mkdir -p "$STATE_DIR"
TIMESTAMP=$(date -Iseconds)

notify() {
    curl -s -X POST "$PAI_VOICE_URL" \
        -H "Content-Type: application/json" \
        -d "{\"message\": \"$1\", \"voice_id\": \"$VOICE_ID\", \"voice_enabled\": true}" \
        > /dev/null 2>&1
}

cd "$REPO" 2>/dev/null || {
    echo "$TIMESTAMP  ERROR  repo not found at $REPO" >> "$LOG_FILE"
    notify "CryptoTrader daily check could not run: repository not found."
    exit 2
}

OUTPUT=$(uv run --no-project python3 scripts/daily_check.py --json "$JSON_FILE" 2>&1)
RC=$?

printf '%s\n' "$OUTPUT" > "$REPORT_FILE"
echo "$TIMESTAMP  rc=$RC" >> "$LOG_FILE"
printf '%s\n' "$OUTPUT" | sed 's/^/    /' >> "$LOG_FILE"

LAST_STATE="ok"
[[ -f "$STATE_FILE" ]] && LAST_STATE=$(cat "$STATE_FILE")

case "$RC" in
    0) STATE="ok" ;;
    1) STATE="fail" ;;
    *) STATE="broken" ;;
esac
echo "$STATE" > "$STATE_FILE"

# Alert on every failing day, not only on state change: an unresolved ledger
# breach is still costing money on day three, and silence would imply it healed.
case "$STATE" in
    fail)
        COUNT=$(printf '%s\n' "$OUTPUT" | grep -c '^  \[FAIL\]')
        NAMES=$(printf '%s\n' "$OUTPUT" | awk '/^  \[FAIL\]/ {printf "%s ", $2}')
        notify "CryptoTrader daily check failed: ${COUNT} problem(s) — ${NAMES}"
        ;;
    broken)
        notify "CryptoTrader daily check could not run. The bot is unchecked today."
        ;;
    ok)
        [[ "$LAST_STATE" != "ok" ]] && notify "CryptoTrader daily check is clean again."
        ;;
esac

exit "$RC"
