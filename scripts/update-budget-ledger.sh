#!/usr/bin/env bash
# update-budget-ledger.sh — Track tool-call usage per agent and enforce budget regimes
#
# Called by agents at each state transition or tool call milestone to:
#   1. Update tool calls used for a specific agent unit
#   2. Recalculate global_calls_remaining
#   3. Detect regime switch (NORMAL → DEGRADE) at 70% spend + <50% units DONE
#   4. Enforce hard ceiling (180 calls, no exceptions)
#   5. Gate OVERRUN_REQUEST (allowed in NORMAL, blocked in DEGRADE)
#   6. Write updated ledger snapshot back to STM
#
# Usage:
#   bash update-budget-ledger.sh --stm PATH --unit A --calls-used 5 --agent developer-a
#   bash update-budget-ledger.sh --stm PATH --unit A --overrun-request --agent developer-a
#   bash update-budget-ledger.sh --stm PATH --status          # print current ledger
#
# Exit codes:
#   0  — OK (within budget)
#   1  — Hard ceiling hit (unit must be DEFERRED immediately)
#   2  — DEGRADE mode: overrun blocked
#   3  — STM not found or ledger block missing

set -euo pipefail

# ── Argument parsing ──────────────────────────────────────────────────────────
STM_PATH=""
UNIT_ID=""
CALLS_USED=""
AGENT_NAME=""
OVERRUN_REQUEST=0
STATUS_ONLY=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --stm)             STM_PATH="$2";    shift 2 ;;
        --unit)            UNIT_ID="$2";     shift 2 ;;
        --calls-used)      CALLS_USED="$2";  shift 2 ;;
        --agent)           AGENT_NAME="$2";  shift 2 ;;
        --overrun-request) OVERRUN_REQUEST=1; shift ;;
        --status)          STATUS_ONLY=1;    shift ;;
        *) shift ;;
    esac
done

if [[ -z "$STM_PATH" || ! -f "$STM_PATH" ]]; then
    echo "[budget-ledger] ERROR: STM not found at '${STM_PATH:-<unset>}'" >&2
    exit 3
fi

# ── Parse current ledger from STM ─────────────────────────────────────────────
# The BUDGET_LEDGER block was written by decompose-task.sh in this format:
#   ## [BUDGET_LEDGER]
#   total_budget: 180
#   regime: NORMAL
#   global_calls_used: 0
#   global_calls_remaining: 180
#   units:
#     - unit: A
#       agent: developer-a
#       allocated: 14
#       used: 0
#       state: NOT_STARTED
# We extract the LAST occurrence of each key (most recent ledger update wins).

TMPDIR_WORK="$(mktemp -d /tmp/budget-ledger-XXXX)"
trap 'rm -rf "$TMPDIR_WORK"' EXIT

# Extract the last BUDGET_LEDGER block from STM
awk '/## \[BUDGET_LEDGER\]/{found=1; buf=""} found{buf=buf"\n"$0} /^## \[/ && !/\[BUDGET_LEDGER\]/ && found{found=0} END{if(buf) print buf}' "$STM_PATH" > "$TMPDIR_WORK/ledger.txt" 2>/dev/null || true

# If no ledger block found, error
if [[ ! -s "$TMPDIR_WORK/ledger.txt" ]]; then
    echo "[budget-ledger] ERROR: No [BUDGET_LEDGER] block found in STM. Run decompose-task.sh first." >&2
    exit 3
fi

# Parse scalar fields from ledger
parse_field() {
    local key="$1"
    grep "^${key}:" "$TMPDIR_WORK/ledger.txt" | tail -1 | awk '{print $2}'
}

TOTAL_BUDGET="$(parse_field total_budget)"
REGIME="$(parse_field regime)"
GLOBAL_USED="$(parse_field global_calls_used)"
GLOBAL_REMAINING="$(parse_field global_calls_remaining)"
TOTAL_BUDGET="${TOTAL_BUDGET:-180}"
REGIME="${REGIME:-NORMAL}"
GLOBAL_USED="${GLOBAL_USED:-0}"
GLOBAL_REMAINING="${GLOBAL_REMAINING:-180}"

# Parse unit entries (unit, agent, allocated, used, state)
# Each unit block starts with "  - unit: X"
parse_units() {
    awk '
    /^  - unit:/ {
        if (unit != "") print unit "|" agent "|" alloc "|" used "|" state
        unit=$3; agent="?"; alloc=0; used=0; state="NOT_STARTED"
    }
    /^    agent:/ { agent=$2 }
    /^    allocated:/ { alloc=$2 }
    /^    used:/ { used=$2 }
    /^    state:/ { state=$2 }
    END { if (unit != "") print unit "|" agent "|" alloc "|" used "|" state }
    ' "$TMPDIR_WORK/ledger.txt"
}

