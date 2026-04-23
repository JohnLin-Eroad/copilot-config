#!/usr/bin/env bash
# write-stm.sh — Append a contribution to the active STM file
#
# Basic usage (unchanged, backward-compatible):
#   bash ~/.copilot/scripts/write-stm.sh "$STM_PATH" "AGENT-NAME" "content"
#
# Unit state machine usage (opt-in):
#   bash ~/.copilot/scripts/write-stm.sh "$STM_PATH" "AGENT-NAME" "content" \
#        --unit "A" --state "IN_PROGRESS"
#
# Valid states: CLAIMED IN_PROGRESS COMPILE_CHECKED DONE FAILED DEFERRED
# Valid transitions:
#   CLAIMED       → IN_PROGRESS
#   IN_PROGRESS   → COMPILE_CHECKED | FAILED | DEFERRED
#   COMPILE_CHECKED → DONE | FAILED | DEFERRED
#   DONE / FAILED   → terminal (rejected)
#   any             → DEFERRED (always allowed as emergency exit)
#
# State header written as HTML comment (parseable, invisible in rendered MD):
#   <!-- UNIT:A STATE:IN_PROGRESS TS:1745284800000 AGENT:developer-A -->

set -euo pipefail

STM_PATH="${1:-}"
AGENT_NAME="${2:-UNKNOWN}"
CONTENT="${3:-}"

# ── Parse optional --unit / --state flags ─────────────────────────────────────
UNIT_ID=""
NEW_STATE=""
shift 3 2>/dev/null || true
while [[ $# -gt 0 ]]; do
    case "$1" in
        --unit)  UNIT_ID="${2:-}";  shift 2 ;;
        --state) NEW_STATE="${2:-}"; shift 2 ;;
        *) shift ;;
    esac
done

# If content not passed as arg (arg 3 was empty), read from stdin
if [[ -z "$CONTENT" ]]; then
    CONTENT="$(cat)"
fi

# ── Guards ────────────────────────────────────────────────────────────────────
if [[ -z "$STM_PATH" ]]; then
    echo "[write-stm] WARNING: STM_PATH not set — skipping write" >&2
    exit 0
fi

if [[ ! -f "$STM_PATH" ]]; then
    echo "[write-stm] WARNING: STM file not found at $STM_PATH — skipping write" >&2
    exit 0
fi

# ── State machine validation (only when --unit and --state provided) ──────────
VALID_STATES="CLAIMED IN_PROGRESS COMPILE_CHECKED DONE FAILED DEFERRED"

if [[ -n "$UNIT_ID" && -n "$NEW_STATE" ]]; then
    # Validate state name
    if ! echo "$VALID_STATES" | grep -qw "$NEW_STATE"; then
        echo "[write-stm] ERROR: Invalid state '$NEW_STATE'. Valid: $VALID_STATES" >&2
        exit 1
    fi

    # Read current state for this unit
    CURRENT_STATE="$(bash "$(dirname "$0")/read-stm-state.sh" "$STM_PATH" "$UNIT_ID" 2>/dev/null || echo "NOT_STARTED")"

    # Terminal state guard
    if [[ "$CURRENT_STATE" == "DONE" || "$CURRENT_STATE" == "FAILED" ]]; then
        echo "[write-stm] ERROR: Unit $UNIT_ID is already $CURRENT_STATE (terminal) — transition to $NEW_STATE rejected" >&2
        exit 1
    fi

    # Transition validation (DEFERRED always allowed as emergency exit)
    TRANSITION_OK=0
    if [[ "$NEW_STATE" == "DEFERRED" ]]; then
        TRANSITION_OK=1
    elif [[ "$CURRENT_STATE" == "NOT_STARTED" && "$NEW_STATE" == "CLAIMED" ]]; then
        TRANSITION_OK=1
    elif [[ "$CURRENT_STATE" == "CLAIMED" && "$NEW_STATE" == "IN_PROGRESS" ]]; then
        TRANSITION_OK=1
    elif [[ "$CURRENT_STATE" == "IN_PROGRESS" && ( "$NEW_STATE" == "COMPILE_CHECKED" || "$NEW_STATE" == "FAILED" ) ]]; then
        TRANSITION_OK=1
    elif [[ "$CURRENT_STATE" == "COMPILE_CHECKED" && ( "$NEW_STATE" == "DONE" || "$NEW_STATE" == "FAILED" ) ]]; then
        TRANSITION_OK=1
    fi

    if [[ $TRANSITION_OK -eq 0 ]]; then
        echo "[write-stm] ERROR: Invalid transition for unit $UNIT_ID: $CURRENT_STATE → $NEW_STATE" >&2
        exit 1
    fi
