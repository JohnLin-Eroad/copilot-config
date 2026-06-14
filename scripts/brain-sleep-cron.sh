#!/usr/bin/env bash
# brain-sleep-cron.sh — launchd wrapper for brain-sleep.py
#
# Runs daily housekeeping on the brain graph. Conservative defaults:
#   - mark-stale threshold:  0.10  (only flips heavily-decayed nodes)
#   - access-log retention:  90 days
#
# Single-instance via flock-style lockfile (skips if a previous run is still going).
# All output → ~/.copilot/logs/brain-sleep.log (rotated weekly via launchd convention).
#
# Env overrides:
#   BRAIN_SLEEP_STALE_THRESHOLD   default 0.10
#   BRAIN_SLEEP_KEEP_DAYS         default 90
#   BRAIN_SLEEP_DRY_RUN           default 0 (set to 1 for dry-run)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$HOME/.copilot/logs"
LOG_FILE="$LOG_DIR/brain-sleep.log"
LOCK_FILE="/tmp/brain-sleep.lock"

mkdir -p "$LOG_DIR"

THRESHOLD="${BRAIN_SLEEP_STALE_THRESHOLD:-0.10}"
KEEP_DAYS="${BRAIN_SLEEP_KEEP_DAYS:-90}"
DRY_RUN="${BRAIN_SLEEP_DRY_RUN:-0}"

DRY_FLAG=""
[ "$DRY_RUN" = "1" ] && DRY_FLAG="--dry-run"

# Single-instance lock (skip if previous run still active)
if [ -f "$LOCK_FILE" ]; then
    pid="$(cat "$LOCK_FILE" 2>/dev/null || echo)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "$(date -u +%FT%TZ) [skip] previous run PID=$pid still active" >> "$LOG_FILE"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

{
    echo "===== brain-sleep start  $(date -u +%FT%TZ)  threshold=$THRESHOLD  keep_days=$KEEP_DAYS  dry_run=$DRY_RUN ====="
    /usr/bin/env python3 "$SCRIPT_DIR/brain-sleep.py" run-all \
        --stale-threshold "$THRESHOLD" \
        --access-log-keep-days "$KEEP_DAYS" \
        $DRY_FLAG
    rc=$?
    echo "===== brain-sleep end    $(date -u +%FT%TZ)  exit=$rc ====="
    exit $rc
} >> "$LOG_FILE" 2>&1