parse_units > "$TMPDIR_WORK/units.txt"

# ── Status-only mode ──────────────────────────────────────────────────────────
if [[ $STATUS_ONLY -eq 1 ]]; then
    # Fetch live states from the STM state machine (HTML comment headers)
    # Format from read-stm-state.sh: UNIT  STATE  AGENT  TIMESTAMP_MS
    SCRIPTS_DIR="$(dirname "$0")"
    bash "$SCRIPTS_DIR/read-stm-state.sh" "$STM_PATH" > "$TMPDIR_WORK/live_states.txt" 2>/dev/null || true

    # Build a lookup: unit → live_state  (skip header/separator lines)
    # Stored as a flat file: "A=DONE\nB=IN_PROGRESS\n..."
    awk 'NR>2 && $1 !~ /^-/ && $1 != "" { print $1 "=" $2 }' \
        "$TMPDIR_WORK/live_states.txt" > "$TMPDIR_WORK/state_lookup.txt" 2>/dev/null || true

    echo ""
    echo "┌──────────────────────────────────────────────────────┐"
    echo "│               BUDGET LEDGER STATUS                   │"
    echo "└──────────────────────────────────────────────────────┘"
    printf "  Regime   : %s\n" "$REGIME"
    printf "  Used     : %d / %d  (remaining: %d)\n" "$GLOBAL_USED" "$TOTAL_BUDGET" "$GLOBAL_REMAINING"
    echo ""
    printf "  %-8s %-24s %-10s %-10s %-16s\n" "UNIT" "AGENT" "ALLOC" "USED" "STATE"
    printf "  %-8s %-24s %-10s %-10s %-16s\n" "----" "-----" "-----" "----" "-----"
    while IFS='|' read -r u ag al us st; do
        [[ -z "$u" ]] && continue
        pct=0
        [[ $al -gt 0 ]] && pct=$(( us * 100 / al ))
        bar=""
        [[ $pct -ge 80 ]] && bar=" 🔴"
        [[ $pct -ge 50 && $pct -lt 80 ]] && bar=" 🟡"
        # Override state with live value from STM state machine
        live_st="$(grep "^${u}=" "$TMPDIR_WORK/state_lookup.txt" 2>/dev/null | cut -d= -f2 || true)"
        [[ -n "$live_st" ]] && st="$live_st"
        printf "  %-8s %-24s %-10s %-10s %-16s\n" "$u" "$ag" "$al" "$us${bar}" "$st"
    done < "$TMPDIR_WORK/units.txt"
    echo ""
    exit 0
fi

# ── Validate inputs for update ─────────────────────────────────────────────────
if [[ -z "$UNIT_ID" ]]; then
    echo "[budget-ledger] ERROR: --unit required for update" >&2
    exit 1
fi

# ── Find unit in ledger ───────────────────────────────────────────────────────
UNIT_ALLOC=0
UNIT_USED=0
UNIT_STATE="NOT_STARTED"
UNIT_AGENT="${AGENT_NAME:-unknown}"

while IFS='|' read -r u ag al us st; do
    [[ "$u" == "$UNIT_ID" ]] || continue
    UNIT_ALLOC="$al"
    UNIT_USED="$us"
    UNIT_STATE="$st"
    UNIT_AGENT="${AGENT_NAME:-$ag}"
    break
done < "$TMPDIR_WORK/units.txt"

# ── Handle OVERRUN_REQUEST ────────────────────────────────────────────────────
if [[ $OVERRUN_REQUEST -eq 1 ]]; then
    if [[ "$REGIME" == "DEGRADE" ]]; then
        echo "[budget-ledger] ❌ OVERRUN BLOCKED: regime=DEGRADE — no burst allowed" >&2
        exit 2
    fi
    if [[ $GLOBAL_REMAINING -le 30 ]]; then
        echo "[budget-ledger] ❌ OVERRUN BLOCKED: global_remaining=$GLOBAL_REMAINING ≤ 30" >&2
        exit 2
    fi
    # Grant 25% burst
    BURST=$(( UNIT_ALLOC / 4 ))
    [[ $BURST -lt 1 ]] && BURST=1
    NEW_ALLOC=$(( UNIT_ALLOC + BURST ))
    echo "[budget-ledger] ✅ OVERRUN GRANTED: unit $UNIT_ID budget $UNIT_ALLOC → $NEW_ALLOC (+$BURST)"
    UNIT_ALLOC=$NEW_ALLOC