fi

# ── Map --state to dashboard STATUS for parser visibility ────────────────────
DASHBOARD_STATUS=""
if [[ -n "$NEW_STATE" ]]; then
    case "$NEW_STATE" in
        CLAIMED)          DASHBOARD_STATUS="starting"    ;;
        IN_PROGRESS)      DASHBOARD_STATUS="in_progress" ;;
        COMPILE_CHECKED)  DASHBOARD_STATUS="in_progress" ;;
        DONE)             DASHBOARD_STATUS="complete"    ;;
        FAILED)           DASHBOARD_STATUS="failed"      ;;
        DEFERRED)         DASHBOARD_STATUS="blocked"     ;;
    esac
fi

# ── Timestamps ────────────────────────────────────────────────────────────────
TIMESTAMP="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
EPOCH_MS="$(date +%s)000"   # ms precision: append 000 (bash date doesn't do ms on macOS)

# ── Build state header comment (only when unit+state provided) ────────────────
STATE_HEADER=""
if [[ -n "$UNIT_ID" && -n "$NEW_STATE" ]]; then
    STATE_HEADER="<!-- UNIT:${UNIT_ID} STATE:${NEW_STATE} TS:${EPOCH_MS} AGENT:${AGENT_NAME} -->"
fi

# ── Atomic append with flock (preferred) or lock-file fallback ────────────────
LOCK_FILE="${STM_PATH}.lock"

_do_append() {
    # Prepend STATUS: for dashboard visibility (agent cards + pipeline diagram)
    local body="${CONTENT}"
    [[ -n "$DASHBOARD_STATUS" ]] && body="STATUS: ${DASHBOARD_STATUS}
${body}"
    if [[ -n "$STATE_HEADER" ]]; then
        printf '\n### %s — %s\n%s\n%s\n' \
            "$AGENT_NAME" "$TIMESTAMP" "$STATE_HEADER" "$body" >> "$STM_PATH"
    else
        printf '\n### %s — %s\n%s\n' \
            "$AGENT_NAME" "$TIMESTAMP" "$body" >> "$STM_PATH"
    fi
}

# Try flock (Linux + macOS with util-linux)
if command -v flock &>/dev/null; then
    (
        flock -w 5 200 || { echo "[write-stm] ERROR: Could not acquire lock within 5s" >&2; exit 1; }
        _do_append
    ) 200>"$LOCK_FILE"
    rm -f "$LOCK_FILE"
# Try shlock (macOS BSD fallback)
elif command -v shlock &>/dev/null; then
    shlock -f "$LOCK_FILE" -p $$
    _do_append
    rm -f "$LOCK_FILE"
# Simple append fallback (no locking available)
else
    _do_append
fi

# ── Output ────────────────────────────────────────────────────────────────────
if [[ -n "$UNIT_ID" && -n "$NEW_STATE" ]]; then
    echo "[write-stm] ✅ Written to STM: $AGENT_NAME @ $TIMESTAMP | unit=$UNIT_ID state=$NEW_STATE"
else
    echo "[write-stm] ✅ Written to STM: $AGENT_NAME @ $TIMESTAMP"
fi