fi

# ── Apply calls-used update ───────────────────────────────────────────────────
if [[ -n "$CALLS_USED" ]]; then
    NEW_UNIT_USED=$(( UNIT_USED + CALLS_USED ))
    DELTA=$CALLS_USED

    # Hard ceiling check (unit total)
    if [[ $NEW_UNIT_USED -gt $UNIT_ALLOC ]]; then
        echo "[budget-ledger] ⚠️  Unit $UNIT_ID over allocated budget ($NEW_UNIT_USED / $UNIT_ALLOC)" >&2
    fi

    # Recalculate global
    NEW_GLOBAL_USED=$(( GLOBAL_USED + DELTA ))
    NEW_GLOBAL_REMAINING=$(( TOTAL_BUDGET - NEW_GLOBAL_USED ))

    # Hard ceiling — no exceptions
    if [[ $NEW_GLOBAL_USED -ge $TOTAL_BUDGET ]]; then
        echo "[budget-ledger] 🛑 HARD CEILING HIT: $NEW_GLOBAL_USED / $TOTAL_BUDGET — unit $UNIT_ID must DEFER" >&2
        # Still write the ledger so state is persisted
        NEW_GLOBAL_REMAINING=0
        UNIT_STATE="DEFERRED"
        exit_code=1
    else
        exit_code=0
    fi

    # Regime switch check (NORMAL → DEGRADE)
    SPEND_PCT=$(( NEW_GLOBAL_USED * 100 / TOTAL_BUDGET ))
    DONE_COUNT=$(grep -c '|DONE$' "$TMPDIR_WORK/units.txt" || true)
    TOTAL_COUNT=$(wc -l < "$TMPDIR_WORK/units.txt" | tr -d ' ')
    DONE_PCT=0
    [[ $TOTAL_COUNT -gt 0 ]] && DONE_PCT=$(( DONE_COUNT * 100 / TOTAL_COUNT ))

    if [[ "$REGIME" == "NORMAL" && $SPEND_PCT -ge 70 && $DONE_PCT -lt 50 ]]; then
        REGIME="DEGRADE"
        echo "[budget-ledger] ⚡ REGIME SWITCH: NORMAL → DEGRADE (spend=${SPEND_PCT}%, done=${DONE_PCT}%)"
    fi
else
    NEW_UNIT_USED=$UNIT_USED
    NEW_GLOBAL_USED=$GLOBAL_USED
    NEW_GLOBAL_REMAINING=$GLOBAL_REMAINING
    exit_code=0
fi

# ── Build updated ledger block ────────────────────────────────────────────────
TOTAL_SCORE="$(parse_field total_score)"
SHARED_FILES="$(parse_field shared_files)"

NEW_LEDGER="## [BUDGET_LEDGER]
total_budget: $TOTAL_BUDGET
total_score: ${TOTAL_SCORE:-0}
regime: $REGIME
global_calls_used: $NEW_GLOBAL_USED
global_calls_remaining: $NEW_GLOBAL_REMAINING
units:"

while IFS='|' read -r u ag al us st; do
    [[ -z "$u" ]] && continue
    if [[ "$u" == "$UNIT_ID" ]]; then
        us=$NEW_UNIT_USED
        al=$UNIT_ALLOC
        ag=$UNIT_AGENT
    fi
    NEW_LEDGER="${NEW_LEDGER}
  - unit: $u
    use_case: ${u}
    agent: $ag
    allocated: $al
    used: $us
    state: $st
    file_count: $(grep -A5 "unit: $u$" "$TMPDIR_WORK/ledger.txt" | grep 'file_count:' | awk '{print $2}' || echo 0)"
done < "$TMPDIR_WORK/units.txt"

NEW_LEDGER="${NEW_LEDGER}
shared_files: ${SHARED_FILES:-0}"

# Write updated ledger to STM
bash "$(dirname "$0")/write-stm.sh" "$STM_PATH" "budget-ledger" "$NEW_LEDGER"

echo "[budget-ledger] ✅ Ledger updated: unit=$UNIT_ID used=${NEW_UNIT_USED}/${UNIT_ALLOC} global=${NEW_GLOBAL_USED}/${TOTAL_BUDGET} regime=$REGIME"

exit ${exit_code:-0}
